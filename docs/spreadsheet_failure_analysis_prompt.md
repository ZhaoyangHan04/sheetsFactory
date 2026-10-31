# Evidence-only analysis of completed spreadsheet attempts

Use `scripts/analyze_spreadsheet_failure.py` to read existing evidence. It does not run a model, calculate a workbook, call the evaluator, retrieve sources, repair files, or change a score. Read only the bound workbook, report and trajectory evidence. Do not read authentication, environment or provider configuration files, and do not copy raw commands that contain credentials.

One completed case:

```sh
.venv312/bin/python scripts/analyze_spreadsheet_failure.py case \
  --inventory INVENTORY.json --case Debugging/04_01 \
  --output-workbook SUBMITTED.xlsx --trajectory TRAJECTORY.json \
  --result RESULT.json --official-score EXISTING_SCORE.json --output ANALYSIS_DIRECTORY
```

One snapshot while a cohort is running:

```sh
.venv312/bin/python scripts/analyze_spreadsheet_failure.py scan \
  --inventory INVENTORY.json --evaluation COHORT_DIRECTORY --output ANALYSIS_DIRECTORY
```

Run the scan again when more cases finish. Identical evidence reuses its receipt. Newly completed or changed evidence produces a separate report; old receipts remain valid. A partial file is an analysis hold, not a failed model case. The scan handles `cases/TASK/terminal.json`, per-case evaluation directories and a standalone evaluation directory. Reused original attempts keep their original result/submission and scores. Preliminary native-terminal reports can precede official scoring.

The input contract, report contract and reviewer diagnosis contract are in `config/spreadsheet_failure_analysis_v1.schema.json`. References bind absolute path, SHA-256 and byte count. `--manifest` supports a manually bound case outside the official inventory. An optional existing `baseline_cache` is usable only if its source definitions and sheets match. No recalculation is performed to obtain one. `analysis_numeric_quantum` controls a separate cache diagnostic and never replaces the actual official score. Raw numeric differences and unavailable formula caches are retained. Exact tool-clock eligibility remains under its original evidence contract; wall time and model time are never substitutes.

## Reviewer prompt

Analyze this completed attempt using the frozen case manifest, offline report, actual trajectory, public instruction, original workbook, reference workbook, submitted workbook and actual score receipts. Return a `reviewed_offline_spreadsheet_failure_diagnosis` under the schema. Do not execute any tool that calculates, evaluates, repairs, downloads or queries a model. State unknown when the required evidence is missing.

1. Establish what happened: normal completion, known tool-budget exhaustion, infrastructure/transport hold, missing submission, or unknown. Keep raw official accuracy/modification/regression, project exact diagnostic and protocol eligibility separate. A scored artifact can coexist with infrastructure failure; a missing terminal is not zero. Preserve the actual clock contract.
2. Identify the official comparison group before interpreting the score. FM and ordinary DBG compare cached values, with formula fallback for some error cases. Embedded DBG compares formula text under the pinned evaluator's normalization. Color DBG also compares font color. Font/style-tree differences and formula spelling differences do not establish financial reasoning error. The extractor's parsed identities, numeric quantization, raw fonts and additive equivalence checks are diagnostics, not an implementation of the official score.
3. Read the public task as a business request, without requiring it to list private cells or formulas. Explain which schedules and outputs it requests and which remain supplied context. For each observed omission, determine whether that business family was actually requested and identifiable. An instruction that names only one schedule while masking other schedules is a scope defect, not established difficulty. An open audit may permit extra changes; do not label every change beyond reference edits an error.
4. Reconstruct the actual model strategy from recorded steps. Cite step IDs for searches, inspections, assumptions, edits, calculations, checks and final submission. Record intact adjacent formulas, unmutated bridges, direct aliases or supplied answers that explain an easy repair. Distinguish an observed shortcut from a conjecture about why it worked. No network syntax in a trace does not prove absence of retrieval or pretrained familiarity. A request mentioning a benchmark/gold is only a lead: claim external-answer retrieval only when an actual successful response/artifact and its use are evidenced. Copying a public original answer is not evidence of independent business reasoning. Never change the frozen network policy retrospectively.
5. For each proposed cause, provide a concrete cell witness with input/reference/output definition and typed value, a relevant trace step, the exact public wording or source business rule, and an independent check. Labels are location, scope, period, unit, finance_reasoning, incomplete, protocol, scoring_ambiguity, infrastructure, cache, evaluator_formula, evaluator_font, external_answer_retrieval or unknown. Separate observation, supported inference, hypothesis and unresolved alternatives. A reference disagreement alone is not an independent financial check. If the source labels support a different period/sign/base convention, retain that policy/scoring ambiguity.
6. Check causal attribution. A repaired root can still have a wrong output because of separate upstream changes. SUM versus addition over numeric operands can be equivalent without proving those operands correct. Do not attribute all downstream errors to one changed formula without a dependency witness and a counterfactual. Describe specific minimal counterfactuals and whether they were actually executed. Never invent a counterfactual score.
7. Recommend at most three transferable mechanisms. For each, bind the actual witness, identify the dimension to vary (coupling, period chronology, unit conversion, financial policy interaction, cross-schedule reconciliation, coherent fault families), state why it tests the observed mechanism, preserve realistic public assumptions, list independent expected-value and complete-change requirements, and state a disconfirming control. Quantity alone is not amplification. Avoid transferring prompt ambiguity, infrastructure failure, missing caches or evaluator-only font/formula quirks as financial reasoning hardness. A coherent family that removes local answer templates is a hypothesis until actually tested.

Conclude with the narrowest supported explanation and the exact unresolved alternatives. This analysis does not certify an entire source, qualify a constructed task, reinterpret historical rewards, or authorize a new attempt. There is no recovery witness or quality filter for the official 200-case cohort.
