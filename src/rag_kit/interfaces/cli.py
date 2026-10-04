"""Typer command-line interface entry point.

Pattern: Adapter.
"""

import asyncio
import sys

import structlog
import typer

app = typer.Typer(
    name="rag-kit",
    help="Agentic RAG Kit CLI for local analysis and ingestion.",
    no_args_is_help=True,
)
logger = structlog.get_logger(__name__)


@app.command()
def ingest() -> None:
    """Ingest raw occurrence or context files."""
    logger.info("command_invoked", command="ingest", status="not_implemented")


@app.command()
def index() -> None:
    """Index chunks into the vector store."""
    logger.info("command_invoked", command="index", status="not_implemented")


@app.command()
def analyze() -> None:
    """Run automated analysis on occurrences."""
    logger.info("command_invoked", command="analyze", status="not_implemented")


@app.command(name="eval")
def evaluate() -> None:
    """Run evaluation benchmark against ground truth."""
    logger.info("command_invoked", command="eval", status="not_implemented")


@app.command()
def check() -> None:
    """Verify local environment, models, and database."""
    logger.info("command_invoked", command="check", status="not_implemented")


def main() -> None:
    """CLI execution entrypoint setting WindowsSelectorEventLoopPolicy when on win32."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportDeprecated]
    app()


if __name__ == "__main__":
    main()
