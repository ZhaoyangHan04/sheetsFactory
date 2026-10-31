#!/usr/bin/env python3
"""Explicit new-scope N360 producer16 reference preparation and execution."""
from pathlib import Path
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_scaled import reference as core

KIND=core.KIND
PREPARED=core.PREPARED
TIME_LIMIT=core.TIME_LIMIT
BACKENDS=core.BACKENDS
spec=core.spec
finance_crosscheck=core.finance_crosscheck
runtime=core.runtime
require=core.require
reference=core.reference
read=core.read
write=core.write
_refs=core._refs
_sha=core._sha
_profile=core._profile
_checked_finance=core._checked_finance
_checked_preparation=core._checked_preparation
_checked_job=core._checked_job
validate_solver_receipt=core.validate_solver_receipt
recipes=core.recipes
finance_recipes=core.finance_recipes
prepare=core.prepare
validate_prepared=core.validate_prepared
execute_prepared=core.execute_prepared
validate_completed=core.validate_completed
main=core.main

if __name__=='__main__':
    raise SystemExit(main())
