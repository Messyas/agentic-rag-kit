"""Smoke tests for the Typer CLI interface."""

from typer.testing import CliRunner

from rag_kit.interfaces.cli import app

runner = CliRunner()


def test_cli_help_lists_expected_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "index" in result.stdout
    assert "analyze" in result.stdout
    assert "eval" in result.stdout
    assert "check" in result.stdout


def test_cli_placeholder_command_logs_not_implemented() -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
