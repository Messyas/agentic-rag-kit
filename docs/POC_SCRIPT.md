# Demo video script

Use anonymized or synthetic material only. The commands are implemented. Install the configured models and index reviewed evidence before recording; measured acceptance results are still pending.

1. **Use case:** explain the analyst's current review process and Proposal A (corrective workflow) or Proposal B (investigation agent).
2. **Local models and hardware:** run `rag-kit check`; capture `python scripts/gpu_probe.py` after loading the local models.
3. **Evaluation set:** run `rag-kit eval --dataset evaluation/datasets --validate-dataset`; show source, size, split, and ground-truth validation.
4. **Baseline:** report rule-based/manual baseline metrics on the same cases as the agent.
5. **Execution:** demonstrate `rag-kit ingest <file.csv> --output evaluation/ingested`; index evidence with `rag-kit index <corpus.jsonl>` and analyze a canonical record with `rag-kit analyze <occurrence.json>`.
6. **Results:** show measured accuracy, field exactness, schema validity, latency, token rate, RAM, and distance to 99% / >95% targets, including sample size and confidence intervals.
7. **Error analysis:** group failed cases by retrieval, grading, schema, and tool-call cause; show traces without sensitive content.
8. **Next steps:** present effort in two-week sprints and distinguish measured results from planned work.

Do not present placeholder or unmeasured values as results. Save the dataset hash, prompt hashes, report, and environment snapshot with the recording artifacts.
