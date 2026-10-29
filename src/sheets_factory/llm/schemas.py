"""Strict, public-only JSON response contracts for Codex CLI callers."""
from __future__ import annotations

from copy import deepcopy
import re


def diagnosis_output_schema(assigned_check_ids: list[str]) -> dict:
    """Require exactly one keyed assessment for every assigned checker.

    A fixed required object prevents the duplicate-ID/missing-ID hole in arrays
    constrained only by length and enum. DiagnosisRunner already accepts this
    keyed representation and preserves independent semantic evidence checks.
    No task data, expected answers, coordinates or private paths enter this schema.
    """
    assigned = list(assigned_check_ids)
    if not assigned or len(assigned) != len(set(assigned)):
        raise ValueError("Assigned check IDs must be nonempty and distinct")
    if any(not isinstance(check_id, str) or not re.fullmatch(r"Q[0-9]{2,}", check_id) for check_id in assigned):
        raise ValueError("Assigned check IDs must use Q followed by at least two digits")
    evidence = {"type": "array", "items": {"type": "string"}}

    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    assessments = {}
    for check_id in assigned:
        assessments[check_id] = obj({
            "check_id": {"type": "string", "enum": [check_id]},
            "state": {"type": "string", "enum": ["clear", "flagged", "unknown", "not_applicable"]},
            "reason": {"type": "string"},
            "evidence": deepcopy(evidence),
        })
    issue = obj({
        "problem_id": {"type": "string", "enum": assigned},
        "claim": {"type": "string"}, "evidence": deepcopy(evidence),
        "certainty": {"type": "string", "enum": ["confirmed", "suspected"]},
        "severity": {"type": "string", "enum": ["blocker", "warning"]},
    })
    request = obj({
        "check_ids": {"type": "array", "items": {"type": "string", "enum": assigned}},
        "reason": {"type": "string"}, "proposed_check": {"type": "string"},
    })
    return obj({
        "assessments": obj(assessments),
        "issues": {"type": "array", "items": issue},
        "evidence_requests": {"type": "array", "items": request},
    })


def instruction_repair_output_schema(assigned_issue_ids: list[str]) -> dict:
    """A Q03 response edits one string; the program preserves the full plan."""
    assigned = list(assigned_issue_ids)
    if not assigned or len(assigned) != len(set(assigned)) or any(not isinstance(item, str) or not item for item in assigned):
        raise ValueError('Assigned issue IDs must be nonempty and distinct')
    properties = {
        'public_instruction': {'type': 'string'},
        'addressed_issue_ids': {'type': 'array', 'items': {'type': 'string', 'enum': assigned}},
        'changes': {'type': 'array', 'items': {'type': 'string'}},
        'unresolved_questions': {'type': 'array', 'items': {'type': 'string'}},
    }
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
