# Result Report Failure Signaling Design

## Objective

Make the GitHub Results Verifier fail visibly whenever a required result-report
destination is not confirmed, without stopping attempts to the remaining
destinations and without resending deliveries already marked complete.

## Required destinations

- Evening reports require Telegram admin, VIP, and free.
- Final reports require Telegram admin, VIP, free, Facebook, and Instagram.
- Only `success` and `complete` are healthy terminal outcomes.
- Every other outcome is unhealthy, including `claim_failed`, `ambiguous`,
  `not_configured`, `token_invalid`, `delivery_failed`, and
  `completion_failed`.

## Design

`publish_result_report` will keep its existing independent-delivery behavior:
it attempts every required destination and returns one status per destination.
It will not raise on the first delivery failure.

`publish_available_result_reports` will continue printing the complete summary
for each eligible report. After all eligible reports have been attempted, it
will validate the collected status maps. If any required destination is not
`success` or `complete`, it will raise a safe runtime error that names only the
report and destination statuses. The exception must not contain tokens,
request bodies, credentials, or remote response bodies.

If no report is eligible, the verifier remains successful. Reports whose
destinations are already `complete` also remain successful and do not call any
external transport.

## Workflow behavior

The existing GitHub Actions step runs `python backend/verificar_resultados.py`.
An unhealthy delivery status will therefore produce a non-zero process exit
and mark the step and workflow as failed. No YAML log parsing or additional
workflow output is required.

## Testing

Tests will prove that:

1. `success` and `complete` are accepted.
2. Every other known delivery outcome is rejected.
3. Validation happens after all destinations have been attempted.
4. A report with one unhealthy destination raises only after its complete
   outcome map has been collected and its summary printed.
5. No eligible reports remain a successful no-op.
6. Existing idempotency tests continue to pass.

## Acceptance criteria

- A five-destination final report with any unconfirmed destination makes the
  Results Verifier workflow fail.
- The log still shows the status of all five destinations.
- A rerun with all five destinations recorded as `complete` succeeds and sends
  nothing again.
- The result-report and Supabase contract test suites pass.
