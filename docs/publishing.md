# Publishing x402-recon to PyPI

This document is for the maintainer holding the PyPI API token. It has **not**
been executed as part of this release task — publishing requires credentials
the implementer does not have. Everything up to the publish command has been
prepared and verified; running the publish command is the maintainer's step.

## 1. Bump the version first

PyPI refuses to accept a re-upload of a version that already exists on the
index, even if the file contents differ. Before building for release, bump
the `version` field in `pyproject.toml`:

```toml
[project]
version = "0.4.0"   # bump this before every release
```

There is no dynamic versioning in this project — the version lives in exactly
one place, `pyproject.toml`. Update it, commit the bump, then build.

## 2. Create a PyPI API token

1. Log in to https://pypi.org (or https://test.pypi.org for a dry run — see
   below) with the account that owns/maintains the `x402-recon` project.
2. Go to Account Settings -> API tokens -> "Add API token".
3. Scope the token to the `x402-recon` project specifically (not
   account-wide), once the project exists on the index. For the very first
   publish of a brand-new project name, PyPI requires an account-wide token
   for that first upload; immediately after, create a project-scoped token
   and revoke the account-wide one.
4. Store the token securely (e.g. in a password manager or as a CI secret).
   Never commit it. Never paste it into chat or an issue.

## 3. Build

From the repo root:

```bash
uv build
```

This produces `dist/x402_recon-<version>-py3-none-any.whl` and
`dist/x402_recon-<version>.tar.gz`. Confirm the version in the filenames
matches the version you just bumped in `pyproject.toml` — if `dist/` has
stale artifacts from a previous version, delete them first or `uv build`
will happily leave both old and new files sitting there.

## 4. Test against TestPyPI first

Before publishing for real, publish to TestPyPI and confirm the install
works from there:

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token <test-pypi-token>
```

Then, from a machine or environment that has never cloned this repository:

```bash
uvx --index-url https://test.pypi.org/simple/ x402-recon --help
```

(TestPyPI does not mirror PyPI's dependency index, but since this package's
runtime dependency list is empty, this should resolve cleanly with no extra
`--extra-index-url` needed.)

## 5. Publish to the real index

Once the TestPyPI install is confirmed working:

```bash
uv publish --token <pypi-token>
```

## 6. Verify the real thing

The check that matters is the one a stranger will actually run — the
README's quick-start line:

```bash
uvx x402-recon --url <endpoint> --last 30d
```

Run this from a machine that has never cloned the repository (a fresh VM,
container, or throwaway environment on another machine works). This is the
only way to confirm the README's quick-start promise is actually true for
someone who is not you and has no local checkout.

## 7. The wheel-install verification already done for this release

Before this hand-off was written, the wheel built for v0.4.0 was verified
by installing it into a throwaway virtual environment created outside this
repository (never install into a venv that has also had `pip install -e .`
run against the source tree — that would hide missing-module bugs) and
running the installed console script directly, not via `uv run` or anything
that touches the source tree:

```bash
uv venv <scratch-dir>/x402check
uv pip install --python <scratch-dir>/x402check/Scripts/python.exe dist/x402_recon-0.4.0-py3-none-any.whl
<scratch-dir>/x402check/Scripts/x402-recon.exe --help
<scratch-dir>/x402check/Scripts/x402-recon.exe --advanced
```

(On macOS/Linux, the paths are `<scratch-dir>/x402check/bin/python` and
`<scratch-dir>/x402check/bin/x402-recon` instead of the `Scripts/*.exe`
forms above.)

Both commands succeeded: `--help` printed the full argument list including
all six subcommands (`ingest`, `categorize`, `report`, `customers`, `fetch`,
`discover`), and `--advanced` printed the four hidden research/validation
commands (`evaluate`, `label`, `shape`, `simulate`). A follow-up check
(`python -c "import x402_recon, os; print(os.path.dirname(x402_recon.__file__))"`)
confirmed the imported package resolved from the venv's `site-packages`, not
from the repository's `src/` tree — proving the wheel is self-contained and
does not depend on any development-time `sys.path` setup.

Repeat this same procedure for each future release before publishing: it is
the only reliable way to catch a wheel that is missing a module, missing an
`__init__.py`, or otherwise packaged incorrectly despite the full test suite
passing from the source tree.

## Reminder: runtime dependencies stay empty

This project's `pyproject.toml` declares `dependencies = []` and that must
remain true — x402-recon is stdlib-only by design. If a future change adds a
runtime dependency, that is a deliberate decision requiring its own review,
not something to fall into via `uv add`.
