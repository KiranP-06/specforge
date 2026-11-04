# ADR 0003: Store the blueprint graph in PostgreSQL (items + links) with pgvector

**Status:** accepted

## Context
The blueprint is a typed graph (requirement → story → module → API → entity, requirement → test or risk). We need versioning, transactions, relational reporting, semantic similarity search and a small operational footprint.

## Decision
Use two tables, `items` (typed nodes with a JSON `data` payload and a `vector(384)` embedding) and `links` (directed, typed edges), plus `item_versions`, `baselines`, `findings` and `comments`. Traversals (change impact, trace matrix) run as breadth-first search in Python over one adjacency query per project.

## Consequences
- One database for everything, backed up with `pg_dump` to S3. No separate graph database to operate.
- Projects have hundreds of nodes, not millions, so in-memory traversal is fast enough. A recursive CTE is the upgrade path if that changes.
- pgvector's `<=>` operator powers semantic search. Tests run on SQLite through a type that falls back to JSON.
