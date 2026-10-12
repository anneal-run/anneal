import re
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from anneal.schema import Message, ModelCall, Run, ToolCall, ToolCallRequest
from anneal.schema.redact import Redactor, find_sensitive, redact_run

T0 = datetime(2026, 10, 12, tzinfo=UTC)


def r(text: str) -> str:
    out = Redactor().redact(text)
    assert isinstance(out, str)
    return out


def test_email_becomes_typed_placeholder() -> None:
    assert r("mail jane@acme.com now") == "mail <EMAIL_1> now"


def test_same_value_same_placeholder_within_one_redactor() -> None:
    red = Redactor()
    assert red.redact(["a@x.io", "b@x.io", "a@x.io"]) == ["<EMAIL_1>", "<EMAIL_2>", "<EMAIL_1>"]


def test_equality_survives_case_and_separator_reformatting() -> None:
    red = Redactor()
    out = red.redact(["Jane@Acme.com", "jane@acme.com", "4111 1111 1111 1111", "4111111111111111"])
    assert out == ["<EMAIL_1>", "<EMAIL_1>", "<CARD_1>", "<CARD_1>"]


def test_fresh_redactor_restarts_numbering() -> None:
    assert r("x@y.io") == r("z@y.io") == "<EMAIL_1>"


def test_each_sensitive_type() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJlLWhlcmU"
    cases = {
        "call +44 20 7946 0958 today": "call <PHONE_1> today",
        "call (415) 555-0132 today": "call <PHONE_1> today",
        "iban DE89 3704 0044 0532 0130 00 ok": "iban <IBAN_1> ok",
        "card 4111-1111-1111-1111 ok": "card <CARD_1> ok",
        f"auth {jwt} ok": "auth <JWT_1> ok",
        "key sk-proj-abcdefghijklmnop1234 ok": "key <KEY_1> ok",
        "key sk-ant-api03-abcdefghijklmnopqrst ok": "key <KEY_1> ok",
        "key ghp_abcdefghijklmnopqrstuvwxyz0123456789 ok": "key <KEY_1> ok",
        "key AKIAIOSFODNN7EXAMPLE ok": "key <KEY_1> ok",
    }
    for raw, want in cases.items():
        assert r(raw) == want, raw


def test_rejected_candidate_does_not_hide_an_overlapping_match() -> None:
    # The card rule first tries a 19-digit span starting inside the phone number;
    # it fails Luhn, and the real card after it must still be found.
    assert r("(212) 555-0199 4111 1111 1111 1111") == "<PHONE_1> <CARD_1>"


def test_non_sensitive_values_are_left_alone() -> None:
    for text in [
        "order 1234 on 2026-10-12",
        "id 3f2b8c1e-9a4d-4e2b-8f1a-2c3d4e5f6a7b",
        "total 1234567890123456 units",  # 16 digits, fails Luhn
        "version 1.2.3 at 10:30",
        "DE00 0000 0000 0000 0000 00",  # fails IBAN checksum
    ]:
        assert r(text) == text, text


def test_structures_redact_values_not_keys() -> None:
    out = Redactor().redact({"a@b.io": ["a@b.io", 3, None, True], "n": 1.5})
    assert out == {"a@b.io": ["<EMAIL_1>", 3, None, True], "n": 1.5}


def test_redact_run_covers_content_fields_and_keeps_ids() -> None:
    run = Run(
        run_id="r1",
        workflow_id="wf",
        started_at=T0,
        status="error",
        input={"ticket": "from jane@acme.com"},
        output="reply to jane@acme.com",
        source="test",
        events=[
            ModelCall(
                event_id="e1",
                ts=T0,
                provider="openai",
                model="m",
                messages=[Message(role="user", content="jane@acme.com")],
                output_text="ok jane@acme.com",
                tool_calls_requested=[
                    ToolCallRequest(id="c1", name="t", args={"to": "bob@acme.com"})
                ],
            ),
            ToolCall(
                event_id="e2",
                ts=T0,
                name="t",
                args={"to": "bob@acme.com"},
                result="sent to bob@acme.com",
                error="bounce bob@acme.com",
            ),
        ],
    )
    out = redact_run(run)
    assert "@acme.com" not in out.model_dump_json()
    assert out.input == {"ticket": "from <EMAIL_1>"}
    model_call, tool_call = out.events
    assert isinstance(model_call, ModelCall) and isinstance(tool_call, ToolCall)
    assert model_call.tool_calls_requested[0].args == {"to": "<EMAIL_2>"}
    assert tool_call.args == {"to": "<EMAIL_2>"}  # equality preserved across events
    assert tool_call.error == "bounce <EMAIL_2>"
    assert out.run_id == "r1" and model_call.event_id == "e1"
    assert run.input == {"ticket": "from jane@acme.com"}  # original untouched


FRAGMENTS = st.sampled_from(
    [
        "jane@acme.com",
        "J.Doe+x@mail.example.org",
        "+1 415 555 0132",
        "(212) 555-0199",
        "4111 1111 1111 1111",
        "5500-0000-0000-0004",
        "GB82 WEST 1234 5698 7654 32",
        "sk-proj-abcdefghijklmnop1234",
        "AKIAIOSFODNN7EXAMPLE",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJlLWhlcmU",
        "<EMAIL_3>",
        "order 42",
        "2026-10-12",
    ]
)
TEXT = st.lists(st.one_of(FRAGMENTS, st.text(max_size=8)), max_size=8).map(" ".join)


@given(TEXT)
def test_redaction_is_idempotent(text: str) -> None:
    once = r(text)
    assert r(once) == once


@given(TEXT)
def test_nothing_sensitive_survives(text: str) -> None:
    assert find_sensitive(r(text)) == []


@given(st.lists(FRAGMENTS, max_size=10))
def test_within_run_equality_is_preserved(values: list[str]) -> None:
    out = Redactor().redact(values)
    assert isinstance(out, list)
    for i, a in enumerate(values):
        for j, b in enumerate(values):
            assert (a == b) <= (out[i] == out[j])


def test_placeholder_shape() -> None:
    assert re.fullmatch(r"<[A-Z]+_\d+>", r("x@y.io"))


def test_redact_run_covers_deopt_reason() -> None:
    from anneal.schema import Deopt

    run = Run(
        run_id="r",
        workflow_id="wf",
        started_at=T0,
        status="success",
        source="test",
        events=[Deopt(event_id="d", ts=T0, step_id="s", reason="enum miss for a@b.io")],
    )
    (deopt,) = redact_run(run).events
    assert isinstance(deopt, Deopt) and deopt.reason == "enum miss for <EMAIL_1>"
