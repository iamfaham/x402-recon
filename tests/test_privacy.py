from x402_recon.privacy import shorten_address

ADDRESS = "0x" + "ab" * 20  # synthetic; never a mainnet address in a fixture


def test_shortening_keeps_the_ends_and_elides_the_middle():
    short = shorten_address(ADDRESS)
    assert short.startswith(ADDRESS[:10])
    assert short.endswith(ADDRESS[-6:])
    assert "…" in short
    assert len(short) < len(ADDRESS)


def test_shortening_matches_the_established_convention():
    # The exact format overview.py has always used, kept so the tool does not
    # grow a second way of writing the same thing.
    assert shorten_address("0x6d6E695b09861467c7d462f5AAF31cF3540B9192") == (
        "0x6d6E695b…0B9192"
    )


def test_an_already_short_string_is_returned_unchanged():
    assert shorten_address("0xabc") == "0xabc"
