"""JSONL run store on local disk.

Layout: `<root>/<workflow_id>/<YYYY-MM-DD>.jsonl`, one run per line, partitioned
by the UTC date of `started_at`. Writes append; when a run_id appears more than
once, the last written version wins on read. Every run is redacted before it
is written; there is no way to write an unredacted run through this API.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from anneal.schema.models import Run
from anneal.schema.redact import redact_run


def _check_workflow_id(workflow_id: str) -> str:
    if workflow_id in {"", ".", ".."} or "/" in workflow_id or "\\" in workflow_id:
        raise ValueError(f"unsafe workflow_id for the store: {workflow_id!r}")
    return workflow_id


class Store:
    """Reads and writes redacted runs under a root directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write(self, runs: Iterable[Run]) -> int:
        """Redact and append `runs`; returns how many were written."""
        count = 0
        for run in runs:
            folder = self.root / _check_workflow_id(run.workflow_id)
            folder.mkdir(parents=True, exist_ok=True)
            day = run.started_at.astimezone(UTC).date().isoformat()
            with (folder / f"{day}.jsonl").open("a", encoding="utf-8") as f:
                f.write(redact_run(run).model_dump_json() + "\n")
            count += 1
        return count

    def workflows(self) -> list[str]:
        """Workflow ids that have runs in this store."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and any(p.glob("*.jsonl")))

    def read(self, workflow_id: str, since: datetime | None = None) -> list[Run]:
        """Runs of `workflow_id` started at or after `since`, sorted by start time."""
        folder = self.root / _check_workflow_id(workflow_id)
        first_day = since.astimezone(UTC).date().isoformat() if since else ""
        latest: dict[str, Run] = {}
        for path in sorted(folder.glob("*.jsonl")):
            if path.stem < first_day:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    run = Run.model_validate_json(line)
                    latest.pop(run.run_id, None)
                    latest[run.run_id] = run
        runs = [r for r in latest.values() if since is None or r.started_at >= since]
        return sorted(runs, key=lambda r: r.started_at)
