"""Typer command-line interface for local ingestion and environment checks."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer
from evaluation.dataset import load_dataset
from evaluation.draft_eval import DraftEvalOptions, evaluate_drafts
from evaluation.hanaro_draft_eval import HanaroEvalOptions, evaluate_hanaro_data
from evaluation.local import LocalEvaluationOptions, evaluate_local
from packs.scrap.assistant_schemas import AssistantDraft, ReportRequest, ReviewRequest
from packs.scrap.local_batch import build_local_requests, reviewed_evidence
from pydantic import TypeAdapter

from rag_kit.application.ingestion.pipeline import prepare_table
from rag_kit.bootstrap.container import Container
from rag_kit.bootstrap.settings import Settings
from rag_kit.domain.models import Document, SourceRef

if TYPE_CHECKING:
    from rag_kit.domain.draft_jobs import ReviewState

app = typer.Typer(
    name="rag-kit",
    help="Local Agentic RAG Kit for scrap occurrence analysis.",
    no_args_is_help=True,
)
database_app = typer.Typer(help="Manage the local PostgreSQL/pgvector schema.")
app.add_typer(database_app, name="db")
draft_app = typer.Typer(help="Generate local scrap drafts and review the queue.")
app.add_typer(draft_app, name="draft")


@draft_app.command("batch")
def draft_batch(
    files: Annotated[list[Path], typer.Argument(exists=True, readable=True)],
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    reviews: Annotated[Path | None, typer.Option("--reviews", exists=True, readable=True)] = None,
) -> None:
    """Ingest spreadsheets and generate reviewable drafts automatically."""
    asyncio.run(_draft_batch(files, queue_path, limit, reviews))


async def _draft_batch(
    files: list[Path], queue_path: Path, limit: int | None, reviews: Path | None
) -> None:
    settings = Settings()
    _require_local_llm(settings)
    async with Container(settings) as container:
        jobs = container.build_draft_jobs(queue_path)
        review_text = (
            await asyncio.to_thread(reviews.read_text, encoding="utf-8") if reviews else ""
        )
        reviewed = reviewed_evidence(
            [json.loads(line) for line in review_text.splitlines() if line.strip()]
        )
        accepted = 0
        created = 0
        for file_path in files:
            if file_path.suffix.lower() not in {".csv", ".xlsx", ".tsv", ".txt", ""}:
                raise typer.BadParameter(f"unsupported file type: {file_path.suffix}")  # noqa: TRY003
            table = container.load_table(file_path)
            prepared = prepare_table(table, container.pack.column_specs)
            remaining = None if limit is None else max(limit - accepted, 0)
            pairs = build_local_requests(
                prepared.rows, file_path.name, limit=remaining, reviewed=reviewed
            )
            accepted += len(pairs)
            created += len(jobs.enqueue_batch([request for pair in pairs for request in pair]))
            typer.echo(
                json.dumps(
                    {
                        "file": str(file_path),
                        "rows_read": len(table.rows),
                        "rows_valid": len(prepared.rows),
                        "layout_adherence": prepared.layout.adherence,
                        "draft_pairs_queued": len(pairs),
                    },
                    ensure_ascii=False,
                )
            )
            if limit is not None and accepted >= limit:
                break
        completed = 0
        failed = 0
        while job := await jobs.process_one():
            completed += job.job_state == "COMPLETED"
            failed += job.job_state == "FAILED"
        typer.echo(json.dumps({"jobs_seen": created, "completed": completed, "failed": failed}))


def _require_local_llm(settings: Settings) -> None:
    from urllib.parse import urlparse  # noqa: PLC0415 - local policy only used by draft commands

    endpoints = (
        [backend.url for backend in settings.llm.balancer.backends]
        if settings.llm.balancer and settings.llm.balancer.backends
        else [settings.ollama.host if settings.llm.provider == "ollama" else settings.llm.base_url]
    )
    if any(urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"} for url in endpoints):
        raise typer.BadParameter("draft batch requires a local LLM endpoint")  # noqa: TRY003


@draft_app.command("queue")
def draft_queue(
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Show generated drafts waiting for analyst review."""
    queue = Container(Settings()).build_draft_queue(queue_path)
    for job in queue.list():
        typer.echo(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "subject_id": job.subject_id,
                    "kind": job.kind,
                    "job_state": job.job_state,
                    "review_state": job.review_state,
                    "attempts": job.attempts,
                },
                ensure_ascii=False,
            )
        )


@draft_app.command("submit")
def draft_submit(
    request_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Queue one versioned host-style review or report request."""
    _require_local_llm(Settings())
    data = json.loads(request_file.read_text(encoding="utf-8"))
    request = (
        ReviewRequest.model_validate(data)
        if "occurrence_id" in data
        else ReportRequest.model_validate(data)
    )

    async def submit() -> None:
        async with Container(Settings()) as container:
            jobs = container.build_draft_jobs(queue_path)
            typer.echo(jobs.enqueue(request).model_dump_json(indent=2))

    asyncio.run(submit())


@draft_app.command("run")
def draft_run(
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Process queued local drafts with the configured local model."""
    asyncio.run(_draft_run(queue_path))


@draft_app.command("eval")
def draft_evaluate(
    output: Annotated[Path, typer.Option("--output")] = Path("evaluation/runs/draft-eval"),
    repetitions: Annotated[int, typer.Option("--repetitions", min=1)] = 1,
) -> None:
    """Compare deterministic and local LLM drafts on the same synthetic cases."""
    settings = Settings()
    _require_local_llm(settings)
    result = asyncio.run(
        evaluate_drafts(
            settings,
            DraftEvalOptions(
                cases_path=Path("evaluation/datasets/draft_cases.jsonl"),
                source_path=Path("examples/hanaro_contract/demo_scrap.csv"),
                reviews_path=Path("examples/hanaro_contract/demo_reviews.jsonl"),
                output_dir=output,
                repetitions=repetitions,
            ),
        )
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@draft_app.command("eval-data")
def draft_evaluate_data(
    source_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output")] = Path("evaluation/runs/hanaro-draft-eval"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=250)] = 24,
    resume: Annotated[bool, typer.Option("--resume")] = False,  # noqa: FBT002 - CLI flag
    repetitions: Annotated[int, typer.Option("--repetitions", min=1, max=10)] = 3,
) -> None:
    """Benchmark evidence integrity on stratified anonymized Hanaro rows."""
    settings = Settings()
    _require_local_llm(settings)
    result = asyncio.run(
        evaluate_hanaro_data(
            settings, HanaroEvalOptions(source_path, output, limit, resume, repetitions)
        )
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


async def _draft_run(queue_path: Path) -> None:
    settings = Settings()
    _require_local_llm(settings)
    async with Container(settings) as container:
        jobs = container.build_draft_jobs(queue_path)
        while job := await jobs.process_one():
            typer.echo(
                json.dumps(
                    {
                        "job_id": job.job_id,
                        "job_state": job.job_state,
                        "review_state": job.review_state,
                        "error": job.error,
                    },
                    ensure_ascii=False,
                )
            )


@draft_app.command("show")
def draft_show(
    job_id: str,
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Inspect a draft, its 4M matrix, citations and gaps."""
    job = Container(Settings()).build_draft_queue(queue_path).get(job_id)
    if job.result_json is None:
        typer.echo(job.model_dump_json(indent=2))
        return
    typer.echo(AssistantDraft.model_validate_json(job.result_json).model_dump_json(indent=2))


@draft_app.command("review")
def draft_review(
    job_id: str,
    decision: Annotated[str, typer.Option("--decision")],
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Record a local review decision; the future host applies approved content."""
    if decision not in {"ACCEPTED", "REJECTED", "NEEDS_INFORMATION"}:
        raise typer.BadParameter("decision must be ACCEPTED, REJECTED or NEEDS_INFORMATION")  # noqa: TRY003
    job = (
        Container(Settings())
        .build_draft_queue(queue_path)
        .review(job_id, cast("ReviewState", decision))
    )
    typer.echo(job.model_dump_json(indent=2))


@draft_app.command("retry")
def draft_retry(
    job_id: str,
    queue_path: Annotated[Path, typer.Option("--queue")] = Path("evaluation/runs/drafts.sqlite3"),
) -> None:
    """Requeue a failed job while it remains under the attempt limit."""
    job = Container(Settings()).build_draft_queue(queue_path).retry(job_id)
    typer.echo(job.model_dump_json(indent=2))


@app.command()
def ingest(
    files: Annotated[list[Path], typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("evaluation/ingested"),
) -> None:
    """Read CSV/XLSX files and write normalized row JSONL files."""
    output.mkdir(parents=True, exist_ok=True)
    for file_path in files:
        suffix = file_path.suffix.lower()
        if suffix not in {".csv", ".xlsx", ".tsv", ".txt", ""}:
            typer.echo(f"unsupported file type: {suffix}", err=True)
            raise typer.Exit(2)
        container = Container(Settings())
        table = container.load_table(file_path)
        prepared = prepare_table(table, container.pack.column_specs)
        target = output / f"{file_path.stem}.jsonl"
        records = prepared.rows
        report = {
            "rows_received": len(table.rows),
            "rows_accepted": len(records),
            "layout": asdict(prepared.layout),
            "issues": [issue.model_dump(mode="json") for issue in prepared.validation.issues],
        }
        (output / f"{file_path.stem}.report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        target.write_text(
            "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in records),
            encoding="utf-8",
        )
        typer.echo(f"{file_path}: {len(records)} rows -> {target}")


@app.command()
def index(corpus: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Index source-backed documents from a corpus JSONL file."""
    asyncio.run(_index(corpus))


async def _index(path: Path) -> None:
    contents = await asyncio.to_thread(path.read_text, encoding="utf-8")
    records = [json.loads(line) for line in contents.splitlines() if line.strip()]
    documents = [
        Document(
            ref=SourceRef(
                source_type=record.get("source_type", "scrap_review"),
                source_id=record["document_id"],
                version=str(record.get("version", "1")),
            ),
            text=record["text"],
            metadata=record.get("metadata", {}),
        )
        for record in records
    ]
    async with Container(Settings()) as container:
        count = await container.build_facade().index_documents(documents)
    typer.echo(json.dumps({"indexed_chunks": count}))


@app.command()
def analyze(
    record: Annotated[Path, typer.Argument(exists=True, readable=True)],
    pipeline: Annotated[str, typer.Option("--pipeline")] = "corrective_rag",
) -> None:
    """Analyze a canonical host record supplied as a JSON object."""
    asyncio.run(_analyze(record, pipeline))


async def _analyze(path: Path, pipeline: str) -> None:
    contents = await asyncio.to_thread(path.read_text, encoding="utf-8")
    record = json.loads(contents)
    async with Container(Settings()) as container:
        result = await container.build_facade(pipeline_name=pipeline).analyze_record(record)
    typer.echo(result.model_dump_json(indent=2))


@app.command(name="eval")
def evaluate(
    dataset: Annotated[
        Path,
        typer.Option("--dataset", exists=True, readable=True, file_okay=True, dir_okay=True),
    ] = Path("evaluation/datasets"),
    validate_dataset: Annotated[bool, typer.Option("--validate-dataset")] = False,  # noqa: FBT002
    profile: Annotated[Path | None, typer.Option("--profile", exists=True, readable=True)] = None,
) -> None:
    """Validate data, inspect a JSONL, or evaluate all arms with a directory."""
    if validate_dataset:
        loaded = load_dataset(dataset)
        typer.echo(
            json.dumps(
                {
                    "cases": len(loaded.cases),
                    "corpus_documents": len(loaded.corpus),
                    "kinds": sorted({case.kind for case in loaded.cases}),
                    "splits": {
                        split: sum(case.split == split for case in loaded.cases)
                        for split in ("dev", "test")
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if profile is not None or dataset.is_dir():
        options = (
            TypeAdapter(LocalEvaluationOptions).validate_json(profile.read_text(encoding="utf-8"))
            if profile is not None
            else LocalEvaluationOptions(
                dataset, Path("evaluation/reports") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            )
        )
        summaries = asyncio.run(evaluate_local(Settings(), options))
        typer.echo(json.dumps(summaries, ensure_ascii=False, indent=2))
        return
    records = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        typer.echo("evaluation dataset is empty", err=True)
        raise typer.Exit(2)
    typer.echo(
        json.dumps({"cases": len(records), "fields": sorted(records[0])}, ensure_ascii=False)
    )


@app.command()
def check() -> None:
    """Check database schema, Ollama endpoint, and local evaluation data."""
    dataset_path = Path("evaluation/datasets/eval_cases.jsonl")
    available_dataset = dataset_path if dataset_path.exists() else None
    asyncio.run(_environment_report(available_dataset))


async def _environment_report(dataset_path: Path | None) -> None:
    settings = Settings()
    report = {
        "ollama_host": settings.ollama.host,
        "llm_model": settings.ollama.llm_model,
        "embedding_model": settings.ollama.embed_model,
        "database": settings.database.url.split("@")[-1],
        "dataset_exists": dataset_path is not None,
    }
    async with Container(settings) as container:
        report.update(await container.check_database())
        report.update(await container.check_ollama())
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


@database_app.command("upgrade")
def database_upgrade() -> None:
    """Create or update the pgvector tables and indexes."""
    asyncio.run(_upgrade_database())


async def _upgrade_database() -> None:
    async with Container(Settings()) as container:
        await container.upgrade_database()


def main() -> None:
    """Apply the Windows-compatible asyncio policy before invoking the CLI."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportDeprecated]
    app()


if __name__ == "__main__":
    main()
