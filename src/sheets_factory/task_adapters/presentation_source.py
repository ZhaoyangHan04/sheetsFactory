"""Execute and certify a new zero-presentation source without editing ancestry."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .lease_family import present_active_schedules, compare_exact_typed, ref, sha, _paths, NS
from ..workbook.engine import LibreOfficeEngine

IMAGE = 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def _read(path):
    return json.loads(Path(path).read_text())


def formula_definitions(path):
    result = {}
    with ZipFile(path) as archive:
        for sheet, name in _paths(archive).items():
            root = ET.fromstring(archive.read(name))
            for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
                formula = cell.find('m:f', NS)
                if formula is not None:
                    result[(sheet, cell.get('r'))] = (tuple(sorted(formula.attrib.items())), formula.text)
    return result


def verify_formula_allowlist(original, completed, conversions):
    before, after = formula_definitions(original), formula_definitions(completed)
    expected = {(x['sheet'], x['cell']) for x in conversions}
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    invalid = [{'sheet': s, 'cell': c, 'before': before.get((s, c)), 'after': after.get((s, c))}
               for s, c in sorted(changed) if (s, c) not in expected or (s, c) in after]
    return {'passed': changed == expected and not invalid,
            'removed_zero_formula_count': len(expected), 'actual_formula_definition_changes': len(changed),
            'unexpected_formula_changes': invalid, 'all_remaining_formula_definitions_unchanged': changed == expected}


def project_lease_zero_bindings(bindings, conversions, independent_ledger):
    """Move only independently recomputed zero bindings into literal controls."""
    result = deepcopy(bindings)
    converted = {(x['sheet'], x['cell']) for x in conversions}
    remaining, proven = [], []
    for binding in result['cell_bindings']:
        key = (binding['sheet'], binding['cell'])
        if key not in converted:
            remaining.append(binding)
            continue
        source = binding['source']
        if source[0] != 'lease_monthly':
            raise ValueError('Only lease monetary bindings may become provided zero controls')
        _, identity, period, field = source
        value = independent_ledger['lease_monthly'][identity][period - 1][field]
        if Decimal(str(value)) != 0:
            raise ValueError('A presented zero is nonzero in the fresh independent ledger')
        result['literal_controls'].append({'sheet': key[0], 'cell': key[1], 'value': 0})
        proven.append({'sheet': key[0], 'cell': key[1], 'independent_source': source,
                       'independently_recomputed_value': str(value)})
    if {(x['sheet'], x['cell']) for x in proven} != converted:
        raise ValueError('Every presented zero requires one original independent binding')
    result['cell_bindings'] = remaining
    return result, proven


def load_original_source(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    source = _read(manifest_path)
    if source.get('financial_audit_passed') is not True or len(source.get('selected', [])) != 1:
        raise ValueError('Exactly one independently audited original source is required')
    if set(source.get('financial_audits', {})) != {'lease', 'programme', 'operating', 'holding'}:
        raise ValueError('This adapter requires the four-module non-circular source version')
    book = Path(source['local_path'])
    if sha(book) != source['derived_workbook_sha256'] or source['selected'][0]['sha256'] != sha(book):
        raise ValueError('Original source workbook identity differs')
    if source['runtime']['image_id'] != IMAGE_ID:
        raise ValueError('Original source runtime differs')
    audits, tracked = {}, {str(manifest_path): sha(manifest_path), str(book): sha(book)}
    for name in source['financial_audits']:
        path = manifest_path.parent / 'private' / (name + '_financial_audit.json')
        data = _read(path)
        if (data.get('passed') is not True or data.get('checked_cells') != source['financial_audits'][name]['checked_cells']
                or data.get('workbook', {}).get('sha256') != sha(book)):
            raise ValueError('Incomplete exact-source independent financial audit: ' + name)
        if any(data.get(k) for k in ('mismatches', 'uncovered', 'uncovered_formulas', 'native_errors', 'control_mismatches')):
            raise ValueError('Original financial audit contains unresolved findings')
        audits[name] = {'artifact': ref(path), 'data': data}
        tracked[str(path)] = sha(path)
    for key in ('financial_audit', 'stability', 'public_scenarios'):
        record = source[key]
        if sha(record['path']) != record['sha256']:
            raise ValueError('Original source proof changed: ' + key)
        tracked[record['path']] = record['sha256']
    if _read(source['stability']['path']).get('stable') is not True:
        raise ValueError('Original source stability did not pass')
    return source, audits, tracked


def build_presentation_source(source_manifest, output, *, policy, project_root, engine=None):
    """Only complete actual engine proofs can populate selected[]."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / 'private'
    private.mkdir()
    start = time.monotonic()
    phase = 'validate_original'
    try:
        source, audits, tracked = load_original_source(source_manifest)
        original = Path(source['local_path'])
        phase = 'present_source'
        raw = output / 'presentation_raw.xlsx'
        conversion = present_active_schedules(original, raw, policy)
        _write(private / 'presentation.json', conversion)
        raw_equality = compare_exact_typed(original, raw, public_note=conversion['public_note'])
        _write(private / 'raw_value_equivalence.json', raw_equality)
        if not raw_equality['passed']:
            raise ValueError('Raw presentation changed existing business values')
        engine = engine or LibreOfficeEngine(project_root, IMAGE, 300)
        if not isinstance(engine, LibreOfficeEngine):
            raise ValueError('Offline fixture engines cannot certify selected sources')
        phase = 'actual_engine_identity'
        runtime = engine.metadata()
        if runtime.get('image_id') != IMAGE_ID:
            raise ValueError('Presentation validation requires the pinned real runtime')
        phase = 'actual_recalculate_and_exact_equivalence'
        goal = engine.recalculate(raw, output / 'composite_model.xlsx')
        equality = compare_exact_typed(original, goal, public_note=conversion['public_note'])
        allowlist = verify_formula_allowlist(original, goal, conversion['conversions'])
        _write(private / 'exact_value_equivalence.json', equality)
        _write(private / 'formula_allowlist.json', allowlist)
        if not equality['passed'] or not allowlist['passed']:
            raise ValueError('Actual LibreOffice presentation is not exactly equivalent within the formula allowlist')
        phase = 'two_actual_stability_passes'
        first = engine.recalculate(goal, private / 'stable_pass1.xlsx')
        second = engine.recalculate(first, private / 'stable_pass2.xlsx')
        checks = {'goal_to_first': compare_exact_typed(goal, first),
                  'first_to_second': compare_exact_typed(first, second)}
        stable = {'stable': all(x['passed'] for x in checks.values()), 'checks': checks,
                  'goal': ref(goal), 'first': ref(first), 'second': ref(second),
                  'runtime': runtime, 'actual_recalculations': 2,
                  'comparison': 'Full exact typed values without cent rounding.'}
        _write(private / 'stability.json', stable)
        if not stable['stable']:
            raise ValueError('New presentation source is not exactly typed-stable')
        phase = 'transitive_independent_financial_coverage'
        # The unchanged public lease primitives permit a fresh existing auditor
        # run with an honest projection of zero formulas into literal controls.
        from ..workbook.lease_finance.ledger import simulate_lease
        from ..workbook.lease_finance.validate import audit_lease_workbook
        specs = _read(source['public_scenarios']['path'])
        lease_ledger = simulate_lease(specs['lease'])
        old_binding_path = Path(source_manifest).parent / 'private/lease_bindings.json'
        lease_binding, zero_checks = project_lease_zero_bindings(
            _read(old_binding_path), conversion['conversions'], lease_ledger)
        _write(private / 'fresh_lease_zero_projection.json', {
            'original_bindings': ref(old_binding_path), 'zero_checks': zero_checks,
            'fresh_independent_ledger_checks': lease_ledger['checks'],
            'zero_count': len(zero_checks), 'all_zero_bindings_independently_recomputed': True})
        fresh_lease = audit_lease_workbook(goal, specs['lease'], lease_ledger, lease_binding)
        fresh_lease.update(workbook=ref(goal), provided_zero_projection=ref(private / 'fresh_lease_zero_projection.json'),
                           provided_zero_count=len(zero_checks), fresh_independent_journal_execution=True)
        if fresh_lease['passed'] is not True:
            _write(private / 'fresh_lease_rejection.json', fresh_lease)
            raise ValueError('Fresh independent lease audit did not cover the presented source')
        coverage, summary = {}, {}
        for name, old in audits.items():
            original_audit = old['data']
            record = {'passed': True, 'method': 'transitive_independent_financial_audit_through_full_exact_typed_equivalence',
                      'workbook': ref(goal), 'original_source': ref(original), 'original_independent_audit': old['artifact'],
                      'exact_value_equivalence': ref(private / 'exact_value_equivalence.json'),
                      'formula_allowlist': ref(private / 'formula_allowlist.json'),
                      'checked_cells': original_audit['checked_cells'],
                      'inherited_checks': original_audit.get('independent_journal_checks', original_audit.get('journal_checks', {})),
                      'financial_policies_and_primitives_unchanged': True,
                      'new_independent_journal_execution_claimed': False,
                      'mismatches': [], 'scope': 'All original independently audited cells retain identical exact typed monetary values; only approved zero formula presentation changed.'}
            if name == 'lease':
                record = fresh_lease
            path = private / (name + '_financial_audit.json')
            _write(path, record)
            coverage[name] = ref(path)
            summary[name] = {'passed': True, 'checked_cells': record['checked_cells'],
                             'validation_method': record['method'],
                             'provided_zero_count': record.get('provided_zero_count', 0)}
        _write(private / 'financial_audit_summary.json', summary)
        for path, expected in tracked.items():
            if sha(path) != expected:
                raise ValueError('Original source evidence changed during presentation validation')
        lineage = {'method': 'exact_value_preserving_active_schedule_presentation',
                   'original_manifest': ref(source_manifest), 'original_source': ref(original),
                   'new_source': ref(goal), 'original_evidence_sha256': tracked,
                   'presentation': ref(private / 'presentation.json'),
                   'full_exact_equivalence': ref(private / 'exact_value_equivalence.json'),
                   'transitive_component_audits': coverage,
                   'old_audits_relabelled_as_new_source': False}
        _write(private / 'transitive_coverage.json', lineage)
        shutil.copy2(source['public_scenarios']['path'], output / 'public_scenarios.json')
        evidence = {'financial_seed_verified': True, 'financial_modeling_eligible': True,
                    'source_business_issues': [], 'validation_method': 'fresh_independent_lease_plus_transitive_exact_other_modules',
                    'transitive_coverage': ref(private / 'transitive_coverage.json'),
                    'independent_financial_audits': coverage, 'qualification': 'Source correctness only; task activity, quality and difficulty are pending.'}
        entry = {'sha256': sha(goal), 'source_sha256': sha(goal), 'local_path': str(goal),
                 'source_kind': 'derived_active_schedule_presentation', 'modes': ['debugging'],
                 'finance_eligible': True, 'financial_modeling_eligible': True, 'finance_evidence': evidence}
        manifest = {'schema_version': 1, 'status': 'actually_verified_active_schedule_source',
                    'qualified': False, 'task_count': 0, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'local_path': str(goal), 'derived_workbook_sha256': sha(goal), 'selected': [entry],
                    'unique_workbooks_inspected': 1, 'download_url': 'derived-active-schedule-presentation',
                    'archive_sha256': None, 'source_ancestors': source['source_ancestors'],
                    'source_original_ancestors': 2, 'financial_audit_passed': True,
                    'financial_validation_method': 'fresh_independent_lease_plus_transitive_exact_other_modules',
                    'financial_audits': summary, 'financial_audit': ref(private / 'financial_audit_summary.json'),
                    'public_scenarios': ref(output / 'public_scenarios.json'),
                    'stability': ref(private / 'stability.json'), 'runtime': runtime,
                    'lineage': ref(private / 'transitive_coverage.json'), 'presentation_policy': policy,
                    'recipe': {str(Path(__file__).resolve()): sha(__file__),
                               str(Path(__file__).with_name('lease_family.py').resolve()): sha(Path(__file__).with_name('lease_family.py'))},
                    'llm_calls': 0, 'api_calls': 0, 'difficulty_measured': False,
                    'elapsed_seconds': time.monotonic() - start}
        _write(output / 'seed_manifest.json', manifest)
        return manifest
    except BaseException as error:
        _write(output / 'rejection.json', {'phase': phase, 'type': type(error).__name__, 'reason': str(error),
                    'selected': [], 'qualified': False, 'task_count': 0,
                    'elapsed_seconds': time.monotonic() - start})
        raise
