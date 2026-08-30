import json

from x402_recon.rejects import render_rejects, write_rejects


def test_rendering_no_rejects_is_empty():
    assert render_rejects([]) == ""


def test_each_reject_names_its_hash_and_reason():
    out = render_rejects([("0xabc", "no blockNumber"), ("0xdef", "bad amount")])
    assert "0xabc" in out
    assert "no blockNumber" in out
    assert "0xdef" in out
    assert "bad amount" in out


def test_a_long_reject_list_is_capped_and_says_how_many_more():
    rejects = [(f"0x{i}", "bad") for i in range(25)]
    out = render_rejects(rejects, limit=10)
    assert "0x9" in out
    assert "0x10" not in out.split("more")[0]
    assert "15 more" in out


def test_a_list_exactly_at_the_cap_says_nothing_about_more():
    out = render_rejects([(f"0x{i}", "bad") for i in range(10)], limit=10)
    assert "more" not in out


def test_writing_rejects_produces_readable_json(tmp_path):
    path = write_rejects([("0xabc", "no blockNumber")], tmp_path / "rejects.json")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [{"tx_hash": "0xabc", "reason": "no blockNumber"}]


def test_writing_creates_missing_parent_directories(tmp_path):
    path = write_rejects([("0xa", "b")], tmp_path / "deep" / "nested" / "rejects.json")
    assert path.exists()


def test_writing_an_empty_list_still_writes_a_file(tmp_path):
    # An empty file is a positive statement that nothing was dropped, which is
    # different from no file at all (which could mean the run never got there).
    path = write_rejects([], tmp_path / "rejects.json")
    assert json.loads(path.read_text(encoding="utf-8")) == []
