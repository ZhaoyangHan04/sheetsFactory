# New N360 reference core

`sheets_factory.workbook.linear_capital_scaled.optimization_runtime` accepts
only the new `linear_capital_scaled_direct_binary_integer_model`, version 2.
Production matrices contain all 360 ordered project flags and all 941 business
rows, with the full declared family census. Tiny one-to-four-project fixtures
are permitted for offline tests. Old 240-project matrices cannot be relabelled.

The private reference keeps the original producer contract: pinned image,
16 CPU, 32 GiB, 256 PIDs, no network, one 3600-second CP-SAT attempt for the best
plan and one 3600-second attempt excluding the complete winner. The model and
verifier resource profile remains 2 CPU / 32 GiB with the unchanged strict
1800-second cumulative tool budget. Preparation only copies existing exact
matrix, source and vendor bytes; it starts no services or financial forward.

The native bundle contains only the new specification and two model adapters,
their three frozen upstream sources and an empty package initializer. Financial
code is imported lazily by model construction and is absent during native
matrix validation and solving. Original runtime and model namespaces remain
unchanged.

`linear_capital_scaled.reference` and
`scripts/run_linear_capital_scaled_reference.py` expose `prepare`,
`validate_prepared`, `execute_prepared`, `validate_completed`, `recipes`,
`_checked_finance` and the original reference material field names. The new
`KIND` is `linear_capital_scaled_producer16_best_runner_dual_financial_reference`;
preparation and completed envelopes use version 2.

The persisted finance terminal has kind
`linear_capital_scaled_full_financial_crosscheck`, version 2, `passed: true`,
`qualified: false`, exact zero `optimizer_calls`, `LO_calls` and `model_calls`,
and `recipe` equal to `reference.finance_recipes()`. These nine fields are exact
three-key artifact references (`path`, `sha256`, `bytes`):

- `specification` and `raw_preparation`;
- `universe_A`, `universe_B`, `model_A`, `model_B`;
- `complete_financial_comparison`, `all_predeclared_plan_comparison` and
  `complete_matrix_comparison`.

The raw preparation binds the same specification reference and canonical hash,
plus a complete nonempty `diagnostic_plans` list. This persisted terminal is
separate from the in-memory financial kernel result,
`independent_scaled_linear_capital_financial_crosscheck`, version 2.

Cold admission rechecks the entire Fraction/Decimal financial comparison,
predeclared diagnostic plans, new 360-project/941-row matrix scope, exact source
hashes and both complete integer matrices. Best and winner-excluded runner must
both have checked native OPTIMAL status, pass every integer row and agree with
both complete financial universes. Their integer-pence objective gap must be at
least one. Limited incumbents and tied runners remain unadmitted. The private
density gate is 120–240 selected projects; it adds no public cardinality rule.

Native solver status plus exact integer primal checks is programmatic evidence,
not a formal global proof. The completed reference remains unqualified for task
quality or final difficulty. Optional unseeded scaled-HiGHS engineering is a
separate route and cannot replace these reference admission gates.

Offline verification:

```bash
.venv312/bin/python -m pytest -q tests/test_linear_capital_scaled_reference.py \
  --basetemp outputs/tmp/scaled-reference-tests-UNIQUE
```

The tests use exact tiny matrices, explicit mocked finance boundaries and
mocked native/container lifecycles. They start no solver, model, spreadsheet
engine, Harbor job, container or dashboard.
