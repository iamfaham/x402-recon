"""Structural invariants, enforced rather than remembered."""

import argparse
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


def _parent_and_subparsers():
    from x402_recon.cli import _build_parser

    parser = _build_parser()
    parent_dests = {action.dest for action in parser._actions if action.dest != "help"}
    subparsers = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return parent_dests, subparsers


def test_no_subcommand_silently_discards_a_top_level_option():
    """A subcommand must never overwrite a value the user gave before it.

    argparse merges a subparser's results into the same namespace the parent
    filled, so a subparser argument sharing a `dest` with a parent argument
    writes its own default over whatever the user typed earlier on the line.
    `x402-recon --rpc-url https://mine fetch ...` silently reverting to the
    public endpoint is that bug, and it sends a user's traffic somewhere they
    did not ask for without saying so.

    Two shapes are safe. `required=True` means the user always supplies the
    value, so there is no default to clobber with. `default=SUPPRESS` means an
    absent argument does not touch the namespace at all, so the parent's value
    survives. Anything else silently discards a choice the user made.
    """
    parent_dests, subparsers = _parent_and_subparsers()

    offenders = []
    for name, subparser in subparsers.items():
        for action in subparser._actions:
            if action.dest == "help" or action.dest not in parent_dests:
                continue
            if action.required or action.default is argparse.SUPPRESS:
                continue
            flag = " ".join(action.option_strings) or f"<{action.dest}>"
            offenders.append(f"{name} {flag} (dest={action.dest})")

    assert offenders == [], (
        "these subcommand arguments overwrite a top-level value the user may "
        f"have set before the subcommand: {offenders}. Give each one "
        "default=argparse.SUPPRESS, or make it required."
    )


def test_the_collision_check_actually_has_collisions_to_check():
    # Guards against the test above passing vacuously: if no subcommand
    # argument ever shared a dest with a top-level one, it would assert
    # nothing. Several legitimately do (report/customers --from and --to).
    parent_dests, subparsers = _parent_and_subparsers()
    shared = [
        (name, action.dest)
        for name, subparser in subparsers.items()
        for action in subparser._actions
        if action.dest != "help" and action.dest in parent_dests
    ]
    assert shared, "expected some subcommand arguments to share a parent dest"
