import pytest

from x402_recon.cache import fetched_ranges, record_range
from x402_recon.db import connect, init_schema
from x402_recon.run import run_overview

ADDRESS = "0x" + "99" * 20
PAYER = "0x" + "11" * 20


class FakeClient:
    """Serves one Transfer log and records which ranges were asked for."""

    def __init__(self):
        self.ranges = []
        self.receipts = 0

    def get_logs(self, *, address, topics, from_block, to_block):
        self.ranges.append((from_block, to_block))
        if topics[2] is None:  # outbound query
            return []
        from x402_recon.chain import TRANSFER_TOPIC0

        pad = lambda a: "0x000000000000000000000000" + a[2:]
        return [
            {
                "transactionHash": "0xaaa",
                "topics": [TRANSFER_TOPIC0, pad(PAYER), pad(ADDRESS)],
                "data": "0x0f4240",
                "blockNumber": hex(from_block),
            }
        ]

    def block_timestamp(self, block_hex):
        return "2026-08-15T12:00:00Z"

    def transaction_receipt(self, tx_hash):
        self.receipts += 1
        return {"logs": []}


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "r.db")
    init_schema(connection)
    return connection


def test_it_fetches_ingests_categorizes_and_returns_an_overview(conn, tmp_path):
    overview = run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=FakeClient(), conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert overview.address == ADDRESS
    assert overview.report.payment_count == 1


def test_it_records_the_range_it_fetched(conn, tmp_path):
    run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=FakeClient(), conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert fetched_ranges(conn) == [(100, 200)]


def test_an_already_cached_range_is_not_refetched(conn, tmp_path):
    record_range(conn, 100, 200)
    client = FakeClient()
    run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=client, conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert client.ranges == [], "should not have hit the network at all"


def test_only_the_gap_is_fetched(conn, tmp_path):
    record_range(conn, 100, 150)
    client = FakeClient()
    run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=client, conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert all(start >= 151 for start, _ in client.ranges), client.ranges


def test_the_sample_can_be_switched_off(conn, tmp_path):
    client = FakeClient()
    run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=client, conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200, take_sample=False,
    )
    assert client.receipts == 0


def test_fetch_rejects_are_preserved_not_discarded(conn, tmp_path):
    class RejectingClient(FakeClient):
        def get_logs(self, *, address, topics, from_block, to_block):
            logs = super().get_logs(
                address=address, topics=topics, from_block=from_block, to_block=to_block
            )
            if topics[2] is not None:  # inbound query only
                logs.append({"transactionHash": "0xbad", "topics": ["0xwrong"]})
            return logs

    overview = run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=RejectingClient(), conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert any(tx_hash == "0xbad" for tx_hash, _ in overview.rejects)


def test_rejects_accumulate_across_multiple_gaps(conn, tmp_path):
    # Two disjoint pre-cached islands leave TWO real gaps: (121,149) and
    # (171,200). Verified: missing_ranges(conn, 100, 200) after these two
    # record_range calls returns exactly two ranges, so the orchestrator's
    # loop genuinely runs twice.
    record_range(conn, 100, 120)
    record_range(conn, 150, 170)

    class RejectingClient(FakeClient):
        def get_logs(self, *, address, topics, from_block, to_block):
            logs = super().get_logs(
                address=address, topics=topics, from_block=from_block, to_block=to_block
            )
            if topics[2] is not None:  # inbound query only
                logs.append(
                    {"transactionHash": f"0xbad{from_block}", "topics": ["0xwrong"]}
                )
            return logs

    overview = run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=RejectingClient(), conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    rejected_hashes = {tx_hash for tx_hash, _ in overview.rejects}
    # One rejected hash per gap iteration - confirms accumulation across
    # BOTH gaps, not just the last one.
    assert "0xbad121" in rejected_hashes
    assert "0xbad171" in rejected_hashes


def test_ingest_side_rejects_are_preserved(conn, tmp_path, monkeypatch):
    from x402_recon.ingest import IngestResult

    def fake_ingest(conn, source_dir):
        return IngestResult(
            inserted=0, skipped_duplicates=0, rejects=[("0xbadrow", "malformed amount")]
        )

    monkeypatch.setattr("x402_recon.run.ingest_from_dir", fake_ingest)

    overview = run_overview(
        address=ADDRESS, start_date="2026-08-01", end_date="2026-08-31",
        client=FakeClient(), conn=conn, work_dir=tmp_path / "w",
        from_block=100, to_block=200,
    )
    assert ("0xbadrow", "malformed amount") in overview.rejects
