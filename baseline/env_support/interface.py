"""What a baseline workflow receives. Implement `run` in workflow.py against these."""

from typing import Any, Protocol


class ToolError(Exception):
    """Raised by `Tools.call` when a tool fails (for example `NotFound: <email>`)."""


class Tools(Protocol):
    def call(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name; returns its result or raises an exception."""
        ...


class Model(Protocol):
    """A language model, offered as four capabilities. Every call costs $0.015."""

    def read(self, run_input: dict[str, Any]) -> dict[str, Any]:
        """Extract {"email", "message", "priority"} from an input, whatever its field names."""
        ...

    def summarize(self, message: str) -> str:
        """A one-line ticket summary of a customer message."""
        ...

    def choose(self, options: list[str], context: dict[str, Any]) -> str:
        """Pick the best of `options` for the context (for example how to route a ticket,
        given its message, priority and customer tier). Always returns one of `options`."""
        ...

    def write(self, purpose: str, context: dict[str, Any]) -> str:
        """Write text: purpose "reply" (the email to the customer) or "final" (the closing
        answer), from a context such as {"message": ..., "ticket_id": ...}."""
        ...
