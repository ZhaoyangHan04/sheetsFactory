"""Static certificates use synthetic caches, never invoke a spreadsheet engine."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

import openpyxl
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import ArrayFormula
import pytest

from sheets_factory.checkers.separated_roots import certify_separated_roots


NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def save_cached(book, path, values):
    """Install explicitly supplied fixture values without evaluating formulas."""
    book.save(path)
    with ZipFile(path) as archive:
        members = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    for index, sheet in enumerate(book, 1):
        name = f'xl/worksheets/sheet{index}.xml'
        tree = ET.fromstring(members[name])
        for cell in tree.iter(NS + 'c'):
            key = (sheet.title, cell.get('r'))
            if key not in values:
                continue
            value = values[key]
            old = cell.find(NS + 'v')
            if old is not None:
                cell.remove(old)
            node = ET.SubElement(cell, NS + 'v')
            if value is None:
                node.text = None
            elif isinstance(value, bool):
                cell.set('t', 'b'); node.text = '1' if value else '0'
            elif isinstance(value, str) and value.startswith('#'):
                cell.set('t', 'e'); node.text = value
            elif isinstance(value, str):
                cell.set('t', 'str'); node.text = value
            else:
                cell.set('t', 'n'); node.text = str(value)
        members[name] = ET.tostring(tree, encoding='utf-8')
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


@pytest.fixture
def case(tmp_path):
    book = openpyxl.Workbook()
    book.active.title = 'Model'
    book.create_sheet('Inputs')
    book['Inputs']['A1'], book['Inputs']['A2'] = 10, 7
    book['Model']['B1'], book['Model']['B2'] = '=Inputs!A1*2', '=Inputs!A2+3'
    edits = [dict(sheet='Model', cell='B1', before='=Inputs!A1*2', after='=Inputs!A1*3'),
             dict(sheet='Model', cell='B2', before='=Inputs!A2+3', after='=Inputs!A2+7')]
    return {'book': book, 'edits': edits, 'directory': tmp_path,
            'goal_values': {('Model', 'B1'): 20, ('Model', 'B2'): 10},
            'combined_values': {('Model', 'B1'): 30, ('Model', 'B2'): 14}}


def prove(case, *, mutated_changes=None, **limits):
    goal = case['directory'] / 'goal.xlsx'
    combined = case['directory'] / 'input.xlsx'
    save_cached(case['book'], goal, case['goal_values'])
    mutated = openpyxl.load_workbook(goal)
    for edit in case['edits']:
        mutated[edit['sheet']][edit['cell']] = edit['after']
    if mutated_changes:
        mutated_changes(mutated)
    save_cached(mutated, combined, case['combined_values'])
    before = goal.read_bytes(), combined.read_bytes()
    result = certify_separated_roots(goal=goal, combined_input=combined, edits=case['edits'], **limits)
    assert before == (goal.read_bytes(), combined.read_bytes()), 'Proof must not mutate input files'
    return result


def assert_rejected(result):
    assert result['passed'] is False and result['blocking'] is True
    assert result['state'] == 'rejected' and result['root_impacts'] == []


def test_independent_changed_roots_prove_single_and_marginal_lower_bounds(case):
    result = prove(case)
    assert result['passed'] is True and result['blocking'] is False
    assert result['proof_method'] == 'separated_roots_with_actual_combined_LO_values'
    assert result['individual_LO_executions'] == result['marginal_LO_executions'] == 0
    assert result['counts_are_lower_bounds'] is True
    assert len(result['goal_sha256']) == len(result['combined_input_sha256']) == len(result['edits_sha256']) == 64
    assert [x['evidence']['root'] for x in result['root_impacts']] == ['Model!B1', 'Model!B2']
    for item in result['root_impacts']:
        assert item['expected_change_count'] == item['combined_marginal']['expected_change_count'] == 1
        assert item['actual_LO_execution'] is item['combined_marginal']['actual_LO_execution'] is False
        assert item['evidence']['root_value_differs_after_grader_normalization'] is True
    assert result['graphs']['original']['closure_cells'] == result['graphs']['mutated']['closure_cells'] == 4


def test_shared_nonroot_ancestors_are_allowed_and_fully_traversed(case):
    case['book']['Model']['C1'] = '=Inputs!A1+1'
    case['book']['Model']['B1'] = '=C1*2'
    case['book']['Model']['B2'] = '=C1+3'
    case['edits'][0].update(before='=C1*2', after='=C1*3')
    case['edits'][1].update(before='=C1+3', after='=C1+7')
    case['goal_values'].update({('Model', 'B1'): 22, ('Model', 'B2'): 14, ('Model', 'C1'): 11})
    case['combined_values'].update({('Model', 'B1'): 33, ('Model', 'B2'): 18, ('Model', 'C1'): 11})
    result = prove(case)
    assert result['passed']
    assert result['graphs']['original']['closure_cells'] == 4
    assert result['graphs']['original']['formula_cells'] == 3


@pytest.mark.parametrize('graph', ['original', 'mutated'])
def test_root_dependency_in_either_graph_fails_even_when_other_is_separated(case, graph):
    if graph == 'original':
        case['book']['Model']['B1'] = '=B2*2'
        case['edits'][0]['before'] = '=B2*2'
    else:
        case['edits'][0]['after'] = '=B2*3'
    result = prove(case)
    assert_rejected(result)
    assert result['graphs'][graph]['root_ancestor_paths'] == [['Model!B1', 'Model!B2']]


def test_transitive_root_dependency_is_not_mistaken_for_shared_input(case):
    case['book']['Model']['C1'] = '=B2+1'
    case['book']['Model']['B1'] = '=C1*2'
    case['edits'][0]['before'] = '=C1*2'
    case['goal_values'][('Model', 'C1')] = 11
    case['combined_values'][('Model', 'C1')] = 15
    result = prove(case)
    assert_rejected(result)
    assert result['graphs']['original']['root_ancestor_paths'] == [['Model!B1', 'Model!C1', 'Model!B2']]


@pytest.mark.parametrize('after', ['=B1+1', '=SUM(B1:B2)', '=IF(FALSE,B2,Inputs!A1*3)'])
def test_root_self_cycles_and_even_inactive_root_branches_are_rejected(case, after):
    case['edits'][0]['after'] = after
    result = prove(case)
    assert_rejected(result)
    assert result['graphs']['mutated']['root_ancestor_paths']


def test_cycle_in_shared_upstream_formulas_rejected(case):
    case['book']['Model']['C1'], case['book']['Model']['D1'] = '=D1', '=C1'
    case['book']['Model']['B1'] = '=C1*2'
    case['edits'][0].update(before='=C1*2', after='=C1*3')
    for key in [('Model', 'C1'), ('Model', 'D1')]:
        case['goal_values'][key] = case['combined_values'][key] = 10
    result = prove(case)
    assert_rejected(result)
    assert 'cycle' in result['graphs']['original']['reason']


@pytest.mark.parametrize('after', ['=INDIRECT("Inputs!A1")*3', '=OFFSET(Inputs!A1,0,0)*3',
    '=missing_name*3', "='[external.xlsx]Inputs'!A1*3", '=NOW()', '=RAND()', '=CUSTOM_ADDIN(Inputs!A1)',
    '=IFERROR(#REF!,30)', '=INFO("directory")', '=SUM(INDEX(Inputs!A1:A2,1):INDEX(Inputs!A1:A2,2))'])
def test_unresolved_dynamic_external_nondeterministic_and_error_formulas_reject(case, after):
    case['edits'][0]['after'] = after
    result = prove(case)
    assert_rejected(result)
    assert result['graphs']['mutated']['state'] == 'rejected'


@pytest.mark.parametrize('where,value', [('root', '#DIV/0!'), ('root', None), ('root', float('nan')),
                                       ('ancestor', '#VALUE!'), ('ancestor', None)])
def test_invalid_root_or_formula_ancestor_cache_rejects(case, where, value):
    if where == 'root':
        case['combined_values'][('Model', 'B1')] = value
    else:
        case['book']['Model']['C1'] = '=Inputs!A1'
        case['book']['Model']['B1'] = '=C1*2'
        case['edits'][0].update(before='=C1*2', after='=C1*3')
        case['goal_values'][('Model', 'C1')] = 10
        case['combined_values'][('Model', 'C1')] = value
    assert_rejected(prove(case))


@pytest.mark.parametrize('goal_value,combined_value,passes', [(1, 1.004, False), (1, 1.005, True),
    (0, -0.004, False), (True, 1, True), ('same', 'same', False)])
def test_root_changes_use_grader_rounding_and_type_distinctions(case, goal_value, combined_value, passes):
    case['goal_values'][('Model', 'B1')] = goal_value
    case['combined_values'][('Model', 'B1')] = combined_value
    result = prove(case)
    assert result['passed'] is passes
    if not passes:
        assert_rejected(result)


def test_nonroot_literal_or_formula_mutation_cannot_hide_interference(case):
    for change in [lambda b: setattr(b['Inputs']['A1'], 'value', 11),
                   lambda b: setattr(b['Model']['D1'], 'value', '=B2')]:
        result = prove(case, mutated_changes=change)
        assert_rejected(result)
        assert 'non-root' in result['reason']


def test_named_inputs_and_optional_sheet_quotes_are_supported(case):
    case['book'].defined_names.add(DefinedName('rate', attr_text='Inputs!$A$1'))
    case['book']['Model']['B1'] = '=rate*2'
    case['edits'][0].update(before='=RATE*2', after="='Inputs'!A1*3")
    result = prove(case, mutated_changes=lambda b: setattr(b['Model']['B1'], 'value', '=Inputs!A1*3'))
    assert result['passed']
    assert result['graphs']['original']['resolved_name_occurrences'] == 1


def test_changed_named_definition_rejected(case):
    case['book'].defined_names.add(DefinedName('rate', attr_text='Inputs!$A$1'))
    result = prove(case, mutated_changes=lambda b: setattr(b.defined_names['rate'], 'attr_text', 'Inputs!$A$2'))
    assert_rejected(result)
    assert 'defined names differ' in result['reason']


def test_whole_column_dependency_includes_all_currently_used_input_cells(case):
    case['book']['Model']['B1'] = '=SUM(Inputs!A:A)*2'
    case['edits'][0].update(before='=SUM(Inputs!A:A)*2', after='=SUM(Inputs!A:A)*3')
    case['goal_values'][('Model', 'B1')] = 34
    case['combined_values'][('Model', 'B1')] = 51
    result = prove(case)
    assert result['passed']
    assert result['graphs']['original']['bounded_whole_ranges'] == 1


@pytest.mark.parametrize('limits', [{'max_dependency_cells': 2}, {'per_formula_reference_cells': 1},
                                  {'max_dependency_edges': 1}])
def test_explicit_analysis_bounds_fail_closed(case, limits):
    case['book']['Model']['B1'] = '=SUM(Inputs!A1:A2)*2'
    case['edits'][0].update(before='=SUM(Inputs!A1:A2)*2', after='=SUM(Inputs!A1:A2)*3')
    assert_rejected(prove(case, **limits))


@pytest.mark.parametrize('limits', [{'max_dependency_cells': True}, {'max_dependency_cells': 500001},
    {'per_formula_reference_cells': 50001}, {'max_dependency_edges': 0}])
def test_invalid_configuration_is_a_rejection(case, limits):
    assert_rejected(prove(case, **limits))


def test_before_after_assertions_are_not_weakened_to_arithmetic_equivalence(case):
    case['edits'][0]['before'] = '=2*Inputs!A1'
    result = prove(case)
    assert_rejected(result)
    assert 'before formula assertion mismatch' in result['reason']


def test_after_actual_formula_assertion_is_checked(case):
    result = prove(case, mutated_changes=lambda b: setattr(b['Model']['B1'], 'value', '=Inputs!A1*4'))
    assert_rejected(result)
    assert 'after formula assertion mismatch' in result['reason']


def test_multicell_array_nonanchor_dependencies_are_not_treated_as_constants(case):
    case['book']['Model']['C1'] = ArrayFormula(ref='C1:C2', text='=Inputs!A1:A2')
    case['book']['Model']['C2'] = 7
    case['book']['Model']['B1'] = '=C2*2'
    case['edits'][0].update(before='=C2*2', after='=C2*3')
    case['goal_values'][('Model', 'C1')] = case['combined_values'][('Model', 'C1')] = 10
    result = prove(case)
    assert_rejected(result)
    assert 'formula group' in result['graphs']['original']['reason']


def test_stale_changed_nonroot_cache_cannot_support_an_independence_receipt(case):
    case['book']['Model']['C1'] = '=Inputs!A1+1'
    case['book']['Model']['B1'] = '=C1*2'
    case['edits'][0].update(before='=C1*2', after='=C1*3')
    case['goal_values'][('Model', 'C1')] = 11
    case['combined_values'][('Model', 'C1')] = 12
    result = prove(case)
    assert_rejected(result)
    assert 'ancestor cache differs' in result['reason']


def test_precision_as_displayed_is_rejected_even_with_no_graph_cycle(case):
    case['book'].calculation.fullPrecision = False
    result = prove(case)
    assert_rejected(result)
    assert 'precision-as-displayed' in result['reason']


def test_invalid_workbook_bytes_return_a_blocking_receipt(tmp_path):
    path = tmp_path / 'invalid.xlsx'
    path.write_bytes(b'not an Excel archive')
    result = certify_separated_roots(goal=path, combined_input=path,
        edits=[dict(sheet='Model', cell='A1', before='=1', after='=2')])
    assert_rejected(result)
    assert result['error_type'] == 'BadZipFile'


def test_eight_hundred_primitive_input_roots_are_certified_without_per_root_workbooks(case):
    sheet = case['book']['Model']
    sheet.delete_rows(1, sheet.max_row)
    case['edits'], case['goal_values'], case['combined_values'] = [], {}, {}
    for row in range(1, 801):
        case['book']['Inputs'].cell(row, 1, row)
        sheet.cell(row, 2, f'=Inputs!A{row}*2')
        case['edits'].append(dict(sheet='Model', cell=f'B{row}',
            before=f'=Inputs!A{row}*2', after=f'=Inputs!A{row}*3'))
        case['goal_values'][('Model', f'B{row}')] = row * 2
        case['combined_values'][('Model', f'B{row}')] = row * 3
    result = prove(case)
    assert result['passed'] and len(result['root_impacts']) == 800
    assert result['graphs']['original']['closure_cells'] == 1600
    assert result['graphs']['mutated']['dependency_edges'] == 800
    assert set(path.name for path in case['directory'].iterdir()) == {'goal.xlsx', 'input.xlsx'}


def test_empty_duplicate_and_nonformula_edits_reject(case):
    for edits in [[], [case['edits'][0], case['edits'][0]],
                  [dict(sheet='Model', cell='B1', before='=Inputs!A1*2', after=None)]]:
        goal = case['directory'] / 'goal.xlsx'
        combined = case['directory'] / 'input.xlsx'
        save_cached(case['book'], goal, case['goal_values'])
        save_cached(case['book'], combined, case['goal_values'])
        assert_rejected(certify_separated_roots(goal=goal, combined_input=combined, edits=edits))
