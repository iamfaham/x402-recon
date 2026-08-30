"""Rows that could not be processed, and how to keep them.

"Nothing silently dropped" is one of this project's standing rules, and a
printed count alone does not satisfy it: the count survives, but which row was
dropped and why does not survive the scrollback. A skipped row must still be
inspectable tomorrow.

Rejects are rare in practice - the first real run against a live endpoint
skipped one row out of 5,349 - which is what makes inline detail affordable.
The cap exists because a systematic decode failure would invert that ratio.
"""

import json
from pathlib import Path


def render_rejects(rejects: list[tuple[str, str]], limit: int = 10) -> str:
    """Render skipped rows for the terminal, capped so a bad run cannot flood it."""
    if not rejects:
        return ""

    shown = rejects[:limit]
    lines = [f"  {tx_hash}: {reason}" for tx_hash, reason in shown]
    remaining = len(rejects) - len(shown)
    if remaining:
        lines.append(f"  ... and {remaining} more")
    return "\n".join(lines)


def write_rejects(rejects: list[tuple[str, str]], path: Path) -> Path:
    """Write the full reject list as JSON, and return the path written.

    An empty list still writes a file: "nothing was dropped" is a positive
    statement, and its absence would be indistinguishable from a run that
    never reached this point.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [{"tx_hash": tx_hash, "reason": reason} for tx_hash, reason in rejects],
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
