"""Whole-run skeletons and near-duplicate clustering.

A skeleton is the run's event sequence as `(kind, name, arg_shape_hash,
result_shape_hash)` steps, using coarse shapes so value lengths don't split
runs apart:

- tool step: `("tool", <tool name>, hash(args shape), hash(result shape) | "error")`
- model step: `("model", <role>, "", "calls:<sorted tool names>" | "text" | ...)`,
  where the role is the event's scope, else `sys:<system_hash>`, else `model`

Runs with identical skeletons share a hash. Distinct skeletons whose
`difflib` ratio is at least the threshold are joined transitively (union-find).
"""

import difflib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import blake3

from anneal.canon.shape import shape, shape_hash
from anneal.schema import Deopt, Event, ModelCall, Run, ToolCall

Step = tuple[str, str, str, str]
Skeleton = tuple[Step, ...]

NEAR_DUPLICATE_RATIO = 0.9


def _step(event: Event) -> Step | None:
    match event:
        case ToolCall():
            result = "error" if event.error else shape_hash(shape(event.result, coarse=True))
            return ("tool", event.name, shape_hash(shape(event.args, coarse=True)), result)
        case ModelCall():
            role = event.scope or (f"sys:{event.system_hash}" if event.system_hash else "model")
            parts = []
            if event.tool_calls_requested:
                names = sorted({t.name for t in event.tool_calls_requested})
                parts.append("calls:" + ",".join(names))
            if event.output_text:
                parts.append("text")
            return ("model", role, "", "+".join(parts) or "empty")
        case Deopt():
            return None


def skeleton(run: Run) -> Skeleton:
    """The run's step sequence; deopt events are not part of the structure."""
    return tuple(s for s in map(_step, run.events) if s is not None)


def skeleton_hash(steps: Skeleton) -> str:
    """blake3 hex digest of the canonical JSON of the steps."""
    return blake3.blake3(json.dumps(steps, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    """Hash of the representative skeleton."""
    skeleton: Skeleton
    """The most common skeleton among the members."""
    run_ids: list[str]
    skeleton_hashes: list[str]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def cluster_runs(runs: Sequence[Run], threshold: float = NEAR_DUPLICATE_RATIO) -> list[Cluster]:
    """Group runs by skeleton, joining near-duplicates; largest cluster first."""
    by_hash: dict[str, list[str]] = {}
    skeletons: dict[str, Skeleton] = {}
    for run in runs:
        steps = skeleton(run)
        h = skeleton_hash(steps)
        skeletons.setdefault(h, steps)
        by_hash.setdefault(h, []).append(run.run_id)

    hashes = list(by_hash)
    uf = _UnionFind(len(hashes))
    for i, a in enumerate(hashes):
        for j in range(i + 1, len(hashes)):
            matcher = difflib.SequenceMatcher(
                None, skeletons[a], skeletons[hashes[j]], autojunk=False
            )
            if matcher.ratio() >= threshold:
                uf.union(i, j)

    groups: dict[int, list[str]] = {}
    for i, h in enumerate(hashes):
        groups.setdefault(uf.find(i), []).append(h)

    clusters = []
    for members in groups.values():
        sizes = Counter({h: len(by_hash[h]) for h in members})
        representative = max(members, key=lambda h: (sizes[h], -hashes.index(h)))
        clusters.append(
            Cluster(
                cluster_id=representative,
                skeleton=skeletons[representative],
                run_ids=sorted(r for h in members for r in by_hash[h]),
                skeleton_hashes=sorted(members),
            )
        )
    return sorted(clusters, key=lambda c: (-len(c.run_ids), c.run_ids[0]))
