"""Native N720 CP-SAT: unchanged financial-free algorithm and16-worker ceiling."""
from collections import Counter as _SCALED_COUNTER
from . import adapter,spec
_SCALED_PRODUCTION_COUNTS=spec.PRODUCTION_COUNTS
exec(compile(adapter.adapted_ast('model_b'),__file__,'exec'),globals())
del build_model
