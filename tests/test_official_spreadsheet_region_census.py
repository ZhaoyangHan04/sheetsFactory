"""Actual frozen pure evaluator + tiny workbook tests; no native or model calls."""
from pathlib import Path
import importlib.util
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.styles import Color, Font
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('official_region_census_tested', ROOT / 'scripts/census_official_spreadsheet_regions.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
EVALUATOR = ROOT / 'outputs/research/spreadsheetbench2_full_official_FM_DBG_inventory_revision2_20261031T155832Z/metadata/official_evaluation.py'


@pytest.fixture(scope='module')
def evaluator():
    return m.load_evaluator(m.reference(EVALUATOR))


def book(tmp_path, name, values, *, sheet='Data', colors=None, cached=None):
    path = tmp_path / (name + '.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for cell, value in values.items():
        ws[cell] = value
    for cell, color in (colors or {}).items():
        ws[cell].font = Font(color=color)
    wb.save(path)
    wb.close()
    if cached:
        # Explicit tiny synthetic OOXML fixture, not an engine or expected-value injection into real data.
        with ZipFile(path) as z:
            members = {n: z.read(n) for n in z.namelist()}
        tree = ET.fromstring(members['xl/worksheets/sheet1.xml'])
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        for node in tree.findall(ns + 'sheetData/' + ns + 'row/' + ns + 'c'):
            if node.attrib['r'] not in cached:
                continue
            kind, value = cached[node.attrib['r']]
            node.set('t', kind)
            v = node.find(ns + 'v')
            if v is None:
                v = ET.SubElement(node, ns + 'v')
            v.text = str(value)
        members['xl/worksheets/sheet1.xml'] = ET.tostring(tree)
        with ZipFile(path, 'w') as z:
            for name, value in members.items():
                z.writestr(name, value)
    return m.reference(path)


def compare(evaluator, source, goal, output, region='Data!A1:B2', *, color=False, formula=False):
    return m.compare_regions(source, goal, output, region,
        {'with_font_color': color, 'with_formula': formula}, evaluator)


def test_complete_rectangle_includes_implicit_blanks_and_uses_official_numeric_tolerance(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 100, 'B1': None})
    b = book(tmp_path, 'gold', {'A1': 100, 'B1': 20})
    c = book(tmp_path, 'out', {'A1': 100.5, 'B1': 19})
    result = compare(evaluator, a, b, c)
    assert result['summary']['region_position_count'] == 4
    assert result['stats'] == dict(regression_correct=3, regression_total=3, modification_correct=0, modification_total=1)
    assert result['regions'][0]['regression_cells'] == ['A1', 'A2', 'B2']
    assert [(x['cell'], x['class']) for x in result['all_misses']] == [('B1', 'modification')]
    assert result['reproduced_metrics'] == dict(regression_accuracy=1, modification_accuracy=0, accuracy=0)


def test_regression_threshold_retains_all_misses_even_when_original_raw_score_passes(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'B1': None})
    b = book(tmp_path, 'gold', {'B1': 10})
    c = book(tmp_path, 'out', {'A1': 'changed', 'A2': 'changed', 'B1': 10})
    result = compare(evaluator, a, b, c, 'Data!A1:A1000,Data!B1')
    assert result['stats']['regression_correct'] == 998
    assert result['reproduced_metrics']['accuracy'] == 1
    assert len(result['all_misses']) == 2


def test_embedded_formula_normalization_does_not_assert_algebraic_equivalence(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 'bad', 'A2': '=SUM(B1:B2)'})
    b = book(tmp_path, 'gold', {'A1': '=+$B$1', 'A2': '=SUM(B1:B2)'})
    c = book(tmp_path, 'out', {'A1': '=b1', 'A2': '=B1+B2'})
    result = compare(evaluator, a, b, c, 'Data!A1:A2', formula=True)
    assert result['stats']['modification_correct'] == 1
    assert result['all_misses'][0]['comparison_rule'] == 'formula'
    assert result['all_misses'][0]['cell'] == 'A2'


def test_color_mode_uses_original_theme_resolution_and_detects_real_color_difference(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 10, 'A2': 20}, colors={'A1': 'FFFF0000', 'A2': 'FF000000'})
    b = book(tmp_path, 'gold', {'A1': 10, 'A2': 20}, colors={'A1': Color(theme=1), 'A2': 'FF000000'})
    c = book(tmp_path, 'out', {'A1': 10, 'A2': 20}, colors={'A1': '00000000', 'A2': 'FFFF0000'})
    result = compare(evaluator, a, b, c, 'Data!A1:A2', color=True)
    assert result['stats']['modification_correct'] == 1
    assert result['stats']['regression_correct'] == 0
    assert [x['cell'] for x in result['all_misses']] == ['A2']


def test_error_placeholder_equivalence_is_overridden_by_original_formula_fallback(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': '=1/0'}, cached={'A1': ('e', '#DIV/0!')})
    b = book(tmp_path, 'gold', {'A1': '=1/0'}, cached={'A1': ('e', '#DIV/0!')})
    c = book(tmp_path, 'out', {'A1': '=IFERROR(1/0,"N/A")'}, cached={'A1': ('str', 'N/A')})
    assert evaluator.compare_cell_value('#DIV/0!', 'N/A')
    result = compare(evaluator, a, b, c, 'Data!A1')
    assert result['all_misses'][0]['comparison_rule'] == 'excel_error_formula_fallback'
    assert result['all_misses'][0]['reference']['data_type'] == 'e'


def test_error_formula_fallback_in_color_mode_preserves_original_color_bypass(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': '=1/0'}, cached={'A1': ('e', '#DIV/0!')})
    b = book(tmp_path, 'gold', {'A1': '=1/0'}, cached={'A1': ('e', '#DIV/0!')}, colors={'A1': 'FFFF0000'})
    c = book(tmp_path, 'out', {'A1': '=1/0'}, cached={'A1': ('e', '#DIV/0!')}, colors={'A1': 'FF000000'})
    result = compare(evaluator, a, b, c, 'Data!A1', color=True)
    assert result['summary']['miss_count'] == 0
    assert result['stats']['regression_correct'] == 1


def test_quoted_comma_sheet_and_case_whitespace_lookup(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 1}, sheet='ACC,Dil ')
    b = book(tmp_path, 'gold', {'A1': 2}, sheet='ACC,Dil')
    c = book(tmp_path, 'out', {'A1': 2}, sheet='acc,dil')
    result = compare(evaluator, a, b, c, "'ACC,Dil'!A1")
    assert not result['holds'] and result['stats']['modification_correct'] == 1


def test_overlapping_regions_keep_duplicate_official_counts_and_all_misses(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 1})
    b = book(tmp_path, 'gold', {'A1': 2})
    c = book(tmp_path, 'out', {'A1': 3})
    result = compare(evaluator, a, b, c, 'Data!A1:A2,Data!A1')
    assert result['summary']['region_position_count'] == 3
    assert len(result['all_misses']) == 2
    assert [x['region_index'] for x in result['all_misses']] == [0, 1]


def test_missing_output_sheet_is_hold_and_every_classified_cell_is_retained(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 1})
    b = book(tmp_path, 'gold', {'A1': 2})
    c = book(tmp_path, 'out', {}, sheet='Other')
    result = compare(evaluator, a, b, c, 'Data!A1:A3')
    assert result['holds'][0]['roles'] == ['output']
    assert result['summary']['miss_count'] == 3
    assert result['all_declared_positions_enumerated'] is True


def test_missing_input_sheet_does_not_invent_unclassified_pass(tmp_path, evaluator):
    a = book(tmp_path, 'in', {}, sheet='Other')
    b = book(tmp_path, 'gold', {'A1': 2})
    c = book(tmp_path, 'out', {'A1': 2})
    result = compare(evaluator, a, b, c, 'Data!A1:A3')
    assert result['summary']['classified_position_count'] == 0
    assert result['summary']['region_position_count'] == 3
    assert result['holds'][0]['roles'] == ['source']
    assert result['all_declared_positions_enumerated'] is False


def test_missing_reference_sheet_is_hold_and_does_not_claim_complete_enumeration(tmp_path, evaluator):
    a = book(tmp_path, 'in', {'A1': 2})
    b = book(tmp_path, 'gold', {}, sheet='Other')
    c = book(tmp_path, 'out', {'A1': 2})
    result = compare(evaluator, a, b, c, 'Data!A1:A3')
    assert result['summary']['classified_position_count'] == 0
    assert result['summary']['region_position_count'] == 3
    assert result['holds'][0]['roles'] == ['reference']
    assert result['all_declared_positions_enumerated'] is False


@pytest.mark.parametrize('category,path,expected', [
    ('Financial_Model', 'Color Embedded.xlsx', (False, False)),
    ('Debugging', 'ordinary.xlsx', (False, False)),
    ('Debugging', 'Color fonts/input.xlsx', (True, False)),
    ('Debugging', 'Embedded formula/input.xlsx', (False, True)),
    ('Debugging', 'Color Embedded.xlsx', (True, True)),
])
def test_exact_mode_dispatch(category, path, expected):
    result = m.comparison_mode({'category': category, 'official_record': {'spreadsheet_path': path}})
    assert tuple(result.values()) == expected


def test_wrong_evaluator_ref_rejected_before_import(tmp_path):
    p = tmp_path / 'wrong.py'
    p.write_text('raise AssertionError("must not import")')
    with pytest.raises(ValueError, match='Unknown official evaluator'):
        m.load_evaluator(m.reference(p))


def plan(tmp_path, *, output=20, stored_accuracy=1):
    source = book(tmp_path, 'source', {'A1': 10, 'B1': None})
    goal = book(tmp_path, 'goal', {'A1': 10, 'B1': 20})
    result = book(tmp_path, 'output', {'A1': 10, 'B1': output})
    case = {'case_key': 'Financial_Model/TOY', 'task_id': 'toy', 'category': 'Financial_Model',
            'official_record': {'spreadsheet_path': 'input.xlsx', 'answer_position': 'Data!A1:B1'}}
    return {'case': case, 'evidence': {'source': source, 'reference': goal, 'output': result}, 'holds': [],
            'original_official_score': {'accuracy': stored_accuracy, 'regression_accuracy': 1,
                                        'modification_accuracy': stored_accuracy}, 'pending': False}


def test_report_has_stable_evidence_and_original_score_is_never_replaced(tmp_path, evaluator):
    p = plan(tmp_path, output=30, stored_accuracy=1)
    report = m.census_case(p, evaluator)
    assert report['status'] == 'hold'
    assert report['original_official_score']['accuracy'] == 1
    assert report['reproduced_metrics']['accuracy'] == 0
    assert report['official_score_consistency'] is False
    assert report['evidence'] == p['evidence']
    assert report['case_key'] == report['case_id'] == 'Financial_Model/TOY'
    assert report['summary']['region_position_count'] == 2
    assert report['summary']['miss_count'] == 1
    assert report['official_score_changed'] is False


def test_pending_case_retained_without_zero_or_fake_score(tmp_path, evaluator):
    p = {'case': {'case_key': 'Debugging/TOY', 'task_id': 'toy', 'category': 'Debugging',
                 'official_record': {'spreadsheet_path': 'input.xlsx'}},
         'evidence': {}, 'holds': ['case_terminal_pending'], 'pending': True}
    report = m.census_case(p, evaluator)
    assert report['status'] == 'pending'
    assert report['original_official_score'] is None
    assert report['summary']['miss_count'] is None


def test_changed_bound_input_ref_is_rejected(tmp_path, evaluator):
    p = plan(tmp_path)
    Path(p['evidence']['source']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='Bound evidence changed'):
        m.census_case(p, evaluator)


def test_mutation_during_comparison_is_detected_by_final_guard(tmp_path, evaluator, monkeypatch):
    p = plan(tmp_path)
    original = evaluator.cell_level_compare_with_classification
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(p['evidence']['output']['path']).write_bytes(b'changed after reading')
        return result
    monkeypatch.setattr(evaluator, 'cell_level_compare_with_classification', mutate)
    with pytest.raises(ValueError, match='Workbook changed during offline comparison'):
        m.census_case(p, evaluator)


def test_alias_content_identity_allows_original_reused_attempt_paths(tmp_path):
    a = tmp_path / 'a.xlsx'
    b = tmp_path / 'copied.xlsx'
    a.write_bytes(b'original'); b.write_bytes(b'original')
    assert m.reference(a) != m.reference(b)
    assert m._same_content(m.reference(a), m.reference(b))
    b.write_bytes(b'another')
    assert not m._same_content(m.reference(a), m.reference(b))


def test_full_inventory_gate_precedes_any_output(tmp_path):
    p = tmp_path / 'fake.json'
    p.write_text(json.dumps({'cases': []}))
    out = tmp_path / 'out'
    with pytest.raises(ValueError, match='Unknown official all200 inventory'):
        m.run_batch(p, tmp_path, out)
    assert not out.exists()


def actual_case_fixture(tmp_path, *, official=True, reused=False):
    case = {'case_key': 'Debugging/TOY', 'task_id': 'external-toy', 'category': 'Debugging',
            'official_record': {'id': 'TOY', 'instruction': 'Audit the supplied workbook.',
                                'spreadsheet_path': 'input.xlsx', 'answer_position': 'Data!A1:B1'},
            'input': book(tmp_path, 'raw_input', {'A1': 10}),
            'goal': book(tmp_path, 'raw_goal', {'A1': 10, 'B1': 20})}
    folder = tmp_path / 'cohort/cases/external-toy'
    trial = (tmp_path / 'retained_trial' if reused else folder / 'evaluation/harbor_jobs/first/trial')
    (trial / 'agent').mkdir(parents=True)
    (trial / 'artifacts/app').mkdir(parents=True)
    (trial / 'result.json').write_text('{"finished_at":"2026-11-01"}')
    (trial / 'agent/trajectory.json').write_text('{"messages":[]}')
    out = book(tmp_path, 'native_output', {'A1': 10, 'B1': 20})
    (trial / 'artifacts/app/output.xlsx').write_bytes(Path(out['path']).read_bytes())
    terminal = {'case_key': case['case_key'], 'task_id': case['task_id']}
    if official:
        alias = tmp_path / 'official_output.xlsx'
        alias.write_bytes(Path(out['path']).read_bytes())
        terminal['official_primary'] = {'input': case['input'], 'reference': case['goal'],
            'same_submitted_alias' if reused else 'output': m.reference(alias),
            'mapped_record': case['official_record'],
            'result': {'accuracy': 1, 'regression_accuracy': 1, 'modification_accuracy': 1}}
        if not reused:
            terminal['official_primary']['evaluator'] = m.reference(EVALUATOR)
    if reused:
        postscore = tmp_path / 'postscore.json'
        postscore.write_text(json.dumps({'pinned_evaluator': m.reference(EVALUATOR)}))
        case['existing_attempt'] = {'result': m.reference(trial / 'result.json'),
                                    'official_postscore': m.reference(postscore)}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'terminal.json').write_text(json.dumps(terminal))
    return case, tmp_path / 'cohort', folder


def test_retained_original_attempt_uses_original_output_and_score_alias_only_for_content(tmp_path, evaluator):
    case, cohort, _ = actual_case_fixture(tmp_path, reused=True)
    bound = m.resolve_case(case, cohort, m.reference(EVALUATOR))
    report = m.census_case(bound, evaluator)
    assert report['status'] == 'complete'
    assert report['evidence']['output'] != report['official_scoring_artifacts']['same_submitted_alias']
    assert m._same_content(report['evidence']['output'], report['official_scoring_artifacts']['same_submitted_alias'])
    assert report['retained_official_postscore'] == case['existing_attempt']['official_postscore']


def test_completed_native_output_without_official_postscore_still_gets_full_region_hold(tmp_path, evaluator):
    case, cohort, _ = actual_case_fixture(tmp_path, official=False)
    bound = m.resolve_case(case, cohort, m.reference(EVALUATOR))
    report = m.census_case(bound, evaluator)
    assert report['status'] == 'hold'
    assert report['original_official_score'] is None
    assert report['official_score_consistency'] is None
    assert report['summary']['region_position_count'] == 2
    assert report['reproduced_metrics']['accuracy'] == 1
    assert set(report['evidence']) == {'source', 'reference', 'output', 'trajectory', 'result', 'case_terminal', 'official_evaluator'}
    assert report['official_score_changed'] is False


def test_multiple_native_trials_and_foreign_scorer_submission_rejected(tmp_path):
    case, cohort, folder = actual_case_fixture(tmp_path)
    terminal = folder / 'terminal.json'
    data = json.loads(terminal.read_text())
    foreign = tmp_path / 'foreign.xlsx'
    foreign.write_bytes(b'another submission')
    data['official_primary']['output'] = m.reference(foreign)
    terminal.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='another submission'):
        m.resolve_case(case, cohort, m.reference(EVALUATOR))
    second = folder / 'evaluation/harbor_jobs/second/trial/result.json'
    second.parent.mkdir(parents=True)
    second.write_text('{}')
    with pytest.raises(ValueError, match='Multiple trials'):
        m.resolve_case(case, cohort, m.reference(EVALUATOR))


def test_batch_retains_all_200_pending_cases_and_freezes_order_before_comparisons(tmp_path, monkeypatch):
    dummy = tmp_path / 'dummy.xlsx'
    dummy.write_bytes(b'not read without a terminal')
    cases = [{'case_key': f'{category}/{i:03}', 'task_id': f'{category}-{i:03}', 'category': category,
              'input': m.reference(dummy), 'goal': m.reference(dummy), 'official_record': {'spreadsheet_path': 'input.xlsx'}}
             for category in ['Financial_Model', 'Debugging'] for i in range(100)]
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({'cases': cases, 'fixed_order': [c['case_key'] for c in cases],
                                     'official_evaluator': m.reference(EVALUATOR)}))
    monkeypatch.setattr(m, 'INVENTORY_SHA', m.reference(inventory)['sha256'])
    result = m.read(m.run_batch(inventory, tmp_path / 'cohort', tmp_path / 'census'))
    assert result['case_order'] == [c['case_key'] for c in cases]
    assert len(result['cases']) == 200
    assert result['counts'] == {'pending': 200}
    assert all(row['summary']['miss_count'] is None for row in result['cases'])
    prospective = m.read(result['prospective'])
    assert len(prospective['case_plans']) == 200
    assert result['new_model_LO_solver_network_calls'] == 0
