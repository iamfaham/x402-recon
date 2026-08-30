"""Command-line interface for x402-recon.

Each pipeline stage is its own subcommand so stages can be re-run independently
while tuning.
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from x402_recon.blocks import days_ago_range, resolve_range
from x402_recon.cache import cache_dir, cache_path
from x402_recon.categorize import run_categorize
from x402_recon.customers import build_customer_report, render_customer_report
from x402_recon.db import SchemaVersionError, connect, init_schema
from x402_recon.discover import DiscoveryError, discover
from x402_recon.evaluate import render_axis_results, run_evaluate
from x402_recon.fetch import fetch_transactions, format_fetch_summary, write_fetched
from x402_recon.ingest import IngestError, format_ingest_summary, ingest_from_dir
from x402_recon.labeling import build_worksheet, write_worksheet
from x402_recon.models import AXIS_COUNT
from x402_recon.overview import render_overview
from x402_recon.rejects import render_rejects, write_rejects
from x402_recon.report import build_report, render_summary, write_csv
from x402_recon.rpc import DEFAULT_BASE_RPC_URL, RpcClient, RpcError
from x402_recon.run import run_overview
from x402_recon.shape import build_shape, render_shape
from x402_recon.simulate import generate_batch, write_batch

_DATE_FORMAT = "%Y-%m-%d"
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_DEFAULT_DB_NAME = "x402-recon.db"
_KNOWN_COMMANDS = {
    "simulate", "ingest", "categorize", "shape", "label", "report",
    "customers", "evaluate", "fetch", "discover",
}

# Machinery for validating the tool's own accuracy rather than for reporting
# on payments. Hidden from the default help via argparse.SUPPRESS, which
# leaves them fully working - nothing that exists today breaks - and listed
# by `--advanced`, because a command that cannot be found is worse than one
# that is merely verbose.
ADVANCED_COMMANDS = frozenset({"simulate", "shape", "label", "evaluate"})


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
        prog="x402-recon",
        description=(
            "Organize agent stablecoin payments into a readable summary. "
            "This tool reads and summarizes payments you have already received. "
            "It never holds or moves funds, and it is not tax or accounting advice."
        ),
        epilog="Run --advanced to list research and validation commands.",
    )
    parser.add_argument(
        "--advanced",
        action="store_true",
        help="list the research and validation commands",
    )
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("address", nargs="?", help="the receiving address to report on")
    parser.add_argument("--url", help="an x402 endpoint; its payTo is discovered")
    parser.add_argument("--last", help="window ending now, e.g. 30d")
    parser.add_argument("--from", dest="start", type=_valid_date, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", type=_valid_date, help="YYYY-MM-DD")
    parser.add_argument("--rpc-url", default=DEFAULT_BASE_RPC_URL)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=f"use a temporary database instead of {cache_dir()}",
    )
    parser.add_argument(
        "--no-sample", action="store_true", help="skip the x402 settlement sample"
    )
    parser.add_argument(
        "--full-addresses",
        action="store_true",
        help="show addresses in full instead of shortened",
    )
    # metavar="command" keeps the usage line from spelling out every
    # subcommand name (including the hidden ones) as {simulate,ingest,...}.
    sub = parser.add_subparsers(dest="command", required=False, metavar="command")

    simulate = sub.add_parser("simulate", help=argparse.SUPPRESS)
    simulate.add_argument("--out", required=True, help="directory to write JSON into")
    simulate.add_argument("--count", type=int, default=120)
    simulate.add_argument("--seed", type=int, default=42)

    ingest = sub.add_parser("ingest", help="load transactions into the database")
    ingest.add_argument("--from", dest="source", required=True, help="source directory")

    sub.add_parser("categorize", help="run the categorization cascade")

    sub.add_parser("shape", help=argparse.SUPPRESS)

    label = sub.add_parser("label", help=argparse.SUPPRESS)
    label.add_argument("--out", required=True, help="path to write the worksheet JSON")

    report = sub.add_parser("report", help="summarize a date range")
    report.add_argument(
        "--from", dest="start", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument(
        "--to", dest="end", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    report.add_argument("--csv", help="also write line-item detail to this CSV path")
    report.add_argument(
        "--full-addresses",
        action="store_true",
        help="show payer addresses in full instead of shortened",
    )

    customers = sub.add_parser(
        "customers", help="split payers into returning vs one-shot for a date range"
    )
    customers.add_argument(
        "--from", dest="start", required=True, type=_valid_date, help="YYYY-MM-DD"
    )
    customers.add_argument(
        "--to", dest="end", required=True, type=_valid_date, help="YYYY-MM-DD"
    )

    sub.add_parser("evaluate", help=argparse.SUPPRESS)

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

    discover_cmd = sub.add_parser(
        "discover", help="read the receiving address out of an x402 endpoint's 402 response"
    )
    discover_cmd.add_argument("url", help="an x402 endpoint")

    # help=argparse.SUPPRESS above is meant to drop a subparser from the
    # choices listing outright, but on this argparse (CPython 3.13) the
    # pseudo-action is still appended and its help renders as the literal
    # string "==SUPPRESS==" instead of being omitted. Filter those entries
    # out explicitly so the four advanced commands are actually hidden,
    # regardless of that rendering quirk.
    sub._choices_actions = [
        action for action in sub._choices_actions if action.help != argparse.SUPPRESS
    ]

    return parser


def _parse_last(value: str) -> int:
    """Parse `--last` values like '30d' into a day count."""
    match = re.fullmatch(r"(\d+)d", value)
    if not match:
        raise ValueError(f"invalid --last {value!r}: expected a form like '30d'")
    return int(match.group(1))


def _run_overview_command(args: argparse.Namespace) -> int:
    """Discover/validate an address, resolve its block range, and render the overview."""
    if not args.address and not args.url:
        _build_parser().print_help()
        return 2

    address = args.address
    source_url = None
    if args.url:
        try:
            requirements = discover(args.url)
        except DiscoveryError as exc:
            print(f"Error: {exc}")
            return 2
        address = requirements.pay_to
        source_url = args.url

    if not _ADDRESS_RE.match(address or ""):
        print(f"Error: {address!r} is not a valid address")
        return 2

    today = datetime.now(timezone.utc).date()

    try:
        client = RpcClient(args.rpc_url)

        if args.last and (args.start or args.end):
            print("Error: --last cannot be combined with --from/--to")
            return 2

        if args.last:
            try:
                days = _parse_last(args.last)
            except ValueError as exc:
                print(f"Error: {exc}")
                return 2
            start_date = (today - timedelta(days=days)).isoformat()
            end_date = today.isoformat()
            from_block, to_block = days_ago_range(client, days)
        elif args.start and args.end:
            start_date, end_date = args.start, args.end
            from_block, to_block = resolve_range(client, args.start, args.end)
        elif args.start or args.end:
            print("Error: both --from and --to are required together")
            return 2
        else:
            start_date = (today - timedelta(days=30)).isoformat()
            end_date = today.isoformat()
            from_block, to_block = days_ago_range(client, 30)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    except RpcError as exc:
        print(f"Error: {exc}")
        print("If this endpoint is rate-limiting, pass --rpc-url with your own provider.")
        return 2

    if args.no_cache:
        fd, tmp_name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db_path = Path(tmp_name)
    else:
        cache_dir().mkdir(parents=True, exist_ok=True)
        db_path = cache_path(address)

    conn = None
    try:
        try:
            conn = connect(db_path)
            init_schema(conn)
        except SchemaVersionError as exc:
            print(f"Error: {exc}")
            print(f"Delete {db_path} and run again.")
            return 2

        work_dir = Path(tempfile.mkdtemp())
        try:
            overview = run_overview(
                address=address,
                start_date=start_date,
                end_date=end_date,
                client=client,
                conn=conn,
                source_url=source_url,
                take_sample=not args.no_sample,
                work_dir=work_dir,
                from_block=from_block,
                to_block=to_block,
            )
        except RpcError as exc:
            print(f"Error: {exc}")
            print(
                "If this endpoint is rate-limiting, pass --rpc-url with your own provider."
            )
            return 2
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        print(render_overview(overview, redact=not args.full_addresses))
        rejects = getattr(overview, "rejects", None)
        if rejects:
            print(f"\n{len(rejects)} row(s) were skipped and excluded from these totals.")
            print(render_rejects(rejects))
            if not args.no_cache:
                # --no-cache means "write nothing to my machine". Honouring
                # that beats completeness; the inline detail above still shows
                # what was dropped.
                rejects_path = write_rejects(
                    rejects, cache_dir() / f"rejects-{address}.json"
                )
                print(f"\nFull list written to {rejects_path}")
        return 0
    finally:
        if args.no_cache:
            close = getattr(conn, "close", None)
            if close is not None:
                close()
            db_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # `address` and the subparsers positional both sit at the top level, and
    # argparse's PARSER-nargs greedily claims the lone bare token even when a
    # subcommand isn't what's meant - so a plain address would otherwise be
    # rejected as an unrecognized command. Pull it out ourselves whenever the
    # first bare token isn't a known subcommand, before argparse ever sees it.
    address_arg = None
    if argv and not argv[0].startswith("-") and argv[0] not in _KNOWN_COMMANDS:
        address_arg = argv.pop(0)

    args = _build_parser().parse_args(argv)
    if address_arg is not None:
        args.address = address_arg

    if args.advanced:
        print("Research and validation commands:\n")
        for name in sorted(ADVANCED_COMMANDS):
            print(f"  {name}")
        print("\nRun `x402-recon <command> --help` for details on any of them.")
        return 0

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

    if args.command == "discover":
        try:
            requirements = discover(args.url)
        except DiscoveryError as exc:
            print(f"Error: {exc}")
            return 2
        print(f"payTo:   {requirements.pay_to}")
        print(f"network: {requirements.network}")
        print(f"asset:   {requirements.asset}")
        if requirements.amount is not None:
            print(f"amount:  {requirements.amount}")
        return 0

    if args.command is None:
        return _run_overview_command(args)

    try:
        conn = connect(Path(args.db or _DEFAULT_DB_NAME))
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
        print(render_summary(data, redact=not args.full_addresses))
        if args.csv:
            written = write_csv(conn, args.start, args.end, Path(args.csv))
            print(f"\nWrote {written} rows to {args.csv}")
            print(
                "  This file contains full addresses and transaction hashes. "
                "Review before sharing."
            )
        return 0

    if args.command == "customers":
        print(render_customer_report(build_customer_report(conn, args.start, args.end)))
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
