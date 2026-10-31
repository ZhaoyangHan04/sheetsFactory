The scaled task validator and development entry are separate, versioned
adapters. They hash-bind the complete original implementations and execute in
their own namespaces. The old scripts and their records remain unchanged.

`scripts/validate_linear_capital_scaled_task_view.py` has one source provider,
`scaled360`, backed by `build_linear_capital_scaled_source.py`. It accepts
`independently_verified_linear_capital_scaled_native_source` version 1 and
`materialized_unverified_linear_capital_scaled_task_view` version 1. Its own
preparation and completed-validation envelopes are version 2; the completed
kind is `linear_capital_scaled_task_view_actual_validation`.

The Python API is `prepare(source_manifest, view_manifest, output,
source_provider='scaled360')`, `validate_prepared(output)`,
`execute_prepared(output)`, and `validate_completed(receipt)`. The CLI provides
`prepare --source-manifest PATH --view-manifest PATH --output PATH`,
`validate --prepared PATH`, `run --prepared PATH`, and
`validate-completed --receipt PATH`. It has no provider override. Preparation
reads existing evidence; only `run` starts actual calculations.

The complete original evidence gates remain: seven actual calculations for a
modeling view, eleven for a debugging view, the same temporary-plan baseline
and three isolated policy families, complete nonempty changed-value sets,
two complete typed input-stability comparisons, typed source-goal stability,
all five positive and negative controls, exact calculation chains and actual
resource receipts. Passing this validator does not qualify a task, run the
normal Factory nodes, or certify difficulty.

`scripts/prepare_linear_capital_scaled_development.py` exposes the original
`prepare`, `validate_prepared`, and `run_development` signatures and CLI
subcommands. Its kind is
`prequality_linear_capital_scaled_native_development`, schema version 2. It
requires the genuine completed scaled validation above. It retains the exact
17-file export, source/instruction/whole-workbook logical task binding, pinned
image, source/agent/verifier resource contract, and `MAX_CONCURRENCY=2` export
audits. Development runs one task with native `gpt-6.1-sol`, `xhigh`, and zero
outer infrastructure retries. Qualified task count remains zero.

The frozen v3 clock policy counts the sum of tool durations, including parallel
tools, strictly below 1800 seconds; model time is excluded. The separate 14400
second elapsed guard is an operational limit. The development source freezes
`factory_stream_retries8_v1` before the first attempt and dispatches through
`native_transport_frontier`. Only native provider `stream_max_retries=8`
changes transport. Request retries and stream idle timeout remain unchanged.
This is a resilience mitigation; it does not establish a transport root cause.
This entry does not use the historical DBG recovery eligibility path.

Both declared history roots are searched and retained. The exact known
zero-model-call preparation schema remains evidence without fabricated model
attempts. Every model selection retains its task checksum. Matching material
is rejected despite renamed tasks or ZIP packaging changes; missing or corrupt
history fails closed. Cold validation permits appended unrelated selections
while requiring every frozen history reference to remain present and unchanged.
Corrupt or same-material additions still fail. Logical material identities retain the original version-1 schema
so changing the driver envelope cannot reset trial history.

Before dispatch, a shared lock and an exclusive per-material record under the
first declared history root prevent two prepared copies from launching the
same material. Both reservation and first-attempt records are retained if the
dispatch fails. A reservation authorizes no second attempt. Per-snapshot
launcher locking also remains in place. Under the shared reservation lock, the
launcher captures the complete current history and its model/nonmodel partition
in both durable records. The evaluation runner receives every captured model
selection, including unrelated selections appended after preparation. The
original prepared snapshot remains immutable.

All implementation checks for this handoff use tiny mocked calculation,
image-inspection, model and observer boundaries. They start no actual source,
finance, solver, LibreOffice, Harbor, model or service. Actual preparation,
validation and development execution require the separately reviewed source
evidence and root authorization.
