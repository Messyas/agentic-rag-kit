"""Architecture and convention tests enforcing Clean Code Charter rules."""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_ROOTS = (Path("src/rag_kit"), Path("packs"))
FORBIDDEN_MODULE_NAMES = {"utils", "helpers", "common", "misc"}
FORBIDDEN_CLASS_SUFFIXES = (
    "Manager",
    "Helper",
    "Util",
    "Utils",
    "Handler",
)  # event handlers are named *Subscriber
ALLOWED_MODULE_LEVEL_MUTABLES = {
    "LLM_CLIENTS",
    "EMBEDDERS",
    "RERANKERS",
    "RETRIEVERS",
    "GRADERS",
    "CHUNKERS",
    "ROUTING_STRATEGIES",
    "CORRECTION_STRATEGIES",
    "TOOL_CALLING_STRATEGIES",
    "PIPELINES",
}


def _python_files() -> list[Path]:
    return [p for root in SOURCE_ROOTS for p in root.rglob("*.py")]


@pytest.mark.parametrize("path", _python_files(), ids=str)
def test_module_name_is_not_a_junk_drawer(path: Path) -> None:
    assert path.stem not in FORBIDDEN_MODULE_NAMES


@pytest.mark.parametrize("path", _python_files(), ids=str)
def test_class_names_are_not_vague(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    vague = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name.endswith(FORBIDDEN_CLASS_SUFFIXES)
    ]
    assert not vague, f"{path}: vague class names {vague}"


@pytest.mark.parametrize("path", _python_files(), ids=str)
def test_no_global_statement_and_no_module_level_mutable_state(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Global)], (
        f"{path}: `global` is forbidden"
    )
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Dict, ast.Set)):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            assert names <= ALLOWED_MODULE_LEVEL_MUTABLES or all(
                n.isupper() and n.startswith("_") for n in names
            ), f"{path}: module-level mutable {names}"


def test_test_names_are_sentences() -> None:
    pattern = re.compile(r"^test_[a-z0-9]+(_[a-z0-9]+){2,}$")  # at least three words
    offenders = []
    for path in Path("tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path}:{n.name}"
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
            and not pattern.match(n.name)
        ]
    assert not offenders, offenders


def test_import_linter_contracts_are_satisfied() -> None:
    cmd = [sys.executable, "-m", "importlinter.cli"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0, f"import-linter failed:\n{res.stdout}\n{res.stderr}"
