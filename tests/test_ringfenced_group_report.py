from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E

from openpyxl import Workbook, load_workbook
import pytest

from sheets_factory.workbook.linear_capital_ringfenced_group import contract as c
from sheets_factory.workbook.linear_capital_ringfenced_group import stream_composition as core, group_report as report


def context():
    return [{'id': identity, 'profile_id': profile, 'specification': {'path': '/fixture/'+identity,
        'sha256': '0'*64, 'bytes': 0}} for identity, profile in zip(c.MANDATE_ORDER, c.PROFILE_ORDER)]


def compose_fixture(tmp_path):
    donors = []; local_reports = []
    for i, (identity, prefix) in enumerate(core.FIXED, 1):
        path = tmp_path/(identity+'.xlsx'); book = Workbook(); sheet = book.active; sheet.title = 'GroupSummary'
        sheet['A1'] = 'Local selected portfolio / GBP pence'
        values = {}
        for si, sid in enumerate(c.SCENARIOS):
            annual = []
            for yi, year in enumerate(c.YEARS):
                row = {'year': year, 'fiscal_year': 2026+year}
                for fi, field in enumerate(c.GROUP_FIELDS, 3):
                    amount = i*100000+si*10000+year*100+fi
                    if field == 'net_lp_cashflow': amount = -amount
                    row[field] = amount; sheet.cell(5+si*20+yi, fi, amount)
                annual.append(row)
            values[sid] = {'annual': annual}
        local_reports.append(values)
        portfolio = book.create_sheet('Portfolio'); portfolio['B3'] = 1; portfolio['B369'] = 1; portfolio['B370'] = i*1000
        book.save(path); book.close()
        donors.append({'id': identity, 'display_name': 'Mandate '+str(i), 'prefix': prefix, 'workbook': core.reference(path)})
    composed = core.compose_toy(donors, tmp_path/'locals.xlsx')
    combined = {sid: {'annual': [{'year': year, 'fiscal_year': 2026+year,
        **{f: sum(local[sid]['annual'][year-1][f] for local in local_reports) for f in c.GROUP_FIELDS}}
        for year in c.YEARS]} for sid in c.SCENARIOS}
    cert = {'mathematical_composition_certified': True, 'new_group_source_admitted': False,
        'composition': {'unique_best': True, 'winner_objective_pence': 10000, 'winner_report': combined}}
    return c.public_contract(context()), composed, cert


def test_all300_scenario_year_fields_and_objective_have_exact_local_mapping(tmp_path):
    public, composed, certificate = compose_fixture(tmp_path)
    plan = report.plan(public, composed); expected = report.expectations(certificate, plan)
    assert len(plan['financial']) == len(plan['formulas']) == len(expected) == 302
    assert expected['B6'] == {'type': 'boolean', 'value': True}
    assert expected['B7'] == {'type': 'number', 'value': '10000'}
    assert expected['C10'] == {'type': 'number', 'value': str(sum(i*100000+103 for i in range(1, 5)))}
    assert expected['F69']['value'].startswith('-')
    for row in range(10, 70):
        for column in 'CDEFG':
            formula = plan['formulas'][column+str(row)]
            assert formula.startswith('=IF($B$6,SUM(')
            assert all("'"+prefix+"GroupSummary'!"+column+str(row-5) in formula for _, prefix in core.FIXED)
    gate = plan['formulas']['B6']
    assert all("'"+prefix+"Portfolio'!"+point+'=1' in gate for _, prefix in core.FIXED for point in ('B3', 'B369'))
    assert all("'"+prefix+"Portfolio'!B370" in plan['formulas']['B7'] for _, prefix in core.FIXED)
    assert not any('winner' in str(x).lower() for x in plan['literals'].values())


def test_append_changes_only_workbook_metadata_and_new_uncached_report(tmp_path):
    public, composed, certificate = compose_fixture(tmp_path); old = deepcopy(composed)
    result = report.append_report(composed, public, tmp_path/'with_report.xlsx')
    assert composed == old and core.reference(composed['output']['path']) == composed['output']
    added = result['report_plan']['added_geometry']
    assert result['sheet_count'] == 9 and added['formulas'] == added['targets'] == 302
    assert result['geometry'] == {k: composed['geometry'][k]+added[k] for k in composed['geometry']}
    with ZipFile(composed['output']['path']) as first, ZipFile(result['output']['path']) as last:
        changed = {name for name in first.namelist() if first.read(name) != last.read(name)}
        assert changed == {'xl/workbook.xml', 'xl/_rels/workbook.xml.rels', '[Content_Types].xml'}
        assert set(last.namelist())-set(first.namelist()) == {'xl/worksheets/ringfenced_group_reporting.xml'}
        root = E.fromstring(last.read('xl/worksheets/ringfenced_group_reporting.xml'))
        assert len(list(root.iter('{'+core.S+'}f'))) == 302
        assert all(cell.find('{'+core.S+'}v') is None for cell in root.iter('{'+core.S+'}c') if cell.find('{'+core.S+'}f') is not None)
    book = load_workbook(result['output']['path']); cached = load_workbook(result['output']['path'], data_only=True)
    try:
        sheet = book[report.SHEET]
        assert sheet['B6'].data_type == 'f' and sheet['B6'].number_format == 'General'
        assert cached[report.SHEET]['B6'].value is None and cached[report.SHEET]['B7'].value is None
        assert sheet['B3'].value.startswith('n/a') and sheet['B4'].value.startswith('n/a')
        assert sheet['A10'].value == 'S01' and sheet['B10'].value == 2027
        assert sheet['A69'].value == 'S03' and sheet['B69'].value == 2046
    finally: book.close(); cached.close()
    assert result['LO_model_solver_Harbor_calls'] == 0 and not result['new_group_source_admitted']


@pytest.mark.parametrize('case', ['missing_fund', 'wrong_prefix', 'wrong_fields', 'report_collision'])
def test_invalid_public_mapping_holds_before_output(tmp_path, case):
    public, composed, _ = compose_fixture(tmp_path)
    if case == 'missing_fund': composed['donors'].pop()
    elif case == 'wrong_prefix': composed['donors'][0]['sheet_map']['Portfolio'] = 'Other - Portfolio'
    elif case == 'wrong_fields': public['group_fields'].reverse()
    else: composed['donors'][0]['sheet_map']['Other'] = report.SHEET
    with pytest.raises(ValueError): report.append_report(composed, public, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


@pytest.mark.parametrize('bad', [True, 0.5, 2**53])
def test_expectations_reject_boolean_as_money_and_nonexact_domain(tmp_path, bad):
    public, composed, certificate = compose_fixture(tmp_path)
    certificate['composition']['winner_report']['S01']['annual'][0]['new_lp_calls'] = bad
    with pytest.raises(ValueError, match='integer'): report.expectations(certificate, report.plan(public, composed))


def test_existing_output_and_geometry_caps_preserved(tmp_path, monkeypatch):
    public, composed, _ = compose_fixture(tmp_path)
    existing = tmp_path/'existing.xlsx'; existing.write_bytes(b'keep')
    with pytest.raises(ValueError, match='fresh'): report.append_report(composed, public, existing)
    assert existing.read_bytes() == b'keep'
    monkeypatch.setitem(core.LIMITS, 'targets', 301)
    with pytest.raises(ValueError, match='ceilings'): report.append_report(composed, public, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()
