# ADR 0003: PostgreSQL and pgvector persistence

Date: 2026-10-04

## Context

The corpus and vector index must remain local and support metadata filters and lexical retrieval.

## Decision

Use PostgreSQL with the pgvector extension as the planned shared persistence adapter; keep vector and lexical reads behind separate ports.

## Consequences

Filtering, transactions, and local lexical/vector searches share one database. The initial schema upgrade and store are implemented and were exercised against the Docker service. Alembic revision management, run repository lifecycle operations, and automated Docker integration coverage remain open.
