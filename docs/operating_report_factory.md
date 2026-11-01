# Operating report task factory

This route constructs different completion and repair tasks from one independently checked financial workbook. The source contains 200 hypothetical service businesses, eight divisions, a portfolio consolidation and six report layouts: 211 worksheets in total. The source is synthetic and does not reuse an official benchmark workbook.

The source has 93,510 financial report fields, including 88,676 formulas and 4,834 explicit unavailable-comparative values. Two financial implementations check the reference independently. Three actual LibreOffice calculations establish the reference and its stability. Each task retains the original reference bytes and supplied business assumptions.

## Plans and material changes

`factory_fm_scaling.py` declares twenty completion plans. Every plan removes all 62,322 forecast formulas and all applicable historical growth calculations. Additional historical calculations are selected as complete business/metric groups. The planner closes these groups over downstream historical dependencies so surviving formulas do not depend on newly missing historical results. The resulting masks contain 71,327–88,322 formula cells. Literal facts, unavailable values, labels and policies remain present.

`factory_debug_scaling.py` declares twenty repair plans. Every plan includes the existing 4,000 sign and growth defects. Deterministic entity selections add 900–4,320 margin or turnover-change defects. The complete formula graph establishes that these additional report outputs have no downstream consumers. Independent financial values establish a nonzero primary impact for every root. The actual input calculation then checks the complete root set against the complete modified-value set; this does not claim a separate LibreOffice execution for each root.

Both emitters edit the OOXML package without rewriting unaffected worksheet cells. They preserve the supplied facts, workbook structure and reference. Variant names and ZIP packaging do not establish different material: the evaluation identity hashes every typed input value, every input formula, every typed reference value and the public request.

## Individual engineering and shared evidence

`build_operating_reports_factory_batch.py` freezes every plan before execution, starts a live dashboard, recalculates each input in the approved isolated LibreOffice runtime, and checks the full sparse value union. A candidate must have a nonempty financial change set, unchanged literal inputs and worksheet structure, and no native errors. It is exported as the existing seventeen-file Harbor resource task, with the same two-CPU/32-GiB profile for calculation, agent and verifier roles.

Business interpretation and reference correctness are reviewed with separate public and private Codex CLI `gpt-6-sol` / `high` calls for each template. Public reviews receive only public artifacts. Private reviews also receive the independent financial evidence. Source correctness, reference stability and the unchanged verifier's positive and negative regression cases are shared evidence. Each new task still retains its own actual native input, full change set, export, real Harbor controls and execution resource observations. The evidence join identifies these scopes explicitly; it does not label one shared review as twenty independent normal pipeline runs.

All twelve checks remain enabled. The candidate shortcut check can be not applicable while the separate strongest-model confirmation remains pending. An observed model score does not decide task quality. Missing execution evidence remains unknown until the corresponding actual artifact exists.

## Development, confirmation and release

`run_operating_reports_factory_frontier.py` accepts one or more engineered batches. It freezes all selected exports before model requests and reserves each logical material separately for development and confirmation. It uses native Codex CLI `gpt-6.1-sol` / `xhigh`, a single attempt per selected task, zero outer retries and the existing version-six cumulative tool accountant. Primitive tool time must be strictly below 1,800 seconds. Model response time is excluded. The 14,400-second operational guard cannot supply a model-failure score.

`freeze_operating_reports_factory_cohort.py` selects exactly ten tasks per category using development evidence only. It prefers valid development failures and then larger predeclared change sets. Infrastructure failures, missing timing and incomplete resource observations cannot enter as zeros. The cohort is persisted before fresh confirmation requests, then copied byte-for-byte to the real repository-root `SpreadsheetEval/` directory.

`run_exact_root_harbor_controls.py` executes these exact commands from the repository root:

```bash
harbor run -p SpreadsheetEval -a oracle
harbor run -p SpreadsheetEval -a nop
```

The control receipt verifies one actual trial for every delivered task, all oracle rewards equal to one and all nop rewards equal to zero. It also checks exact payloads, both execution roles, image ancestry and the absence of the owned containers after completion.

`join_operating_reports_factory_final_quality.py` combines the shared semantic/source evidence with each selected material's engineering and actual execution evidence. `finalize_operating_reports_factory_release.py` requires that complete quality join, the exact root controls and a fresh twenty-task confirmation with Overall Pass@1 at most 0.2. It recomputes the effective scores and checks that the delivered payloads match the confirmed snapshots.

## Batch commands

The batch builder consumes the retained, hash-bound source manifest. Its source provider is in `scripts/build_operating_reports_200_source_revision2.py`; earlier source and task engineering receipts remain immutable.

```bash
.venv312/bin/python scripts/build_operating_reports_factory_batch.py \
  --mode financial_modeling --count 20 --concurrency 4 --output outputs/research/my_fm_batch
.venv312/bin/python scripts/build_operating_reports_factory_batch.py \
  --mode debugging --count 20 --concurrency 4 --output outputs/research/my_debug_batch

.venv312/bin/python scripts/run_operating_reports_factory_frontier.py prepare \
  --batch outputs/research/my_fm_batch/engineered_batch.json \
  --batch outputs/research/my_debug_batch/engineered_batch.json \
  --phase development --concurrency 16 --output outputs/difficulty/my_development --run
```

The general pipeline continues to support arbitrary seed paths through `scripts/run.sh --seeds /path/to/workbooks --count 40`. This retained-source factory is a separate reproducible task family, not an assumption about every spreadsheet's sheet names or field structure.

The one-shot continuation can start while that development batch is running. It waits for the existing terminal, freezes the cohort, runs fresh confirmation alongside the exact root controls, joins quality evidence and writes the final release receipt. It never restarts an existing attempt. Its dashboard remains available through all these stages.

```bash
.venv312/bin/python scripts/finish_operating_reports_factory_batch.py \
  --development-terminal outputs/difficulty/my_development/terminal.json \
  --batch outputs/research/my_fm_batch/engineered_batch.json \
  --batch outputs/research/my_debug_batch/engineered_batch.json \
  --fm-join /path/to/shared_fm_native_join.json \
  --debug-join /path/to/shared_debug_native_join.json \
  --confirmation-concurrency 20 --output outputs/research/my_delivery
```

## Statistics

Count the reference as one synthetic source, the forty different inputs as forty candidates, and the selected twenty inputs as twenty delivered tasks only after finalization succeeds. Report candidate conversion and source count separately. Development and fresh confirmation calls are separate observations. Native input/output token totals come from actual completed usage records; cached input is a subset, and provider payment remains unknown without billing evidence. Shared semantic calls and historical experiments have separate consumption scopes.

## Published batch and append-only timing interpretation

The [version-two release](../reports/operating_report_factory_release.json) qualifies twenty tasks, ten per category. The frozen, fresh native `gpt-6.1-sol` / `xhigh` confirmation has zero successes in twenty attempts. The [actual root controls](../reports/operating_report_factory_controls.json) contain twenty oracle rewards of one and twenty nop rewards of zero, with actual resources for both execution roles. All twelve checks remain enabled: each delivered task has evidence for Q01–Q12; candidate Q08 is not applicable because the separate frozen-set difficulty gate supplies that measurement.

The original F11 attempt retains timing `UNKNOWN`. Its original aggregate evaluation retains `infrastructure_failed`, which was derived from that timing status. The narrow missing parser case was a pure display expression, `rr.forEach(r=>text(r));`. A separate read-only supplement binds all twenty-two complete execution wrappers from that same attempt and establishes a conservative cumulative tool upper bound of 126.614143299 seconds. It does not run a new attempt or change the execution-budget contract.

`finalize_operating_reports_factory_with_timing_supplement.py` consumes the original confirmation and this additional evidence. It verifies the original hashes and the supplement, constructs a scoped in-memory interpretation, and invokes the unchanged, hash-pinned quality join and finalizer. It writes new reports with `timing_interpretation` provenance. It does not modify the original protocol results, raw rewards, UNKNOWN state, aggregate status, logs or reservations. The published report explicitly records zero new model, LibreOffice and Harbor calls for this step.

On the construction machine, the retained evidence can be consumed again into **fresh output paths** with the following command. These private inputs are under ignored `outputs/`; they are not required to run the delivered oracle/nop tasks. The consumer refuses existing output files, so choose a new directory for each audit.

```bash
.venv312/bin/python scripts/finalize_operating_reports_factory_with_timing_supplement.py \
  --cohort outputs/research/operating_reports_factory_delivery_20261101T050700Z/cohort/cohort_frozen.json \
  --fm-join outputs/research/factory_shared_FM_semantic_review_20261101T043814Z/all20_native_append_only_join.json \
  --debug-join outputs/research/factory_shared_DBG_semantic_review_20261101T044147Z/all20_native_append_only_join.json \
  --root-controls outputs/research/operating_reports_factory_delivery_20261101T050700Z/root_controls/terminal.json \
  --confirmation outputs/research/operating_reports_factory_delivery_20261101T050700Z/confirmation/terminal.json \
  --supplement outputs/research/operating_reports_factory_F11_timing_supplement_20261101T054200Z/receipt.json \
  --quality-output outputs/research/release_evidence_replay_01/quality.json \
  --output outputs/research/release_evidence_replay_01/release.json
```

The actual confirmed set includes ten tasks with only the two known two-decimal boundary differences. The other ten have associate-income display differences, nine also with the boundary differences. The [failure summary](../reports/operating_report_factory_failure_summary.json) reports observed cells; it does not establish a unique financial reasoning cause for every failure. The fixed primary grading rule and each actual score remain unchanged.
