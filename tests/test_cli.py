from pathlib import Path

import pytest

from ledger.cli import main


def test_full_pipeline_produces_a_report(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"
    out = tmp_path / "report.csv"

    assert main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"]) == 0
    assert main(["--db", str(db), "ingest", "--from", str(data)]) == 0
    assert main(["--db", str(db), "categorize"]) == 0
    assert main(
        ["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-12-31",
         "--csv", str(out)]
    ) == 0

    captured = capsys.readouterr().out
    assert "Net received" in captured
    assert out.exists()
    assert len(out.read_text().splitlines()) >= 121  # header + 120 rows


def test_ingested_count_meets_the_v0_bar(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"])
    main(["--db", str(db), "ingest", "--from", str(data)])

    captured = capsys.readouterr().out
    assert "Rejected:            0" in captured


def test_evaluate_reports_metrics(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    assert main(["--db", str(db), "evaluate"]) == 0
    captured = capsys.readouterr().out
    assert "Precision" in captured
    assert "Calibration" in captured


def test_evaluate_without_ground_truth_explains_itself(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"
    data.mkdir()
    (data / "transactions.json").write_text(
        """[{"tx_hash": "0x1", "sender_address": "0xa", "receiver_address": "0xm",
             "amount_micro_usdc": 1000, "timestamp": "2026-08-18T10:00:00Z",
             "memo": null, "chain": "sim", "raw_payload": "{}"}]"""
    )

    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    assert main(["--db", str(db), "evaluate"]) == 1
    assert "ground truth" in capsys.readouterr().out.lower()


def test_report_on_empty_range_does_not_claim_zero_revenue(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    main(["--db", str(db), "report", "--from", "2020-01-01", "--to", "2020-01-31"])
    assert "No transactions found" in capsys.readouterr().out


def test_report_accepts_a_valid_zero_padded_date_range(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    exit_code = main(
        ["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-09-30"]
    )
    assert exit_code == 0
    assert "Net received" in capsys.readouterr().out


def test_report_rejects_unpadded_date(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"

    with pytest.raises(SystemExit) as excinfo:
        main(["--db", str(db), "report", "--from", "2026-8-1", "--to", "2026-09-30"])
    assert excinfo.value.code != 0
    assert "2026-8-1" in capsys.readouterr().err


def test_report_rejects_out_of_range_date(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"

    with pytest.raises(SystemExit) as excinfo:
        main(
            ["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-13-99"]
        )
    assert excinfo.value.code != 0
    assert "2026-13-99" in capsys.readouterr().err


def test_report_rejects_garbage_date(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"

    with pytest.raises(SystemExit) as excinfo:
        main(["--db", str(db), "report", "--from", "garbage", "--to", "2026-09-30"])
    assert excinfo.value.code != 0
    assert "garbage" in capsys.readouterr().err


def test_report_date_error_names_the_expected_format(tmp_path: Path, capsys):
    db = tmp_path / "ledger.db"

    with pytest.raises(SystemExit):
        main(["--db", str(db), "report", "--from", "garbage", "--to", "2026-09-30"])
    err = capsys.readouterr().err
    assert "YYYY-MM-DD" in err
