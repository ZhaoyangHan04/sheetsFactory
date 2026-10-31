#!/usr/bin/env python3
"""Fixed N720600 private-reference prepare/validate/run; execution is explicit."""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_n720_reference.reference import (
 KIND,PREPARED,TIME_LIMIT,prepare,validate_prepared,execute_prepared,validate_completed,main)
if __name__=='__main__':raise SystemExit(main())
