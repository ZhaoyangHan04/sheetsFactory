"""Offline workbook/cache fixtures; no actual LO, model or qualification claims."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes import joint_controls as node
from sheets_factory.task_adapters.public_input_priority import canonical, ref
from sheets_factory.workbook import compare_workbooks


def cached_fixture(source, destination):
    """Evaluate only the small test grammar; this is not a workbook engine."""
    book = openpyxl.load_workbook(source, keep_links=False)
    cache = {}

    def evaluate(sheet, address):
        key = (sheet, address)
        if key in cache:
            return cache[key]
        value = book[sheet][address].value
        if isinstance(value, str) and value.startswith('='):
            expression = value[1:]
            equivalent = re.fullmatch(r'IF\(TRUE\(\),(.*),""\)', expression)
            if equivalent:
                expression = equivalent.group(1)
            if re.fullmatch(r'[A-Z]+[1-9][0-9]*', expression):
                value = evaluate(sheet, expression)
            else:
                value = int(expression)
        cache[key] = value
        return value

    for sheet in book:
        for cell in sheet._cells.values():
            if cell.data_type == 'f':
                evaluate(sheet.title, cell.coordinate)
    names = book.sheetnames[:]
    book.close()
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(source) as old, ZipFile(destination, 'w') as new:
        for item in old.infolist():
            raw = old.read(item.filename)
            matched = re.fullmatch(r'xl/worksheets/sheet([0-9]+)\.xml', item.filename)
            if matched:
                sheet = names[int(matched.group(1)) - 1]
                xml = ET.fromstring(raw)
                for cell in xml.findall('.//s:c', ns):
                    if cell.find('s:f', ns) is None:
                        continue
                    value = cell.find('s:v', ns)
                    if value is None:
                        value = ET.SubElement(cell, '{' + ns['s'] + '}v')
                    value.text = str(cache[(sheet, cell.attrib['r'])])
                    cell.attrib.pop('t', None)
                raw = ET.tostring(xml, encoding='utf-8')
            new.writestr(item, raw)
    return Path(destination)


class FixtureEngine:
    """Records offline substitutions; it never invokes an external process."""
    def __init__(self):
        self.calls = []
        self.fail_at = None
        self.mutate = None
        self.return_other = False

    def recalculate(self, source, output):
        self.calls.append((Path(source), Path(output)))
        if len(self.calls) == self.fail_at:
            raise RuntimeError('Declared offline engine failure')
        cached_fixture(source, output)
        if self.mutate:
            self.mutate(Path(source), Path(output))
        return source if self.return_other else output


def fixture_context(tmp_path, monkeypatch, *, masked=1, pure_masked=False, provider='composite_complete_financial_graph_v2'):
    directory = tmp_path / 'task'; private = directory / 'revisions/000/private'
    public = directory / 'revisions/000/public'
    private.mkdir(parents=True); public.mkdir()
    book = openpyxl.Workbook(); book.active.title = 'Finance'
    book.active['B1'] = 1; book.active['C1'] = 1
    edits = []
    for index in range(masked):
        address = 'A' + str(index + 1)
        book.active[address] = '=B1'
        edits.append({'sheet': 'Finance', 'cell': address, 'before': '=B1',
                      'after': '=C1' if pure_masked else '=IF(TRUE(),C1,"")'})
    address = 'A' + str(masked + 1); book.active[address] = '=3'
    edits.append({'sheet': 'Finance', 'cell': address, 'before': '=3', 'after': '=4'})
    raw_goal = tmp_path / 'raw_goal.xlsx'; book.save(raw_goal); book.close()
    goal = cached_fixture(raw_goal, private / 'goal.xlsx')
    book = openpyxl.load_workbook(goal)
    for edit in edits:
        book[edit['sheet']][edit['cell']] = edit['after']
    raw_input = tmp_path / 'raw_input.xlsx'; book.save(raw_input); book.close()
    source = cached_fixture(raw_input, public / 'input.xlsx')
    engine = FixtureEngine()
    ctx = TaskContext('offline', 'dbg-offline', 'debugging', goal, directory,
        {node.SETTING: node.setting()}, None, None, engine)
    ctx.data = {'input': source, 'goal': goal,
        'plan': {'edits': edits, 'family_adapter': {'id': provider}, 'public_rules': ['Offline public policy']},
        'delta': compare_workbooks(source, goal, goal)}
    ctx.save('joint_repair_certificate.json', {'activity_contract': node.JOINT_METHOD, 'offline_fixture': True})
    # Actual certificate validation has its own full-artifact tests. This explicit
    # fixture isolates normal actual-grade/candidate routing without inventing LO.
    calls = []
    def validate(certificate, actual_goal, actual_input, actual_edits, delta):
        assert certificate['offline_fixture'] is True
        assert actual_goal == goal and actual_input == source and actual_edits == edits
        calls.append(True)
        return {'complete_required_D_count': delta['expected_change_count']}
    monkeypatch.setattr(node, 'validate_joint_certificate', validate)
    return ctx, engine, calls


def read(ctx, name):
    return json.loads((ctx.revision_dir / 'private' / name).read_text())


@pytest.mark.parametrize('provider', ['composite_complete_financial_graph_v2', 'composite_complete_semantic_graph_v3'])
def test_actual_normal_grader_selects_first_observable_single_omission(tmp_path, monkeypatch, provider):
    ctx, engine, proof_calls = fixture_context(tmp_path, monkeypatch, provider=provider)
    original = deepcopy(ctx.data['plan']); binding = (ref(ctx.data['goal']), ref(ctx.data['input']))
    result = node.JointObservableControlsNode().execute(ctx)
    assert {name: value['reward'] for name, value in result['controls'].items()} == node.CONTROL_REWARDS
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['state'] == 'verified' and receipt['passed'] is True and proof_calls == [True]
    assert receipt['selected_plan_edit_index'] == 1
    assert [attempt['reward'] for attempt in receipt['attempts']] == [1, 0]
    assert [attempt['selected'] for attempt in receipt['attempts']] == [False, True]
    assert len(engine.calls) == receipt['actual_workbook_LO_started_count'] == receipt['actual_workbook_LO_completed_count'] == 4
    assert all(call['completed'] and call['started_at'] and call['finished_at'] for call in receipt['engine_calls'])
    assert ctx.data['plan'] == original and (ref(ctx.data['goal']), ref(ctx.data['input'])) == binding
    assert set(result['controls']) == set(node.CONTROL_REWARDS)
    assert compare_workbooks(ctx.data['input'], ctx.data['goal'], ctx.revision_dir / 'private/controls/missed_root.xlsx')['reward'] == 0
    assert receipt['individual_or_marginal_activity_claimed'] is False
    assert receipt['all_physical_edits_observable_claimed'] is False
    assert receipt['quality_recovery_difficulty_certified'] is False and 'root_impacts' not in result
    for index in (0, 1):
        assert json.loads(Path(receipt['attempts'][index]['comparison']['path']).read_text())['reward'] == [1, 0][index]
    assert ref(Path(receipt['attempt_receipt']['path'])) == receipt['attempt_receipt']


def test_default_eight_attempt_cap_fails_without_skipping_to_ninth(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch, masked=8)
    ctx.config[node.SETTING].pop('max_missed_root_attempts')
    with pytest.raises(TaskRejected, match='frozen attempt limit'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['state'] == 'failed' and receipt['selected_plan_edit_index'] is None
    assert receipt['max_missed_root_attempts'] == 8 and len(receipt['attempts']) == 8
    assert [r['plan_edit_index'] for r in receipt['attempts']] == list(range(8))
    assert all(r['reward'] == 1 and not r['selected'] for r in receipt['attempts'])
    assert len(engine.calls) == 10  # equivalent + eight real fixture omissions + extra
    actual = json.loads(Path(receipt['local_controls']['path']).read_text())
    assert {k: v['reward'] for k, v in actual.items()} == {**node.CONTROL_REWARDS, 'missed_root': 1}
    assert not (ctx.revision_dir / 'private/local_controls.json').exists()
    assert not (ctx.revision_dir / 'private/controls/missed_root.xlsx').exists()


def test_explicit_smaller_limit_is_not_silently_extended(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    ctx.config[node.SETTING] = node.setting(max_missed_root_attempts=1)
    with pytest.raises(TaskRejected, match='frozen attempt limit'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert len(engine.calls) == 3 and json.loads(Path(receipt['local_controls']['path']).read_text())['missed_root']['reward'] == 1


def test_equal_direct_reference_prefilter_does_not_spend_actual_attempt_limit(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch, masked=10, pure_masked=True)
    result = node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['prescreened_physical_edit_count'] == 11
    assert [r['plan_edit_index'] for r in receipt['skipped_candidates']] == list(range(10))
    assert all(r['state'] == 'skipped_equal_goal_reference' and not r['counterfactual_or_marginal_effect_proved']
               for r in receipt['skipped_candidates'])
    assert receipt['eligible_plan_edit_indices'] == [10] and receipt['selected_plan_edit_index'] == 10
    assert len(engine.calls) == 3 and result['controls']['missed_root']['reward'] == 0
    assert receipt['attempts'][0]['actual_attempt_index'] == 0


@pytest.mark.parametrize('formula,expected', [
    ("='Lease O''Brien'!$C$10", ("Lease O'Brien", 'C10')),
    ('=Finance!A1', ('Finance', 'A1')), ('=$C$10', ('Local', 'C10')),
    ('=SUM(A1)', None), ('=A1+A2', None), ('=A1:A2', None),
    ("='[external.xlsx]Finance'!A1", None), ("='First:Last'!A1", None),
    ('=XFE1', None), ('=A1048577', None), ('=named_reference', None)])
def test_prefilter_only_accepts_local_single_cell_references(formula, expected):
    assert node._single_reference(formula, 'Local') == expected


@pytest.mark.parametrize('left,right', [(True, 1), (0, None), ('', ''), ('same', 'different'),
    (datetime(2030, 1, 1), 47484)])
def test_prefilter_does_not_confuse_types_empty_or_unknown_values(tmp_path, left, right):
    path = tmp_path / 'typed.xlsx'; book = openpyxl.Workbook(); book.active.title = 'Finance'
    book.active['B1'] = left; book.active['C1'] = right; book.save(path); book.close()
    edits = [{'sheet': 'Finance', 'cell': 'A1', 'before': '=B1', 'after': '=C1'}]
    assert node.prescreen_equal_goal_references(path, edits) == {}


def test_all_prefiltered_candidates_do_not_create_a_fake_five_control_receipt(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch, pure_masked=True)
    ctx.data['plan']['edits'].pop()  # All remaining candidates are the equal-reference form.
    with pytest.raises(TaskRejected, match='no unfiltered single-omission candidate'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['state'] == 'failed' and len(receipt['skipped_candidates']) == 1
    assert receipt['selected_plan_edit_index'] is None and engine.calls == []
    assert not (ctx.revision_dir / 'private/local_controls.json').exists()


@pytest.mark.parametrize('maximum', [True, False, 0, 9, -1, 1.0, None])
def test_attempt_budget_is_strict_and_frozen(maximum):
    with pytest.raises(ValueError, match='integer from 1 through 8'):
        node.setting(max_missed_root_attempts=maximum)


@pytest.mark.parametrize('defect', ['bool_version', 'unknown_method', 'wrong_implementation', 'unknown_key', 'wrong_upstream'])
def test_malformed_or_changed_optin_fails_before_any_calculation(tmp_path, monkeypatch, defect):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    value = ctx.config[node.SETTING]
    if defect == 'bool_version': value['version'] = True
    elif defect == 'unknown_method': value['method'] = 'assume_all_roots_observable'
    elif defect == 'wrong_implementation': value['implementation']['sha256'] = '0' * 64
    elif defect == 'unknown_key': value['fallback'] = True
    else: value['upstream_controls_sha256'] = '0' * 64
    with pytest.raises(ValueError): node.JointObservableControlsNode().execute(ctx)
    assert engine.calls == []


@pytest.mark.parametrize('mode,optin', [('financial_modeling', None), ('financial_modeling', False), ('debugging', None)])
def test_fm_and_nonoptin_delegate_the_original_node(monkeypatch, mode, optin):
    observed = []
    monkeypatch.setattr(node.construction.ControlsNode, 'execute', lambda self, ctx: observed.append(ctx) or {'legacy': True})
    ctx = SimpleNamespace(mode=mode, config={node.SETTING: optin})
    assert node.JointObservableControlsNode().execute(ctx) == {'legacy': True} and observed == [ctx]


def test_engine_error_is_retained_and_never_skipped_for_another_candidate(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    engine.fail_at = 2
    with pytest.raises(RuntimeError, match='Declared offline engine failure'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert len(engine.calls) == 2 and len(receipt['attempts']) == 1
    assert receipt['state'] == 'failed' and receipt['engine_calls'][-1]['completed'] is False
    assert receipt['engine_calls'][-1]['error_type'] == 'RuntimeError'
    assert receipt['actual_workbook_LO_started_count'] == 2 and receipt['actual_workbook_LO_completed_count'] == 1
    assert receipt['selected_plan_edit_index'] is None


def test_same_revision_retry_retains_failed_attempt_and_publishes_only_successful_controls(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch); engine.fail_at = 2
    with pytest.raises(RuntimeError): node.JointObservableControlsNode().execute(ctx)
    failed = read(ctx, 'joint_control_selection.json'); failed_ref = failed['attempt_receipt']
    failed_bytes = Path(failed_ref['path']).read_bytes()
    assert not (ctx.revision_dir / 'private/local_controls.json').exists()
    assert not (ctx.revision_dir / 'private/controls').exists()
    engine.fail_at = None
    result = node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['passed'] is True and receipt['attempt_id'] != failed['attempt_id']
    assert receipt['prior_failed_attempts'] == [failed_ref] and Path(failed_ref['path']).read_bytes() == failed_bytes
    assert len(engine.calls) == 6 and receipt['actual_workbook_LO_completed_count'] == 4
    assert result['controls'] == read(ctx, 'local_controls.json')
    successful_bytes = Path(receipt['attempt_receipt']['path']).read_bytes()
    with pytest.raises(ValueError, match='must not overwrite'):
        node.JointObservableControlsNode().execute(ctx)
    assert len(engine.calls) == 6 and Path(receipt['attempt_receipt']['path']).read_bytes() == successful_bytes


def test_retry_rejects_tampered_prior_failed_attempt_instead_of_losing_its_history(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch); engine.fail_at = 2
    with pytest.raises(RuntimeError): node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    Path(receipt['attempt_receipt']['path']).write_text('{}')
    with pytest.raises(ValueError, match='Changed public-priority artifact'):
        node.JointObservableControlsNode().execute(ctx)
    assert len(engine.calls) == 2


def test_wrong_runtime_output_path_is_not_accepted(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch); engine.return_other = True
    with pytest.raises(ValueError, match='different output artifact'):
        node.JointObservableControlsNode().execute(ctx)
    assert read(ctx, 'joint_control_selection.json')['actual_workbook_LO_completed_count'] == 0


@pytest.mark.parametrize('bad', [{'reward': 0, 'error': 'BrokenWorkbook'}, {'reward': 0, 'structure_ok': False}, {'reward': False, 'structure_ok': True}])
def test_broken_grade_cannot_supply_a_fake_negative_control(tmp_path, monkeypatch, bad):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    original = node.compare_workbooks
    def compare(source, goal, candidate):
        result = original(source, goal, candidate)
        if Path(candidate).name == 'recalculated.xlsx': result.update(bad)
        return result
    monkeypatch.setattr(node, 'compare_workbooks', compare)
    with pytest.raises(ValueError, match='normal, structure-preserving grade'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    assert receipt['selected_plan_edit_index'] is None and len(receipt['attempts']) == 1


def test_unapproved_other_literal_change_is_not_a_single_omission(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    def corrupt(source, output):
        if output.name != 'recalculated.xlsx': return
        book = openpyxl.load_workbook(output); book['Finance']['B1'] = 999
        raw = output.with_name('corrupt_raw.xlsx'); book.save(raw); book.close(); cached_fixture(raw, output)
    engine.mutate = corrupt
    with pytest.raises(ValueError, match='unapproved definition or typed literal'):
        node.JointObservableControlsNode().execute(ctx)
    assert read(ctx, 'joint_control_selection.json')['selected_plan_edit_index'] is None


def test_no_existing_control_receipt_is_overwritten(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    original = {'old': 'immutable evidence'}; ctx.save('local_controls.json', original)
    with pytest.raises(ValueError, match='must not overwrite'):
        node.JointObservableControlsNode().execute(ctx)
    assert read(ctx, 'local_controls.json') == original and engine.calls == []


def test_wrong_contract_or_missing_real_joint_proof_fails_closed(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    ctx.save('joint_repair_certificate.json', {'activity_contract': 'assume_activity'})
    with pytest.raises(ValueError, match='actual joint-workbook construction certificate'):
        node.JointObservableControlsNode().execute(ctx)
    assert engine.calls == []


def test_actual_certificate_validator_is_called_not_just_passed_flag(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    from sheets_factory.pipelines.joint_repair_activity import validate_joint_certificate
    monkeypatch.setattr(node, 'validate_joint_certificate', validate_joint_certificate)
    with pytest.raises(ValueError, match='proof is incomplete'):
        node.JointObservableControlsNode().execute(ctx)
    assert engine.calls == []


def test_goal_context_after_formula_is_asserted_before_runtime(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    ctx.data['plan']['edits'][0]['before'] = '=77'
    with pytest.raises(ValueError, match='before formula differs'):
        node.JointObservableControlsNode().execute(ctx)
    assert engine.calls == []


def test_bad_positive_control_is_kept_even_after_a_real_negative_is_found(tmp_path, monkeypatch):
    ctx, engine, _ = fixture_context(tmp_path, monkeypatch)
    original = node.compare_workbooks
    def compare(source, goal, candidate):
        result = original(source, goal, candidate)
        if Path(candidate).name == 'equivalent.xlsx': result['reward'] = 0
        return result
    monkeypatch.setattr(node, 'compare_workbooks', compare)
    with pytest.raises(TaskRejected, match='controls did not match'):
        node.JointObservableControlsNode().execute(ctx)
    receipt = read(ctx, 'joint_control_selection.json')
    result = json.loads(Path(receipt['local_controls']['path']).read_text())
    assert result['equivalent']['reward'] == 0 and result['missed_root']['reward'] == 0
    assert len(engine.calls) == 4 and read(ctx, 'joint_control_selection.json')['passed'] is False
