"""Structural invariants, enforced rather than remembered."""

import pathlib

NETWORK_MODULES = {"rpc.py", "discover.py"}

# The transport surfaces that actually open a connection. Deliberately does
# NOT include bare "urllib" - urllib.parse is pure string parsing with no
# network capability, and a module using it for something like extracting a
# hostname for display is not a violation of this invariant.
_NETWORK_TRANSPORT_MARKERS = ("urllib.request", "http.client", "socket")


def _source_files():
    root = pathlib.Path(__file__).resolve().parent.parent / "src" / "x402_recon"
    return sorted(root.glob("*.py"))


def test_only_rpc_and_discover_touch_the_network():
    # Every other stage stays offline, which is what keeps the pipeline
    # testable and a fetched batch replayable from disk.
    offenders = []
    for path in _source_files():
        if path.name in NETWORK_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in _NETWORK_TRANSPORT_MARKERS):
            offenders.append(path.name)
    assert offenders == [], f"network access leaked into: {offenders}"


def test_the_network_modules_still_exist():
    # Guards against the test above passing vacuously after a rename.
    names = {path.name for path in _source_files()}
    assert NETWORK_MODULES <= names
