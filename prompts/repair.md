# Repair a constructed task using numbered evidence

You receive the current source-backed plan and a deterministic issue route report. Propose a minimally changed task plan that fixes only confirmed task defects. Suspected issues require evidence first. Do not substitute solver output for the reference goal. Do not disclose exact debugging root addresses or correct formulas in public instructions, or target values in modeling instructions.

Keep the same task mode and real source workbook; repair assumptions only when supported by public source evidence or explicit fully stated task rules. If a change needs a different reference goal or target, declare it. Rebuild from the immutable source, never the prior solver output. Difficulty is deferred for this run and must not trigger extra mutations solely because a solver succeeded.

Return JSON {"repaired_task": TASK_WITH_SAME_FIELDS_AS_ORIGINAL, "addressed_issue_ids":[],"changes":[],"unresolved_questions":[]} or {"repaired_task":null,"reason":"unrepairable with available public evidence"}.

For Q04/Q09, the protected reference scope includes all values changed by the injected/masked roots, including downstream results. Merely excluding a defective downstream worksheet in prose does not fix a contaminated reference. Baseline formula correction is unsupported by this executor. Select different source-backed roots whose entire affected closure is correct, or return unrepairable.
