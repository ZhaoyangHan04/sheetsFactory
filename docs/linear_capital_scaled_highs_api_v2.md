The first HiGHS transport test reached one native `Highs` instance and API
configuration attempt. It reached zero `native.run()` calls and zero optimizer
searches. P01 was never started. The pinned HiGHS 1.15.1 Python convenience
method `setMaximize()` returns `None`; the original engineering code required
a `HighsStatus.kOk` return and rejected it. The original source, preparations,
failure, exact resource snapshots, and verified owned cleanup remain unchanged.

The API-v2 route contains only new files. `highs_engineering_api_v2.py` checks
the exact original engine SHA and replaces one expression,
`native.setMaximize()`, with
`native.changeObjectiveSense(hs.ObjSense.kMaximize)`. The existing `configured`
status check remains. A native error status still stops the attempt. All math,
coefficient scaling, exact deduplication, solver settings, candidate rounding,
original-row audits, and nonadmission behavior remain the original code. The
mathematical result envelope remains version 1; the compatibility module has
API version 2. Native bundles contain the new wrapper under
`highs_engineering.py` and the exact original under
`frozen_highs_engineering.py`, so imports never require repository paths.

`highs_runtime_api_v2.py` checks and loads the exact original HiGHS lifecycle
in its own namespace. Only the engine import, the six-file portable source
closure, owned container names, and preparation/terminal API-v2 identities and
envelope versions change. The original two-CPU lifecycle, image and dependency
checks, dashboard, before/after resource evidence, artifact retention, and
full-ID cleanup remain unchanged. Neither old module globals nor source bytes
are modified.

`run_linear_capital_scaled_highs_screen_api_v2.py` likewise binds the original
driver SHA, imports the two new adapters, uses new API-v2 kinds/version 2, and
records the exact retained original failure in both prospective records. Its
recipe includes all new wrappers and the old driver, runtime, engine, original
two-CPU lifecycle, and complete matrix-validation closure. Its CLI commands
and arguments match the original driver. An old failed or passed prospective
cannot serve as this route's tiny API pass.

The new route uses the same frozen HiGHS 1.15.1/NumPy 1.26.4 vendor, fixed
three-project numeric fixture and fixed P01 matrix. Both new prospective
records are prepared before any new optimizer run. Every attempt retains
2 CPUs, 32 GiB, PID limit 256, no network, the pinned image, the unchanged
800-second native maximum and separate 920-second operational guard, no seed,
no objective cut, no exclusion and zero outer retries. P01 remains blocked
until its own new tiny test returns exact native OPTIMAL, plan `[0,1,1]`,
objective 13, all three integer row audits and verified cleanup. This path
does not admit a reference or certify hardness.

Focused tests reproduce the actual convenience-method `None` return, check
both success and error statuses on the low-level call, compare unchanged pure
math with the original, import the complete portable native bundle without
creating a native solver, recheck cold source/dependency identities, and
preserve the first-attempt and prior-failure gates. They start no native
optimizer, container, model, LibreOffice, Harbor or financial forward. Actual
new tiny/P01 execution remains pending root review of final hashes and both
concrete prospective records.
