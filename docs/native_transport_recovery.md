# One bounded development recovery after a native transport failure

This feature prepares a future recovery of the exact completed M02 debugging
trial whose original terminal SHA-256 is
`62cefd334f71b94eb2829dcd7ed79902516eaa8bc88ed0d5f275e569dc82c115`.
It does not launch a recovery automatically. Development results cannot qualify
the final benchmark, and infrastructure failure remains unscored.

The prospective profile
`config/native_transport_profiles/factory_stream_retries8_v1.json` adds only
`model_providers.factory.stream_max_retries = 8`. HTTP request retries and the
stream idle timeout retain their defaults. The native model and effort stay
`gpt-6.1-sol` and `xhigh`; cumulative tool time stays strictly below 1800 seconds
with parallel executions added and model time excluded. The 14400-second
operational guard, original native CLI binary, pinned image, 2 CPU / 32 GiB
resource profile, prompt and complete seventeen-file export stay bound to the
first preparation. This is a resilience mitigation. The failed transport layer
is unknown, so this is not an established root-cause fix.

The isolated `native_transport_frontier` module starts from the exact frozen
version-three runner AST. Counted substitutions add the transport setting,
frozen profile checks, provenance and an isolated installed-agent class path.
Scoring, tool clocks, execution, dashboard and resource observation use the
existing implementations. The original runners and first preparation entry
remain unchanged.

## Evidence required before preparation

`scripts/prepare_linear_capital_transport_recovery.py` requires the exact
original terminal, original probe and completed read-only diagnostic hashes.
It checks the completed actual Harbor trial, native `turn.failed` stream/request
error, null score, zero scored tasks, raw verifier zero caused by a missing
submission, and absence of a submitted workbook. It binds every existing file
in the ended evaluation tree, local provider/installed-agent implementations,
original native binary, and all original token usage. It retains the first
attempt's 46773 input, 549 output and 42112 cached input tokens.

Completed model scores of either zero or one, raw one, unknown failures,
operational-guard or incomplete-timing evidence, unfinished trials, changed
material/export, intentional stop, duplicate trial or existing recovery are
ineligible. The exact original selection is the sole same-material exception
in history. Every history entry is retained; other uses of the same logical
material are rejected even after task renaming or workbook repackaging.

The new immutable `recovery_manifest.json` is stored under the standard searched
history roots. It reserves at most one recovery for this material. A shared
history-root lock serializes preparation and the durable launch reservation.
The launch receipt spends that recovery even if launching fails. The inherited
runner's generic retry allowance does not authorize any further attempt.
Old manifests, trial bytes, zero-retry terminal and token history are preserved.

## Commands

Run from the repository root. The `assess` command is read-only and starts no
model, spreadsheet engine, optimizer, Harbor job, container or dashboard:

```bash
.venv312/bin/python scripts/prepare_linear_capital_transport_recovery.py assess \
  --parent-terminal outputs/difficulty/linear-capital-M02-DBG-first-development-20261031T095900Z/prepared/development_terminal.json \
  --transport-diagnostic outputs/difficulty/linear-capital-M02-DBG-first-development-20261031T095900Z/prepared/completed_dbg_transport_readonly_diagnostic_v2.json
```

After review, `prepare` accepts those same two arguments and a fresh `--output`
directory under `outputs/difficulty` or `outputs/research`. It creates the
immutable reservation and starts no services. `validate --prepared DIRECTORY`
rechecks that reservation and all original evidence.

Only the separate explicit command below starts the one recovery. Its prepared
directory must already contain the reviewed reservation. Both paths must be
fresh, separate directories under the standard history roots:

```bash
.venv312/bin/python scripts/prepare_linear_capital_transport_recovery.py run-development \
  --prepared outputs/difficulty/REVIEWED_RECOVERY/prepared \
  --output outputs/difficulty/REVIEWED_RECOVERY/evaluation
```

All cold checks finish before the existing evaluator starts its normal live
dashboard and audit. There is no additional UI. Credentials retain the approved
existing configuration references and are never copied into the recovery
manifest or printed by these commands.

## Offline verification

```bash
.venv312/bin/python -m pytest -q tests/test_linear_capital_transport_recovery.py \
  --basetemp outputs/tmp/native-transport-recovery-tests-UNIQUE
```

These tests use explicit mocked source/engine admission and mock the evaluator
and observer. They verify evidence eligibility, full history, unchanged material,
profile/TOML propagation, immutable parent artifacts, the one-recovery bound,
failed-launch reservation and concurrent launcher exclusion. They make no model,
spreadsheet-engine, optimizer, Harbor or Docker calls. Separate unchanged-runner
regressions cover the original linear preparation and all three original
frontier namespaces.

The stream retry setting follows the official
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
