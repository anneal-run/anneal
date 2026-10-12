"""Lenient date parsing shared by provenance matching and the `fmt_date` template filter."""

import contextlib
from datetime import date, datetime

DATE_FORMATS = (
    "%Y-%m-%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
)


def parse_dates(value: object) -> set[date]:
    """Every date `value` can be read as; more than one when day and month are ambiguous."""
    if not isinstance(value, str):
        return set()
    text = value.strip()
    found: set[date] = set()
    with contextlib.suppress(ValueError):
        found.add(datetime.fromisoformat(text).date())
    for fmt in DATE_FORMATS:
        with contextlib.suppress(ValueError):
            found.add(datetime.strptime(text, fmt).date())
    return found
