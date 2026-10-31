#!/usr/bin/env python3
"""Explicit private N720/N1080 SCIP reference experiments; prepare is service-free."""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sheets_factory.workbook.linear_capital_dimension_scip_reference import main
if __name__=='__main__':raise SystemExit(main())
