# Deferred Work

This file tracks work deliberately excluded from the first implementation pass.
Items here must not be presented as available v1 behavior.

## Priority explorer fixes — completed

- [x] Aggregate repeated coverage warnings as one message with an occurrence count.
- [x] Support Boolean topic filtering with required topics (AND) and alternative topics (OR).
- [x] Show every applicable guiding-topic tag on each paper card.
- [x] Organize dense graphs by discovery level and provide alternate layouts.
- [x] Add graph selection history and a one-click reset to the full graph.

## Priority discovery workflow — completed

- [x] Retry provider throttling with bounded backoff and schedule forward retrieval before bibliography-heavy backward retrieval.
- [x] Support citation discovery from one or more resolved seed papers.
- [x] Add bounded topic search, result review, and selected-paper graph creation.

## Scale beyond the local MVP

- Define artifact retention, run expiration, disk quotas, cleanup, and recovery
  of abandoned runs.
- Add PostgreSQL and a distributed worker queue before supporting horizontally
  scaled or multi-instance execution.
- Evaluate configurable limits above 1,000 papers only after durable execution,
  API-budget controls, and graph-rendering performance are in place.

## Provider coverage and API budgets

- Add and reconcile additional citation providers while preserving a fully
  functional keyless path; expose disagreements and provider-specific coverage.
- Define per-provider request budgets, caching policy, circuit breakers, and
  user-visible estimates before starting expensive runs.
- Add a provider cache that respects upstream terms and metadata freshness.
- Measure OpenAlex rate-limit behavior under forward and bidirectional expansion.
- Tune candidate page, frontier, and run-wide request budgets from observed
  keyless-provider behavior without weakening explicit coverage reporting.

## Discovery capabilities

- Add a downloadable local topic corpus/index so topic search can run without
  network access; the current bounded topic search uses keyless OpenAlex.
- Add a foundational-paper discovery mode using backward citation tracing and
  influence-based ranking. Evaluate DFS as one traversal option, but do not treat
  traversal order alone as evidence that a work is foundational.
- Improve relevance ranking by combining semantic similarity, citation proximity
  to seeds, and recency; keep each signal visible and configurable.
- Construct hybrid topic/citation graphs.
- Evaluate better resolution for arbitrary publication pages.
- Improve local GROBID extraction, reference matching, and deployment guidance.
- Investigate citation-context enrichment where a suitable provider permits it.

## Analysis and visualization

- Add community detection, centrality metrics, path analysis, and clustering.
- Add scalable server-side graph aggregation for graphs beyond the v1 limit.
- Add saved filter views and shareable explorer configurations.
- Evaluate alternate layouts and WebGL rendering for dense graphs.

## Product and operations

- Add authentication, ownership, sharing, and multi-user isolation if deployed
  beyond a trusted local environment.
- Add live progress transport using server-sent events or WebSockets.
- Define production observability, backup, privacy, and deployment policies.
- Add internationalization and expanded accessibility testing.
