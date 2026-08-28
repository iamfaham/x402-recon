"""The packaging metadata a PyPI listing needs, pinned so it cannot regress."""

import pathlib
import tomllib


def _pyproject():
    root = pathlib.Path(__file__).resolve().parent.parent
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_python_floor_is_eleven():
    assert _pyproject()["project"]["requires-python"] == ">=3.11"


def test_runtime_dependencies_are_still_empty():
    # The whole project rests on this: stdlib only, no supply chain.
    assert _pyproject()["project"]["dependencies"] == []


def test_the_listing_metadata_a_stranger_reads_is_present():
    project = _pyproject()["project"]
    for field in ("name", "version", "description", "readme", "license", "keywords"):
        assert field in project, f"missing {field}"
    assert project["name"] == "x402-recon"


def test_classifiers_declare_every_supported_python():
    classifiers = " ".join(_pyproject()["project"]["classifiers"])
    for version in ("3.11", "3.12", "3.13"):
        assert version in classifiers


def test_project_urls_point_at_the_repository():
    urls = _pyproject()["project"]["urls"]
    assert any("github.com/iamfaham/x402-recon" in url for url in urls.values())
