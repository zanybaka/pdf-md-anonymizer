"""QA-001: precision/recall evaluation harness over the synthetic corpus.

Dev tool — it lives under ``tests/`` and is not shipped in the installed
package (the wheel only contains ``src/anonymizer``). Run it from the repo
root with ``PYTHONPATH=src python -m tests.evaluate_corpus`` to print
per-category precision and recall over the labelled documents in
``tests/corpus/`` (``PYTHONPATH=src`` mirrors the ``pythonpath`` pytest setting
so the harness finds ``anonymizer`` without an editable install).

Each corpus document is a JSON object with:
  - ``name``: a short label
  - ``text``: the synthetic document text — fictional data only, never real PII
  - ``expected``: a list of ``{"category", "value"}`` the detector should find

Detection is scored on ``(category, value)`` pairs rather than exact character
offsets, so the corpus can be authored and extended without hand-counting
positions. Per category: a detected pair that is expected counts as a true
positive, an unexpected one as a false positive, an undetected expected pair
as a false negative; precision = tp/(tp+fp), recall = tp/(tp+fn).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from anonymizer.api import Options
from anonymizer.detect import detect_all

CORPUS_DIR = Path(__file__).parent / "corpus"


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[dict]:
    """Load numbered corpus documents (``NN-*.json``) from the corpus directory."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(p for p in corpus_dir.glob("*.json") if p.stem[:2].isdigit())
    ]


def _default_detect(text: str):
    return detect_all(text, Options())


def _pairs(items) -> Counter:
    return Counter((i["category"], i["value"]) for i in items)


def evaluate(corpus: list[dict], detect_fn=_default_detect) -> dict[str, dict]:
    """Score ``corpus`` per category, returning tp/fp/fn/precision/recall.

    ``detect_fn`` maps document text to a list of detected spans; it defaults
    to the real pipeline and can be swapped for a deliberately broken detector
    to confirm a recall regression shows up in the numbers.
    """
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    for doc in corpus:
        expected = _pairs(doc["expected"])
        detected = _pairs(
            {"category": s.category, "value": s.value} for s in detect_fn(doc["text"])
        )
        for (category, _value), count in detected.items():
            matched = min(count, expected.get((category, _value), 0))
            tp[category] += matched
            fp[category] += count - matched
        for (category, _value), count in expected.items():
            matched = min(count, detected.get((category, _value), 0))
            fn[category] += count - matched

    metrics: dict[str, dict] = {}
    for category in sorted(set(tp) | set(fp) | set(fn)):
        t, f, m = tp[category], fp[category], fn[category]
        metrics[category] = {
            "tp": t,
            "fp": f,
            "fn": m,
            "precision": t / (t + f) if (t + f) else 1.0,
            "recall": t / (t + m) if (t + m) else 1.0,
        }
    return metrics


def format_report(metrics: dict[str, dict]) -> str:
    """Render ``metrics`` as a fixed-width per-category table."""
    header = f"{'category':<12}{'precision':>11}{'recall':>9}{'tp':>6}{'fp':>6}{'fn':>6}"
    lines = [header, "-" * len(header)]
    for category, m in metrics.items():
        lines.append(
            f"{category:<12}{m['precision']:>11.2f}{m['recall']:>9.2f}"
            f"{m['tp']:>6}{m['fp']:>6}{m['fn']:>6}"
        )
    return "\n".join(lines)


def main() -> None:
    corpus = load_corpus()
    if not corpus:
        print(f"no corpus documents found in {CORPUS_DIR}")
        return
    metrics = evaluate(corpus)
    print(f"corpus: {len(corpus)} document(s) from {CORPUS_DIR}")
    print(format_report(metrics))


if __name__ == "__main__":
    main()
