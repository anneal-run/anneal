"""A read-only GitHub REST client with an on-disk response cache.

Every GET is cached by URL and parameters, so reruns are deterministic and cost
no API quota. With `offline=True` a cache miss raises instead of calling GitHub;
tests and reruns use that. Rate limits are respected: when the remaining quota of
a bucket (core or search) is low, or GitHub answers 403/429 with a reset or
retry-after, the client sleeps until the window resets.

The token (env `GITHUB_TOKEN`) only needs public read access.
"""

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

API = "https://api.github.com"
CACHE = Path(__file__).parent / ".cache" / "github"
LOW_WATER = 3


class CacheMiss(LookupError):
    pass


class GitHub:
    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path = CACHE,
        offline: bool = False,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.cache_dir = cache_dir
        self.offline = offline
        self.client = client
        self.sleep = sleep
        self.requests = 0
        self._wait_until: dict[str, float] = {}

    def _key(self, path: str, params: Mapping[str, Any]) -> Path:
        raw = json.dumps([path, sorted(params.items())], default=str)
        return self.cache_dir / f"{hashlib.sha256(raw.encode()).hexdigest()[:32]}.json"

    def get(self, path: str, **params: Any) -> Any:
        """GET `path` (relative to the API root) and return the JSON body."""
        file = self._key(path, params)
        if file.exists():
            return json.loads(file.read_text())["body"]
        if self.offline:
            raise CacheMiss(f"{path} {params}")
        body = self._fetch(path, params)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"path": path, "params": params, "body": body}))
        return body

    def _fetch(self, path: str, params: Mapping[str, Any]) -> Any:
        bucket = "search" if path.startswith("/search/") else "core"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        client = self.client or httpx.Client(timeout=30)
        for _ in range(5):
            if (wait := self._wait_until.get(bucket, 0) - time.time()) > 0:
                self.sleep(wait)
            response = client.get(API + path, params=dict(params), headers=headers)
            self.requests += 1
            self._note_limits(bucket, response)
            if response.status_code in (403, 429) and self._rate_limited(response):
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"rate limited five times on {path}")

    def _note_limits(self, bucket: str, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        if remaining is not None and reset is not None and int(remaining) <= LOW_WATER:
            self._wait_until[bucket] = float(reset) + 1

    def _rate_limited(self, response: httpx.Response) -> bool:
        if retry := response.headers.get("retry-after"):
            self.sleep(float(retry))
            return True
        if response.headers.get("x-ratelimit-remaining") == "0":
            reset = float(response.headers.get("x-ratelimit-reset", time.time() + 60))
            self.sleep(max(reset - time.time(), 0) + 1)
            return True
        return False
