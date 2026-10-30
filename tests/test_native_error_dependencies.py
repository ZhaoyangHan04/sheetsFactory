import openpyxl
import pytest

from sheets_factory.checkers.native_error_dependencies import (
    dependency_error_reach, validate_static_reference_syntax,
)


def workbook(tmp_path, formulas, table=None):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Model'
    for coordinate, value in formulas.items():
        sheet[coordinate] = value
    if table is not None:
        sheet = book.create_sheet('Industry averages')
        for coordinate, value in table.items():
            sheet[coordinate] = value
    path = tmp_path / 'goal.xlsx'
    book.save(path)
    book.close()
    return path


def errors(*labels):
    return [{'sheet': value.rsplit('!', 1)[0], 'cell': value.rsplit('!', 1)[1],
             'cached_error': '#DIV/0!'} for value in labels]


def test_nyu_fixed_lookup_columns_exclude_only_unused_table_errors(tmp_path):
    path = workbook(tmp_path, {'A1': '=IF(B1=0,0,VLOOKUP(C1,\'Industry averages\'!$A$2:$Z$95,7))',
                              'B1': 1, 'C1': 'Pharma'},
                    {'A2': 'Pharma', 'G2': 1.2, 'F18': '=#DIV/0!', 'S29': '=#DIV/0!',
                     'Y78': '=#DIV/0!', 'Z18': '=#DIV/0!'})
    candidates = errors(*(f'Industry averages!{cell}' for cell in ['F18', 'S29', 'Y78', 'Z18']))
    result = dependency_error_reach(path, ['Model!A1'], candidates)
    assert result['state'] == 'verified'
    assert result['per_delta_errors'] == {'Model!A1': []}
    certificate, = result['exclusions']
    assert certificate['formula_cell'] == 'Model!A1'
    assert certificate['key_column'] == 'A' and certificate['return_column'] == 'G'
    assert certificate['selected_column_index'] == 7
    assert len(certificate['ignored_errors']) == 4


@pytest.mark.parametrize('column', ['B1', '1+2', '3.0', '0', '-1', '5'])
def test_nonliteral_or_invalid_return_column_cannot_exclude_errors(tmp_path, column):
    path = workbook(tmp_path, {'A1': f'=VLOOKUP(C1,\'Industry averages\'!A1:D4,{column})',
                              'B1': 3, 'C1': 'Pharma'}, {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2']
    assert not result['exclusions']


@pytest.mark.parametrize('extra', ["+SUM('Industry averages'!B2)",
                                  "+VLOOKUP(C1,'Industry averages'!A1:D4,2)"])
def test_error_referenced_elsewhere_remains_reachable(tmp_path, extra):
    path = workbook(tmp_path, {'A1': "=VLOOKUP(C1,'Industry averages'!A1:D4,3)" + extra,
                              'C1': 'Pharma'}, {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2']
    assert result['exclusions']


def test_error_in_lookup_key_is_not_removed_by_table_certificate(tmp_path):
    path = workbook(tmp_path, {'A1': "=VLOOKUP('Industry averages'!B2,'Industry averages'!A1:D4,3)"},
                    {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2']


def test_key_and_return_columns_always_remain_relevant(tmp_path):
    path = workbook(tmp_path, {'A1': "=VLOOKUP(C1,'Industry averages'!B1:E4,3,0)", 'C1': 1},
                    {'B2': '=#DIV/0!', 'D3': '=#DIV/0!', 'C4': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'],
                                    errors('Industry averages!B2', 'Industry averages!D3', 'Industry averages!C4'))
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2', 'Industry averages!D3']
    assert result['exclusions'][0]['ignored_errors'] == ['Industry averages!C4']


def test_mutually_masked_iferror_keeps_both_error_ancestors(tmp_path):
    path = workbook(tmp_path, {'A1': '=#DIV/0!', 'B1': '=#DIV/0!', 'C1': '=IFERROR(A1+B1,0)'})
    result = dependency_error_reach(path, ['Model!C1'], errors('Model!A1', 'Model!B1'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors'] == {'Model!C1': ['Model!A1', 'Model!B1']}
    assert not result['exclusions']


def test_different_outputs_have_individual_not_global_error_sets(tmp_path):
    path = workbook(tmp_path, {'A1': '=#DIV/0!', 'B1': '=#DIV/0!', 'C1': '=IFERROR(A1,0)',
                              'D1': '=IFERROR(B1,0)', 'E1': '=C1+D1'})
    result = dependency_error_reach(path, ['Model!C1', 'Model!D1', 'Model!E1'],
                                    errors('Model!A1', 'Model!B1'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors'] == {'Model!C1': ['Model!A1'], 'Model!D1': ['Model!B1'],
                                          'Model!E1': ['Model!A1', 'Model!B1']}


@pytest.mark.parametrize('formula', ["=HLOOKUP(C1,'Industry averages'!A1:D4,3)",
                                    "=INDEX('Industry averages'!A1:D4,C1,3)",
                                    "=IF(C1,'Industry averages'!B2,0)"])
def test_other_functions_do_not_receive_lookup_exemptions(tmp_path, formula):
    path = workbook(tmp_path, {'A1': formula, 'C1': 0}, {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2']
    assert not result['exclusions']


@pytest.mark.parametrize('formula', ['=INDIRECT("B1")', '=OFFSET(B1,0,0)', '=named_input',
                                    '=Missing!A1', '=A1'])
def test_unresolved_references_missing_sheets_and_cycles_are_unknown(tmp_path, formula):
    path = workbook(tmp_path, {'A1': formula, 'B1': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Model!B1'))
    assert result['state'] == 'unknown'
    assert result['reason']


def test_dependency_limit_is_complete_and_long_chain_does_not_use_recursion(tmp_path):
    formulas = {f'A{index}': f'=A{index+1}' for index in range(1, 1200)}
    formulas['A1200'] = '=#DIV/0!'
    path = workbook(tmp_path, formulas)
    result = dependency_error_reach(path, ['Model!A1', 'Model!A2'], errors('Model!A1200'), max_cells=1200)
    assert result['state'] == 'verified' and result['closure_cells'] == 1200
    assert result['per_delta_errors']['Model!A1'] == ['Model!A1200']
    assert dependency_error_reach(path, ['Model!A1'], errors('Model!A1200'), max_cells=1199)['state'] == 'unknown'


def test_nested_commas_and_quoted_sheet_names_are_parsed_by_token_occurrence(tmp_path):
    path = workbook(tmp_path, {'A1': "=VLOOKUP(IF(B1,1,2),'Industry averages'!A1:D4,3,IF(B1,0,1))",
                              'B1': 1}, {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified' and result['per_delta_errors']['Model!A1'] == []
    assert len(result['exclusions']) == 1


def test_large_unexpanded_table_is_unknown_not_an_exclusion_certificate(tmp_path):
    path = workbook(tmp_path, {'A1': "=VLOOKUP(C1,'Industry averages'!A1:Z1000,3)", 'C1': 1},
                    {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'unknown'
    assert not result['exclusions']


@pytest.mark.parametrize('condition,formula', [
    ('TRUE', '=IF(TRUE,5,A1)'), ('FALSE', '=IF(FALSE,A1,5)'),
    ('1', '=IF(1,5,A1)'), ('0', '=IF(0,A1,5)'),
    ('TRUE()', '=IF(TRUE(),5,A1)'), ('FALSE()', '=IF(FALSE(),A1,5)'),
])
def test_literal_if_excludes_only_provably_unselected_argument(tmp_path, condition, formula):
    path = workbook(tmp_path, {'A1': '=#DIV/0!', 'B1': formula})
    result = dependency_error_reach(path, ['Model!B1'], errors('Model!A1'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!B1'] == []
    certificate, = result['exclusions']
    assert certificate['kind'] == 'if_literal_condition'
    assert certificate['condition'] == condition
    assert certificate['ignored_errors'] == ['Model!A1']


@pytest.mark.parametrize('formula', ['=IF(TRUE,A1,5)', '=IF(FALSE,5,A1)',
                                    '=IF(1+0,5,A1)', '=IF(B1,5,A1)',
                                    '=IF(TRUE,5,A1)+SUM(A1)'])
def test_selected_if_argument_or_other_occurrence_remains_relevant(tmp_path, formula):
    path = workbook(tmp_path, {'A1': '=#DIV/0!', 'B1': 1, 'C1': formula})
    result = dependency_error_reach(path, ['Model!C1'], errors('Model!A1'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!C1'] == ['Model!A1']


@pytest.mark.parametrize('formula,selected', [
    ("=INDEX('Industry averages'!B2:E5,2,3)", 'Industry averages!D3'),
    ("=INDEX('Industry averages'!B2:B5,2)", 'Industry averages!B3'),
])
def test_literal_index_keeps_only_selected_cell(tmp_path, formula, selected):
    path = workbook(tmp_path, {'A1': formula}, {'B2': '=#DIV/0!', 'B3': 7, 'D3': 8})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified' and result['per_delta_errors']['Model!A1'] == []
    certificate, = result['exclusions']
    assert certificate['kind'] == 'index_fixed_row_and_column'
    assert certificate['selected_cell'] == selected
    assert certificate['ignored_errors'] == ['Industry averages!B2']


@pytest.mark.parametrize('formula', ["=INDEX('Industry averages'!B2:E5,0,3)",
                                    "=INDEX('Industry averages'!B2:E5,2)",
                                    "=INDEX('Industry averages'!B2:E5,2,C1)",
                                    "=INDEX('Industry averages'!B2:E5,9,3)"])
def test_unproven_index_selection_retains_all_table_references(tmp_path, formula):
    path = workbook(tmp_path, {'A1': formula, 'C1': 3}, {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2']
    assert not result['exclusions']


def test_index_selected_error_and_separate_occurrence_remain_relevant(tmp_path):
    path = workbook(tmp_path, {'A1': "=INDEX('Industry averages'!B2:E5,2,3)+SUM('Industry averages'!B2)"},
                    {'B2': '=#DIV/0!', 'D3': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2', 'Industry averages!D3'))
    assert result['state'] == 'verified'
    assert result['per_delta_errors']['Model!A1'] == ['Industry averages!B2', 'Industry averages!D3']


def test_nested_unselected_if_argument_does_not_leak_inner_references(tmp_path):
    path = workbook(tmp_path, {'A1': '=#DIV/0!', 'B1': '=#DIV/0!',
                              'C1': '=IF(TRUE,8,IF(FALSE,A1,SUM(B1)))'})
    result = dependency_error_reach(path, ['Model!C1'], errors('Model!A1', 'Model!B1'))
    assert result['state'] == 'verified' and result['per_delta_errors']['Model!C1'] == []


def test_public_certificate_does_not_hide_unsupported_formula_references(tmp_path):
    path = workbook(tmp_path, {'A1': '=IF(TRUE,5,INDIRECT("B1"))', 'B1': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Model!B1'))
    assert result['state'] == 'unknown'
    assert not result['exclusions']


def test_reversed_range_cannot_be_mistaken_for_an_empty_dependency_set(tmp_path):
    path = workbook(tmp_path, {'A1': "=IFERROR(SUM('Industry averages'!D4:A1),0)"},
                    {'B2': '=#DIV/0!'})
    result = dependency_error_reach(path, ['Model!A1'], errors('Industry averages!B2'))
    assert result['state'] == 'unknown'
    assert 'invalid bounded reference' in result['reason']


def test_constructed_index_range_cannot_hide_errors_between_literal_arrays(tmp_path):
    path = workbook(tmp_path, {'A1': 1, 'B2': '=#DIV/0!', 'B3': '=#DIV/0!',
                              'D4': 2, 'F1': '=IFERROR(SUM(INDEX(A1:B2,1,1):INDEX(D4:E5,1,1)),0)'})
    result = dependency_error_reach(path, ['Model!F1'], errors('Model!B2', 'Model!B3'))
    assert result['state'] == 'unknown'
    assert 'compound' in result['reason']
    assert not result['exclusions']


@pytest.mark.parametrize('formula', [
    '=SUM(INDEX(A1:B2,1,1):INDEX(D4:E5,1,1))',
    '=SUM(A1:INDEX(D4:E5,1,1))',
    '=SUM(A1:B2 C1:D2)', '=SUM((A1:B2,C1:D2))',
    '=SUM(A2:A1)', '=SUM(XFE1:XFE2)', '=SUM(A0:A2)',
    '=SUM(A1', '=SUM(Sheet1:Sheet3!A1)',
])
def test_public_static_syntax_validator_rejects_uncovered_references(formula):
    assert validate_static_reference_syntax(formula) is not None


@pytest.mark.parametrize('formula', [
    '=SUM(A1:B2, C1:D2)', '=IF(TRUE(), 5, A1)',
    "=IF(G36=0,,VLOOKUP(G36,'Industry averages'!$A$2:$Z$95,15))",
    "=INDEX('Industry averages'!A1:D4,2,3)",
])
def test_public_static_syntax_validator_allows_ordinary_formula_spacing(formula):
    assert validate_static_reference_syntax(formula) is None
