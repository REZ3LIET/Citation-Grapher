# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Citation Grapher is a local-first literature discovery app: resolve seed papers (or pick them from a topic search), traverse their citation neighborhoods breadth-first through keyless public providers (OpenAlex, arXiv, ACL Anthology, Semantic Scholar fallback), annotate topics, and export reproducible datasets. `DOCUMENTATION.md` is the authoritative behavioral spec; `IMPLEMENTATION_PLAN.md` holds the fixed policy decisions; `TODO.md` tracks deferred work.

## Commands

Run from the repo root unless noted (Python 3.10+, Node 20+):

```bash
pip install -e '.[dev,embeddings]'        # embeddings extra is optional; without it a hash-embedding fallback is used
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload   # API on :8000, docs at /docs

cd frontend && npm install && npm run dev  # UI on :5173, proxies /api -> :8000
```

Tests:

```bash
pytest                                              # all backend tests (testpaths = backend/tests)
pytest backend/tests/test_runner.py::test_one_seed_runs_bfs_and_forward_is_scheduled_first
cd frontend && npm test                             # vitest run
cd frontend && npx vitest run src/features/explorer/topicFilters.test.ts
cd frontend && npm run build                        # tsc -b + vite build; this is the type check
```

`npm run lint` is configured but ESLint is not installed, so it fails; rely on `npm run build` for type checking.

Docker: `docker compose up --build` (add `--profile pdf` for local GROBID on :8070).

## Architecture

**Backend (`backend/app`, FastAPI, installed as package `app`).**
- `main.py` lifespan runs `init_db()` (which applies Alembic migrations programmatically from `alembic.ini` at the repo root) and then `runner.resume_interrupted()`, which reclaims leases on any run left in an active phase and re-enqueues it. Schema changes need a new migration in `backend/alembic/versions/`.
- `core/runner.py` — `DiscoveryRunner`, a module-level singleton with a single-thread `ThreadPoolExecutor`. It drives a run through phases (`resolving → collecting_frontier → scheduling_frontier → [awaiting_continue] → completing_edges → annotating → exporting → completed | completed_partial | failed`). All progress (checkpoint, counters, warnings, exclusions, coverage) is stored as JSON text columns on `RunRecord` (`*_json`, read and written via `loads`/`dumps`), so every step must be restart-safe and resume from `checkpoint_json`. Unexpected errors after papers have been retained turn into `completed_partial` with a partial export, not `failed`.
- `discovery/scheduler.py` — `Candidate` dedup/merge plus deterministic ordering (lower citation count, then newer year, then canonical ID) and round-robin interleaving across seed frontiers. Candidates serialize to and from checkpoints.
- `providers/openalex.py` — despite its name, `OpenAlexClient` is the main provider facade. It handles OpenAlex plus arXiv HTML bibliography parsing, ACL Anthology resolution, and Semantic Scholar forward fallback. Every request goes through a `consume_request` callback that charges the per-run request budget. `providers/arxiv.py` handles arXiv search and resolution fallback; `providers/grobid.py` identifies PDFs.
- `topics/annotator.py` — multi-label topic similarity (Sentence Transformers, or a deterministic hash fallback that raises an `embedding_fallback` warning).
- `exports/writer.py` — writes `papers.csv`, `citations.csv`, `run_metadata.json`, and `graph.graphml` under `data/runs/<run-id>/`. It also builds filtered subset ZIPs and validates CSV imports.
- `api/routes.py` — every endpoint (`/runs`, `/runs/{id}/continue|expand|stop|graph|exports`, `/topic-search`, `/seed-pdfs/identify`, `/import`). `schemas.py` holds the Pydantic models.
- Config: `core/config.py` `Settings`, env prefix `CITATION_GRAPHER_` (see `.env.example`). Budgets, the 500 pause threshold and 1,000 hard limit, and retry settings live there.

**Frontend (`frontend/src`, React 18 + TS + Vite + Cytoscape).** `App.tsx` is a screen state machine (configure → progress → explore → export) that polls `GET /runs/{id}` every 1.5s during active phases. Features sit under `features/{configuration,discovery,explorer,export}`. Pure logic, such as signed citation-layer layout (`graphLayout.ts`) and the typed Boolean `AND`/`OR`/parentheses filter parser (`topicFilters.ts`), lives in separate unit-tested modules. API calls are in `api/client.ts` and shared types in `types/index.ts`.

## Invariants to preserve

- Edges always point citing → cited and come only from provider or bibliography evidence. Topic similarity never creates edges. Topics only annotate, except with the opt-in `topic_filter` run setting: candidates whose best topic score is below `topic_filter_threshold` are pruned per level in `DiscoveryRunner._prune_by_topic` (seeds and unscorable papers are always kept, and pruned ones are recorded as `below_topic_relevance` exclusions).
- Canonical ID precedence: normalized DOI > `openalex:` ID > arXiv DOI > `acl:` ID > conservative title, author, and year match. Bibliography entries that can't be resolved but have enough metadata can be kept as provisional `bibliography:...` nodes with provenance `source_attested_unresolved`.
- BFS levels are processed and checkpointed one at a time (max depth 3). With direction `both`, forward requests are scheduled before backward ones.
- The year range is a hard filter at every level. Excluded or missing-year candidates are recorded as exclusions, never dropped silently.
- An exact pause at 500 retained papers (`awaiting_continue`) and a hard stop at 1,000 (`partial_limit_reached`).
- Every reached budget or provider failure must be reported: it marks `retrieval_complete: false` and adds a warning or limitation. `literature_coverage_complete` is always false.

## Testing patterns

Backend runner tests replace `runner_module.SessionLocal` with an in-memory or tmp-path SQLite sessionmaker, and `runner_module.OpenAlexClient` with fake provider classes, using `monkeypatch`. HTTP-level provider tests pass `transport=httpx.MockTransport(handler)` to `OpenAlexClient` (`respx` is a dev dependency but isn't used). No test should hit real network providers.
