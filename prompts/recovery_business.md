# Independent analyst reconstruction

You receive only the public input workbook, task instruction and workbook profile. Independently reconstruct the requested financial model or debug its errors as a professional analyst. Use the actual model layout, labels, source inputs, custom policies and ordinary financial conventions. The task need not restate standard accounting or spell out each helper formula. Do not invent missing business data or use a private reference.

Return a complete Python/openpyxl program that reads /workspace/input.xlsx and writes /workspace/output.xlsx. The host will execute it in a fresh offline environment, recalculate it with LibreOffice and compare the complete output. Preserve unrelated data and formulas. Do not inspect credentials, environment variables, network sources or hidden files. Inspect the public files with focused commands when needed. Do not run a prolonged search against hidden expected values.

Return JSON {"code":"complete runnable Python program","public_evidence_used":[],"assumptions_added":[],"unresolved_questions":[]}.

Document the public workbook evidence and ordinary model conventions used in public_evidence_used. Standard financial relationships supported by labels and model structure are derivations, not newly invented business assumptions. assumptions_added is for additional factual or contractual conditions absent from the task and workbook. Record a material unresolved business choice in unresolved_questions; a missing step-by-step calculation tutorial is not such a choice.
