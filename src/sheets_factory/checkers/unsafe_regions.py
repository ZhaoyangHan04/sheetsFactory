"""Evidence-based native defects in the full value delta, selected by source hash."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from openpyxl.utils.cell import range_boundaries


@dataclass(frozen=True)
class Region:
    sheet: str
    min_col: int
    min_row: int
    max_col: int
    max_row: int

    def contains(self, coordinate):
        sheet, col, row = coordinate
        return (sheet == self.sheet and self.min_col <= col <= self.max_col
                and self.min_row <= row <= self.max_row)


def parse_region(spec):
    if isinstance(spec, str):
        if '!' not in spec:
            raise ValueError('Region must include a worksheet')
        sheet, address = spec.rsplit('!', 1)
        if sheet.startswith("'") and sheet.endswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
    elif isinstance(spec, dict):
        sheet = spec.get('sheet')
        address = spec.get('range', spec.get('cell'))
    else:
        raise ValueError('Region must be a string or a sheet/range object')
    if not isinstance(sheet, str) or not sheet or not isinstance(address, str):
        raise ValueError('Region requires a nonempty sheet and bounded A1 address')
    address = address.strip()
    if not re.fullmatch(r'\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?', address):
        raise ValueError('Only bounded A1 cells and rectangles are supported')
    min_col, min_row, max_col, max_row = range_boundaries(address)
    if not (1 <= min_col <= max_col <= 16384 and 1 <= min_row <= max_row <= 1048576):
        raise ValueError('Region exceeds Excel limits')
    return Region(sheet, min_col, min_row, max_col, max_row)


def inspect_unsafe_regions(expected_changes, known_risks, *, sheet_names=None):
    """Intersect every computed changed value with evidenced native-risk regions.

    `known_risks` entries require risk_id, certainty, unsafe_regions and evidence.
    Prose-only legacy warnings are returned for evidence collection, never
    silently declared safe. The caller must supply actual worksheet names.
    """
    if not known_risks:
        return {'state': 'not_applicable', 'blocking': False, 'issues': [], 'risk_results': [],
                'evidence_requests': [], 'reason': 'No known native-risk facts supplied; this is not baseline certification.'}
    coordinates, unknown, findings, risk_results = {}, [], [], []
    for label in expected_changes:
        try:
            region = parse_region(label)
            if region.min_col != region.max_col or region.min_row != region.max_row:
                raise ValueError('A computed delta entry must identify one cell')
            coordinates[str(label)] = (region.sheet, region.min_col, region.min_row)
        except (TypeError, ValueError) as exc:
            unknown.append({'source': 'expected_changes', 'value': label, 'reason': str(exc)})
    actual_sheets = set(sheet_names or [])
    if sheet_names is None:
        unknown.append({'source': 'sheet_names', 'reason': 'Actual worksheet names are required to validate the risk registry'})
    for index, risk in enumerate(known_risks):
        if not isinstance(risk, dict):
            unknown.append({'source': f'known_risks/{index}', 'reason': 'Legacy prose requires structured regions and evidence',
                            'description': str(risk)})
            continue
        risk_id = risk.get('risk_id')
        if not isinstance(risk_id, str) or not risk_id.strip():
            unknown.append({'source': f'known_risks/{index}', 'reason': 'A stable nonempty risk_id is required'})
            continue
        certainty, evidence = risk.get('certainty'), risk.get('evidence')
        specs = risk.get('unsafe_regions', risk.get('regions'))
        if certainty not in {'confirmed', 'suspected'} or not evidence or not isinstance(specs, list) or not specs:
            unknown.append({'risk_id': risk_id, 'reason': 'Risk requires certainty, evidence and nonempty unsafe_regions'})
            continue
        try:
            regions = [parse_region(spec) for spec in specs]
            if sheet_names is not None and any(region.sheet not in actual_sheets for region in regions):
                raise ValueError('Risk registry references a worksheet absent from the actual workbook')
        except (TypeError, ValueError) as exc:
            unknown.append({'risk_id': risk_id, 'reason': str(exc)})
            continue
        hits = sorted(label for label, coordinate in coordinates.items() if any(region.contains(coordinate) for region in regions))
        risk_results.append({'risk_id': risk_id, 'certainty': certainty, 'unsafe_regions': specs,
                             'intersection_with_full_delta': hits, 'evidence': evidence})
        if not hits:
            continue
        findings.append({'issue_id': 'native-region-' + str(risk_id), 'problem_id': 'Q09',
                         'certainty': certainty, 'severity': 'blocker',
                         'route_id': 'R09' if certainty == 'confirmed' else 'R12',
                         'claim': 'A known native unsafe region intersects required computed output changes',
                         'evidence': evidence, 'risk_id': risk_id, 'affected_cells': hits})
    if any(finding['certainty'] == 'confirmed' for finding in findings):
        state = 'flagged'
    elif unknown or findings:
        state = 'unknown'
    else:
        state = 'clear'
    return {'state': state, 'blocking': state == 'flagged', 'issues': findings,
            'risk_results': risk_results, 'evidence_requests': unknown,
            'full_delta_size': len(coordinates),
            'reason': 'Checked explicit unsafe cell/value regions against the complete recalculated delta; '
                      'fixed upstream inputs and graph ancestry alone are not automatically task defects.'}


def evaluate_native_risk_guard(expected_changes, source_sha256, *, project_root, sheet_names,
                               registry_path=None, legacy_risks=()):
    """Load optional facts by exact source hash; malformed/prose facts go to LLM.

    Only confirmed, evidenced region intersections cause a programmatic block.
    A missing default registry means no registered facts, never certification.
    """
    path = Path(registry_path or 'data/manifests/native_risks.json')
    if not path.is_absolute():
        path = Path(project_root) / path
    selected, requests = [], []
    registry_hash = None
    if not re.fullmatch(r'[a-f0-9]{64}', str(source_sha256)):
        requests.append({'source': 'source_sha256', 'reason': 'A full immutable source SHA-256 is required'})
    if path.is_file():
        try:
            raw = path.read_bytes()
            registry_hash = hashlib.sha256(raw).hexdigest()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('sources'), list):
                raise ValueError('Native-risk registry requires a sources list')
            for index, source in enumerate(data['sources']):
                if not isinstance(source, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(source.get('source_sha256'))):
                    requests.append({'source': f'registry/sources/{index}', 'reason': 'Source requires a full SHA-256'})
                    continue
                if source['source_sha256'] != source_sha256:
                    continue
                if not isinstance(source.get('risks'), list):
                    requests.append({'source': f'registry/sources/{index}', 'reason': 'Matched source requires a risks list'})
                    continue
                selected.extend(source['risks'])
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            requests.append({'source': 'native_risk_registry', 'reason': str(exc)})
    elif registry_path is not None:
        requests.append({'source': 'native_risk_registry', 'reason': 'Explicitly configured registry is unavailable'})
    if isinstance(legacy_risks, (list, tuple)):
        selected.extend(legacy_risks)
    elif legacy_risks:
        selected.append(legacy_risks)
    result = inspect_unsafe_regions(expected_changes, selected, sheet_names=sheet_names)
    result['evidence_requests'].extend(requests)
    if requests and result['state'] != 'flagged':
        result.update(state='unknown', blocking=False)
    result.update(source_sha256=source_sha256, registry_path=str(path), registry_sha256=registry_hash,
        registered_risk_count=len(selected) - (len(legacy_risks) if isinstance(legacy_risks, (list, tuple)) else bool(legacy_risks)),
        legacy_risks=list(legacy_risks) if isinstance(legacy_risks, (list, tuple)) else ([legacy_risks] if legacy_risks else []),
        baseline_business_correctness_certified=False,
        llm_q09_still_required=True,
        program_block_policy='Only evidenced confirmed unsafe-region intersections with full expected delta')
    return result
