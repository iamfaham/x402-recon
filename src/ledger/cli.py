"""Command-line interface for Ledger.

Each pipeline stage is its own subcommand so stages can be re-run independently
while tuning.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from ledger.categorize import run_categorize
from ledger.db import connect, init_schema
from ledger.evaluate import render_evaluation, run_evaluate
from ledger.ingest import format_ingest_summary, ingest_from_dir
from ledger.report import build_report, render_summary, write_csv
from ledger.simulate import generate_batch, write_batch

_DATE_FORMAT = "%Y-%m-%d"


def _valid_date(value: str) -> str:
    """argparse `type=` validator for --from/--to.

    Must be strict zero-padded YYYY-MM-DD. strptime already rejects
    out-of-range values like "2026-13-99", but it happily accepts unpadded
    input like "2026-8-1", which is exactly what a non-technical user is
    likely to type. Re-formatting the parsed value and comparing it back to
    the original catches that case too, so a date the user almost certainly
    did not mean is never silently accepted.
    """
    try:
        parsed = datetime.strptime(value, _DATE_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}: expected YYYY-MM-DD (zero-padded), "
            f"e.g. 2026-08-01 ({exc})"
        ) from None
    if parsed.strftime(_DATE_FORMAT) != value:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}: expected YYYY-MM-DD (zero-padded), "
            f"e.g. 2026-08-01"
        )
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger",
        description=(
            "Organize agent stablecoin payments into a readable summary. "
            "This tool reads and summarizes payments you have already received. "
            "It never holds or moves funds, and it is not tax or accounting advice."
        ),
    )
    parser.add_argument("--db", default="ledger.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    simulate = sub.add_parser("simulate", help="generate a synthetic transaction batch")
    simulate.add_argument("--out", required=True, help="directory to write JSON into")
    simulate.add_argument("--count", type=int, default=120)
    simulate.add_argument("--seed", type=int, default=42)

    ingest = sub.add_parser("ingest", help="load transactions into the database")
    ingest.add_argument("--from", dest="source", required=True, help="source directory")

    sub.add_parser("categorize", help="run the categorization cascade")

    report = sub.add_parser("report", help="summarize a date range")
    report.add_argument(
        "--from", dest="start", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument(
        "--to", dest="end", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument("--csv", help="also write line-item detail to this CSV path")

    sub.add_parser("evaluate", help="score categorization against ground truth")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "simulate":
        batch = generate_batch(count=args.count, seed=args.seed)
        tx_path, gt_path, hz_path = write_batch(batch, Path(args.out))
        print(f"Generated {len(batch.transactions)} transactions.")
        for path in (tx_path, gt_path, hz_path):
            print(f"  {path}")
        return 0

    conn = connect(Path(args.db))
    init_schema(conn)

    if args.command == "ingest":
        print(format_ingest_summary(ingest_from_dir(conn, Path(args.source))))
        return 0

    if args.command == "categorize":
        print(f"Categorized {run_categorize(conn)} transactions.")
        return 0

    if args.command == "report":
        data = build_report(conn, args.start, args.end)
        print(render_summary(data))
        if args.csv:
            written = write_csv(conn, args.start, args.end, Path(args.csv))
            print(f"\nWrote {written} rows to {args.csv}")
        return 0

    if args.command == "evaluate":
        result = run_evaluate(conn)
        if result is None:
            print(
                "No ground truth available, so accuracy cannot be scored.\n"
                "Ground truth comes from simulated data, or from a hand-labeled sample."
            )
            return 1
        print(render_evaluation(result))
        return 0

    return 1


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
