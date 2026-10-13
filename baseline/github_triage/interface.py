"""What a baseline triage workflow receives. Implement `run` in workflow.py against these."""

from typing import Any, Protocol


class ToolError(Exception):
    """Raised by `Tools.call` when a tool fails (for example an issue that does not exist)."""


class Tools(Protocol):
    def call(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name; returns its result (parsed JSON) or raises ToolError."""
        ...


class Model(Protocol):
    """The same language model the agent uses (claude-haiku-5-5). You pay for its tokens:
    every call's input and output tokens are counted into cost per task."""

    def complete(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        """One model call. Without `schema`, returns the reply text. With a JSON schema
        (an object schema), returns a dict matching it, or raises ValueError if the model's
        answer does not parse."""
        ...
