This is a separate engineering screen for the fixed completed `L360-P01`
integer model. It consumes the previously completed raw and full A/B financial
artifacts, retains the complete original 360-project/941-row matrix, and mounts
only the canonical matrix, minimal frozen matrix-validation code, and frozen
dependency bytes. It does not consume a winner, incumbent, objective cut,
excluded plan, or reference-solver output.

`highs_runtime.py` creates an isolated copy of the hash-bound original
two-CPU optimization lifecycle. It reuses its dashboard, progress reporting,
producer lease, exact image/resource checks before and after execution, complete
artifact retention, full-ID owned cleanup and absence proof. The container is
the original pinned image with 2 CPUs, 32 GiB, PID limit 256 and no network.
The unchanged `highs_engineering.py` receives exactly two threads and an
800-second native limit; the separate operational guard is 920 seconds. There
are no outer retries. Preparation starts no optimizer or container.

The solver scales objective coefficients by one million, removes only exact
duplicate and satisfied zero rows, and scales each remaining row and RHS by
`max(1, RHS, max(abs(coefficients)))`. Relative and absolute native gaps are
zero, and MIP feasibility tolerance is `1e-9`. The observed M02 native route
requested absolute gap `1e-7`; this screen retains the already-reviewed
engineering adapter's stricter zero setting. Every retained integer candidate
is audited against all original rows with Python integers, including dropped
rows, and its exact pence objective is recomputed.

The pinned image lacks NumPy. A separate, owned, read-only dependency probe
retained that failure and proved cleanup. Root then approved an isolated new
vendor containing the exact official PyPI `highspy==1.15.1` CPython 3.12 Linux
wheel (SHA256
`9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b`)
and exact copies of the existing approved `numpy==1.26.4` package, metadata and
shared libraries. No package was installed into the image, old vendor or host
environment. The complete 806-file new inventory, all 791 original NumPy file
references, official metadata, wheel bytes and an owned pinned-image import
probe are frozen and checked again before execution. The probe imported both
modules from the mounted vendor without creating a native solver instance.
The M02 dependency versions were not retained; version equivalence is unknown.

`scripts/run_linear_capital_scaled_highs_screen.py` has explicit `prepare-tiny`,
`validate-tiny`, and `run-tiny` commands for one three-project API smoke, plus
`prepare`, `validate`, and `run` for fixed P01. Preparation requires exact
`--vendor-lock`, `--dependency-probe` and fresh `--output` paths. P01 preparation
also requires `--tiny-prepared`. The tiny matrix is the unchanged passing
three-project CP-SAT transport fixture, with canonical row IDs. Its expected
plan `[0,1,1]`, objective 13 and all three row checks stay in the host
prospective; they are absent from the native job request. Both prospective
records must be reviewed before any solver starts. The tiny maximum remains
800 seconds, even though this trivial matrix should finish immediately.

P01 execution requires the exact completed tiny native optimum, integer
plan/objective/row audit, dependency identity and owned cleanup. A tiny failure
blocks P01 and is preserved without retry. Per-job exclusive started records
and launcher locks retain the first engineering attempt. An actual P01 result
always remains unqualified and nonadmitting, including native OPTIMAL. Float
status and gaps do not constitute formal optimality proof or a hardness
certificate. This experiment tests a previously effective scaled solver route;
it does not certify the task's difficulty or change any model tool-time budget.

The test suite uses tiny matrices and mocked process, dashboard, resource and
solver-result boundaries. No native optimizer executes during tests. Actual
800-second solves remain pending root review of both concrete prospective
records and the dependency/image plan.
