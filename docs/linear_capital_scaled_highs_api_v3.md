API-v3 preserves both prior failure routes. Together they created two native
HiGHS instances and two API configuration attempts, reached zero `native.run`
calls/optimizer searches, and never started P01. API-v2 corrected the void
`setMaximize()` convenience wrapper. Its next failure was the strict status
check around diagnostic `writeModel()`, after generated-name warnings and a
written LP; that attempt did not retain the exact returned status.

The new engineering module hash-binds API-v2 and keeps its objective-sense fix.
It changes only diagnostic export handling: capture `writeModel`'s exact
return, permit only `HighsStatus.kOk` or `HighsStatus.kWarning`, and require
the requested fresh LP to exist and be nonempty before search. Other statuses,
missing files and empty files stop the attempt. Errors include the actual
returned status; successful solver results retain `native_model_export_status`
and `native_model_export_bytes`. No global option-status check is relaxed.
The diagnostic LP is never fed into `native.run`; native coefficients, row
deduplication/scaling, rounding, options, limits and exact audits are unchanged.

The runtime is a hash-bound thin copy of API-v2 with new version-3 envelope
identities, owned names and a seven-file portable native closure. The closure
contains API-v3 as `highs_engineering.py`, the frozen API-v2 wrapper as
`highs_engineering_api_v2.py`, the frozen original engine, and the four existing
model/spec wrappers and frozen kernels. The driver similarly reuses the exact
API-v2 AST constructor and preserves the complete first-attempt and tiny/P01
gates. Both new prospective records bind both immutable prior diagnostics and
the complete old/new source recipe. Old source, preparations, failures, vendor
and image are unchanged.

Before any new native instance, a read-only audit of the approved HiGHS 1.15.1
Python source and binding stubs checked every called API. `setOptionValue`,
`addVars`, `changeColsCost`, `changeColsIntegrality`, `changeObjectiveSense`,
`addRow`, `writeModel`, and `run` declare `HighsStatus`; none has a void Python
override. The existing `run` allowance for kOk/kWarning is retained. The
solution/info/status/runtime accessors return the declared objects/scalars
used by the unchanged result extraction. The audit creates no native instance.

Focused tests reproduce the void convenience API, strict status errors,
warning/ok exports, missing/empty exports, exact status retention, unchanged
pure math, complete portable imports, immutable two-failure lineage and
first-attempt guards. No native optimizer runs in tests.

Both new prospective records are frozen and cold-validated before execution.
The bounded operational authorization permits one new API-v3 tiny search and,
only after its own exact native OPTIMAL/[0,1,1]/13/all-three-row/resource/cleanup
pass, one fixed P01 search. Both retain the same vendor/image, 2 CPUs, 32 GiB,
PID limit 256, no network, 800-second native maximum, separate 920-second guard,
zero retries, no seed, no objective cut and no exclusion. Any actual failure
stops the sequence. P01 results remain unqualified and nonadmitting; this
engineering repair makes no claim about model scores or question difficulty.
