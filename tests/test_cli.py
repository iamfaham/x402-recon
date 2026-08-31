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


def _seeded_report_db(tmp_path: Path):
    """A database with a full 42-character sender address so redaction is
    actually observable (shorten_address is a no-op at <=16 chars)."""
    db = tmp_path / "l.db"
    data = tmp_path / "data"
    data.mkdir()
    address = "0x" + "ab" * 20
    (data / "transactions.json").write_text(
        f"""[{{"tx_hash": "0x1", "sender_address": "{address}",
             "receiver_address": "0xm", "amount_micro_usdc": 1000000,
             "timestamp": "2026-08-10T10:00:00Z", "memo": null,
             "chain": "sim", "raw_payload": "{{}}"}},
             {{"tx_hash": "0x2", "sender_address": "{address}",
             "receiver_address": "0xm", "amount_micro_usdc": 2000000,
             "timestamp": "2026-08-11T10:00:00Z", "memo": null,
             "chain": "sim", "raw_payload": "{{}}"}}]"""
    )
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    return db, address


def test_full_addresses_flag_before_report_is_honored(tmp_path: Path, capsys):
    db, address = _seeded_report_db(tmp_path)
    capsys.readouterr()

    main(
        ["--db", str(db), "--full-addresses", "report",
         "--from", "2026-08-01", "--to", "2026-08-31"]
    )
    out = capsys.readouterr().out
    assert address in out, "explicit top-level --full-addresses must not be lost"


def test_full_addresses_flag_after_report_is_honored(tmp_path: Path, capsys):
    db, address = _seeded_report_db(tmp_path)
    capsys.readouterr()

    main(
        ["--db", str(db), "report", "--full-addresses",
         "--from", "2026-08-01", "--to", "2026-08-31"]
    )
    out = capsys.readouterr().out
    assert address in out


def test_report_without_full_addresses_flag_stays_redacted(tmp_path: Path, capsys):
    db, address = _seeded_report_db(tmp_path)
    capsys.readouterr()

    main(
        ["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-08-31"]
    )
    out = capsys.readouterr().out
    assert address not in out
    assert "…" in out


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
    monkeypatch.setattr("x402_recon.cli.render_overview", lambda o, **k: "OVERVIEW")
    monkeypatch.setattr("x402_recon.cli.days_ago_range", lambda c, d: (1, 2))
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())

    code = main(["0x" + "99" * 20, "--no-cache"])
    assert code == 0
    assert "OVERVIEW" in capsys.readouterr().out
    assert captured["address"] == "0x" + "99" * 20


def _stub_overview_with_rejects(monkeypatch, tmp_path, rejects):
    """Build a real Overview (over an empty database) carrying the given rejects,
    and wire it into main() the same way the other overview tests do: patch
    run_overview and the block-range lookup, and hand out a fake RPC client."""
    from x402_recon.db import connect, init_schema
    from x402_recon.overview import build_overview

    db_path = tmp_path / "empty-for-rejects.db"
    conn = connect(db_path)
    init_schema(conn)
    overview = build_overview(
        conn,
        "0x" + "ab" * 20,
        "2026-07-01",
        "2026-07-31",
        rejects=rejects,
    )

    monkeypatch.setattr("x402_recon.cli.run_overview", lambda **k: overview)
    monkeypatch.setattr("x402_recon.cli.days_ago_range", lambda c, d: (1, 2))
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())


def test_the_overview_prints_reject_detail_not_just_a_count(monkeypatch, tmp_path, capsys):
    _stub_overview_with_rejects(
        monkeypatch, tmp_path, rejects=[("0xabc", "no blockNumber")]
    )
    main(["0x" + "ab" * 20, "--last", "30d", "--no-cache"])
    out = capsys.readouterr().out
    assert "1 row(s) were skipped" in out
    assert "0xabc" in out, "the hash must be shown, not just counted"
    assert "no blockNumber" in out, "the reason must be shown"


def test_no_cache_writes_no_reject_file(monkeypatch, tmp_path, capsys):
    # --no-cache means "write nothing to my machine", and that beats completeness.
    _stub_overview_with_rejects(monkeypatch, tmp_path, rejects=[("0xabc", "bad")])
    main(["0x" + "ab" * 20, "--last", "30d", "--no-cache"])
    out = capsys.readouterr().out
    assert "0xabc" in out, "inline detail is still shown"
    assert "rejects-" not in out, "no file path should be printed"


def test_reject_filename_is_lowercased_like_the_cache_db(monkeypatch, tmp_path, capsys):
    # cache_path() lowercases the address before building its filename, so two
    # differently-cased spellings of the same address share one cache
    # database. The reject file must follow the same convention so they also
    # share one reject file.
    mixed_case_address = "0x" + "Ab" * 20
    _stub_overview_with_rejects(monkeypatch, tmp_path, rejects=[("0xabc", "bad")])
    monkeypatch.setattr("x402_recon.cli.cache_dir", lambda: tmp_path)

    main([mixed_case_address, "--last", "30d"])
    out = capsys.readouterr().out

    expected = tmp_path / f"rejects-{mixed_case_address.lower()}.json"
    assert expected.exists(), f"expected lowercased reject filename, got output: {out}"
    assert str(expected) in out


def test_from_without_to_is_an_error(capsys, monkeypatch):
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())
    code = main(["0x" + "99" * 20, "--from", "2026-07-01"])
    assert code == 2
    assert "both --from and --to are required together" in capsys.readouterr().out


def test_to_without_from_is_an_error(capsys, monkeypatch):
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())
    code = main(["0x" + "99" * 20, "--to", "2026-07-31"])
    assert code == 2
    assert "both --from and --to are required together" in capsys.readouterr().out


def test_last_combined_with_from_to_is_an_error(capsys, monkeypatch):
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())
    code = main([
        "0x" + "99" * 20, "--last", "30d",
        "--from", "2026-07-01", "--to", "2026-07-31",
    ])
    assert code == 2
    assert "cannot be combined" in capsys.readouterr().out


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


def test_work_dir_is_removed_after_a_successful_run(tmp_path, monkeypatch):
    created = {}

    def fake_mkdtemp():
        d = tmp_path / "work"
        d.mkdir()
        created["path"] = d
        return str(d)

    monkeypatch.setattr("x402_recon.cli.tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())
    monkeypatch.setattr("x402_recon.cli.days_ago_range", lambda c, d: (1, 2))
    monkeypatch.setattr("x402_recon.cli.connect", lambda p: object())
    monkeypatch.setattr("x402_recon.cli.init_schema", lambda c: None)

    class Fake:
        rejects = []

    monkeypatch.setattr("x402_recon.cli.run_overview", lambda **k: Fake())
    monkeypatch.setattr("x402_recon.cli.render_overview", lambda o, **k: "OVERVIEW")

    main(["0x" + "99" * 20, "--no-cache"])
    assert not created["path"].exists()


def test_the_no_cache_database_file_is_deleted_after_use(tmp_path, monkeypatch):
    made_path = {}

    def fake_mkstemp(suffix=".db"):
        p = tmp_path / "nocache.db"
        p.touch()
        made_path["path"] = p
        return (0, str(p))

    monkeypatch.setattr("x402_recon.cli.tempfile.mkstemp", fake_mkstemp)
    monkeypatch.setattr("x402_recon.cli.tempfile.mkdtemp", lambda: str(tmp_path / "w"))
    (tmp_path / "w").mkdir(exist_ok=True)
    monkeypatch.setattr("x402_recon.cli.RpcClient", lambda *a, **k: object())
    monkeypatch.setattr("x402_recon.cli.days_ago_range", lambda c, d: (1, 2))
    monkeypatch.setattr("x402_recon.cli.connect", lambda p: object())
    monkeypatch.setattr("x402_recon.cli.init_schema", lambda c: None)

    class Fake:
        rejects = []

    monkeypatch.setattr("x402_recon.cli.run_overview", lambda **k: Fake())
    monkeypatch.setattr("x402_recon.cli.render_overview", lambda o, **k: "OVERVIEW")

    main(["0x" + "99" * 20, "--no-cache"])
    assert not made_path["path"].exists()


from x402_recon.cli import ADVANCED_COMMANDS


def test_research_commands_are_absent_from_the_default_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for name in ADVANCED_COMMANDS:
        assert name not in out, f"{name} should be hidden from default help"


def test_everyday_commands_are_still_listed(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for name in ("discover", "report", "customers", "fetch"):
        assert name in out


def test_the_default_help_points_at_advanced(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--advanced" in capsys.readouterr().out


def test_advanced_lists_the_hidden_commands(capsys):
    code = main(["--advanced"])
    out = capsys.readouterr().out
    for name in ADVANCED_COMMANDS:
        assert name in out
    assert code == 0


def test_a_hidden_command_still_works_exactly_as_before(tmp_path, capsys):
    # Hiding must not break anyone following existing documentation.
    assert main(["simulate", "--out", str(tmp_path), "--count", "10"]) == 0
    assert (tmp_path / "transactions.json").exists()


def test_writing_a_csv_warns_that_it_contains_full_addresses(tmp_path: Path, capsys):
    db = tmp_path / "l.db"
    data = tmp_path / "data"

    main(["simulate", "--out", str(data), "--count", "120", "--seed", "42"])
    main(["--db", str(db), "ingest", "--from", str(data)])
    main(["--db", str(db), "categorize"])
    capsys.readouterr()

    main(
        ["--db", str(db), "report", "--from", "2026-08-01", "--to", "2026-09-30",
         "--csv", str(tmp_path / "out.csv")]
    )
    out = capsys.readouterr().out
    assert "full addresses" in out.lower()
    assert "review before sharing" in out.lower()
