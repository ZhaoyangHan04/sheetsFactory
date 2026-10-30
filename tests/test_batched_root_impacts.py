"""Batch proofs retain actual context and reject all partial/uncertain evidence."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import types

import openpyxl
import pytest

from sheets_factory.checkers.batched_roots import prove_batched_root_impacts, validate_root_impact_batches
from sheets_factory.nodes.construction import construction_contract
from sheets_factory.nodes import construction as construction_module
from sheets_factory.core.node import TaskRejected
from test_separated_roots import save_cached
from test_construction_template_and_root_proof_hooks import construction_fixture


class ArithmeticFixtureEngine:
    """Evaluate only small arithmetic fixtures; this is not an Excel backend."""
    def __init__(self):
        self.calls = []

    def recalculate(self, source, destination):
        self.calls.append((Path(source), Path(destination)))
        book = openpyxl.load_workbook(source)
        cache, active = {}, set()

        def cell_value(sheet, address):
            key = sheet, address
            if key in cache:
                return cache[key]
            value = book[sheet][address].value
            if not isinstance(value, str) or not value.startswith('='):
                return value or 0
            if key in active:
                raise ValueError('cycle in fixture')
            active.add(key)
            def evaluate(node):
                if isinstance(node, ast.Constant):
                    return node.value
                if isinstance(node, ast.Name):
                    return cell_value(sheet, node.id)
                if isinstance(node, ast.BinOp):
                    left, right = evaluate(node.left), evaluate(node.right)
                    if isinstance(node.op, ast.Add): return left + right
                    if isinstance(node.op, ast.Sub): return left - right
                    if isinstance(node.op, ast.Mult): return left * right
                    if isinstance(node.op, ast.Div): return left / right
                raise ValueError('unsupported fixture arithmetic')
            result = evaluate(ast.parse(value[1:], mode='eval').body)
            active.remove(key)
            cache[key] = result
            return result
        for sheet in book:
            for cell in list(sheet._cells.values()):
                if cell.data_type == 'f':
                    cell_value(sheet.title, cell.coordinate)
        save_cached(book, destination, cache)
        book.close()
        return Path(destination)


@pytest.fixture
def case(tmp_path):
    book = openpyxl.Workbook()
    book.active.title = 'Entity1'
    book.create_sheet('Entity2')
    for i, sheet in enumerate(book, 1):
        sheet['A1'], sheet['C1'], sheet['C2'] = 10 * i, '=A1*2', '=C1+1'
    raw = tmp_path / 'raw.xlsx'; book.save(raw); book.close()
    engine = ArithmeticFixtureEngine()
    goal = engine.recalculate(raw, tmp_path / 'goal.xlsx')
    edits = [dict(sheet='Entity1', cell='C1', before='=A1*2', after='=A1*3'),
             dict(sheet='Entity1', cell='C2', before='=C1+1', after='=C1-1'),
             dict(sheet='Entity2', cell='C1', before='=A1*2', after='=A1*4'),
             dict(sheet='Entity2', cell='C2', before='=C1+1', after='=C1-2')]
    return dict(directory=tmp_path, goal=goal, edits=edits, batches=[[0, 2], [1, 3]], engine=engine)


def prove(case, **overrides):
    book = openpyxl.load_workbook(case['goal'])
    for edit in case['edits']:
        book[edit['sheet']][edit['cell']] = edit['after']
    raw = case['directory'] / 'combined_raw.xlsx'; book.save(raw); book.close()
    combined = case['engine'].recalculate(raw, case['directory'] / 'combined.xlsx')
    case['engine'].calls.clear()
    arguments = dict(goal=case['goal'], combined_input=combined, edits=case['edits'],
        batches=case['batches'], engine=case['engine'], directory=case['directory'] / 'proof')
    arguments.update(overrides)
    before = case['goal'].read_bytes(), combined.read_bytes()
    result = prove_batched_root_impacts(**arguments)
    assert before == (case['goal'].read_bytes(), combined.read_bytes())
    return result


def rejected(result):
    assert result['passed'] is False and result['blocking'] is True
    assert result['root_impacts'] == []


def test_interacting_entity_chains_use_two_actual_calls_per_independent_batch(case):
    result = prove(case)
    assert result['passed'] and not result['blocking']
    assert len(case['engine'].calls) == result['actual_batch_LO_execution_count'] == 4
    assert result['individual_root_LO_executions'] == result['individual_marginal_LO_executions'] == 0
    assert result['complete_per_root_changed_sets_claimed'] is False
    assert [item['root_index'] for item in result['root_impacts']] == [0, 1, 2, 3]
    assert all(item['expected_change_count'] == 1 for item in result['root_impacts'])
    assert all(batch['state'] == 'proven' for batch in result['batches'])


def test_marginal_proof_restores_from_full_mutation_with_reversed_assertions(case):
    result = prove(case)
    marginal = result['root_impacts'][1]['combined_marginal']
    assert marginal['base'] == 'full_combined_mutation' and marginal['edits_reversed'] is True
    assert marginal['evidence']['goal_value'] == ['number', '29.00']
    assert marginal['evidence']['combined_value'] == ['number', '31.00']
    raw = openpyxl.load_workbook(case['directory'] / 'proof/batch_001_combined_marginal_raw.xlsx')
    assert raw['Entity1']['C1'].value == '=A1*3'  # Other batch remains broken.
    assert raw['Entity1']['C2'].value == '=C1+1'
    assert result['batches'][1]['combined_marginal']['edits_reversed'] is True


@pytest.mark.parametrize('batches', [None, [], [[]], [[0, 1, 2]], [[0, 1], [1, 2, 3]],
    [[0, 1, 2, 3, 4]], [[-1, 0, 1, 2, 3]], [[True, 0, 2, 3]], [(0, 1, 2, 3)]])
def test_invalid_partitions_reject_before_any_engine_call(case, batches):
    result = prove(case, batches=batches)
    rejected(result)
    assert case['engine'].calls == []


def test_batch_limit_is_explicit_and_cannot_be_bypassed(case):
    result = prove(case, max_batches=1)
    rejected(result)
    assert case['engine'].calls == []


def test_dependent_roots_in_a_batch_fail_without_fallback(case):
    result = prove(case, batches=[[0, 1], [2, 3]])
    rejected(result)
    assert len(case['engine'].calls) == 1
    assert result['batches'][0]['individual']['passed'] is False
    assert 'separation/value proof failed' in result['reason']


def test_an_individually_inactive_root_rejects_all_partial_proofs(case):
    case['edits'][1]['after'] = '=C1+1.001'
    result = prove(case)
    rejected(result)
    assert result['batches'][0]['state'] == 'proven'
    assert result['batches'][1]['individual']['passed'] is False


def test_root_inactive_only_in_full_combined_context_rejects(case):
    case['edits'][1]['after'] = '=C1+1+(C1-30)'
    result = prove(case)
    rejected(result)
    assert result['batches'][1]['individual']['passed'] is True
    assert result['batches'][1]['combined_marginal']['passed'] is False
    assert len(case['engine'].calls) == 4


def test_combined_cancellation_is_allowed_when_both_real_root_effects_exist(case):
    case['edits'][0]['after'] = '=A1*2+2'
    result = prove(case)
    assert result['passed']
    # Full combined C2=21 equals its original value21, but changing its own
    # formula alone and restoring it in context each has an observable effect.
    assert result['root_impacts'][1]['evidence']['goal_value'] == ['number', '21.00']
    assert result['root_impacts'][1]['evidence']['combined_value'] == ['number', '19.00']
    assert result['root_impacts'][1]['combined_marginal']['evidence']['goal_value'] == ['number', '21.00']
    assert result['root_impacts'][1]['combined_marginal']['evidence']['combined_value'] == ['number', '23.00']


def test_engine_failure_is_honest_execution_error_not_a_proven_impact(case):
    class FailedEngine:
        def recalculate(self, source, destination):
            raise RuntimeError('fixture engine unavailable')
    result = prove(case, engine=FailedEngine())
    rejected(result)
    assert result['state'] == 'execution_error'
    assert result['actual_batch_LO_execution_count'] == 0
    assert 'engine unavailable' in result['reason']


def test_missing_partition_has_no_implicit_autobatching_or_default_mode_change():
    assert construction_contract('debugging', {})['root_impact_validation'] == 'strict'
    assert construction_contract('debugging', {'construction': {'root_impact_validation': 'separated_roots'}})['root_impact_validation'] == 'separated_roots'
    selected = construction_contract('debugging', {'construction': {'root_impact_validation': 'batched_separated_roots', 'max_root_impact_batches': 12}})
    assert selected['max_root_impact_batches'] == 12
    with pytest.raises(ValueError):
        construction_contract('debugging', {'construction': {'max_root_impact_batches': True}})
    assert validate_root_impact_batches([[1], [0]], 2) == [[1], [0]]


@pytest.fixture
def batch_construction_fixture(construction_fixture, monkeypatch):
    context, observed = construction_fixture
    context.config['construction']['root_impact_validation'] = 'batched_separated_roots'
    context.data['plan']['root_impact_batches'] = [[0, 3], [1, 4], [2, 5]]
    certificate = deepcopy(observed['certificate'])
    certificate.update(proof_method='batched_separated_roots_with_actual_LO_values',
                       batch_count=3, actual_batch_LO_execution_count=6)
    for item in certificate['root_impacts']:
        item['proof_method'] = 'batched_separation_and_actual_LO_values'
        item['combined_marginal'].update(edits_reversed=True, base='full_combined_mutation')
    observed['batch_certificate'] = certificate
    observed['batch_calls'] = []
    fake = types.ModuleType('sheets_factory.checkers.batched_roots')
    def prove(**kwargs):
        observed['batch_calls'].append(kwargs)
        return deepcopy(observed['batch_certificate'])
    fake.prove_batched_root_impacts = prove
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    return context, observed


def test_construct_routes_explicit_batches_and_records_actual_method(batch_construction_fixture):
    context, observed = batch_construction_fixture
    result = construction_module.ConstructNode().execute(context)
    assert observed['calculations'] == 1  # Explicit helper double owns its calls.
    assert len(observed['batch_calls']) == 1 and not observed['certificate_calls']
    call = observed['batch_calls'][0]
    assert call['batches'] == context.data['plan']['root_impact_batches']
    assert call['goal'] == result['goal'] and call['combined_input'] == result['input']
    assert call['max_dependency_cells'] == 500000 and call['per_formula_reference_cells'] == 50000
    assert (context.revision_dir / 'private/batched_roots_certificate.json').is_file()
    method = result['construction_validation']['root_impact_validation']
    assert method['method'] == 'batched_separated_roots'
    assert method['actual_batch_LO_execution_count'] == 6
    assert method['individual_LO_executions'] is method['marginal_LO_executions'] is False


def test_construct_rejected_batch_proof_never_falls_back(batch_construction_fixture):
    context, observed = batch_construction_fixture
    observed['batch_certificate'].update(passed=False, blocking=True, state='rejected', reason='root interference')
    with pytest.raises(TaskRejected, match='batched root-impact proof rejected'):
        construction_module.ConstructNode().execute(context)
    assert observed['calculations'] == 1
    assert (context.revision_dir / 'private/batched_roots_certificate.json').is_file()


def test_construct_partial_or_wrong_direction_batch_proof_rejects(batch_construction_fixture):
    context, observed = batch_construction_fixture
    observed['batch_certificate']['root_impacts'][0]['combined_marginal']['edits_reversed'] = False
    with pytest.raises(TaskRejected, match='does not prove every declared root'):
        construction_module.ConstructNode().execute(context)
    assert observed['calculations'] == 1


def test_construct_engine_failure_keeps_execution_error_class(batch_construction_fixture):
    context, observed = batch_construction_fixture
    observed['batch_certificate'].update(passed=False, blocking=True, state='execution_error', reason='LO fixture failure')
    with pytest.raises(RuntimeError, match='recalculation failed'):
        construction_module.ConstructNode().execute(context)
    assert observed['calculations'] == 1
