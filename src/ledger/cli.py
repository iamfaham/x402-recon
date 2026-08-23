"""Command-line interface for Ledger.

Each pipeline stage is its own subcommand so stages can be re-run independently
while tuning.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from ledger.categorize import run_categorize
from ledger.db import SchemaVersionError, connect, init_schema
from ledger.evaluate import render_axis_results, run_evaluate
from ledger.fetch import fetch_transactions, format_fetch_summary, write_fetched
from ledger.ingest import IngestError, format_ingest_summary, ingest_from_dir
from ledger.labeling import build_worksheet, write_worksheet
from ledger.models import AXIS_COUNT
from ledger.report import build_report, render_summary, write_csv
from ledger.rpc import DEFAULT_BASE_RPC_URL, RpcClient, RpcError
from ledger.shape import build_shape, render_shape
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

    sub.add_parser("shape", help="describe a batch's structure, with no scores")

    label = sub.add_parser("label", help="emit a worksheet for hand-labeling payers")
    label.add_argument("--out", required=True, help="path to write the worksheet JSON")

    report = sub.add_parser("report", help="summarize a date range")
    report.add_argument(
        "--from", dest="start", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument(
        "--to", dest="end", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument("--csv", help="also write line-item detail to this CSV path")

    sub.add_parser("evaluate", help="score categorization against ground truth")

    fetch = sub.add_parser("fetch", help="fetch real payments from the chain")
    fetch.add_argument("--receiver", required=True, help="the address that was paid")
    fetch.add_argument("--out", required=True, help="directory to write JSON into")
    fetch.add_argument("--from-block", type=int, required=True)
    fetch.add_argument("--to-block", type=int, required=True)
    fetch.add_argument(
        "--rpc-url",
        default=DEFAULT_BASE_RPC_URL,
        help="JSON-RPC endpoint (override to use your own node)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "simulate":
        batch = generate_batch(count=args.count, seed=args.seed)
        tx_path, gt_path, hz_path, st_path = write_batch(batch, Path(args.out))
        print(f"Generated {len(batch.transactions)} transactions.")
        for path in (tx_path, gt_path, hz_path, st_path):
            print(f"  {path}")
        return 0

    if args.command == "fetch":
        try:
            result = fetch_transactions(
                RpcClient(args.rpc_url),
                receiver=args.receiver,
                from_block=args.from_block,
                to_block=args.to_block,
            )
        except RpcError as exc:
            print(f"Error: {exc}")
            return 2
        path = write_fetched(result, Path(args.out))
        print(format_fetch_summary(result))
        print(f"  {path}")
        return 0

    try:
        conn = connect(Path(args.db))
        init_schema(conn)
    except SchemaVersionError as exc:
        print(f"Error: {exc}")
        return 2

    try:
        if args.command == "ingest":
            print(format_ingest_summary(ingest_from_dir(conn, Path(args.source))))
            return 0
    except IngestError as exc:
        print(f"Error: {exc}")
        return 2

    if args.command == "categorize":
        row_count = run_categorize(conn)
        transaction_count = row_count // AXIS_COUNT
        print(
            f"Categorized {transaction_count} transactions "
            f"({row_count} rows across {AXIS_COUNT} axes)."
        )
        return 0

    if args.command == "shape":
        print(render_shape(build_shape(conn)))
        return 0

    if args.command == "label":
        path = write_worksheet(build_worksheet(conn), Path(args.out))
        print(f"Wrote worksheet to {path}")
        print("Fill in true_group and evidence by hand, then convert to")
        print("ground_truth.json before ingesting.")
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
        print(render_axis_results(result))
        return 0

    return 1


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
