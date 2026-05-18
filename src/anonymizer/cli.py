"""The ``anon`` command-line entrypoint."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from anonymizer.api import Options, anonymize
from anonymizer.batch import process_files, read_input
from anonymizer.mapping import dumps_map, load_map, restore


_EXAMPLES = """\
examples:
  anon doc.md                                  writes doc.anon.md (no map by default)
  anon doc.pdf                                  same, from a PDF (via pdf2md)
  anon doc.md --map out.map.json               writes doc.anon.md + out.map.json
  anon doc.md -o out.md --map out.map.json     explicit output paths
  cat doc.md | anon -                          read from stdin, write to stdout
  anon "docs/*.pdf" -o outdir/                 batch: many files into a directory
  anon --no-ner-org doc.md                     keep organization names as-is
  anon restore out.md --map out.map.json -o original.md
                                               restore the original text
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anon",
        description="Anonymize PDF or Markdown documents by replacing private "
        "data with reversible {{TOKEN}} placeholders.",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    anon = sub.add_parser("anonymize", help="Anonymize one or more documents (default)")
    _add_anonymize_args(anon)

    restore_p = sub.add_parser("restore", help="Restore original text from a map")
    restore_p.add_argument("input", help="Anonymized Markdown file, or '-' for stdin")
    restore_p.add_argument("-o", "--output", help="Output file (default: stdout)")
    restore_p.add_argument("--map", required=True, help="Replacement map JSON file")

    return parser


def _add_anonymize_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "input",
        nargs="+",
        help="Input .pdf/.md file(s), glob pattern(s), or '-' for stdin",
    )
    p.add_argument(
        "-o", "--output",
        help="Output file (single input) or directory (multiple inputs); "
        "default: <name>.anon.md next to each input",
    )
    p.add_argument(
        "--map",
        help="Map JSON file (single input) or directory (multiple inputs); "
        "default: not written (opt-in)",
    )
    p.add_argument(
        "--ner-org", action=argparse.BooleanOptionalAction, default=True,
        help="Tokenize organizations via NER (default: on)",
    )
    p.add_argument(
        "--ner-loc", action=argparse.BooleanOptionalAction, default=True,
        help="Tokenize locations via NER (default: on)",
    )
    p.add_argument(
        "--consistency-sweep", action=argparse.BooleanOptionalAction, default=True,
        help="Propagate each detected value to its other occurrences (default: on)",
    )
    p.add_argument(
        "--ner-pos-filter", action=argparse.BooleanOptionalAction, default=True,
        help="Drop ORG/LOC NER spans built only from common nouns (default: on)",
    )
    p.add_argument("--llm", action="store_true", help="Enable local Ollama detection pass")
    p.add_argument(
        "--pdf2md-cmd", default=None,
        help="pdf2md executable (default: the env-local pdf2md, else pdf2md on PATH)",
    )


def _expand_inputs(patterns: list[str]) -> list[str]:
    """Expand glob patterns; keep '-' and literal paths as given."""
    expanded: list[str] = []
    for pattern in patterns:
        if pattern == "-":
            expanded.append(pattern)
            continue
        matches = sorted(glob.glob(pattern, recursive=True))
        expanded.extend(matches if matches else [pattern])
    return expanded


_STAGE_LABELS = {"converting": "converting PDF…", "detecting": "detecting…"}


def _run_single(inp: str, args: argparse.Namespace, options: Options) -> int:
    is_stdin = inp == "-"

    def on_stage(stage: str) -> None:
        print(f"anon: {_STAGE_LABELS.get(stage, stage)}", file=sys.stderr)

    try:
        if is_stdin:
            text = sys.stdin.read()
        else:
            text = read_input(inp, args.pdf2md_cmd, on_stage)
    except Exception as exc:  # noqa: BLE001
        print(f"anon: {exc}", file=sys.stderr)
        return 1

    on_stage("detecting")
    result = anonymize(text, options)

    # Output: explicit -o; else stdout for stdin; else <stem>.anon.md next to
    # the input file.
    if args.output:
        out_path: Path | None = Path(args.output)
    elif is_stdin:
        out_path = None
    else:
        src = Path(inp)
        out_path = src.with_name(f"{src.stem}.anon.md")

    # Map: explicit --map only; no automatic side-write.
    map_path: Path | None = Path(args.map) if args.map else None

    if out_path is None:
        sys.stdout.write(result.text)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.text, encoding="utf-8")

    if map_path is not None:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(dumps_map(result.mapping), encoding="utf-8")

    if out_path is None:
        print("anon: done", file=sys.stderr)
    else:
        written = str(out_path)
        if map_path is not None:
            written += f", {map_path}"
        print(f"anon: done — wrote {written}", file=sys.stderr)
    return 0


def _run_batch(inputs: list[str], args: argparse.Namespace, options: Options) -> int:
    output_dir = Path(args.output) if args.output else Path(".")
    map_dir: Path | None = Path(args.map) if args.map else None
    output_dir.mkdir(parents=True, exist_ok=True)
    if map_dir is not None:
        map_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)

    def on_stage(index: int, count: int, path: Path, stage: str) -> None:
        label = _STAGE_LABELS.get(stage, stage)
        print(f"[{index}/{count}] {path.name} — {label}", file=sys.stderr)

    failed = 0
    for i, result in enumerate(
        process_files(
            inputs,
            output_dir=output_dir,
            map_dir=map_dir,
            options=options,
            pdf2md_cmd=args.pdf2md_cmd,
            on_stage=on_stage,
        ),
        start=1,
    ):
        if result.status == "failed":
            failed += 1
            print(
                f"[{i}/{total}] FAILED {result.input_path}: {result.error}",
                file=sys.stderr,
            )
        elif result.status == "cancelled":
            print(f"[{i}/{total}] cancelled {result.input_path}", file=sys.stderr)
        else:
            print(
                f"[{i}/{total}] {result.input_path} → {result.output_path}",
                file=sys.stderr,
            )
    return 1 if failed else 0


def _run_anonymize(args: argparse.Namespace) -> int:
    options = Options(
        ner_org=args.ner_org,
        ner_loc=args.ner_loc,
        llm=args.llm,
        consistency_sweep=args.consistency_sweep,
        ner_pos_filter=args.ner_pos_filter,
    )
    inputs = _expand_inputs(args.input)

    if len(inputs) == 1:
        return _run_single(inputs[0], args, options)

    if "-" in inputs:
        print("anon: stdin ('-') cannot be combined with other inputs", file=sys.stderr)
        return 1
    return _run_batch(inputs, args, options)


def _run_restore(args: argparse.Namespace) -> int:
    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.input).read_text(encoding="utf-8")
        mapping = load_map(args.map)
    except Exception as exc:  # noqa: BLE001
        print(f"anon restore: {exc}", file=sys.stderr)
        return 1

    original = restore(text, mapping)
    if args.output:
        Path(args.output).write_text(original, encoding="utf-8")
    else:
        sys.stdout.write(original)
    return 0


def main() -> None:
    argv = sys.argv[1:]
    # Allow `anon INPUT ...` without the explicit `anonymize` subcommand.
    if argv and argv[0] not in ("anonymize", "restore", "-h", "--help"):
        argv = ["anonymize", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(2)
    if args.command == "restore":
        sys.exit(_run_restore(args))
    sys.exit(_run_anonymize(args))


if __name__ == "__main__":
    main()
