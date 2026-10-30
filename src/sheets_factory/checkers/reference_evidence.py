"""Compact privileged review index over a complete immutable evidence artifact.

This module hashes and summarizes evidence. It performs no financial calculations
and assigns no diagnostic assessment or approval.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pointer(parent, key):
    return parent + '/' + str(key).replace('~', '~0').replace('/', '~1')


def _compact(value, pointer='', *, list_limit=6, string_limit=1600):
    if isinstance(value, dict):
        return {key: _compact(item, _pointer(pointer, key), list_limit=list_limit,
                              string_limit=string_limit) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) <= list_limit:
            return [_compact(item, _pointer(pointer, i), list_limit=list_limit,
                             string_limit=string_limit) for i, item in enumerate(value)]
        return {'summary_kind': 'complete_list_in_bound_artifact', 'json_pointer': pointer,
                'count': len(value), 'sha256': _sha(_bytes(value)),
                'representative_examples_only': [
                    _compact(value[i], _pointer(pointer, i), list_limit=list_limit,
                             string_limit=string_limit) for i in sorted({0, len(value)-1})]}
    if isinstance(value, str) and len(value) > string_limit:
        return {'summary_kind': 'complete_string_in_bound_artifact', 'json_pointer': pointer,
                'characters': len(value), 'sha256': _sha(_bytes(value)),
                'preview_not_complete_evidence': value[:200]}
    return value


def _write_immutable(root, raw):
    checksum = _sha(raw)
    folder = Path(root) / checksum
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / 'complete_private_evidence.json'
    if target.is_symlink():
        raise ValueError('Private evidence artifact cannot be a symlink')
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError('Existing immutable private evidence differs from its SHA')
    else:
        temporary = folder / ('.' + uuid4().hex + '.tmp')
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != raw:
                    raise ValueError('Concurrent immutable private artifact mismatch')
        finally:
            temporary.unlink(missing_ok=True)
    return {'path': str(target.resolve()), 'sha256': checksum, 'bytes': len(raw),
            'complete': True, 'encoding': 'UTF-8 JSON'}


def _audit_references(value):
    found = {}
    def visit(item):
        if isinstance(item, dict):
            if (isinstance(item.get('path'), str) and isinstance(item.get('sha256'), str)
                    and ('audit' in Path(item['path']).name.lower()
                         or 'checked_cells' in item)):
                found[(item['path'], item['sha256'])] = item
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return list(found.values())


def _audit_summary(reference):
    result = {'artifact': {key: reference[key] for key in ('path', 'sha256')},
              'sha256_verified': False,
              'evidence_category': 'financial_coverage' if 'checked_cells' in reference else 'additional_referenced_audit'}
    path = Path(reference['path'])
    try:
        if not path.is_file():
            raise ValueError('Referenced audit is missing')
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Referenced audit exceeds the bounded reader size')
        raw = path.read_bytes()
        observed = _sha(raw)
        result['observed_sha256'] = observed
        if observed != reference['sha256']:
            raise ValueError('Referenced audit SHA does not match')
        audit = json.loads(raw)
        if not isinstance(audit, dict):
            raise ValueError('Referenced audit must be an object')
        result['sha256_verified'] = True
        keys = ('passed', 'checked_cells', 'formula_count', 'new_formula_count',
                'covered_formula_cells', 'public_parameters_verified',
                'all_new_formula_cells_independently_covered', 'monetary_identity_checks',
                'independent_journal_checks', 'checks', 'workbook', 'scope')
        result['declared_coverage_and_invariants'] = {
            key: _compact(audit[key], '/' + key) for key in keys if key in audit}
        result['complete_tables'] = {
            key: {'count': len(audit[key]), 'sha256': _sha(_bytes(audit[key])),
                  'json_pointer': '/' + key}
            for key in ('cell_checks', 'mismatches', 'uncovered', 'native_errors',
                        'control_mismatches', 'violations')
            if isinstance(audit.get(key), (list, dict))}
    except (OSError, ValueError, TypeError) as exc:
        result['integrity_problem'] = str(exc)
    return result


def _mutation_boundaries(private):
    plan = private.get('plan', {})
    edits = plan.get('edits', []) if isinstance(plan, dict) else []
    if not isinstance(edits, list):
        edits = []
    counts = Counter()
    groups = {}
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            continue
        mechanism = str(edit.get('mechanism', 'unspecified'))
        counts[mechanism] += 1
        groups.setdefault(mechanism, []).append(index)
    examples = []
    # The mechanism inventory is complete; examples deliberately remain bounded.
    for mechanism, indices in list(groups.items())[:32]:
        for index in sorted({indices[0], indices[-1]}):
            record = edits[index]
            examples.append({'mechanism': mechanism, 'complete_record_pointer': f'/plan/edits/{index}',
                'public_location': {key: record[key] for key in ('sheet', 'cell') if key in record},
                'business_rule': record.get('business_rule'), 'event_context': record.get('event_context')})
    return {'edit_count': len(edits), 'complete_mechanism_counts': dict(counts),
            'examples_are_not_full_root_coverage': True, 'boundary_examples': examples}


def reference_review_evidence(private, artifact_root):
    """Return a review index and the exact complete evidence's receipt.

    Every private input is retained in the immutable artifact. Any change in even
    an unlisted record changes that artifact SHA and the private cache identity.
    """
    raw = _bytes(private)
    artifact = _write_immutable(artifact_root, raw)
    summary = _compact(private)
    return {'summary_version': 1, 'summary_is_not_a_quality_verdict': True,
            'full_artifact': artifact, 'private_summary': summary,
            'financial_audits': [_audit_summary(ref) for ref in _audit_references(
                private.get('source_assessment', {}))],
            'mutation_boundaries': _mutation_boundaries(private),
            'field_inventory': {key: {'type': type(value).__name__,
                'count': len(value) if isinstance(value, (dict, list, str)) else None,
                'sha256': _sha(_bytes(value))} for key, value in private.items()}}
