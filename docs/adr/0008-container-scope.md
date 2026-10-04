# ADR 0008: Container-scoped object lifetimes

Date: 2026-10-04

## Context

Global client state makes isolated tests and multiple app instances unsafe.

## Decision

Cache long-lived adapters inside each `Container` instance and close them in reverse creation order.

## Consequences

Instances are isolated by composition scope. The full set of lazy properties and lifecycle tests remains to be implemented.
