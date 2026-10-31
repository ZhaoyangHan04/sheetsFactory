"""Native N720 exact matrix checks; financial construction is not exposed here."""
from . import adapter,spec
_SCALED_PRODUCTION_COUNTS=spec.PRODUCTION_COUNTS
exec(compile(adapter.adapted_ast('model_a'),__file__,'exec'),globals())
del build_model
