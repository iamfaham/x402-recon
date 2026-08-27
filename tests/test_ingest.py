import json
from pathlib import Path

import pytest

from x402_recon.db import connect, init_schema, load_transactions
from x402_recon.ingest import IngestError, format_ingest_summary, ingest_from_dir
from x402_recon.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND


def write_source(tmp_path: Path, rows: list[dict], ground_truth: dict | None = None) -> Path:
    source = tmp_path / "data"
    source.mkdir(parents=True, exist_ok=True)
    (source / "transactions.json").write_text(json.dumps(rows))
    if ground_truth is not None:
        (source / "ground_truth.json").write_text(json.dumps(ground_truth))
    return source


def valid_row(tx_hash: str = "0x1", **overrides) -> dict:
    row = {
        "tx_hash": tx_hash,
        "sender_address": "0xsender",
        "receiver_address": "0xreceiver",
        "amount_micro_usdc": 1234,
        "timestamp": "2026-08-18T10:00:00Z",
        "memo": None,
        "chain": "base-sepolia-sim",
        "raw_payload": "{}",
    }
    row.update(overrides)
    return row


def fresh_conn(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    return conn


def test_ingests_valid_rows(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1"), valid_row("0x2")])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 2
    assert result.rejects == []
    assert len(load_transactions(conn)) == 2


def test_rerunning_ingest_skips_duplicates_rather_than_overwriting(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])

    ingest_from_dir(conn, source)
    second = ingest_from_dir(conn, source)

    assert second.inserted == 0
    assert second.skipped_duplicates == 1
    assert len(load_transactions(conn)) == 1


def test_rejects_row_missing_required_field(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    bad = valid_row("0x2")
    del bad["sender_address"]
    source = write_source(tmp_path, [valid_row("0x1"), bad])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 1
    assert len(result.rejects) == 1
    assert "sender_address" in result.rejects[0][1]


def test_rejects_negative_amount(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1", amount_micro_usdc=-5)])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 0
    assert len(result.rejects) == 1
    assert "amount" in result.rejects[0][1].lower()


def test_rejects_non_integer_amount(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1", amount_micro_usdc=1.5)])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 0
    assert len(result.rejects) == 1


def test_rejects_malformed_timestamp(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1", timestamp="18/08/2026")])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 0
    assert len(result.rejects) == 1
    assert "timestamp" in result.rejects[0][1]


def test_rejects_unpadded_timestamp(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(
        tmp_path, [valid_row("0x1", timestamp="2026-8-1T5:0:0Z")]
    )

    result = ingest_from_dir(conn, source)

    assert result.inserted == 0
    assert len(result.rejects) == 1
    assert "timestamp" in result.rejects[0][1].lower()
    assert "zero-padded" in result.rejects[0][1].lower()


def test_loads_ground_truth_when_present(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")], ground_truth={"0x1": "agent-a"})

    ingest_from_dir(conn, source)

    rows = conn.execute("SELECT tx_hash, true_group FROM ground_truth").fetchall()
    assert len(rows) == 1
    assert rows[0]["true_group"] == "agent-a"


def test_succeeds_without_ground_truth_file(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")], ground_truth=None)

    result = ingest_from_dir(conn, source)

    assert result.inserted == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM ground_truth").fetchone()["n"] == 0


def test_summary_reports_rejects_visibly(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    bad = valid_row("0x2")
    del bad["chain"]
    source = write_source(tmp_path, [valid_row("0x1"), bad])

    summary = format_ingest_summary(ingest_from_dir(conn, source))

    assert "1" in summary
    assert "reject" in summary.lower()
    assert "chain" in summary


def test_tx_type_defaults_to_payment_when_absent(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    ingest_from_dir(conn, source)
    row = conn.execute("SELECT tx_type FROM transactions").fetchone()
    assert row["tx_type"] == TX_TYPE_PAYMENT


def test_refund_tx_type_is_accepted(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1", tx_type=TX_TYPE_REFUND)])
    result = ingest_from_dir(conn, source)
    assert result.inserted == 1
    row = conn.execute("SELECT tx_type FROM transactions").fetchone()
    assert row["tx_type"] == TX_TYPE_REFUND


def test_unknown_tx_type_is_rejected(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1", tx_type="chargeback")])
    result = ingest_from_dir(conn, source)
    assert result.inserted == 0
    assert len(result.rejects) == 1
    assert "tx_type" in result.rejects[0][1]


def test_refunds_are_still_rejected_when_negative(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(
        tmp_path, [valid_row("0x1", tx_type=TX_TYPE_REFUND, amount_micro_usdc=-5)]
    )
    result = ingest_from_dir(conn, source)
    assert result.inserted == 0
    assert len(result.rejects) == 1


def test_hazards_file_is_loaded_when_present(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    (source / "hazards.json").write_text(json.dumps({"0x1": "interleaved_one_off"}))

    ingest_from_dir(conn, source)

    row = conn.execute("SELECT tx_hash, hazard FROM hazards").fetchone()
    assert row["hazard"] == "interleaved_one_off"


def test_missing_hazards_file_is_normal(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    result = ingest_from_dir(conn, source)
    assert result.inserted == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM hazards").fetchone()["n"] == 0


def test_missing_source_directory_raises_ingest_error(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    with pytest.raises(IngestError) as exc:
        ingest_from_dir(conn, tmp_path / "nope")
    assert "transactions.json" in str(exc.value)


def test_malformed_transactions_json_raises_ingest_error(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = tmp_path / "data"
    source.mkdir()
    (source / "transactions.json").write_text("{not json")
    with pytest.raises(IngestError) as exc:
        ingest_from_dir(conn, source)
    assert "valid JSON" in str(exc.value)


def test_transactions_json_must_be_an_array(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = tmp_path / "data"
    source.mkdir()
    (source / "transactions.json").write_text(json.dumps({"tx_hash": "0x1"}))
    with pytest.raises(IngestError) as exc:
        ingest_from_dir(conn, source)
    assert "array" in str(exc.value)


def test_malformed_ground_truth_raises_ingest_error(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    (source / "ground_truth.json").write_text(json.dumps(["not", "a", "mapping"]))
    with pytest.raises(IngestError) as exc:
        ingest_from_dir(conn, source)
    assert "ground_truth" in str(exc.value)


def test_service_truth_is_loaded_when_present(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    (source / "service_truth.json").write_text(json.dumps({"0x1": "weather-api"}))

    ingest_from_dir(conn, source)

    row = conn.execute("SELECT tx_hash, true_service FROM service_truth").fetchone()
    assert row["true_service"] == "weather-api"


def test_missing_service_truth_is_normal(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])

    result = ingest_from_dir(conn, source)

    assert result.inserted == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM service_truth").fetchone()["n"] == 0


def test_malformed_service_truth_raises_ingest_error(tmp_path: Path):
    conn = fresh_conn(tmp_path)
    source = write_source(tmp_path, [valid_row("0x1")])
    (source / "service_truth.json").write_text(json.dumps(["not", "a", "mapping"]))

    with pytest.raises(IngestError) as exc:
        ingest_from_dir(conn, source)
    assert "service_truth" in str(exc.value)
