import hashlib

from x402_recon.keccak import keccak256, topic0


def test_empty_string_matches_the_known_ethereum_vector():
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )


def test_abc_matches_the_known_vector():
    assert keccak256(b"abc").hex() == (
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    )


def test_this_is_keccak_not_nist_sha3():
    # THE PADDING TRAP. Keccak pads with 0x01, NIST SHA-3 with 0x06. Using
    # hashlib.sha3_256 would give a wrong answer that looks entirely plausible.
    assert keccak256(b"") != hashlib.sha3_256(b"").digest()


def test_topic0_reproduces_the_independently_pinned_transfer_topic():
    # chain.TRANSFER_TOPIC0 was pinned from an external source before this
    # implementation existed. If these agree, the implementation is validated
    # AND the pinned constant stops being an article of faith.
    assert topic0("Transfer(address,address,uint256)") == (
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )


def test_topic0_derives_the_authorization_used_topic():
    assert topic0("AuthorizationUsed(address,bytes32)") == (
        "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"
    )


def test_topic0_returns_a_prefixed_sixty_six_character_string():
    result = topic0("Transfer(address,address,uint256)")
    assert result.startswith("0x")
    assert len(result) == 66


def test_hashing_is_stable_across_calls():
    assert keccak256(b"stability") == keccak256(b"stability")


def test_a_long_input_spanning_multiple_blocks_is_handled():
    # The rate is 136 bytes; this forces more than one absorb block.
    assert len(keccak256(b"x" * 500)) == 32
