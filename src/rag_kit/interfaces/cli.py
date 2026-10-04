"""Typer command-line interface for local ingestion and environment checks."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from evaluation.dataset import load_dataset
from evaluation.local import LocalEvaluationOptions, evaluate_local
from pydantic import TypeAdapter

from rag_kit.application.ingestion.pipeline import prepare_table
from rag_kit.bootstrap.container import Container
from rag_kit.bootstrap.settings import Settings
from rag_kit.domain.models import Document, SourceRef

app = typer.Typer(
    name="rag-kit",
    help="Local Agentic RAG Kit for scrap occurrence analysis.",
    no_args_is_help=True,
)
database_app = typer.Typer(help="Manage the local PostgreSQL/pgvector schema.")
app.add_typer(database_app, name="db")


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
