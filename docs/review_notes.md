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
