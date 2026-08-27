import pytest

from x402_recon.cache import (
    cache_dir,
    cache_path,
    fetched_ranges,
    missing_ranges,
    record_range,
)
from x402_recon.db import SCHEMA_VERSION, connect, init_schema


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "c.db")
    init_schema(connection)
    return connection


def test_schema_version_was_bumped_for_the_new_table():
    assert SCHEMA_VERSION == 4


def test_cache_path_is_under_the_cache_dir_and_lowercased():
    address = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    path = cache_path(address)
    assert path.parent == cache_dir()
    assert path.name == address.lower() + ".db"


def test_nothing_fetched_means_the_whole_range_is_missing(conn):
    assert missing_ranges(conn, 100, 200) == [(100, 200)]


def test_a_fully_covered_range_is_not_refetched(conn):
    record_range(conn, 100, 200)
    assert missing_ranges(conn, 100, 200) == []
    assert missing_ranges(conn, 120, 180) == []


def test_only_the_gap_is_returned(conn):
    record_range(conn, 100, 150)
    assert missing_ranges(conn, 100, 200) == [(151, 200)]


def test_a_hole_in_the_middle_is_found(conn):
    record_range(conn, 100, 120)
    record_range(conn, 160, 200)
    assert missing_ranges(conn, 100, 200) == [(121, 159)]


def test_several_holes_are_all_found(conn):
    record_range(conn, 100, 110)
    record_range(conn, 130, 140)
    record_range(conn, 180, 200)
    assert missing_ranges(conn, 100, 200) == [(111, 129), (141, 179)]


def test_adjacent_ranges_merge_rather_than_leaving_a_phantom_gap(conn):
    # 100-150 and 151-200 are contiguous; there is no missing block between.
    record_range(conn, 100, 150)
    record_range(conn, 151, 200)
    assert fetched_ranges(conn) == [(100, 200)]
    assert missing_ranges(conn, 100, 200) == []


def test_overlapping_ranges_merge_without_double_counting(conn):
    record_range(conn, 100, 160)
    record_range(conn, 140, 200)
    assert fetched_ranges(conn) == [(100, 200)]


def test_a_range_outside_what_was_fetched_is_entirely_missing(conn):
    record_range(conn, 100, 200)
    assert missing_ranges(conn, 300, 400) == [(300, 400)]


def test_an_old_schema_database_is_refused_with_a_clear_message(tmp_path):
    from x402_recon.db import SchemaVersionError

    path = tmp_path / "old.db"
    connection = connect(path)
    connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    connection.execute("INSERT INTO schema_version (version) VALUES (3)")
    connection.commit()
    connection.close()

    with pytest.raises(SchemaVersionError, match="Delete it"):
        init_schema(connect(path))
