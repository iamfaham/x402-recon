"""How addresses are shown, and why they are shortened by default.

These addresses are already public: anyone can read them off the chain. What
is sensitive is not the address but the ASSOCIATION - "these are the customers
of this particular seller" - which is a fact the tool's user produced by
running it, not one the chain publishes. Output that scrolls past and gets
pasted into an issue should not carry that association by default.

The CSV export deliberately keeps full addresses: it is the accounting
artifact, written to a named path as a deliberate act, and a truncated address
cannot be reconciled against anything or looked up on a block explorer.
"""


def shorten_address(address: str) -> str:
    """Shorten an address for display, keeping both ends recognisable.

    Produces 0x6d6E695b…0B9192. This is the format the overview header has
    always used; it lives here so the project has exactly one way of writing
    a shortened address.
    """
    if len(address) <= 16:
        return address
    return address[:10] + "…" + address[-6:]
