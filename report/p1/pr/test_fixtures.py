"""The harness fixtures travel with the change."""

from pathlib import Path

FIXTURES = Path('report/p1/fixtures.jsonl')


def test_harness_fixtures_present() -> None:
    assert FIXTURES.is_file()
