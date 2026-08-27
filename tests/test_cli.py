from pathlib import Path

import pytest

from x402_recon.cli import main


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


def test_categorize_reports_transaction_count_not_row_count(tmp_path: Path, capsys):
    # I2: run_categorize returns one row per axis per transaction (2 * N), so
    # printing that number bare as "transactions" overstates it 2x. This pins
    # the corrected wording, honestly reporting both figures.
    db = tmp_path / "ledger.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "1"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    capsys.readouterr()

    assert main(["--db", str(db), "categorize"]) == 0
    captured = capsys.readouterr().out
    assert "Categorized 138 transactions (276 rows across 2 axes)." in captured


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


def test_missing_source_directory_gives_a_clean_error(tmp_path: Path, capsys):
    db = tmp_path / "l.db"
    code = main(["--db", str(db), "ingest", "--from", str(tmp_path / "nope")])
    captured = capsys.readouterr()
    assert code == 2
    assert "transactions.json" in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_malformed_source_json_gives_a_clean_error(tmp_path: Path, capsys):
    db = tmp_path / "l.db"
    source = tmp_path / "data"
    source.mkdir()
    (source / "transactions.json").write_text("{not json")

    code = main(["--db", str(db), "ingest", "--from", str(source)])
    captured = capsys.readouterr()
    assert code == 2
    assert "valid JSON" in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_stale_database_gives_a_clean_error(tmp_path: Path, capsys):
    import sqlite3

    db = tmp_path / "old.db"
    raw = sqlite3.connect(db)
    raw.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()

    code = main(["--db", str(db), "categorize"])
    captured = capsys.readouterr()
    assert code == 2
    assert "out of date" in (captured.out + captured.err).lower()
    assert "Traceback" not in captured.out + captured.err


def test_simulate_writes_four_files(tmp_path: Path, capsys):
    assert main(["simulate", "--out", str(tmp_path / "d"), "--count", "120"]) == 0
    for name in (
        "transactions.json", "ground_truth.json", "hazards.json", "service_truth.json"
    ):
        assert (tmp_path / "d" / name).exists()


def test_evaluate_renders_both_axes(tmp_path: Path, capsys):
    db = tmp_path / "l.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "42"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    assert main(["--db", str(db), "evaluate"]) == 0
    out = capsys.readouterr().out
    assert "Who paid you" in out
    assert "What they paid for" in out


def test_evaluate_without_service_truth_still_scores_the_payer_axis(tmp_path: Path, capsys):
    # The real-data path: a human supplies payer truth alone.
    db = tmp_path / "l.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "42"])
    (data / "service_truth.json").unlink()
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    assert main(["--db", str(db), "evaluate"]) == 0
    out = capsys.readouterr().out
    assert "Precision" in out
    assert "unscored" in out.lower()


def test_report_shows_both_breakdowns(tmp_path: Path, capsys):
    db = tmp_path / "l.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "42"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    main(["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-09-30"])
    out = capsys.readouterr().out
    assert "Who paid you" in out
    assert "What they paid for" in out


def test_fetch_is_rejected_cleanly_when_the_endpoint_errors(tmp_path, capsys, monkeypatch):
    from x402_recon.rpc import RpcError

    def explode(*args, **kwargs):
        raise RpcError("eth_getLogs failed: range too wide")

    monkeypatch.setattr("x402_recon.cli.fetch_transactions", explode)
    code = main(
        [
            "fetch",
            "--receiver", "0x" + "99" * 20,
            "--out", str(tmp_path),
            "--from-block", "0",
            "--to-block", "10",
        ]
    )
    assert code == 2
    assert "range too wide" in capsys.readouterr().out


def test_fetch_never_opens_the_database(tmp_path, monkeypatch):
    # fetch writes files and must work before any database exists, exactly as
    # simulate does. If it fell through to connect(), a fresh user would be
    # forced to create a database to download their own transactions.
    from x402_recon.fetch import FetchResult

    monkeypatch.setattr(
        "x402_recon.cli.fetch_transactions", lambda *a, **k: FetchResult([], [])
    )

    def fail(*args, **kwargs):
        raise AssertionError("fetch must not open the database")

    monkeypatch.setattr("x402_recon.cli.connect", fail)
    assert main(
        [
            "fetch",
            "--receiver", "0x" + "99" * 20,
            "--out", str(tmp_path),
            "--from-block", "0",
            "--to-block", "10",
        ]
    ) == 0


def test_a_bare_address_runs_the_overview(tmp_path, capsys, monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        class Fake:
            pass
        return Fake()

    monkeypatch.setattr("x402_recon.cli.run_overview", fake_run)
    monkeypatch.setattr("x402_recon.cli.render_overview", lambda o: "OVERVIEW")
    monkeypatch.setattr("x402_recon.cli.days_ago_range", lambda c, d: (1, 2))
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())

    code = main(["0x" + "99" * 20, "--no-cache"])
    assert code == 0
    assert "OVERVIEW" in capsys.readouterr().out
    assert captured["address"] == "0x" + "99" * 20


def test_a_malformed_address_is_rejected_by_name(capsys):
    assert main(["not-an-address"]) == 2
    assert "not a valid address" in capsys.readouterr().out


def test_no_address_and_no_url_prints_help_and_fails(capsys):
    assert main([]) == 2


def test_discovery_failure_is_reported_not_raised(capsys, monkeypatch):
    from x402_recon.discover import DiscoveryError

    def explode(url, **kwargs):
        raise DiscoveryError("answered 200, not 402 - it did not ask for payment")

    monkeypatch.setattr("x402_recon.cli.discover", explode)
    assert main(["--url", "https://example.test/x"]) == 2
    assert "did not ask for payment" in capsys.readouterr().out


def test_existing_subcommands_still_work(tmp_path, capsys):
    assert main(["simulate", "--out", str(tmp_path), "--count", "10"]) == 0
