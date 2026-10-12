"""Task-level success for the synthetic support workflow.

Stands in for the definition a partner agrees to in writing before compilation:
the job is done when a ticket was created for the customer the lookup returned
and the reply was sent to the person who wrote in.
"""

from anneal.schema import Run, ToolCall


def support_task_done(run: Run, recorded: Run) -> bool:
    if run.status != "success":
        return False
    calls = {e.name: e for e in run.events if isinstance(e, ToolCall) and not e.error}
    lookup, ticket, send = (
        calls.get(n) for n in ("lookup_customer", "create_ticket", "send_email")
    )
    if lookup is None or ticket is None or send is None or not isinstance(lookup.result, dict):
        return False
    return bool(
        ticket.args.get("customer_id") == lookup.result.get("customer_id")
        and send.args.get("to") == run.input["email"]
    )
