# ADR 0007: Evaluation metric definitions and targets

Date: 2026-10-04

## Context

The demo needs comparable baseline and agent measurements with uncertainty disclosed.

## Decision

Use explicit file-read, valid-row, layout, outcome, citation, field, schema, tool, consistency, and runtime metrics. Report n and confidence intervals alongside the 99% target and >95% floor.

## Consequences

Small test sets cannot support strong claims without intervals. A complete report runner and calibration remain backlog work.
