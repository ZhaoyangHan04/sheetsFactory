# Process-local source reuse for a future N360 paired view

`scripts/prepare_linear_capital_scaled_cached_view_pair.py` is a new entry point.
It does not change either frozen paired-view producer or any running attempt.
Only `--run` permits actual view calculations. Import and preparation start no
LibreOffice, model, solver, or Harbor service.

The entry point constructs the committed
`linear_capital_scaled_quality.LinearSourceAdmission` once for the selected
source in each Python process. That object invokes the real, SHA-bound provider's
complete cold source validator. Its recursive references bind the source,
financial and native evidence, workbook, bindings, public primitives, resource
profile, provider registry, provider module, and financial recipe. Later calls
use `require_source_admission` to guard those references. Small artifacts are
hashed on each check; large artifacts are hashed at admission and whenever their
complete filesystem identity changes, following the committed admission policy.

The source result is reused through private function-global namespaces and a
source helper facade. All local functions from the frozen pool pair and task
validator have their original code objects and a private global dictionary.
The source facade accepts only the exact admitted source reference. Unknown
functions, unexpected imported functions, and closures fail closed. No original
module globals are patched. JSON metadata, fabricated objects, objects from
another admission namespace, and objects inherited by another process cannot
authorize source reuse.

Failure and terminal writes use an immutable copy of the original admission
metadata. They do not call a source guard while writing a diagnostic. The
unchanged validation and recipe boundaries still perform the guards; a failure
there must be retained even when the source has changed. A mocked mid-run source
mutation verifies that both failed validators and the failed pair retain their
terminals and release the original leases.

The frozen full 20-member pool policy and original P01 first-development
declaration remain binding. The pair still fixes and materializes both modes,
prepares both validators before the first calculation, then performs exactly
seven modeling and eleven debugging calculations. Original source identity,
canonical bindings, task-view recipe, entire D, typed stability, all five local
controls, all debugging family effects against the same provisional-plan
baseline, actual resource receipts, pinned image, owned cleanup, fresh output,
no-retry, dashboard, and lease checks remain in their original bytecode.

Every pair preparation and terminal reports the current process's genuine
source cold-validation count, its process ID, and the complete reuse policy.
These fields report execution; they cannot re-create an opaque admission. A
separate `prepare` process and `--prepared --run` process each cold-validate once.
A single `--source-manifest ... --output ... --run` process cold-validates once
across preparation and execution. A new process always constructs a new opaque
admission. The count describes source validation only; it does not count or
replace view calculations, full comparisons, normal quality, or difficulty work.

Preparation example, after a complete actual source is available:

```bash
.venv312/bin/python scripts/prepare_linear_capital_scaled_cached_view_pair.py \
  --source-manifest /absolute/verified/source_manifest.json \
  --output /absolute/fresh/output
```

Actual execution requires the explicit `--prepared /absolute/fresh/output --run`
form, or `--run` on the preparation command. Neither form permits a replacement
provider, alternative pool, new runtime limits, or a retry of an existing attempt.

Unit tests use real tiny workbooks and complete frozen comparison/control code,
with explicit mocks at financial admission, task-plan compilation, resource
engine, and dashboard boundaries. They exercise the exact 7+11 role inventories,
one cold validation per live session, a new cold session for a new process,
unchanged original globals, source/provenance/recipe drift, forbidden fake
admissions, incomplete D/control/family/resource evidence, and failure retention.
No actual service call is authorized by adding this feature.
