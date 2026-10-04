# ADR 0004: Local client and optional routing

Date: 2026-10-04

## Context

The PoC runs on one local Ollama server; shared-server protection is a later concern.

## Decision

Use the Ollama adapter as the local default. Keep routing behind separate strategies and defer gateway deployment until measured capacity needs it.

## Consequences

The local path stays simple. Optional balanced local backends are wired through LLM settings, with priority admission, bounded failover and cooldown. Periodic health checks and gateway deployment remain pending.
