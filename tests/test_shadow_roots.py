"""Proof logic with a clearly labelled offline cache fixture, never real LO."""
from copy import deepcopy
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries, get_column_letter
import pytest

from sheets_factory.checkers.shadow_roots import prove_shadow_root_impacts, qualify_scalar_shadow

_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _rewrite(path, transform):
    with ZipFile(path) as archive:
        files = [(item, archive.read(item.filename)) for item in archive.infolist()]
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for item, payload in files:
            archive.writestr(item, transform(item.filename, payload))


def _formula(path, sheet_index, address, text):
    def transform(name, payload):
        if name != f'xl/worksheets/sheet{sheet_index}.xml':
            return payload
        tree = ET.fromstring(payload)
        cell = next(cell for cell in tree.iter(_NS + 'c') if cell.attrib['r'] == address)
        child = cell.find(_NS + 'f')
        if child is None:
            child = ET.SubElement(cell, _NS + 'f')
        child.text = text[1:]
        return ET.tostring(tree)
    _rewrite(path, transform)


class FixtureEngine:
    """Small deterministic arithmetic fixture, not an Excel or financial oracle."""
    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault

    def metadata(self):
        return {'backend': 'libreoffice_uno_docker', 'network': 'none',
                'image_id': 'sha256:' + 'a' * 64, 'version': 'OFFLINE TEST FIXTURE ONLY'}

    def recalculate(self, raw, output):
        self.calls.append((Path(raw), Path(output)))
        if self.fault == 'second_execution' and len(self.calls) == 2:
            raise RuntimeError('Explicit fixture second execution failure')
        book = openpyxl.load_workbook(raw)
        memo, active = {}, set()
        def flat(values):
            for value in values:
                if isinstance(value, list):
                    yield from flat(value)
                else:
                    yield value
        def reference(sheet, expression):
            sn, address = expression.rsplit('!', 1) if '!' in expression else (sheet, expression)
            if sn.startswith("'"):
                sn = sn[1:-1].replace("''", "'")
            if ':' not in address:
                return value(sn, address)
            left, top, right, bottom = range_boundaries(address)
            return [value(sn, get_column_letter(col) + str(row))
                    for row in range(top, bottom + 1) for col in range(left, right + 1)]
        def value(sheet, address):
            key = sheet, address.replace('$', '')
            if key in memo:
                return memo[key]
            if key in active:
                raise ValueError('Offline fixture cycle')
            active.add(key)
            cell = book[sheet][key[1]]
            if cell.data_type != 'f':
                result = cell.value if cell.value is not None else 0
            else:
                expression = ''
                for token in Tokenizer(cell.value).items:
                    if token.type == 'OPERAND' and token.subtype == 'RANGE':
                        expression += repr(reference(sheet, token.value))
                    elif token.type == 'FUNC' and token.subtype == 'OPEN':
                        expression += token.value.lower()
                    elif token.type == 'SEP':
                        expression += ','
                    else:
                        expression += token.value
                result = eval(expression, {'__builtins__': {}}, {
                    'sum': lambda *args: sum(flat(args)), 'min': min, 'max': max, 'round': round})
            active.remove(key)
            memo[key] = result
            return result
        names = book.sheetnames
        for sheet in book:
            for cell in list(sheet._cells.values()):
                if cell.data_type == 'f':
                    value(sheet.title, cell.coordinate)
        if self.fault == 'subcent_business' and 'individual_shadow' in Path(output).name:
            memo[('Model', 'A1')] += .001
        book.close()
        with ZipFile(raw) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                match = re.fullmatch(r'xl/worksheets/sheet([0-9]+)\.xml', item.filename)
                if match:
                    sn = names[int(match.group(1)) - 1]
                    tree = ET.fromstring(payload)
                    for cell in tree.iter(_NS + 'c'):
                        key = sn, cell.attrib['r']
                        if cell.find(_NS + 'f') is None or key not in memo:
                            continue
                        cached = cell.find(_NS + 'v')
                        if cached is None:
                            cached = ET.SubElement(cell, _NS + 'v')
                        cached.text = str(memo[key])
                        cell.attrib.pop('t', None)
                    payload = ET.tostring(tree)
                target.writestr(item, payload)
        if self.fault == 'shadow_formula' and 'individual_shadow' in Path(output).name:
            _formula(output, len(names), 'B2', '=99')
        if callable(self.fault):
            self.fault(len(self.calls), raw, output)
        return output


def fixture(tmp_path, *, cancellation=False, definitions=None, mutations=None):
    original = definitions or {'A1': '=Inputs!B1', 'B1': '=A1*2', 'C1': '=Inputs!B1*3'}
    changed = mutations or {'A1': '=Inputs!B1*2',
        'B1': '=A1+Inputs!B1*' + ('2' if cancellation else '3'), 'C1': '=Inputs!B1*4'}
    book = openpyxl.Workbook()
    book.active.title = 'Model'
    book.create_sheet('Inputs')['B1'] = 10
    for address, formula in original.items():
        book['Model'][address] = formula
    raw, goal, combined = tmp_path / 'original_raw.xlsx', tmp_path / 'goal.xlsx', tmp_path / 'combined.xlsx'
    book.save(raw)
    book.close()
    FixtureEngine().recalculate(raw, goal)
    book = openpyxl.load_workbook(goal)
    for address, formula in changed.items():
        book['Model'][address] = formula
    raw = tmp_path / 'combined_raw.xlsx'
    book.save(raw)
    book.close()
    FixtureEngine().recalculate(raw, combined)
    edits = [{'sheet': 'Model', 'cell': address, 'before': formula,
              'after': changed[address], 'mechanism': 'explicit_test_fixture'}
             for address, formula in original.items()]
    return goal, combined, edits


def prove(tmp_path, paths, engine=None, **kwargs):
    goal, combined, edits = paths
    return prove_shadow_root_impacts(goal=goal, combined_input=combined, edits=edits,
        engine=engine or FixtureEngine(), directory=tmp_path / 'proof', **kwargs)


def test_two_actual_contexts_prove_chain_roots_without_individual_execution_claims(tmp_path):
    paths = fixture(tmp_path)
    original_bytes = [path.read_bytes() for path in paths[:2]]
    edits = deepcopy(paths[2])
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is True and result['blocking'] is False
    assert result['state'] == 'proven' and result['root_count'] == 3
    assert len(engine.calls) == result['actual_LO_execution_count'] == 2
    assert result['actual_LO_started_count'] == 2
    assert result['individual_root_LO_executions'] == result['individual_marginal_LO_executions'] == 0
    assert result['union_graph']['root_dependencies_on_other_roots_allowed'] is True
    assert result['union_graph']['all_ancestor_functions_pure_and_position_independent'] is True
    assert result['complete_per_root_changed_sets_claimed'] is False
    assert result['business_correctness_certificate'] is result['difficulty_claimed'] is False
    check = result['root_checks'][1]
    assert check['goal_normalized_value'] == ['number', '20.00']
    assert check['after_in_original_parents']['normalized'] == ['number', '40.00']
    assert check['combined_normalized_value'] == ['number', '50.00']
    assert check['before_in_combined_parents']['normalized'] == ['number', '40.00']
    assert all(impact['expected_change_count'] == impact['combined_marginal']['expected_change_count'] == 1
               for impact in result['root_impacts'])
    assert paths[2] == edits
    assert [path.read_bytes() for path in paths[:2]] == original_bytes
    assert all(context['all_business_exact_typed_values_unchanged'] for context in result['contexts'])
    for path in paths[:2]:
        book = openpyxl.load_workbook(path)
        assert book.sheetnames == ['Model', 'Inputs']
        book.close()
    assert (tmp_path / 'proof/shadow_roots_certificate.json').is_file()


def test_combined_cancellation_rejects_despite_goal_and_combined_root_difference(tmp_path):
    result = prove(tmp_path, fixture(tmp_path, cancellation=True))
    assert result['passed'] is False and result['root_impacts'] == []
    assert result['actual_LO_execution_count'] == 2
    check = result['root_checks'][1]
    assert check['goal_normalized_value'] != check['combined_normalized_value']
    assert check['individual_active'] is True and check['combined_marginal_active'] is False


def test_subcent_only_root_change_does_not_count_as_graded_activity(tmp_path):
    paths = fixture(tmp_path, definitions={'A1': '=Inputs!B1'}, mutations={'A1': '=Inputs!B1+.001'})
    result = prove(tmp_path, paths)
    assert result['passed'] is False and result['root_impacts'] == []
    assert not result['root_checks'][0]['individual_active']


def test_union_cycle_is_rejected_even_when_each_endpoint_graph_is_acyclic(tmp_path):
    paths = fixture(tmp_path, definitions={'A1': '=B1', 'B1': '=Inputs!B1'},
                    mutations={'A1': '=Inputs!B1', 'B1': '=A1'})
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and 'UNION graph' in result['reason']
    assert not engine.calls


@pytest.mark.parametrize('formula', ['=ROW()', '=COLUMN(Inputs!B1)', '=NOW()',
    '=INDIRECT("B2")', '=OFFSET(B2,0,0)', '=UNKNOWN(B2)'])
def test_positional_volatile_dynamic_and_unknown_ancestor_functions_fail_before_execution(tmp_path, formula):
    paths = fixture(tmp_path)
    for path in paths[:2]:
        _formula(path, 2, 'B1', formula)
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and not engine.calls
    assert result['root_impacts'] == []


@pytest.mark.parametrize('formula', ['=A1:A10', '=ROUND(A1:A10,2)', '=SUM(A1:A10*2)',
    '=SUMIF(A1:A10,B1:B10,C1:C10)', '=INDEX(A1:A10,0)', '=CHOOSE(1,A1:A10,B1:B10)'])
def test_implicit_intersection_and_unproved_reference_returns_cannot_be_shadowed(formula):
    with pytest.raises(ValueError):
        qualify_scalar_shadow(formula, 'Ledger')


@pytest.mark.parametrize('formula', ['=SUM(A1:A10)', '=SUM(A1:A10,B1)',
    '=SUMIF(A1:A10,B1,C1:C10)', '=SUMIFS(A1:A10,B1:B10,C1)',
    '=SUMPRODUCT((A1:A10>B1)*C1:C10)', '=NPV(B1,C1:C10)',
    '=XIRR(B1:B10,C1:C10)', '=VLOOKUP(B1,A1:C10,2,FALSE)'])
def test_scalar_reducers_explicit_array_context_and_lookup_roles_are_supported(formula):
    qualified = qualify_scalar_shadow(formula, 'Ledger')
    assert "'Ledger'!" in qualified


def test_scalar_shadow_keeps_strings_absolute_anchors_and_quoted_sheet_names():
    result = qualify_scalar_shadow('=IF($A1="A1",SUM(B2:$C$4),\'Other Sheet\'!D5)', "Owner's Ledger")
    assert result == '=IF(\'Owner\'\'s Ledger\'!$A1="A1",SUM(\'Owner\'\'s Ledger\'!B2:$C$4),\'Other Sheet\'!D5)'


@pytest.mark.parametrize('field', ['before', 'after'])
def test_exact_formula_assertions_bind_both_contexts_before_engine_calls(tmp_path, field):
    paths = fixture(tmp_path)
    paths[2][0][field] = '=Inputs!B1+7'
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and field + ' formula assertion' in result['reason']
    assert not engine.calls


def test_hidden_nonroot_formula_change_is_rejected_before_execution(tmp_path):
    paths = fixture(tmp_path)
    _formula(paths[1], 2, 'B1', '=10')
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and 'non-root formula or literal' in result['reason']
    assert not engine.calls


def test_subcent_business_change_on_scratch_addition_is_not_hidden_by_cent_rounding(tmp_path):
    engine = FixtureEngine('subcent_business')
    result = prove(tmp_path, fixture(tmp_path), engine)
    assert not result['passed'] and 'exact typed business-sheet' in result['reason']
    assert result['business_value_changes']['cells'] == ['Model!A1']
    assert len(engine.calls) == 1 and result['root_impacts'] == []


def test_actual_shadow_formula_must_match_the_asserted_counterfactual(tmp_path):
    result = prove(tmp_path, fixture(tmp_path), FixtureEngine('shadow_formula'))
    assert not result['passed'] and 'Actual shadow formula' in result['reason']
    assert result['root_impacts'] == []


def test_failed_second_actual_execution_is_retained_and_never_returns_partial_proof(tmp_path):
    result = prove(tmp_path, fixture(tmp_path), FixtureEngine('second_execution'))
    assert result['state'] == 'execution_error' and result['root_impacts'] == []
    assert result['actual_LO_started_count'] == 2 and result['actual_LO_execution_count'] == 1
    assert result['engine_calls'][0]['actual_execution_completed'] is True
    assert result['engine_calls'][1]['actual_execution_completed'] is False
    assert Path(result['engine_calls'][1]['raw_path']).is_file()


def test_context_hash_mutation_during_execution_fails_closed(tmp_path):
    paths = fixture(tmp_path)
    def change_context(index, raw, output):
        if index == 1:
            with paths[0].open('ab') as stream:
                stream.write(b'context modified')
    result = prove(tmp_path, paths, FixtureEngine(change_context))
    assert not result['passed'] and 'Context workbook changed' in result['reason']
    assert result['actual_LO_execution_count'] == 1


def test_edit_plan_mutation_during_execution_fails_closed(tmp_path):
    paths = fixture(tmp_path)
    def change_plan(index, raw, output):
        if index == 1:
            paths[2][0]['mechanism'] = 'changed while proving'
    result = prove(tmp_path, paths, FixtureEngine(change_plan))
    assert not result['passed'] and 'Caller edit assertions changed' in result['reason']
    assert result['root_impacts'] == []


def test_fresh_directory_and_dependency_frontier_are_strict(tmp_path):
    paths = fixture(tmp_path)
    directory = tmp_path / 'exists'
    directory.mkdir()
    (directory / 'marker').write_text('keep')
    with pytest.raises(FileExistsError):
        prove_shadow_root_impacts(goal=paths[0], combined_input=paths[1], edits=paths[2],
            engine=FixtureEngine(), directory=directory)
    assert (directory / 'marker').read_text() == 'keep'
    result = prove(tmp_path, paths, max_dependency_cells=1)
    assert not result['passed'] and 'frontier' in result['reason']
    assert result['actual_LO_execution_count'] == 0


@pytest.mark.parametrize('definition', ["'[external.xlsx]Data'!$B$1", 'OFFSET(Inputs!$B$1,0,0)'])
def test_external_or_dynamic_defined_name_in_ancestry_is_rejected(tmp_path, definition):
    paths = fixture(tmp_path)
    for path in paths[:2]:
        _formula(path, 2, 'B1', '=UnsafeName')
        def transform(name, payload):
            if name != 'xl/workbook.xml':
                return payload
            tree = ET.fromstring(payload)
            names = tree.find(_NS + 'definedNames')
            if names is None:
                names = ET.SubElement(tree, _NS + 'definedNames')
            ET.SubElement(names, _NS + 'definedName', {'name': 'UnsafeName'}).text = definition
            return ET.tostring(tree)
        _rewrite(path, transform)
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert not result['passed'] and not engine.calls
    assert 'Unresolved' in result['reason']


def test_many_dependent_roots_still_use_two_context_replays_and_iterative_graph_walk(tmp_path):
    count = 1000
    original = {'A1': '=Inputs!B1'}
    mutated = {'A1': '=Inputs!B1+1'}
    for index in range(2, count + 1):
        original['A' + str(index)] = '=A' + str(index - 1) + '+1'
        mutated['A' + str(index)] = '=A' + str(index - 1) + '+2'
    paths = fixture(tmp_path, definitions=original, mutations=mutated)
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert result['passed'] is True and len(result['root_impacts']) == count
    assert result['actual_LO_execution_count'] == len(engine.calls) == 2
    assert result['union_graph']['closure_cells'] == count + 1
    assert result['root_checks'][-1]['individual_active'] is True
    assert result['root_checks'][-1]['combined_marginal_active'] is True


@pytest.mark.parametrize('change', ['date', 'visibility', 'defined_name', 'epoch'])
def test_nonfinancial_dates_and_hidden_context_structure_are_not_ignored(tmp_path, change):
    paths = fixture(tmp_path)
    target = paths[0] if change == 'date' else paths[1]
    book = openpyxl.load_workbook(target)
    if change == 'date':
        book['Model']['A1'].number_format = 'yyyy-mm-dd'
    elif change == 'visibility':
        book['Inputs'].row_dimensions[1].hidden = True
    elif change == 'defined_name':
        from openpyxl.workbook.defined_name import DefinedName
        book.defined_names.add(DefinedName('AddedContextName', attr_text='Inputs!$B$1'))
    elif change == 'epoch':
        from openpyxl.utils.datetime import CALENDAR_MAC_1904
        book.epoch = CALENDAR_MAC_1904
    raw = tmp_path / 'changed_raw.xlsx'
    book.save(raw)
    book.close()
    FixtureEngine().recalculate(raw, target)
    engine = FixtureEngine()
    result = prove(tmp_path, paths, engine)
    assert not result['passed'] and not engine.calls
    assert result['root_impacts'] == []
