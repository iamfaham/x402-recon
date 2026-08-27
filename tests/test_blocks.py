# tests/test_blocks.py
import pytest

from x402_recon.blocks import (
    days_ago_range,
    first_block_at_or_after,
    last_block_at_or_before,
    resolve_range,
)

GENESIS = 1_700_000_000  # arbitrary epoch base for the fake chain
SPACING = 2              # seconds per block
HEAD = 100_000


class FakeChain:
    """A chain where block N has timestamp GENESIS + N*SPACING."""

    def __init__(self, head=HEAD):
        self.head = head
        self.calls = 0

    def call(self, method, params):
        self.calls += 1
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            if number > self.head or number < 0:
                return None
            return {"timestamp": hex(GENESIS + number * SPACING)}
        raise AssertionError(f"unexpected method {method}")


def test_finds_the_first_block_at_or_after_a_timestamp():
    chain = FakeChain()
    target = GENESIS + 500 * SPACING
    assert first_block_at_or_after(chain, target) == 500


def test_finds_the_first_block_after_when_the_target_falls_between_blocks():
    # Block 500 is at T, block 501 at T+2. A target of T+1 must round FORWARD,
    # because "from" means "at or after".
    chain = FakeChain()
    assert first_block_at_or_after(chain, GENESIS + 500 * SPACING + 1) == 501


def test_finds_the_last_block_at_or_before_a_timestamp():
    chain = FakeChain()
    assert last_block_at_or_before(chain, GENESIS + 500 * SPACING) == 500


def test_last_block_rounds_backward_between_blocks():
    # "to" means "at or before", so a target between 500 and 501 gives 500.
    chain = FakeChain()
    assert last_block_at_or_before(chain, GENESIS + 500 * SPACING + 1) == 500


def test_a_target_before_the_chain_starts_gives_the_first_block():
    chain = FakeChain()
    assert first_block_at_or_after(chain, GENESIS - 10_000) == 0


def test_a_target_after_head_gives_head_for_the_upper_bound():
    chain = FakeChain()
    assert last_block_at_or_before(chain, GENESIS + HEAD * SPACING + 10_000) == HEAD


def test_a_from_target_after_head_is_an_error_rather_than_an_empty_scan():
    chain = FakeChain()
    with pytest.raises(ValueError, match="after the latest block"):
        first_block_at_or_after(chain, GENESIS + HEAD * SPACING + 10_000)


def test_the_search_is_logarithmic_not_linear():
    # 100k blocks must not cost 100k requests. log2(100000) ~= 17, plus the
    # head lookup and a little slack.
    chain = FakeChain()
    first_block_at_or_after(chain, GENESIS + 500 * SPACING)
    assert chain.calls < 30


def test_resolve_range_uses_start_of_day_and_end_of_day():
    chain = FakeChain()
    # Build dates that land inside the fake chain's window.
    from datetime import datetime, timezone

    start_dt = datetime.fromtimestamp(GENESIS + 1_000 * SPACING, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(GENESIS + 5_000 * SPACING, tz=timezone.utc)
    from_block, to_block = resolve_range(
        chain, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    )
    assert from_block <= 1_000
    assert to_block >= 5_000
    assert from_block < to_block


def test_an_inverted_range_is_rejected_by_name():
    chain = FakeChain()
    with pytest.raises(ValueError, match="before"):
        resolve_range(chain, "2026-08-31", "2026-08-01")


def test_days_ago_range_ends_at_head():
    chain = FakeChain()
    from_block, to_block = days_ago_range(chain, 1)
    assert to_block == HEAD
    assert from_block < to_block
