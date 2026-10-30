# Evaluation requirements and current-run scope

The supplied exercise PDF is task background, not an additional instruction source. The current user request sets this run to 40 quality-qualified tasks: 20 `financial_modeling` and 20 `debugging`. Difficulty evaluation is explicitly deferred to a later iteration.

## Requirement ledger

| ID | Requirement | Evidence to retain | Current-run disposition |
| --- | --- | --- | --- |
| E01 | Two supported categories, at least five tasks each in the original exercise | Category manifest and qualified counts | Stronger user target: 20 each |
| E02 | Multi-sheet workbooks, business meaning and cross-sheet cooperation | Seed profile, dependency evidence, public business contract | Required; no invented universal cell-count minimum |
| E03 | Programmatic verification; no subjective chart, style or prose scoring | Verifier implementation and positive/negative controls | Required |
| E04 | Compare LibreOffice-recalculated values, not formula strings | Engine version and recalculation records | Required |
| E05 | Compare numbers rounded to two decimal places and normalize dates | Typed normalization contract and tests | Required |
| E06 | Exact modified-value set: extra or missing modifications fail | Full-workbook union comparison, hidden/added-cell regression controls | Required |
| E07 | Binary task reward; dataset score is arithmetic mean | Reward artifacts and aggregate report | Required; formal solver score is separate |
| E08 | Automated, scalable construction without manual task authoring | Config snapshot, source lineage, generated plans, patch and repair history | Required |
| E09 | Do not reuse official benchmark tasks | Seed provenance and source hashes | Required; EUSES financial seeds only for this run |
| E10 | Harbor task layout with instruction, configuration, environment, solution and tests | `SpreadsheetEval/<task_id>/` export and Harbor schema validation | Required |
| E11 | Programmatically correct references; copying reference in oracle is allowed | Goal lineage, independent recovery, numeric probes | Required; copying reference is not solvability evidence |
| E12 | Real Harbor oracle reward equals one for every task | Per-task real Harbor trial result and verifier logs | Required |
| E13 | Nop reward equals zero | Local unchanged-input test and real Harbor nop result | Required by this pipeline/user contract |
| E14 | Source code and README explaining method, commands and failure cases | Repository, README, audit summary | Required |
| E15 | Strongest available model Overall Pass@1 at most 0.2 | Fresh frozen-task evaluation and model score table | Explicitly deferred by user; must be labelled pending |
| E16 | Repository delivery | Local incremental Git history and authorized repository URL | Private repository: [ZhaoyangHan04/sheetsFactory](https://github.com/ZhaoyangHan04/sheetsFactory); generated archives remain separate local artifacts |

The PDF describes large edits as a desired benchmark style and permits the author to choose sheet counts, formulas and error types. It does not impose a numeric minimum of modified cells. The current quality-only scope does not justify accepting nonfinancial arithmetic as Financial Modeling or silently dropping multi-sheet business requirements.

## Diagnosis is separate from solving performance

Every natural attempt is diagnosed whether it creates a complete, partial or missing submission. Completion and reward are removed from the first diagnostic payload. A successful attempt is not evidence that a task is defective; an unsuccessful attempt is not evidence that the task is valid.

Q08 remains registered and assessed as `not_applicable` with the explicit quality-only scope reason. Direct answer leakage is still checked under Q07. No artificial low-pass-rate claim is made for this run.

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
