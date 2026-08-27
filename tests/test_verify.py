from x402_recon.chain import AUTHORIZATION_USED_TOPIC0, USDC_BASE_MAINNET
from x402_recon.verify import (
    X402_SAMPLE_SIZE,
    sample_x402_settlement,
    render_sample,
)


class FakeReceipts:
    def __init__(self, eip3009_hashes):
        self.eip3009 = set(eip3009_hashes)
        self.asked = []

    def transaction_receipt(self, tx_hash):
        self.asked.append(tx_hash)
        if tx_hash in self.eip3009:
            return {
                "logs": [
                    {
                        "address": USDC_BASE_MAINNET,
                        "topics": [AUTHORIZATION_USED_TOPIC0, "0xaa", "0xbb"],
                    }
                ]
            }
        return {"logs": [{"address": USDC_BASE_MAINNET, "topics": ["0xother"]}]}


def test_counts_how_many_sampled_transactions_are_eip3009():
    hashes = [f"0x{i}" for i in range(10)]
    client = FakeReceipts(hashes[:7])
    result = sample_x402_settlement(client, hashes)
    assert result.checked == 10
    assert result.settled_via_eip3009 == 7
    assert result.total_available == 10


def test_the_sample_is_bounded_no_matter_how_many_payments_there_are():
    hashes = [f"0x{i}" for i in range(5_000)]
    client = FakeReceipts(hashes)
    result = sample_x402_settlement(client, hashes)
    assert result.checked == X402_SAMPLE_SIZE
    assert result.total_available == 5_000
    assert len(client.asked) == X402_SAMPLE_SIZE


def test_an_authorization_log_from_another_contract_does_not_count():
    # Only AuthorizationUsed emitted BY the USDC contract is evidence.
    class Impostor:
        def transaction_receipt(self, tx_hash):
            return {
                "logs": [
                    {"address": "0x" + "ee" * 20, "topics": [AUTHORIZATION_USED_TOPIC0]}
                ]
            }

    result = sample_x402_settlement(Impostor(), ["0x1"])
    assert result.settled_via_eip3009 == 0


def test_a_missing_receipt_is_counted_as_checked_but_not_as_evidence():
    class NoReceipts:
        def transaction_receipt(self, tx_hash):
            return None

    result = sample_x402_settlement(NoReceipts(), ["0x1", "0x2"])
    assert result.checked == 2
    assert result.settled_via_eip3009 == 0


def test_an_empty_input_returns_zeroes_without_calling_the_client():
    class Explodes:
        def transaction_receipt(self, tx_hash):
            raise AssertionError("should not be called")

    result = sample_x402_settlement(Explodes(), [])
    assert result.checked == 0
    assert result.total_available == 0


def test_render_states_what_was_sampled_and_what_was_found():
    text = render_sample(
        sample_x402_settlement(FakeReceipts(["0x1"]), ["0x1", "0x2"])
    )
    assert "Sampled 2" in text
    assert "EIP-3009" in text


def test_render_is_silent_when_nothing_was_sampled():
    class Explodes:
        def transaction_receipt(self, tx_hash):
            raise AssertionError("should not be called")

    assert render_sample(sample_x402_settlement(Explodes(), [])) == ""
