"""Native-error gates: explicit fixture caches plus opt-in real LO probes."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

import openpyxl
import pytest

from sheets_factory.checkers.native_error_probe import exact_typed_value, probe_native_errors
from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes.construction import ConstructNode, validate_plan
from sheets_factory.workbook.engine import LibreOfficeEngine


ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cached_fixture(path, formulas=None, caches=None):
    """Explicitly declared cache fixtures; this helper is not a formula evaluator."""
    book = openpyxl.Workbook()
    book.active.title = 'Out'
    for row in range(1, 7):
        book['Out'][f'A{row}'] = (formulas or {}).get(f'A{row}', '=IF(TRUE,Table!A1,Table!B1)')
    table = book.create_sheet('Table')
    table['A1'] = 10
    table['B1'] = '=1/0'
    table['C1'] = '=1/0'
    book.create_sheet('Context')['A1'] = 'USD annual'
    book.create_sheet('Notes')['A1'] = 'public rules'
    book.save(path)
    with ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    for part, values in [('xl/worksheets/sheet1.xml', {f'A{i}': 10 for i in range(1, 7)} | (caches or {})),
                         ('xl/worksheets/sheet2.xml', {'B1': '#DIV/0!', 'C1': '#DIV/0!'})]:
        xml = ET.fromstring(parts[part])
        for cell in xml.findall('.//s:c', NS):
            if cell.attrib['r'] not in values:
                continue
            value = values[cell.attrib['r']]
            cell.attrib['t'] = 'e' if isinstance(value, str) and value.startswith('#') else 'n'
            cached = cell.find('s:v', NS)
            if cached is None:
                cached = ET.SubElement(cell, '{' + NS['s'] + '}v')
            cached.text = str(value)
        parts[part] = ET.tostring(xml)
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def plan(path):
    book = openpyxl.load_workbook(path)
    try:
        return {'public_instruction': 'Restore annual outputs using the stated rules.',
                'public_rules': ['Table A1 is USD annual input; use the literal selected branch.'],
                'reference_evidence': ['public Table A1'],
                'edits': [{'sheet': 'Out', 'cell': f'A{i}', 'before': book['Out'][f'A{i}'].value,
                           'after': None} for i in range(1, 7)]}
    finally:
        book.close()


class FixtureTransport:
    """Return declared output observations; never claim calculation semantics."""
    def __init__(self, goal, observed=None, fail=False):
        self.goal, self.observed, self.fail = goal, observed, fail
        self.inputs = []

    def recalculate(self, source, destination):
        self.inputs.append(Path(source))
        if self.fail:
            raise RuntimeError('fixture: calculation unavailable')
        shutil.copy2(self.goal, destination)
        if self.observed:
            book = openpyxl.load_workbook(destination)
            for label, value in self.observed.items():
                sheet, cell = label.rsplit('!', 1)
                book[sheet][cell] = value
            book.save(destination)
            book.close()
        return destination


def run_probe(tmp_path, goal, engine=None, **kwargs):
    return probe_native_errors(goal=goal, required_delta=kwargs.pop('required_delta', ['Out!A1']),
        candidates=kwargs.pop('candidates', []), engine=engine or FixtureTransport(goal),
        directory=tmp_path / 'probes', source_sha256=digest(goal), plan={'test': 'explicit fixture'},
        revision=3, immutable_files={'source': goal, 'baseline': goal}, **kwargs)


def test_validate_plan_records_ancestor_errors_but_never_clears_them(tmp_path):
    source = cached_fixture(tmp_path / 'goal.xlsx')
    validation = validate_plan(plan(source), source, 'financial_modeling')
    assert validation['native_error_candidates'] == [{'sheet': 'Table', 'cell': 'B1',
        'cached_error': '#DIV/0!', 'formula': '=1/0'}]
    assert validation['native_error_candidates_provisional'] is True


@pytest.mark.parametrize('formula,cache,code', [
    ('=Table!B1', '#DIV/0!', 'Q04'),
    ('=Table!A1+NOW()', 10, 'Q10'),
    ('=INDIRECT("Table!A1")', 10, 'Q10'),
])
def test_root_error_volatile_and_unsupported_remain_hard_rejections(tmp_path, formula, cache, code):
    source = cached_fixture(tmp_path / 'goal.xlsx', {'A1': formula}, {'A1': cache})
    with pytest.raises(TaskRejected, match=code):
        validate_plan(plan(source), source, 'financial_modeling')


@pytest.mark.parametrize('formula', ['=IF(TRUE,Table!A1,Table!B1)', '=INDEX(Table!A1:B1,1,1)',
    '=VLOOKUP(10,Table!A1:C1,1,FALSE)'])
def test_narrow_certificate_and_all_probes_required_for_inactive_state(tmp_path, formula):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': formula})
    engine = FixtureTransport(goal)
    result = run_probe(tmp_path, goal, engine)
    assert not result['blocking'] and result['state'] == 'current_scenario_inactive'
    assert result['business_correctness_certificate'] is False
    assert result['dependency_certificates']['per_delta_errors'] == {'Out!A1': []}
    assert len(result['probes']) == 2 * len(result['candidates']) + 2
    assert len({p['input_sha256'] for p in result['probes']}) >= 2
    assert result['immutable_unchanged'] and digest(goal) == result['goal_sha256']
    assert json.loads((tmp_path / 'probes/receipt.json').read_text()) == result


def test_unchanged_sentinels_cannot_clear_uncertified_single_error(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': '=IFERROR(Table!B1,10)'})
    result = run_probe(tmp_path, goal)
    assert result['blocking'] and result['state'] == 'unknown'
    assert result['uncertified_paths'] == {'Out!A1': ['Table!B1']}
    assert all(p['state'] == 'unchanged' for p in result['probes'])


def test_one_other_reference_path_defeats_unused_column_certificate(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': '=INDEX(Table!A1:B1,1,1)+IFERROR(Table!B1,0)'})
    result = run_probe(tmp_path, goal)
    assert result['blocking'] and result['uncertified_paths']['Out!A1'] == ['Table!B1']


@pytest.mark.parametrize('observed', [10.000001, True, '#VALUE!', '10'])
def test_exact_typed_changes_include_tiny_numeric_and_boolean_and_error_and_text(tmp_path, observed):
    goal = cached_fixture(tmp_path / 'goal.xlsx')
    result = run_probe(tmp_path, goal, FixtureTransport(goal, {'Out!A1': observed}))
    assert result['blocking'] and result['certainty'] == 'confirmed'
    assert 'Out!A1' in result['probes'][0]['changed_values']


def test_actual_goal_error_in_downstream_D_rejects_without_any_probe(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', caches={'A6': '#VALUE!'})
    engine = FixtureTransport(goal)
    result = run_probe(tmp_path, goal, engine, required_delta=['Out!A1', 'Out!A6'])
    assert result['blocking'] and result['problem_id'] == 'Q04'
    assert result['goal_error_cells'] == ['Out!A6'] and not engine.inputs


def test_errored_ancestor_unique_to_downstream_D_is_discovered(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': '=Table!A1', 'A6': '=IFERROR(Table!C1,10)'})
    result = run_probe(tmp_path, goal, required_delta=['Out!A1', 'Out!A6'])
    assert result['blocking']
    assert result['uncertified_paths'] == {'Out!A6': ['Table!C1']}


def test_probe_failure_is_unknown_not_success(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx')
    result = run_probe(tmp_path, goal, FixtureTransport(goal, fail=True))
    assert result['blocking'] and result['state'] == 'unknown'
    assert result['probes'][0]['state'] == 'unknown'


def test_joint_probes_have_separate_coordinate_weights_and_fresh_clones(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': '=IFERROR(Table!B1-Table!C1,10)'})
    engine = FixtureTransport(goal)
    result = run_probe(tmp_path, goal, engine)
    assert result['blocking']  # All paths must still have a certificate.
    assert len(result['probes']) == 6
    for probe in result['probes'][-2:]:
        assert probe['kind'] == 'joint' and len(set(probe['assignments'].values())) == 2
    for probe in result['probes'][:4]:
        book = openpyxl.load_workbook(probe['input'])
        remaining = 'C1' if 'Table!B1' in probe['assignments'] else 'B1'
        assert book['Table'][remaining].value == '=1/0'
        book.close()
    assert digest(goal) == result['goal_sha256']


def test_candidate_and_source_binding_limits_reject(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx')
    assert run_probe(tmp_path, goal, max_candidates=0)['blocking']
    other = tmp_path / 'other'
    other.mkdir()
    result = run_probe(other, goal, candidates=[{'sheet': 'Table', 'cell': 'A1'}])
    assert result['blocking'] and 'not an actual cached error' in result['reason']


def test_no_errors_still_has_full_D_receipt(tmp_path):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': '=Table!A1'})
    result = run_probe(tmp_path, goal)
    assert result['state'] == 'not_applicable' and not result['blocking']
    assert result['required_delta'] == ['Out!A1']


@pytest.mark.parametrize('formula', ['=SUM(Table!B2:B1)', '=SUM(Table!XFE1:XFE2)',
    '=IFERROR(SUM(INDEX(Table!A1:B2,1,1):INDEX(Table!D4:E5,1,1)),10)',
    '=SUM((Table!A1,Table!B1))', '=SUM(Table!A1:B2 Table!B1:C2)'])
def test_malformed_range_cannot_skip_candidate_discovery(tmp_path, formula):
    goal = cached_fixture(tmp_path / 'goal.xlsx', {'A1': formula})
    result = run_probe(tmp_path, goal)
    assert result['blocking'] and result['problem_id'] == 'Q10'


class QuietAudit:
    def emit(self, *args, **kwargs):
        pass


def test_construct_persists_probe_and_validation_before_rejecting(tmp_path, monkeypatch):
    source = cached_fixture(tmp_path / 'source.xlsx')
    ctx = TaskContext('r', 'fm-fixture', 'financial_modeling', source, tmp_path / 'task',
        {'project_root': str(ROOT)}, QuietAudit(), None, FixtureTransport(source))
    ctx.data.update(baseline=source, source_id=digest(source), plan=plan(source))
    monkeypatch.setattr('sheets_factory.nodes.construction.compare_workbooks', lambda *a: {
        'expected_change_count': 6, 'expected_changes': [f'Out!A{i}' for i in range(1, 7)],
        'goal_sheets': ['Out', 'Table', 'Context', 'Notes']})
    # A downstream error does not pass validation of the six edited roots.
    monkeypatch.setattr('sheets_factory.nodes.construction.probe_native_errors', lambda **kw: {
        'blocking': True, 'problem_id': 'Q09', 'reason': 'uncertified path',
        'state': 'unknown', 'candidates': [], 'probes': [], 'duration_ms': 5})
    with pytest.raises(TaskRejected, match='Q09: uncertified path'):
        ConstructNode().execute(ctx)
    assert json.loads((ctx.revision_dir / 'private/native_error_probe.json').read_text())['blocking']
    assert ctx.data['construction_validation']['native_error_probe']['blocking']


@pytest.mark.skipif(os.environ.get('SF_TEST_LIBREOFFICE') != '1', reason='Requires actual Docker LibreOffice')
@pytest.mark.parametrize('formula,should_pass', [
    ('=IF(TRUE,Table!A1,Table!B1)', True),
    ('=INDEX(Table!A1:B1,1,1)', True),
    ('=IFERROR(Table!B1,10)', False),
    ('=IFERROR(Table!B1-Table!C1,10)', False),
])
def test_real_LO_error_sensitivity_and_immutability(tmp_path, formula, should_pass):
    raw = cached_fixture(tmp_path / 'raw.xlsx', {'A1': formula})
    engine = LibreOfficeEngine(ROOT)
    goal = engine.recalculate(raw, tmp_path / 'goal.xlsx')
    before = digest(goal)
    result = run_probe(tmp_path, goal, engine, engine_metadata=engine.metadata())
    assert (not result['blocking']) == should_pass
    assert result['immutable_unchanged'] and digest(goal) == before
    if not should_pass:
        assert result['state'] == 'observed_required_D_change'
        assert any(probe['changed_values'] for probe in result['probes'])
    assert result['engine']['backend'] == 'libreoffice_uno_docker'
