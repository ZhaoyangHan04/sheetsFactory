import openpyxl
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import ArrayFormula

from sheets_factory.checkers.native_error_dependencies import dependency_error_reach


def workbook(tmp_path):
    book = openpyxl.Workbook()
    book.active.title = 'Input Data'
    book['Input Data']['A1'] = '#DIV/0!'
    book['Input Data']['B1'] = 7
    book.create_sheet('Result')
    return book, tmp_path / 'reference.xlsx'


def test_static_names_keep_error_and_clean_dependencies_distinct(tmp_path):
    book, path = workbook(tmp_path)
    book.defined_names.add(DefinedName('bad', attr_text="'Input Data'!$A$1"))
    book.defined_names.add(DefinedName('good', attr_text="'Input Data'!$B$1"))
    book.defined_names.add(DefinedName('alias_bad', attr_text='bad'))
    book['Result']['A1'] = '=alias_bad+0'
    book['Result']['B1'] = '=good+0'
    book.save(path)
    report = dependency_error_reach(path, ['Result!A1', 'Result!B1'], [{'sheet': 'Input Data', 'cell': 'A1'}])
    assert report['state'] == 'verified'
    assert report['per_delta_errors']['Result!A1'] == ['Input Data!A1']
    assert report['per_delta_errors']['Result!B1'] == []


def test_bounded_whole_row_keeps_existing_far_error(tmp_path):
    book, path = workbook(tmp_path)
    book['Input Data']['Z9'] = '#VALUE!'
    book['Result']['A1'] = "=SUM('Input Data'!9:9)"
    book.save(path)
    report = dependency_error_reach(path, ['Result!A1'], [{'sheet': 'Input Data', 'cell': 'Z9'}])
    assert report['state'] == 'verified'
    assert report['per_delta_errors']['Result!A1'] == ['Input Data!Z9']


def test_single_cell_array_is_analyzed_without_changing_its_formula(tmp_path):
    book, path = workbook(tmp_path)
    book['Result']['A1'] = ArrayFormula(ref='A1:A1', text="=SUM('Input Data'!B1)")
    book.save(path)
    report = dependency_error_reach(path, ['Result!A1'], [{'sheet': 'Input Data', 'cell': 'A1'}])
    assert report['state'] == 'verified'
    assert report['per_delta_errors']['Result!A1'] == []
    after = openpyxl.load_workbook(path)
    assert isinstance(after['Result']['A1'].value, ArrayFormula)


def test_unresolved_external_name_blocks_analysis(tmp_path):
    book, path = workbook(tmp_path)
    book.defined_names.add(DefinedName('missing_source', attr_text="'[1]other.xlsx'!$A$1"))
    book['Result']['A1'] = '=missing_source'
    book.save(path)
    report = dependency_error_reach(path, ['Result!A1'], [])
    assert report['state'] == 'unknown'
