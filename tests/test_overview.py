import pytest

from x402_recon.db import connect, init_schema
from x402_recon.overview import build_overview, render_overview
from x402_recon.verify import SampleResult

ADDRESS = "0x" + "99" * 20


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "o.db")
    init_schema(connection)
    return connection


def _seed(conn, rows):
    for tx_hash, sender, amount, timestamp in rows:
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload, tx_type)
               VALUES (?, ?, ?, ?, ?, NULL, 'base', '{}', 'payment')""",
            (tx_hash, sender, ADDRESS, amount, timestamp),
        )
    conn.commit()


def _loyal(conn):
    _seed(
        conn,
        [(f"0x{i}", f"0xcust{i % 2}", 1_000_000, "2026-08-02T00:00:00Z") for i in range(10)],
    )
    return conn


def _probes(conn):
    _seed(
        conn,
        [(f"0x{i}", f"0xprobe{i}", 50_000, "2026-08-02T00:00:00Z") for i in range(30)],
    )
    return conn


def test_a_discovered_address_may_be_called_x402(conn):
    text = render_overview(
        build_overview(
            _loyal(conn), ADDRESS, "2026-08-01", "2026-08-31",
            source_url="https://x402.example.test/search",
        )
    )
    assert "x402.example.test" in text
    assert "payTo discovered from" in text


def test_a_raw_address_is_never_called_x402(conn):
    # THE PROVENANCE RULE. Without a 402 telling us this is a payTo, we cannot
    # claim the payments are x402 - they are simply USDC received.
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "discovered" not in text.lower()
    assert "USDC payments" in text


def test_the_headline_shows_money_and_payers(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "Net received" in text
    assert "Distinct payers" in text
    assert "$10.00" in text


def test_the_customer_table_shows_all_three_bands(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "Returning (3+)" in text
    assert "Tried twice" in text
    assert "One-shot" in text


def test_the_probe_warning_appears_above_the_notes_not_inside_them(conn):
    text = render_overview(
        build_overview(_probes(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "appeared exactly once" in text
    assert text.index("appeared exactly once") < text.index("Notes")


def test_no_probe_warning_for_genuine_repeat_usage(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "appeared exactly once" not in text


def test_the_missing_memo_is_a_note_not_a_section(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "no memo" in text
    assert "What they paid for" not in text


def test_the_uncalibrated_caveat_is_present_on_unlabeled_data(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "uncalibrated" in text


def test_the_sample_line_renders_when_a_sample_was_taken(conn):
    # The sample note is only meaningful once an address is a confirmed
    # payTo (see test_the_sample_note_never_renders_for_a_raw_address below),
    # so this exercises it with source_url set.
    text = render_overview(
        build_overview(
            _loyal(conn), ADDRESS, "2026-08-01", "2026-08-31",
            source_url="https://x402.example.test/search",
            sample=SampleResult(checked=10, settled_via_eip3009=10, total_available=10),
        )
    )
    assert "Sampled 10" in text


def test_the_sample_note_never_renders_for_a_raw_address(conn):
    # The sample note says "x402" / "EIP-3009" - that wording assumes the
    # address is a confirmed payTo. A raw address has no such confirmation,
    # so the note must not render even when a sample was taken. (The header
    # and provenance line legitimately contain the literal string "x402" -
    # the header names the tool, and the provenance line explicitly denies
    # x402 confirmation - so this checks for the specific leaking wording
    # rather than a blanket "x402" absence.)
    text = render_overview(
        build_overview(
            _loyal(conn), ADDRESS, "2026-08-01", "2026-08-31",
            sample=SampleResult(checked=10, settled_via_eip3009=10, total_available=10),
        )
    )
    assert "Sampled" not in text
    assert "EIP-3009" not in text
    assert "settled the way x402 does" not in text
    assert "consistent with x402" not in text


def test_an_empty_range_says_so_instead_of_printing_an_empty_table(conn):
    text = render_overview(
        build_overview(conn, ADDRESS, "2026-08-01", "2026-08-31")
    )
    assert "no payments" in text.lower()


def test_it_gives_no_tax_or_accounting_advice(conn):
    text = render_overview(
        build_overview(_loyal(conn), ADDRESS, "2026-08-01", "2026-08-31")
    ).lower()
    for forbidden in ("deductible", "taxable", "you should", "consult", "write off"):
        assert forbidden not in text


def test_the_overview_rounds_aggregates_to_cents(conn):
    _seed(conn, [("0xa", "0xcust0", 437_914_959, "2026-08-02T00:00:00Z")])
    out = render_overview(build_overview(conn, ADDRESS, "2026-08-01", "2026-08-31"))
    assert "$437.91" in out
    assert "$437.914959" not in out.split("Notes")[0], "the table must not show six decimals"


def test_the_overview_shows_the_exact_total_when_rounding_lost_something(conn):
    _seed(conn, [("0xa", "0xcust0", 437_914_959, "2026-08-02T00:00:00Z")])
    out = render_overview(build_overview(conn, ADDRESS, "2026-08-01", "2026-08-31"))
    assert "$437.914959" in out, "the exact figure must survive somewhere"


def test_the_overview_omits_the_exact_total_when_rounding_lost_nothing(conn):
    # Two payments from the same payer (rather than one) so payments-per-payer
    # clears PROBE_RATIO_CEILING and the unrelated probe-traffic warning (whose
    # wording "appeared exactly once" itself contains the substring "exact")
    # does not confound this assertion.
    _seed(
        conn,
        [
            ("0xa", "0xcust0", 2_500_000, "2026-08-02T00:00:00Z"),
            ("0xb", "0xcust0", 2_500_000, "2026-08-03T00:00:00Z"),
        ],
    )
    out = render_overview(build_overview(conn, ADDRESS, "2026-08-01", "2026-08-31"))
    assert "$5.00" in out
    assert "exact" not in out.lower(), "a clean total needs no footnote"
