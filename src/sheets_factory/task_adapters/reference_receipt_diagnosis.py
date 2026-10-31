"""Opt-in reference receipt transport; no registry or historical cache changes."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

from . import linear_capital_scaled_reference_review as upstream
from ..checkers import runner as runner_module
from ..llm import schemas
from ..nodes import quality

PROTOCOL = 'reference_receipt_diagnosis_v1'
DEPENDENCIES = {
    upstream.__file__: 'c8d2857d2984b4c05a5b05f7125ca6887e27010addaac7df14c3d8394f835f34',
    str(Path(upstream.__file__).with_name('linear_capital_scaled.py')): '05102d8b97f50f3cd830e9c7d420e2c421bc2f69d54d9f01b1e55a97a28a43cc',
    str(Path(upstream.__file__).with_name('linear_capital_portfolio.py')): 'ae1810d4ff04977e5fe25d6922e153f4e109aee1323c8fcf068c5b2677b44283',
    runner_module.__file__: 'c2d3c04de55de4914746efa5743b523645efea0e80d50926fcdb1e777d19ded9',
    schemas.__file__: 'e9fbc98bd91384dfc88b348cd972cd9be22d937404f8915167da964be8f57cd5',
    quality.__file__: '1c2f9e53c989eb4372ae645ec71364c2e4acf4b04dd1518fa9a08c76f1198929',
}
PRIVATE_RECEIPT_INSTRUCTIONS = (
    '\nReference receipt protocol v1: For Q04 clear, evidence must be exactly one string '
    'beginning reference_review_json: followed by a JSON object. Read the exact binding '
    'from private.reference_review_requirements.binding in evidence.json. Include that '
    'binding unchanged, nonempty business_evidence from actual inspected policies, and '
    'nonempty financial_validation_checks with check, method, passed=true and evidence '
    'from independent calculations actually completed. The example is a format, not '
    'evidence. Put supporting details inside the receipt. If evidence is insufficient '
    'or a defect is found, return unknown or flagged as appropriate; these states do '
    'not require a passed receipt. Never invent a calculation or a passed result.\n'
)


def verify_dependencies():
    for path, expected in DEPENDENCIES.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen receipt diagnosis dependency changed: ' + path)


def diagnosis_output_schema(assigned_check_ids):
    result = schemas.diagnosis_output_schema(assigned_check_ids)
    checks = result['properties']['assessments']['properties']
    if 'Q04' in checks:
        clear, other = deepcopy(checks['Q04']), deepcopy(checks['Q04'])
        clear['properties']['state']['enum'] = ['clear']
        clear['properties']['evidence'] = {'type': 'array', 'minItems': 1, 'maxItems': 1,
            'items': {'type': 'string', 'pattern': '^reference_review_json:'}}
        other['properties']['state']['enum'] = ['flagged', 'unknown', 'not_applicable']
        checks['Q04'] = {'anyOf': [clear, other]}
    return result


def _response(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('Reviewer backend must return a JSON object')
    return value.get('payload', value)


def _q04_problems(value, binding):
    assessments = _response(value).get('assessments', {})
    if isinstance(assessments, list):
        assessments = {a.get('check_id', a.get('id')): a for a in assessments}
    if assessments.get('Q04', {}).get('state') != 'clear':
        return []
    if not isinstance(binding, dict) or not binding:
        return ['Q04: current reference binding required']
    checked = quality.reference_review_assessments({'assessments': assessments}, binding)
    return [problem for problem in checked['problems'] if problem.startswith('Q04:')]


class ReceiptDiagnosisRunner(runner_module.DiagnosisRunner):
    """Reject malformed clear results before the original runner can cache them."""

    def diagnose(self, task_bundle, traces, controls, reviewer_callable, config=None, *, batch_cache=None):
        private = task_bundle.get('private', {})
        binding = private.get('reference_review_requirements', {}).get('binding')
        cache = batch_cache if batch_cache is not None else {}
        working = deepcopy(cache.get(PROTOCOL, {'entries': {}}))
        rejected = []
        for scope, entries in [('legacy', cache.get('entries', {})),
                               ('current', working.get('entries', {}))]:
            for fingerprint, entry in list(entries.items()):
                if 'Q04' not in entry.get('assigned_check_ids', []):
                    continue
                try:
                    problems = _q04_problems(entry.get('result'), binding)
                except (ValueError, TypeError, AttributeError):
                    problems = ['Q04: malformed cached response']
                if problems:
                    rejected.append({'cache_scope': scope, 'fingerprint': fingerprint,
                        'problems': problems, 'result_sha256': hashlib.sha256(json.dumps(
                            entry.get('result'), sort_keys=True, default=str).encode()).hexdigest()})
                    if scope == 'current':
                        entries.pop(fingerprint)

        def review(payload):
            if reviewer_callable is None:
                raise RuntimeError('No reviewer backend configured')
            response = reviewer_callable(payload)
            if 'Q04' in payload['assigned_check_ids']:
                problems = _q04_problems(response, binding)
                if problems:
                    raise ValueError('Reference receipt response protocol: ' + '; '.join(problems))
            return response

        report = super().diagnose(task_bundle, traces, controls, review, config, batch_cache=working)
        cache[PROTOCOL] = working
        report['reference_receipt_protocol'] = {'id': PROTOCOL, 'rejected_cached_results': rejected,
            'legacy_cache_reused': False, 'legacy_cache_modified': False}
        return report


verify_dependencies()
_original = upstream.LinearDiagnoseNode._execute_diagnose
_namespace = dict(_original.__globals__)
_builtins = dict(vars(builtins))


def _schema_import(name, globals=None, locals=None, fromlist=(), level=0):
    if (name, tuple(fromlist), level) == ('llm.schemas', ('diagnosis_output_schema',), 2):
        return SimpleNamespace(diagnosis_output_schema=diagnosis_output_schema)
    return builtins.__import__(name, globals, locals, fromlist, level)


_builtins['__import__'] = _schema_import
_namespace.update(__builtins__=_builtins, DiagnosisRunner=ReceiptDiagnosisRunner,
    PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS=(
        _original.__globals__['PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS'] + PRIVATE_RECEIPT_INSTRUCTIONS))


class ReferenceReceiptDiagnosisNode(upstream.LinearDiagnoseNode):
    """Explicitly select this node in a future recipe; historical nodes are unchanged."""
    _execute_diagnose = FunctionType(_original.__code__, _namespace,
        _original.__name__, _original.__defaults__, _original.__closure__)
