#!/usr/bin/env python3
"""Freeze/validate explicit V3 cohorts through an isolated frozen publication AST.

No model, LO, Docker or Harbor operation is performed. Publication is explicit;
validation is the default. Only the existing admitted source families are valid.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.evaluation.clock_resource_publication import cli_ast

exec(compile(cli_ast(), __file__, 'exec'), globals())
