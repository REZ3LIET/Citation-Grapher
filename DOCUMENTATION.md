# Citation Grapher — Comprehensive Documentation

This document describes the application as it is currently implemented. It
covers the product behavior, architecture, discovery pipeline, provider
strategy, data model, user interface, visualization, filtering, exports,
configuration, testing, deployment constraints, and known limitations.

## 1. Purpose and current scope

Citation Grapher is a local-first literature discovery tool. A user can start
from one or more known papers, or search for papers by topic and select seeds,
then expand a directed citation graph around those seeds.

The application is designed to:

- resolve scholarly paper identities conservatively;
- discover backward references, forward citations, or both;
- expand the graph breadth-first through one to three levels;
- checkpoint every completed level and preserve partial results;
- annotate papers against guiding topics without using topics to fabricate or
  prune citation edges;
- expose provider and application coverage limitations;
- provide an interactive, traceable graph and paper list;
- filter papers with typed Boolean logic; and
- export complete runs or referentially consistent filtered subsets.

The graph is a discovery aid, not a claim to be a complete representation of
the scholarly literature. A completed run means the configured attempted
traversal was processed; it does not mean every real-world citation was found.

### Local-first versus fully offline

The backend, persistence, topic scoring, visualization, and exports run
locally. New scholarly metadata and citation discovery still use public online
providers. Once canonical CSV files have been exported, they can be imported
and explored without contacting a scholarly provider.

No paid API or API key is required for the implemented default path. Keyless
provider pools can be throttled, so the application preserves partial data and
reports the limitation rather than treating an empty provider response as
global proof that no citations exist.

## 2. Technology and architecture

| Area | Implementation |
| --- | --- |
| Frontend | React 18, TypeScript, Vite |
| Graph visualization | Cytoscape.js |
| Backend API | FastAPI and Pydantic |
| Persistence | SQLite, SQLAlchemy, Alembic |
| HTTP | `httpx` |
| Graph export | NetworkX |
| Topic embeddings | Sentence Transformers when available |
| Embedding fallback | Deterministic local hash embeddings |
| Optional PDF metadata | Local GROBID service |
| Backend tests | Pytest |
| Frontend tests | Vitest and React Testing Library |

The frontend communicates with the backend through `/api`. The backend runs a
single local discovery worker and stores durable run state in SQLite. Generated
run artifacts are written below `data/runs/<run-id>/` by default.

```text
Browser
  │
  ├── configuration, progress, explorer, exports
  │
FastAPI backend
  │
  ├── durable discovery runner
  ├── provider adapters
  ├── topic annotation
  └── export/import validation
  │
SQLite + data/runs
```

Docker is optional. It packages the frontend, backend, persistent data volume,
and optional GROBID profile, but local development can run directly with
Python, Uvicorn, Node, and Vite.

## 3. Implemented user workflows

### 3.1 Start with known papers

The user provides one or more seed identifiers or URLs, guiding topics, an
inclusive year range, a direction, and a target level.

Accepted seed forms include:

- DOI or DOI URL;
- OpenAlex work ID or URL;
- arXiv ID or URL; and
- ACL Anthology paper URL.

At least one seed and one guiding topic are required. Only one seed needs to
resolve successfully. Multiple seeds do not need to be connected, and each
resolved seed starts its own independent frontier.

### 3.2 Search by topic

The configuration screen also supports bounded Boolean paper search. The user
can type a provider search query such as:

```text
unlearning AND (causal OR counterfactual)
```

The backend searches OpenAlex first. If the keyless OpenAlex allowance is
unavailable, it falls back to arXiv search. The result list is bounded, reports
whether more matches are known, and requires the user to select papers before
creating a graph.

Topic search finds candidate seeds. It does not itself create citation edges.

### 3.3 Import an existing graph

The user can upload `papers.csv` and `citations.csv`. Import validates required
columns, unique paper IDs, unique edges, and referential integrity. Imported
graphs open directly in the explorer without scholarly provider calls.

Imported graphs can be filtered and exported, but cannot be expanded because
they do not contain an active discovery checkpoint and provider frontier.

### 3.4 Identify a seed from a PDF

A PDF up to 25 MB can be sent to a locally running GROBID service to identify
seed metadata. The current UI uses this to add an identifier to the seed list.
General full-PDF bibliography traversal is not wired into the main discovery
runner; arXiv HTML bibliography extraction is the implemented backward
fallback.

## 4. Provider strategy

### 4.1 OpenAlex

OpenAlex is the primary provider for:

- resolving DOI, OpenAlex, and arXiv identifiers;
- conservative title/author/year enrichment;
- topic search;
- OpenAlex reference-list resolution; and
- forward-citation queries.

Every request, including retries, counts against the durable run request
budget.

### 4.2 arXiv

arXiv is used for:

- seed metadata fallback when OpenAlex cannot resolve an arXiv seed;
- bounded topic-search fallback;
- native resolution of bibliography entries with arXiv identifiers; and
- parsing arXiv HTML bibliographies when an OpenAlex record has no usable
  `referenced_works` list.

The bibliography parser preserves the raw citation, its position, title URL,
publication year, and first-author evidence where available.

### 4.3 ACL Anthology

ACL URLs are resolved from page citation metadata. OpenAlex enrichment is
accepted only with conservative title, author, and year agreement. If
enrichment fails, the authoritative ACL identity and metadata can still be
retained.

### 4.4 Semantic Scholar

Semantic Scholar is a bounded forward-citation fallback. It is queried when
OpenAlex returns no forward-citation papers or is temporarily unavailable.
Returned citing papers are normalized by DOI or arXiv ID where possible and
carry `semantic_scholar` provenance.

The fallback is keyless. Its shared pool can return HTTP 429. If that happens,
the run reports provider retrieval as incomplete and keeps all data already
resolved.

The current implementation does not merge Semantic Scholar into a non-empty
OpenAlex forward result. It is a fallback, not a complete multi-provider union.

### 4.5 GROBID

GROBID is optional and local. It is currently exposed for PDF seed
identification. It is available through the Docker Compose `pdf` profile or a
separately running service at the configured URL.

### 4.6 Providers deliberately not integrated

- **Google Scholar:** no supported public scholarly-data API suitable for this
  keyless, reproducible workflow; automated scraping is fragile and restricted.
- **NASA ADS:** the UI can be used manually, but automated ADS retrieval is not
  currently implemented and commonly requires credentials.
- **Paid third-party scraping/search APIs:** excluded from the no-key default
  path.

## 5. Paper identity and citation integrity

Identity precedence is conservative:

1. normalized DOI;
2. OpenAlex work ID when no DOI is available;
3. canonical arXiv DOI derived from an arXiv ID;
4. authoritative ACL Anthology ID; or
5. exact normalized title with compatible author and year evidence.

Typical canonical IDs include:

```text
doi:10.48550/arxiv.2604.15847
openalex:W123456789
acl:2025.coling-main.524
semantic_scholar:<paper-id>
```

A citation edge always points from the citing paper to the cited paper:

```text
citing paper ──cites──> cited paper
```

Topic similarity never creates an edge. An edge is stored only when a provider
or source bibliography supplies citation evidence.

### Source-attested unresolved references

Backward retrieval attempts each selected bibliography entry independently.
One failed lookup does not abort later entries. Resolution proceeds through:

1. explicit DOI/arXiv identifiers and OpenAlex batch lookup;
2. native arXiv metadata for OpenAlex-missing arXiv works;
3. authoritative ACL links;
4. punctuation-safe exact title search; and
5. conservative title, first-author, and year validation.

If an entry still cannot be canonically resolved but has enough source metadata
and a year, it can be retained as a provisional node such as:

```text
bibliography:arxiv:<source-id>:ref:<position>
```

Its provenance is `source_attested_unresolved`. This does not claim a canonical
identity; it records that the source paper explicitly contained the citation.
The raw bibliography text and reference position remain attached as evidence.

## 6. Discovery execution flow

```text
Validate configuration
        ↓
Resolve each seed independently
        ↓
Store resolved seeds at level 0
        ↓
Collect one complete bounded frontier
        ↓
Resolve, validate, deduplicate, and year-filter candidates
        ↓
Deterministically schedule retained candidates
        ↓
Store directed citation edges
        ↓
Checkpoint the completed level
        ↓
Repeat sequentially until requested level
        ↓
Complete retained internal edges
        ↓
Annotate topics
        ↓
Export complete or partial result
```

### 6.1 Seed resolution

Every seed produces diagnostics containing:

- original input;
- resolution status;
- canonical ID;
- resolution method;
- publication year;
- known reference count;
- known citing-paper count;
- retrieved candidate count; and
- candidates excluded by year.

Seeds outside the year range are recorded as exclusions. A run fails with
`insufficient_resolved_seeds` only when no year-eligible seed resolves. It does
not require two seeds, two edges, a shared reference, or connected seed
components.

### 6.2 Breadth-first levels

Seeds are depth 0. Immediate references and citing papers are depth 1. Their
neighbors are depth 2, and so on through depth 3.

Even when level 3 is requested, processing remains sequential:

```text
level 0 → complete and checkpoint level 1
        → complete and checkpoint level 2
        → complete and checkpoint level 3
```

No level is skipped. The frontend defaults to level 1. After a completed level,
the user can select **Run next level** or enable auto-next to request the
remaining levels through level 3. The backend still processes and checkpoints
each intermediate level individually.

### 6.3 Direction scheduling

Supported directions are:

- `backward`: papers referenced by the current frontier;
- `forward`: papers citing the current frontier; and
- `both`.

When both is selected, bounded forward requests are scheduled across the
frontier before bibliography-heavy backward resolution so backward lookups
cannot consume the entire request budget first.

### 6.4 Candidate ordering and seed fairness

Retrieved candidates are deduplicated by canonical identity while retaining all
parents, directions, providers, and contributing seed frontiers.

Within a frontier, ordering is deterministic:

1. lower known provider citation count first;
2. newer publication year first; and
3. canonical ID as a stable tie-breaker.

Candidates with a missing citation count sort after known counts. Multiple seed
frontiers are interleaved round-robin so a large neighborhood from one seed
does not monopolize a bounded run.

### 6.5 Year filtering

The inclusive year range is enforced at every level. Provider-side filters are
used when possible, followed by local verification. Missing-year and
out-of-range candidates are not silently discarded; they are recorded as
exclusions and reflected in diagnostics.

## 7. Checkpointing, limits, and recovery

The runner stores run configuration, counters, warnings, exclusions, seed
results, frontiers, ordered candidates, schedule positions, retrieval attempts,
and coverage metadata in SQLite.

Durable boundaries include provider request accounting and candidate scheduling
progress. On backend startup, active runs from the previous process are
reclaimed and re-enqueued.

Default limits are:

| Limit | Default |
| --- | ---: |
| Expansion depth | 1, maximum 3 |
| Pages per provider query | 3 |
| Candidates per parent/direction | 600 |
| Pending candidates per depth | 10,000 |
| Provider requests per run | 1,500 |
| Topic-search requests | 4 |
| Pause threshold | 500 retained papers |
| Final hard limit | 1,000 retained papers |

At exactly 500 retained papers, the run enters `awaiting_continue`. The user can
continue or stop and export. At exactly 1,000 papers, discovery stops and
returns everything retained with `partial_limit_reached`.

Provider failures, application caps, and unexpected level errors do not erase
resolved seeds or previously checkpointed levels. Whenever possible, the run
finishes annotation and export as `completed_partial`.

## 8. Run phases and outcomes

Normal phases include:

```text
created
resolving
collecting_frontier
scheduling_frontier
awaiting_continue
completing_edges
annotating
exporting
completed | completed_partial | failed
```

Important outcomes include:

- `fully_processed_attempted_traversal`;
- `no_citation_candidates`;
- `provider_retrieval_incomplete`;
- `partial_limit_reached`;
- `user_stopped`;
- `level_processing_error`; and
- `insufficient_resolved_seeds`.

Seed-level statuses and run-level outcomes are separate. For example, one seed
can fail resolution while another resolves and completes discovery.

## 9. Coverage and warning semantics

The progress screen aggregates identical warnings as:

```text
warning name (count)
message
```

Common warnings include:

- `unresolved_bibliography_entries`;
- `provider_rate_limited` or `provider_daily_budget`;
- `provider_retrieval_incomplete`;
- `collection_budget`; and
- `embedding_fallback`.

`retrieval_complete: false` means at least one attempted frontier was capped,
unavailable, unsupported, or otherwise incomplete. Retained papers and edges
remain valid for the evidence that was collected.

`literature_coverage_complete` is always false because no provider can prove
complete coverage of all scholarly literature.

An intentional small cap can therefore produce `completed_partial` even when
every selected candidate resolved successfully. The status describes the
unprocessed frontier, not invalid retained data.

## 10. Topic annotation

Guiding topics annotate papers after citation discovery. They do not prune BFS
and do not create citation relationships.

The preferred model is:

```text
sentence-transformers/all-MiniLM-L6-v2
```

The default label threshold is `0.35`. Each paper stores a score for every
guiding topic and can receive multiple applicable tags.

If Sentence Transformers is unavailable, the backend uses a deterministic
local hash-embedding fallback and records `embedding_fallback`. These scores are
heuristic cosine similarities, not probabilities. The fallback can produce
lower-quality classifications even when a title contains an obviously related
concept.

## 11. Explorer and visualization

The explorer combines:

- a newest-first Discovered Papers list;
- an interactive citation graph;
- paper details and topic scores;
- connected-paper navigation;
- previous-selection history and reset controls; and
- non-destructive filters.

### 11.1 Citation-layer layout

The default Cytoscape layout is deterministic and directional:

```text
Backward L3 ← Backward L2 ← Backward L1 ← Seeds → Forward L1 → Forward L2 → Forward L3
```

- seeds remain at the center;
- backward generations move left as depth increases;
- forward generations move right as depth increases;
- papers within a column use stable year/title/ID ordering;
- imported graphs infer sides from citation direction when discovery provenance
  is absent; and
- force-directed and grid layouts remain optional.

Hovering or selecting a node displays its title. Selecting a non-seed paper
highlights the shortest citation chain back to the nearest seed and mutes
unrelated edges. Selecting a seed highlights its directly connected frontier.
The **Fit graph** control restores the complete view.

### 11.2 Other filters

The explorer supports:

- free-text title, author, DOI, and ID search;
- inclusive minimum and maximum year;
- role: all, seeds, or discovered;
- provider or internal citation-count threshold;
- graph distance of one to three hops from the current selection; and
- minimum topic relevance.

All active filter families are combined with logical AND.

## 12. Typed Boolean topic filtering

The explorer contains a text field for complete Boolean expressions. For
example:

```text
(LLMs OR Large language models) AND unlearning AND (causal OR counterfactual)
```

Supported syntax:

- `AND`;
- `OR`;
- nested parentheses;
- case-insensitive operators;
- multi-word topic terms; and
- quoted topic names that contain operator words, such as
  `"research AND development"`.

`AND` has higher precedence than `OR`. Parentheses are recommended whenever the
intended grouping should be unmistakable.

Malformed expressions show an inline error rather than silently changing their
meaning. Subset export is disabled until the expression is valid.

Evaluation works as follows:

1. If the normalized term matches a configured relevance-score name, the score
   is tested against the current relevance threshold.
2. If no score exists for that term, the explorer performs a literal,
   case-insensitive match against title, abstract, and assigned topic tags.

The literal fallback allows aliases such as `LLMs` and `Large language models`
to be useful even when only one form was supplied as an embedding topic. It is
literal evidence and does not invent a similarity score.

## 13. Full-run exports

Completed and partial runs generate:

### `papers.csv`

Columns:

```text
paper_id
title
authors
year
venue
abstract
doi
url
is_seed
discovery_depth
topics
relevance_scores
provider_citation_count
internal_in_count
internal_out_count
classification_status
provenance
```

Authors and topics are JSON arrays. Relevance scores and provenance are JSON
objects stored in quoted CSV cells. Spreadsheet-formula-leading text is escaped
on export.

### `citations.csv`

Columns:

```text
citing_paper_id
cited_paper_id
citation_provenance
retrieval_date
citation_context
```

Both endpoints are guaranteed to exist in `papers.csv`.

### `run_metadata.json`

Contains configuration, final status, counters, coverage, warnings, exclusions,
provider limitations, and reproducibility notes.

### `graph.graphml`

Contains the directed retained graph for interoperable graph tools.

## 14. Filtered subset export

The explorer provides **Export subset (N)**, where `N` is the current number of
visible papers after all filters.

The downloaded ZIP contains:

- `papers.csv` with only visible papers;
- `citations.csv` with only edges whose citing and cited endpoints are both in
  the subset;
- `graph.graphml` for the same induced subgraph; and
- `subset_metadata.json` with the Boolean expression, all other filter values,
  source run ID, counts, and coverage inherited from the run.

This design prevents dangling citation endpoints. Full-run exports remain
unchanged and available separately.

## 15. Backend API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Health check |
| POST | `/api/topic-search` | Bounded topic-based paper search |
| POST | `/api/seed-pdfs/identify` | Identify a PDF through local GROBID |
| POST | `/api/runs` | Create and enqueue a discovery run |
| GET | `/api/runs` | List runs |
| GET | `/api/runs/{run_id}` | Read run status and coverage |
| POST | `/api/runs/{run_id}/continue` | Continue after the 500-paper pause |
| POST | `/api/runs/{run_id}/expand` | Increase target level sequentially |
| POST | `/api/runs/{run_id}/stop` | Stop discovery and export retained data |
| GET | `/api/runs/{run_id}/graph` | Retrieve papers, citations, and run data |
| GET | `/api/runs/{run_id}/exports/{filename}` | Download a canonical full-run export |
| POST | `/api/runs/{run_id}/exports/subset` | Build and download a filtered ZIP |
| POST | `/api/import` | Import a canonical CSV pair |

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`
when the backend is running.

## 16. Configuration

Settings use the `CITATION_GRAPHER_` environment prefix. Common values are:

| Environment variable | Default |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./data/citation_grapher.db` |
| `RUNS_DIR` | `./data/runs` |
| `OPENALEX_BASE_URL` | `https://api.openalex.org` |
| `GROBID_BASE_URL` | `http://localhost:8070` |
| `MAX_PAGES_PER_QUERY` | `3` |
| `MAX_CANDIDATES_PER_PARENT_DIRECTION` | `600` |
| `MAX_PENDING_CANDIDATES_PER_DEPTH` | `10000` |
| `MAX_PROVIDER_REQUESTS_PER_RUN` | `1500` |
| `MAX_TOPIC_SEARCH_REQUESTS` | `4` |
| `PAPER_WARNING_THRESHOLD` | `500` |
| `PAPER_HARD_LIMIT` | `1000` |
| `TOPIC_THRESHOLD` | `0.35` |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `REQUEST_TIMEOUT_SECONDS` | `20` |
| `PROVIDER_MAX_RETRIES` | `3` |
| `PROVIDER_RETRY_BASE_SECONDS` | `0.5` |
| `PROVIDER_RETRY_MAX_SECONDS` | `8` |
| `CORS_ORIGINS` | `http://localhost:5173` |

The full environment variable name is the prefix plus the name in the table,
for example `CITATION_GRAPHER_MAX_PROVIDER_REQUESTS_PER_RUN`.

## 17. Local development

Requirements:

- Python 3.10 or newer;
- Node 20 or newer; and
- internet access for new provider-backed discovery.

Backend setup:

```bash
cd /workspaces/Portfolio/workdir/Citation-Grapher
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,embeddings]'
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload
```

Frontend setup in another terminal:

```bash
cd /workspaces/Portfolio/workdir/Citation-Grapher/frontend
npm install
npm run dev
```

Open:

- frontend: `http://localhost:5173`;
- backend: `http://localhost:8000`; and
- API docs: `http://localhost:8000/docs`.

The embeddings extra is optional. Without it, discovery still runs with the
deterministic fallback and reports that fallback in coverage warnings.

## 18. Docker usage

Docker is not required when development already occurs inside a suitable
container or local environment.

Standard Compose startup:

```bash
docker compose up --build
```

With optional GROBID:

```bash
docker compose --profile pdf up --build
```

Compose exposes the frontend on port 5173 and backend on port 8000. SQLite and
run artifacts are stored in the `citation-data` volume.

## 19. Common troubleshooting

### Port 8000 is already in use

Inspect the listener:

```bash
ss -ltnp 'sport = :8000'
```

Alternatives, if installed:

```bash
lsof -i :8000
fuser 8000/tcp
```

Either stop the old process or run Uvicorn on another port:

```bash
uvicorn app.main:app --app-dir backend --reload --port 8001
```

If the backend port changes, update the frontend proxy configuration as needed.

### The run says retrieval-incomplete

Inspect `Coverage & warnings` and `run_metadata.json`. Typical causes are:

- a deliberate candidate or page cap;
- unresolved bibliography entries;
- provider throttling;
- a provider without the required identifier; or
- the run-wide request budget.

The retained graph is still valid for recorded evidence.

### Only seeds are returned

Check per-seed diagnostics and retrieval attempts. A resolved seed with no
OpenAlex forward citations may still receive Semantic Scholar fallback results.
For backward discovery, arXiv HTML fallback requires an arXiv identity and an
available HTML bibliography.

### The graph is visually dense

Use the Citation layers layout, Boolean topic filter, year/role/citation
filters, or distance filter. Select a paper to highlight its path to a seed and
use Fit graph to restore the overall view.

## 20. Deployment notes

### GitHub Pages

GitHub Pages can host only the compiled static frontend. It cannot run FastAPI,
SQLite, the discovery worker, provider orchestration, or GROBID.

A usable hosted deployment therefore needs:

1. the frontend built and hosted as static assets;
2. the FastAPI backend hosted on a service that supports Python processes and
   persistent storage;
3. frontend API configuration pointing to that backend;
4. backend CORS configured for the Pages origin; and
5. a persistence strategy suitable for the host.

Without a backend, GitHub Pages can only provide a redesigned browser-only mode
for static/imported data; that mode is not currently implemented as a standalone
deployment.

### Free-tier constraints

Free backend hosts may sleep, erase ephemeral disks, limit memory/CPU, or
terminate long requests. SQLite is appropriate for the current single-worker
local design but not for multiple backend instances sharing writes. Durable
hosted or multi-user deployment would require additional operational design,
potentially including PostgreSQL and a real worker queue.

## 21. Verification status

The implemented behavior is covered by backend and frontend tests, including:

- one-seed and disconnected multi-seed discovery;
- independent seed diagnostics;
- forward-before-backward scheduling;
- sequential level checkpointing;
- exact pause and hard-limit behavior;
- provider retries and keyless throttling;
- arXiv bibliography parsing and five-reference regression coverage;
- native arXiv and ACL bibliography resolution;
- source-attested provisional references;
- Semantic Scholar forward fallback;
- CSV integrity and filtered subset ZIP integrity;
- topic search and CSV import;
- warning aggregation;
- multi-label paper tags;
- selection history;
- signed citation-layer positioning; and
- typed Boolean expression parsing and evaluation.

Latest verification performed during implementation:

```text
Backend:  39 tests passed
Frontend: 12 tests passed
Frontend production build: passed
git diff --check: passed
```

The configured frontend lint command currently cannot run because ESLint is not
installed in `frontend/package.json`. TypeScript checking still runs as part of
the production build.

## 22. Known limitations and deferred work

- Provider coverage is incomplete and provider disagreement is not fully
  reconciled.
- Semantic Scholar is only a forward fallback after an empty/unavailable
  OpenAlex result.
- Keyless provider availability and rate limits can vary.
- The local hash embedding fallback is less semantically capable than the
  configured Sentence Transformer.
- GROBID-backed general bibliography expansion is not integrated into the main
  runner.
- No Google Scholar or automated ADS adapter is implemented.
- No authentication, user ownership, sharing, or multi-user isolation exists.
- No provider cache or downloadable offline scholarly index exists.
- No community detection, centrality, clustering, or server-side aggregation is
  implemented.
- Maximum discovery depth is 3 and the final retained-paper limit is 1,000.
- Large hosted or multi-instance deployments need a different persistence and
  worker architecture.
- Saved filter views and shareable explorer URLs are not implemented.

See `TODO.md` for the maintained deferred-work list and
`IMPLEMENTATION_PLAN.md` for the original architectural plan and fixed policy
decisions.

