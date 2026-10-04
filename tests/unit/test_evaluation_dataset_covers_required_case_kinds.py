"""The versioned synthetic dataset has held-out cases and complete kind coverage."""

from pathlib import Path

from evaluation.dataset import load_dataset


def test_evaluation_dataset_validates_corpus_references_and_splits() -> None:
    dataset = load_dataset(Path("evaluation/datasets"))

    assert len(dataset.cases) == 4
    assert {case.kind for case in dataset.cases} == {
        "answerable",
        "unanswerable",
        "prompt_injection",
        "layout_variant",
    }
    assert {case.split for case in dataset.cases} == {"dev", "test"}
