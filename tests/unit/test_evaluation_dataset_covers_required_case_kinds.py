"""The versioned synthetic dataset has held-out cases and complete kind coverage."""

from pathlib import Path

from evaluation.dataset import load_dataset


def test_evaluation_dataset_validates_corpus_references_and_splits() -> None:
    dataset = load_dataset(Path("evaluation/datasets"))

    assert len(dataset.cases) == 48
    assert {case.kind for case in dataset.cases} == {
        "answerable",
        "unanswerable",
        "prompt_injection",
        "layout_variant",
    }
    assert {case.split for case in dataset.cases} == {"dev", "test"}
    documents = {document.document_id: document for document in dataset.corpus}
    for case in dataset.cases:
        if case.ground_truth.required_source_ids:
            source = documents[case.ground_truth.required_source_ids[0]]
            assert source.metadata["component_family"] == case.subject_fields["component_family"]
