# ADR 0005: Reranker device and memory budget

Date: 2026-10-04

## Context

The target RTX 3070 has 8 GB VRAM and the local LLM and embedder compete for memory.

## Decision

Disable reranking by default and configure the optional cross-encoder on CPU until GPU measurements show safe headroom.

## Consequences

The baseline remains usable on constrained hardware. Quality and latency impact must be measured before enabling it.
