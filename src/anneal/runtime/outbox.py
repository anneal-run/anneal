"""Outbox for side-effect tool calls (CONTRACT, ANNEAL-ROADMAP.md M1.7).

Before a side-effect tool is called, an `intent` record with its operation key
is written and synced to disk; after the call it becomes `done`. A run that
dies in between leaves the intent open. On restart, `recover` asks each tool's
`reconcile(key)` hook whether the operation happened: `done`, `not_done` or
`unknown`. An unknown outcome, including a tool with no hook or a hook that
fails, is never retried and never handed to an agent to repeat: `recover`
raises `NeedsHuman` once every open intent has been processed.

Records are JSON files, one per key, written atomically (temp file, fsync,
rename). `Outbox()` with no directory keeps them in memory, for replay and tests.
"""

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import blake3
from pydantic import AwareDatetime, BaseModel, ConfigDict

OutboxState = Literal["intent", "done", "not_done", "unknown"]
ReconcileAnswer = Literal["done", "not_done", "unknown"]
Reconcile = Callable[[str], ReconcileAnswer]


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical(args: Any) -> str:
    """Key-order and int/float-insensitive JSON of tool arguments."""
    return json.dumps(_normalize(args), sort_keys=True, separators=(",", ":"))


class OutboxRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    run_id: str
    step_id: str
    tool: str
    args: Any
    state: OutboxState
    updated_at: AwareDatetime


class NeedsHuman(Exception):
    """Side effects whose outcome is unknown; a person must decide."""

    def __init__(self, records: list[OutboxRecord]) -> None:
        keys = ", ".join(f"{r.tool}:{r.key}" for r in records)
        super().__init__(f"outcome unknown, not retried: {keys}")
        self.records = records


class Outbox:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else None
        self._memory: dict[str, OutboxRecord] = {}
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        assert self.root is not None
        return self.root / f"{blake3.blake3(key.encode()).hexdigest()[:32]}.json"

    def _save(self, record: OutboxRecord) -> None:
        if self.root is None:
            self._memory[record.key] = record
            return
        path = self._path(record.key)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(record.model_dump_json())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def get(self, key: str) -> OutboxRecord | None:
        if self.root is None:
            return self._memory.get(key)
        path = self._path(key)
        if not path.exists():
            return None
        return OutboxRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def records(self) -> list[OutboxRecord]:
        if self.root is None:
            found = list(self._memory.values())
        else:
            found = [
                OutboxRecord.model_validate(json.loads(p.read_text(encoding="utf-8")))
                for p in self.root.glob("*.json")
            ]
        return sorted(found, key=lambda r: (r.updated_at, r.key))

    def write_intent(self, key: str, *, run_id: str, step_id: str, tool: str, args: Any) -> None:
        """Record that `tool` is about to be called under `key`; durable before the call."""
        if self.get(key) is not None:
            raise ValueError(f"operation key {key} is already in the outbox")
        now = datetime.now(UTC)
        record = OutboxRecord(
            key=key,
            run_id=run_id,
            step_id=step_id,
            tool=tool,
            args=args,
            state="intent",
            updated_at=now,
        )
        self._save(record)

    def mark(self, key: str, state: OutboxState) -> OutboxRecord:
        record = self.get(key)
        if record is None:
            raise KeyError(key)
        updated = record.model_copy(update={"state": state, "updated_at": datetime.now(UTC)})
        self._save(updated)
        return updated

    def open_intents(self) -> list[OutboxRecord]:
        return [r for r in self.records() if r.state == "intent"]


def reconcile_one(record: OutboxRecord, reconcilers: Mapping[str, Reconcile]) -> ReconcileAnswer:
    """Ask the tool's hook; a missing hook, a failure or an invalid answer is `unknown`."""
    hook = reconcilers.get(record.tool)
    if hook is None:
        return "unknown"
    try:
        answer = hook(record.key)
    except Exception:
        return "unknown"
    return answer if answer in ("done", "not_done", "unknown") else "unknown"


def recover(
    outbox: Outbox, reconcilers: Mapping[str, Reconcile], *, raise_on_unknown: bool = True
) -> list[OutboxRecord]:
    """Reconcile every open intent; raise `NeedsHuman` for those still unknown."""
    records = [outbox.mark(r.key, reconcile_one(r, reconcilers)) for r in outbox.open_intents()]
    unknown = [r for r in records if r.state == "unknown"]
    if unknown and raise_on_unknown:
        raise NeedsHuman(unknown)
    return records
