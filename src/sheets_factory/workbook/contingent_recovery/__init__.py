"""Explicit annual contingent rent contracts and finite-grid recovery feedback."""
from .contract import load_spec, validate_spec, validate_contracts
from .solver import (solve_year, evaluate_total, monotonicity_proof,
                     ContingentRecoveryError, MonotonicityError,
                     NonUniqueFixedPointError, ConvergenceError)

__all__ = ['load_spec', 'validate_spec', 'validate_contracts', 'solve_year',
           'evaluate_total', 'monotonicity_proof', 'ContingentRecoveryError',
           'MonotonicityError', 'NonUniqueFixedPointError', 'ConvergenceError']
