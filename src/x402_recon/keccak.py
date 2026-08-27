"""Keccak-256, as Ethereum uses it.

The standard library does not provide this. `hashlib.sha3_256` is NOT a
substitute: Ethereum uses original Keccak padding (0x01) while NIST SHA-3 uses
0x06, so the wrong one produces plausible-looking wrong hashes. The tests pin
known vectors specifically to catch that.

Having this lets topic hashes be derived rather than pasted, which means the
constant already pinned in chain.py can be checked against an independent
computation instead of trusted.
"""

_ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

_ROTATIONS = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

_MASK = (1 << 64) - 1
_RATE = 136  # bytes absorbed per block for Keccak-256


def _rotl(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _permute(state: list[list[int]]) -> None:
    for round_index in range(24):
        parity = [
            state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]
            for x in range(5)
        ]
        theta = [parity[(x - 1) % 5] ^ _rotl(parity[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= theta[x]

        rotated = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                rotated[y][(2 * x + 3 * y) % 5] = _rotl(state[x][y], _ROTATIONS[x][y])

        for x in range(5):
            for y in range(5):
                state[x][y] = rotated[x][y] ^ (
                    (~rotated[(x + 1) % 5][y]) & rotated[(x + 2) % 5][y]
                )

        state[0][0] ^= _ROUND_CONSTANTS[round_index]


def keccak256(data: bytes) -> bytes:
    """Keccak-256 digest of `data`, 32 bytes."""
    padded = bytearray(data)
    padded.append(0x01)  # original Keccak padding, NOT NIST SHA-3's 0x06
    while len(padded) % _RATE != 0:
        padded.append(0x00)
    padded[-1] ^= 0x80

    state = [[0] * 5 for _ in range(5)]
    for offset in range(0, len(padded), _RATE):
        block = padded[offset : offset + _RATE]
        for i in range(_RATE // 8):
            state[i % 5][i // 5] ^= int.from_bytes(block[i * 8 : i * 8 + 8], "little")
        _permute(state)

    out = bytearray()
    for i in range(4):
        out += state[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out[:32])


def topic0(signature: str) -> str:
    """The 0x-prefixed event topic hash for a Solidity event signature."""
    return "0x" + keccak256(signature.encode("ascii")).hex()
