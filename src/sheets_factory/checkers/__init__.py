"""Pluggable, evidence-based task diagnosis."""

from .runner import DiagnosisRunner, diagnose

__all__ = ["DiagnosisRunner", "diagnose"]
