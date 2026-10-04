# ADR 0001: Hexagonal architecture

Date: 2026-10-04

## Context

The kit must support local providers and domain packs without coupling use cases to vendor SDKs.

## Decision

Keep pure models and Protocol ports in `domain`, orchestration in `application`, adapters in `infrastructure`, and concrete wiring in `bootstrap`.

## Consequences

Adapters can be replaced and the import-linter guards the dependency direction. Composition requires explicit bootstrap wiring.
