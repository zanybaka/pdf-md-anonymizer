"""QA-001: synthetic labelled corpus and the precision/recall harness."""

import re

from anonymizer.api import Options
from anonymizer.detect import detect_all
from tests.evaluate_corpus import evaluate, format_report, load_corpus


def test_corpus_loads_labelled_documents():
    corpus = load_corpus()
    assert corpus, "no corpus documents found under tests/corpus/"
    for doc in corpus:
        assert doc["text"].strip()
        assert doc["expected"]
        for span in doc["expected"]:
            assert span["category"] and span["value"]


def test_harness_reports_per_category_metrics():
    metrics = evaluate(load_corpus())
    assert metrics
    for m in metrics.values():
        assert 0.0 <= m["precision"] <= 1.0
        assert 0.0 <= m["recall"] <= 1.0
    report = format_report(metrics)
    assert "precision" in report and "recall" in report


def test_recall_regression_is_visible_in_the_numbers():
    corpus = load_corpus()
    baseline = evaluate(corpus)
    # Pick a category the corpus actually exercises and the detector finds.
    category = next(
        c for c, m in baseline.items()
        if m["tp"] + m["fn"] > 0 and m["recall"] > 0.0
    )

    def broken_detect(text):
        # Deliberate regression: this category is no longer detected.
        return [s for s in detect_all(text, Options())
                if s.category != category]

    regressed = evaluate(corpus, detect_fn=broken_detect)
    assert regressed[category]["recall"] < baseline[category]["recall"]


def test_pos_filter_improves_loc_precision_on_corpus():
    # NER-007: the noisy-transcript corpus document leaks a LOC false positive
    # ("Вокруг") when the ORG/LOC POS filter is off; with it on (default) LOC
    # precision over the corpus is clean.
    corpus = load_corpus()
    on = evaluate(corpus, detect_fn=lambda t: detect_all(t, Options()))
    off = evaluate(
        corpus,
        detect_fn=lambda t: detect_all(t, Options(ner_pos_filter=False)),
    )
    on_loc = on.get("LOC", {}).get("precision", 1.0)
    off_loc = off.get("LOC", {}).get("precision", 1.0)
    assert on_loc > off_loc


def test_corpus_contains_no_real_pii():
    # Synthetic data only: email addresses use reserved test/example TLDs and
    # the only company is the «Рога и Копыта» placeholder.
    for doc in load_corpus():
        text = doc["text"]
        for email in re.findall(r"[\w.\-]+@[\w.\-]+", text):
            assert email.endswith((".test", ".example", ".invalid")), email
