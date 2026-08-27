"""The orchestrator: an address and a block range in, a rendered report out.

This is the only place in the codebase that knows the whole sequence - fetch
what's missing from the cache, ingest it, categorize it, sample it, render the
combined overview. Every step it calls already exists and is tested on its
own; this module just calls them in the right order and only over the blocks
that are actually missing.

Date-to-block resolution is deliberately not here. `from_block`/`to_block`
arrive already resolved as plain integers, so this module never imports
`blocks.py` and stays testable against a fake chain client with no notion of
real dates.
"""

import sqlite3
from pathlib import Path

from x402_recon.cache import missing_ranges, record_range
from x402_recon.categorize import run_categorize
from x402_recon.fetch import fetch_transactions, write_fetched
from x402_recon.ingest import ingest_from_dir
from x402_recon.models import TX_TYPE_PAYMENT
from x402_recon.overview import Overview, build_overview
from x402_recon.verify import sample_x402_settlement


def _tx_hashes_in_range(
    conn: sqlite3.Connection, start_date: str, end_date: str
) -> list[str]:
    """Payment tx hashes reported in this date range, for the settlement sample."""
    rows = conn.execute(
        "SELECT tx_hash FROM transactions "
        "WHERE tx_type = ? AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp, id",
        (TX_TYPE_PAYMENT, f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z"),
    ).fetchall()
    return [row["tx_hash"] for row in rows]


def run_overview(
    *,
    address: str,
    start_date: str,
    end_date: str,
    client,
    conn: sqlite3.Connection,
    source_url: str | None = None,
    take_sample: bool = True,
    work_dir: Path,
    from_block: int,
    to_block: int,
) -> Overview:
    """Fetch the gap, ingest it, categorize everything, and render an overview.

    Only the block ranges not already recorded in the cache are fetched from
    `client`. Each fetched sub-range is recorded as soon as it lands, so a
    failure partway through never marks unfetched blocks as fetched.
    """
    work_dir = Path(work_dir)

    for gap_start, gap_end in missing_ranges(conn, from_block, to_block):
        result = fetch_transactions(
            client, receiver=address, from_block=gap_start, to_block=gap_end
        )
        write_fetched(result, work_dir)
        ingest_from_dir(conn, work_dir)
        record_range(conn, gap_start, gap_end)

    run_categorize(conn)

    sample = None
    if take_sample:
        hashes = _tx_hashes_in_range(conn, start_date, end_date)
        sample = sample_x402_settlement(client, hashes)

    return build_overview(
        conn, address, start_date, end_date, source_url=source_url, sample=sample
    )
