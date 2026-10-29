# Independent pipeline review

The review separated task correctness from solver completion. It used local fixtures and inspected the actual orchestration; no API calls were made by the review tests.

## Findings addressed before the production run

1. **Public rules absent from the actual instruction.** The public diagnostician previously received plan rules that the solver could not necessarily see. Instruction construction now materializes those rules, and the regression test reads the actual instruction artifact.
2. **Recovery script existence mistaken for reproducibility.** Independent recovery now re-executes the generated program with only public input in a fresh network-disabled container. A manually saved workbook and an unrelated script cannot certify recovery.
3. **Every diagnostic problem sent to content repair.** The controller now dispatches numbered route classes. Evidence collection and infrastructure retries remain within the same revision and have separate finite budgets. Only confirmed repair-class findings can change task content.
4. **Manually added recovery findings missing routes.** The mandatory recovery gate now updates issues, enabled Q12 assessment, routing and blocking coverage consistently. Disabling Q12 cannot disable the separate recovery gate.
5. **Hardcoded pipeline stages.** Registered BaseNode implementations are loaded through BasePipeline and mode-specific YAML phase templates. Mandatory quality stages and ordering are validated at startup.
6. **Variants capable of duplicating task modules.** Variants retain the original source identity, are scheduled after the first pass only for finance-eligible sources, and reject duplicate or substantially overlapping target sets. Debugging variants are not scheduled by default.

## Validation boundaries

- `tests/test_pipeline.py` uses explicit fixture caches and mocked process boundaries to test contracts, branching, budgets and isolation. Those tests do not claim to emulate LibreOffice.
- Actual LibreOffice and Harbor controls are independently executed by the production and integration paths.
- An incomplete natural attempt still produces a trace and enters diagnosis. No solved/reward branch was added to the developer diagnostic controller.
- Difficulty remains explicitly deferred. Source eligibility, target deduplication, missing assumptions, answer leakage and reference correctness remain quality requirements.

## Continuing limitations to disclose

- A successful public recovery witness is necessary evidence, but cannot formally prove that natural-language requirements have a unique interpretation. Independent semantic checks remain required.
- The first implementation uses ordered phases with a controller-managed bounded repair loop, rather than an unrestricted user-defined cyclic graph.
- Provider token reporting may be unavailable on interrupted calls. Audit reports must preserve unknown usage instead of claiming zero consumption.

## Findings during the first production batch

- The development inspection directory and final Harbor directory differ. A prompt clarification now evaluates the delivered `/app` contract. Prompt hashes and the reason are recorded as a run amendment; a local targeted contract review covers early tasks.
- Correct edited roots do not establish correctness of the complete changed-value closure. A depreciation task affected a native monthly-profit formula that subtracted annual depreciation. The ready export was quarantined with a confirmed Q09 finding. Planning and reference diagnosis now explicitly inspect downstream changed outputs, their periods and units. A scope disclaimer cannot exclude those outputs from the value verifier.
- An instruction that requires every outside value to remain unchanged contradicts required downstream recalculation. Two otherwise reproducible tasks were quarantined for Q03, including one with successful real Harbor controls. Preserving unedited formulas and literal inputs is distinct from preserving their calculated results. Repair must create a new revision and repeat quality checks and actual Harbor controls; old controls remain historical evidence.

External findings are stored in each affected task's `external_quality_review.json`, in the run event log, and in separate business-review artifacts. They are not silently erased by changing the reference or by reclassifying the difficulty gate.

## Reliability changes during continuation

- Each diagnostic response now has a strict schema covering exactly its assigned check IDs. A missing item is a protocol failure, never a clear assessment. Successful diagnostic batches can be reused only for the same input, goal, revision, prompt, schema and evidence fingerprint; retries rerun the failed batch.
- A Q03-only repair returns a minimal public-instruction patch. The program copies every other plan field, so omitted metadata or an incidental rewrite of private evidence cannot invalidate an otherwise focused repair. Every applied patch still consumes a revision and repeats all gates.
- A natural attempt that reaches its time budget after observable model/tool progress retains its partial trace and is diagnosed without a completion score. Verified provider/process failures remain infrastructure findings. The independent public-information recovery witness must still complete successfully.
- Confirmed native defects are registered by source hash and specific cells. The guard checks intersections with the complete changed-value set instead of rejecting the whole source. An example is a 2003 monthly-interest formula that reused December 2002 lease interest.
- Actual Harbor controls are bound to exported file hashes and task revisions. Unchanged validated tasks retain their proof; a new or changed export must receive new oracle and nop trials. Release packaging rechecks the persisted trials, staging bytes, diagnosis and independent recovery before selecting tasks.

Code changes made after a producer starts apply to a subsequent process. Prompt and native-risk files are read during their respective nodes; their mid-run amendments retain before/after hashes in the event audit. Neither mechanism silently resets candidate budgets or upgrades historical results.
