"""Where fetched transactions live between runs, and what is still missing.

Re-scanning a month of blocks on every invocation is slow and rude to a public
endpoint, so a run records which block ranges it retrieved and later runs fetch
only the gaps.

The gap arithmetic is the part most likely to go quietly wrong - a dropped
range loses real payments, an overlapping one double-counts them - so it is
pure logic over an open connection, and it is tested on its own.
"""

import sqlite3
from pathlib import Path

_CACHE_DIR_NAME = ".x402-recon"


def cache_dir() -> Path:
    """Where per-address cache databases live."""
    return Path.home() / _CACHE_DIR_NAME


def cache_path(address: str) -> Path:
    """The cache database for one receiving address."""
    return cache_dir() / f"{address.lower()}.db"


def record_range(conn: sqlite3.Connection, from_block: int, to_block: int) -> None:
    """Record that a block range has been fetched."""
    conn.execute(
        "INSERT INTO fetched_ranges (from_block, to_block) VALUES (?, ?)",
        (from_block, to_block),
    )
    conn.commit()


def fetched_ranges(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """All fetched ranges, merged and sorted.

    Ranges that touch or overlap are merged: 100-150 and 151-200 cover every
    block from 100 to 200, and treating them as separate would invent a gap
    at 150/151 that does not exist.
    """
    rows = conn.execute(
        "SELECT from_block, to_block FROM fetched_ranges ORDER BY from_block"
    ).fetchall()
    merged: list[tuple[int, int]] = []
    for row in rows:
        start, end = row["from_block"], row["to_block"]
        if merged and start <= merged[-1][1] + 1:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def missing_ranges(
    conn: sqlite3.Connection, from_block: int, to_block: int
) -> list[tuple[int, int]]:
    """The sub-ranges of [from_block, to_block] that have not been fetched."""
    gaps: list[tuple[int, int]] = []
    cursor = from_block
    for start, end in fetched_ranges(conn):
        if end < cursor:
            continue
        if start > to_block:
            break
        if start > cursor:
            gaps.append((cursor, min(start - 1, to_block)))
        cursor = max(cursor, end + 1)
        if cursor > to_block:
            return gaps
    if cursor <= to_block:
        gaps.append((cursor, to_block))
    return gaps
