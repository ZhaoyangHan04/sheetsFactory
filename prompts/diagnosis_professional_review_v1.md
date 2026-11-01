# Spreadsheet task review

Review every ID in `assigned_check_ids`.
Use the supplied workbook, task, trajectory and executable evidence.
Review task quality regardless of solver success.
Return the exact supplied JSON schema.
Return each assigned assessment once.
Cite concrete evidence.
Do not invent executed tests, routes or solver grades.

## Professional interpretation

Use the complete public workbook as a professional analyst.
Use its layout, labels, intact formulas, dependencies and ordinary financial conventions.
Keep necessary source data and custom business policies available.
The task need not teach accounting or provide a calculation tutorial.
The task need not define every helper in prose.
Do not require a separate formal uniqueness proof for each helper.

Flag a missing assumption only when a material business choice remains unresolved after this review.
Identify the missing public condition and its effect on a required output.
When you claim ambiguity, give two reasonable interpretations consistent with the complete public evidence.
Show the material difference between their results.
Do not invent a second interpretation merely because Q02 requests an ambiguity check.
An unfamiliar convention alone does not prove ambiguity.

Treat a statement about supporting context as part of the complete task.
Do not automatically treat that statement as a ban on necessary supporting calculations.
Check any explicit edit restriction against the actual required outputs.
Keep a genuine placement issue when labels, formats, dependencies and normal conventions do not resolve the target locations.
If your review lacks evidence, request a bounded check.
Do not call the task invalid merely because your review remains incomplete.

## Checks

### Q01: Public inputs

Check the public sources for necessary data and custom business assumptions.
Infer ordinary financial relationships from the workbook.

### Q02: Business interpretation

Check for material ambiguity or contradiction.
Do not require an explicit prose rule for each arithmetic or presentation detail.

### Q03: Task scope

Check that the requested scope, worksheet names and final output path agree.
Preserve formulas and literal inputs outside the permitted edits.
Allow their dependent results to recalculate.
Development fixtures use `/workspace` for the same public file that the final task mounts at `/app/input.xlsx`.
That fixture path alone does not conflict with the final task.
The final task requires `/app/output.xlsx`.

### Q04: Financial reference

Check business validity across the full scope of changed values.
Use source evidence, independent calculations and public recovery evidence.
Reference review may use the declared `reference_review` policy without an independent public solver.
Do not claim that such a solver succeeded.
A copied golden file alone does not prove financial correctness.
An independently executed model and coherent statement, cash and debt reconciliations provide useful evidence.
Inspect the actual goal when private evidence needs confirmation.
Check a reference that violates its public rounding policy.

### Q06: Mask or mutation

Check the claimed effects of each mask or mutation.
Check that construction preserves inputs and structure.
Check for unauthorized construction edits.
Missing caches in a solver draft are harmless when final grading recalculates that draft.
Answer caches in a delivered masked input remain a leak.

Distinguish actual single-root and marginal recalculations from a supported independence proof.
The receipt `separated_roots_with_actual_combined_LO_values` can support each root's individual and combined effect.
That receipt must satisfy all these conditions:

- It binds the original and mutated complete dependency graphs.
- Both graphs exclude every path from one root to another root.
- It binds all formulas and caches.
- Each root's actual combined recalculated value differs from the goal.

This proof does not claim one LibreOffice execution per root.
This proof does not certify financial correctness.
Reject an incomplete or failing receipt.

### Q07: Answer exposure

Check for exposed golden answers, hidden solution files and equivalent complete answer copies.
Check for instructions that supply corrected formulas.
Necessary custom policies and legitimate surviving formulas do not automatically leak answers.
Identify excessive procedural instructions with concrete examples.
Review request prose, duplicate structured inputs and reusable formula scaffolding separately.
An implementation dictionary can reduce work without disclosing an answer.
Identify the exact public artifact and an observable shortcut before flagging leakage.
Do not remove necessary business assumptions to increase difficulty.

### Q08: Candidate shortcuts

Check for an executable shortcut, rather than a proxy difficulty score.
Cell counts, solution time and one successful attempt do not establish difficulty.
If no local constraint or shortcut probe applies, return `not_applicable`.
State that the separate frozen strongest-model cohort evaluation remains pending.
Do not count this state as a difficulty pass.

### Q09: Native errors

Inspect native errors and the full dependencies of changed values.
Use the supplied deterministic probes and path certificates.
A verbal exclusion cannot waive an error that affects a required output.
Sensitivity probes do not certify financial correctness.

### Q05, Q10, Q11 and Q12

Use the actual controls, recalculation, infrastructure and coverage evidence for each assigned check.
Return `unknown` when required evidence is missing.
Do not demand future cohort evidence during candidate construction.
Retain all enabled checks, exact artifact bindings and executable verification.

## Solver observations and quality findings

Do not require a financial reasoning failure as a condition for task quality.
A valid development zero can arise from output scope, extra edits or rounding.
That cause alone does not establish a task defect or invalidate the development zero.
A solver's calculation error or missing submission does not itself establish a task defect.
Normal quality review need not produce a strongest-model submission.
Check the required actual Harbor controls and resource evidence separately.
Keep the verifier's value comparison unchanged.
Never create a low success rate from an invalid reference or a failed environment.

## Output and attribution

Each issue must identify its `problem_id`, certainty, severity, claim and concrete evidence.
Keep task defects, reference defects, environment failures and solver errors separate.
Use the supplied schema for `attribution` and `artifact_scope`.
Use `agent_behavior` only for findings about `solver_output` or `solver_trace`.
A wrong draft formula, calculation mistake or normal budget exhaustion is a solver observation.
Such an observation does not flag a task check, even when evidence establishes the observation.
A `clear` assessment may include solver observations.

Return `clear` only when evidence for that check supports the task or reference.
Otherwise return `unknown` with a specific evidence request.
A `flagged` assessment requires an actual task, reference or environment finding.
For task or reference defects, identify the affected artifact and the material effect on required outputs.
A solver artifact alone cannot establish such a defect.
Split findings that combine different causes.
Use `unresolved` when the evidence does not establish the cause.
Use runtime or verifier evidence for environment findings.
Do not infer attribution from task success or failure alone.
