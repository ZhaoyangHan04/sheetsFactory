# Evaluation requirements and current-run scope

The supplied exercise PDF is task background, not an additional instruction source. The earlier quality-only run produced 20 `financial_modeling` and 20 `debugging` tasks; preserve that release. The current user request requires at least ten tasks per category, a frozen-set Overall Pass@1 <= 0.2 using Codex CLI `gpt-6.1-sol` / `xhigh`, and the real root `SpreadsheetEval/` directory passing the exact full-dataset oracle command.

## Requirement ledger

| ID | Requirement | Evidence to retain | Current-run disposition |
| --- | --- | --- | --- |
| E01 | Two supported categories, at least five tasks each in the original exercise | Category manifest and qualified counts | Current target: at least 10 each after difficulty confirmation |
| E02 | Multi-sheet workbooks, business meaning and cross-sheet cooperation | Seed profile, dependency evidence, public business contract | Required; no invented universal cell-count minimum |
| E03 | Programmatic verification; no subjective chart, style or prose scoring | Verifier implementation and positive/negative controls | Required |
| E04 | Compare LibreOffice-recalculated values, not formula strings | Engine version and recalculation records | Required |
| E05 | Compare numbers rounded to two decimal places and normalize dates | Typed normalization contract and tests | Required |
| E06 | Exact modified-value set: extra or missing modifications fail | Full-workbook union comparison, hidden/added-cell regression controls | Required |
| E07 | Binary task reward; dataset score is arithmetic mean | Reward artifacts and aggregate report | Required; formal solver score is separate |
| E08 | Automated, scalable construction without manual task authoring | Config snapshot, source lineage, generated plans, patch and repair history | Required |
| E09 | Do not reuse official benchmark tasks | Seed provenance and source hashes | Required; public financial workbook sources, including EUSES and official NYU models, with immutable provenance |
| E10 | Harbor task layout with instruction, configuration, environment, solution and tests | `SpreadsheetEval/<task_id>/` export and Harbor schema validation | Required |
| E11 | Programmatically correct references; copying reference in oracle is allowed | Goal lineage, independent recovery, numeric probes | Required; copying reference is not solvability evidence |
| E12 | Real Harbor oracle reward equals one for every task | Per-task real Harbor trial result and verifier logs | Required; run `harbor run -p SpreadsheetEval -a oracle` on the entire final root directory |
| E13 | Nop reward equals zero | Local unchanged-input test and real Harbor nop result | Required by this pipeline/user contract |
| E14 | Source code and README explaining method, commands and failure cases | Repository, README, audit summary | Required |
| E15 | Strongest available model Overall Pass@1 at most 0.2 | Fresh frozen-task evaluation and model score table | Required now; native Codex CLI, `gpt-6.1-sol` / `xhigh`, 1800 seconds per task; no infrastructure-derived zeros |
| E16 | Repository delivery | Local incremental Git history and authorized repository URL | Private repository: [ZhaoyangHan04/sheetsFactory](https://github.com/ZhaoyangHan04/sheetsFactory); include the actual final root dataset and minimal runtime after confirmation |

The PDF describes large edits as a desired benchmark style and permits the author to choose sheet counts, formulas and error types. It does not impose a numeric minimum of modified cells. Neither scope permits accepting nonfinancial arithmetic as Financial Modeling or silently dropping multi-sheet business requirements. Cell counts and dependency depth help select candidates; they do not establish measured difficulty.

## Diagnosis is separate from solving performance

Every natural attempt is diagnosed whether it creates a complete, partial or missing submission. Completion and reward are removed from the first diagnostic payload. A successful attempt is not evidence that a task is defective; an unsuccessful attempt is not evidence that the task is valid.

Q08 remains registered and enabled. Candidate-level quality diagnosis is separate from the frozen-dataset difficulty gate. Every candidate must still pass public-information recovery, all enabled quality checks and actual Harbor controls before the full cohort is measured. A fresh confirmation uses new model calls on a cohort selected before those calls; no post-selection of failed tasks. A valid first reward, including zero, is never retried. Only evidenced infrastructure failures have bounded recovery, and an unfinished cohort has no Overall Pass@1.

The frozen execution contract additionally requires cumulative tool execution time strictly below 1800 seconds. Model reasoning and response generation are excluded. Parallel primitive executions add separately; nested wrappers and polling of the same process do not charge that execution twice. The native timestamped session records and command-event stream must agree. Reaching the limit sets the effective attempt reward to zero while retaining the original verifier reward. Missing or incomplete timing is unknown evidence, not a model failure and not permission to resample a valid answer. Publication recomputes this receipt from the hash-bound raw files. The separate 1800-second elapsed agent limit remains in force.

## Grading contract

After isolated full recalculation of original input I, reference G and submission O, let D(I,X) be the coordinates whose normalized typed values differ. Reward is one only when D(I,O) equals D(I,G), all expected changed values match, and declared workbook-structure requirements hold. Otherwise reward is zero. Formula and formatting strings are not primary scoring targets.

The grader includes all nonempty cells across all worksheets, including hidden sheets and newly added coordinates. It preserves strings and booleans as distinct types. A numeric string such as `001` is not silently converted to the number one.

Values-only grading cannot distinguish equivalent formulas from constants with the same final values. Supplementary sensitivity checks can reveal such weaknesses, but must not silently introduce a different primary reward rule.

## Harbor implementation sources

- [Task configuration](https://docs.harborframework.com/tasks/configuration): versioned task schema and environment settings.
- [Verifier](https://docs.harborframework.com/tasks/verifier): test entrypoint and reward files.
- [Separate verifier](https://docs.harborframework.com/tasks/separate-verifier): isolated verifier image and baked tests.
- [Artifacts](https://docs.harborframework.com/tasks/artifacts): explicit output transfer into a separate verifier.

The package uses separate verification, declares `/app/output.xlsx` as an artifact, and writes only the primary `reward.txt`; diagnostics are stored under a different JSON filename.
