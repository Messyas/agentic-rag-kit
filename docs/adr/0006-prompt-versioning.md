# ADR 0006: Prompt versioning and evaluation gates

Date: 2026-10-04

## Context

Evaluation results must be reproducible across prompt changes.

## Decision

Store prompts as versioned files, hash their contents, and require evaluation artifacts for changes to production prompts.

## Consequences

Reports can identify their prompt revision. Prompt registry, templates, and evaluation gating remain to be completed.
