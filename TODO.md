# Deferred Work

This file tracks work deliberately excluded from the first implementation pass.
Items here must not be presented as available v1 behavior.

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

## Discovery capabilities

- Implement topic-only literature discovery and construct citation graphs
  without requiring citation-connected seed papers.
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
