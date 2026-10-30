#!/usr/bin/env python3
"""Prepare and optionally verify an explicitly hypothetical financial portfolio.

Each subsidiary is independently emitted and journaled before sheet names are
namespaced. No journal values enter a financial formula or a public forecast.
A prepared file is never selected without two real LibreOffice recalculations,
complete independent formula coverage, typed stability and accounting checks.
"""
from __future__ import annotations

import argparse
from copy import copy, deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import time

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import get_column_letter as L
from openpyxl.utils.cell import quote_sheetname

from sheets_factory.workbook.derived_gold.spec import resolve_spec
from sheets_factory.workbook.derived_gold.presentation import apply_public_presentation
from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.validate import audit_workbook, ledger_invariants_pass, posted_money_matches
from sheets_factory.workbook.derived_gold.task_templates import propose_project_task, _formula_rectangles
from sheets_factory.workbook.compare import compare_workbooks
from sheets_factory.workbook.engine import LibreOfficeEngine

ROOT = Path(__file__).resolve().parents[1]
RECIPE_FILES = (
    'scripts/build_portfolio_source.py', 'scripts/build_covenant_sources.py',
    'scripts/build_derived_scenarios.py',
    'src/sheets_factory/workbook/derived_gold/spec.py',
    'src/sheets_factory/workbook/derived_gold/excel.py',
    'src/sheets_factory/workbook/derived_gold/ledger.py',
    'src/sheets_factory/workbook/derived_gold/validate.py',
    'src/sheets_factory/workbook/derived_gold/presentation.py',
    'src/sheets_factory/workbook/derived_gold/task_templates.py',
    'src/sheets_factory/workbook/engine.py',
    'src/sheets_factory/workbook/uno_recalculate.py',
    'src/sheets_factory/workbook/compare.py',
    'tests/test_portfolio_source.py',
)
PUBLIC_SHEETS = ('Portfolio Index', 'Group Statements', 'Group Summary')
GROUP_RULES = [
    'This is a hypothetical reporting portfolio of twelve separately financed operating subsidiaries, each owned 100%. It is not twelve observed companies. The common public NYU ancestor supplies only the benchmark anchors stated on each Source Inputs sheet.',
    'There are no intercompany transactions, balances, guarantees, minority interests, acquisition goodwill, foreign currencies or consolidation adjustments. There are no additional parent operating balances, expenses or taxes. Group capital is the sum of the subsidiaries\' paid-in capital; subsidiary equity is not counted again as a separate parent investment asset.',
    'All subsidiaries use the same thirty-six calendar months and nominal USD reporting currency. Each entity\'s Scenario, Source Inputs and Read Me contain its own provided assumptions and contract. Entity IDs and sheet mappings are listed below. An entity\'s tax attributes and debt covenants are separate and cannot be shared, netted, or cured by another entity.',
    'Group monthly income, cash flow and balance-sheet lines aggregate the corresponding posted subsidiary amounts for that month. Annual flows sum the twelve posted monthly flows; annual opening balances are the first month\'s opening balances, and annual closing balances, cash before allocation and the closing balance check use the last month. Annual cash gap is the sum of monthly gaps. Sum each subsidiary\'s independently settled tax and deferred tax; do not recompute a pooled group tax.',
    'Group operating cash excludes segregated DSRA cash. Group total cash includes both accounts. Reserve funding, release and support are internal cash transfers and do not enter group CFO, CFI or CFF. The three group cash reconciliations and the net-assets identity must hold without a balancing plug.',
    'The Group Summary owner values are sums of the subsidiary owner values, with no additional holding discount or fee. Owner equity funding is the sum of each entity\'s initial equity, and owner distributions and sale proceeds pass directly to the external portfolio owner. No averaging of entity IRRs or discount rates is requested.',
]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def _ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': _sha(path), 'bytes': path.stat().st_size}


def _load_adapter(root):
    spec = importlib.util.spec_from_file_location('_portfolio_covenant_adapter', root/'scripts/build_covenant_sources.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite_formula(formula, mapping):
    """Change only qualified sheet-reference tokens, never string contents."""
    if not isinstance(formula, str) or not formula.startswith('='):
        raise ValueError('A scalar Excel formula is required')
    tokens = Tokenizer(formula).items
    for token in tokens:
        if token.type != 'OPERAND' or token.subtype != 'RANGE' or '!' not in token.value:
            continue
        pattern = re.compile(r"('(?:[^']|'')*'|[^'!:]+)!")
        matches = list(pattern.finditer(token.value))
        if not matches or matches[0].start() != 0:
            raise ValueError('External or 3D references are not supported')
        def replace(match):
            name = match.group(1)
            if '[' in name or ']' in name or ':' in name:
                raise ValueError('External or 3D references are not supported')
            original = name[1:-1].replace("''", "'") if name.startswith("'") and name.endswith("'") else name
            if original not in mapping:
                raise ValueError('Formula refers outside its entity: ' + original)
            return quote_sheetname(mapping[original]) + '!'
        token.value = pattern.sub(replace, token.value)
    return '=' + ''.join(token.value for token in tokens)


def namespace_bindings(value, mapping):
    if isinstance(value, dict):
        return {key: mapping[item] if key == 'sheet' and isinstance(item, str) and item in mapping
                else namespace_bindings(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [namespace_bindings(item, mapping) for item in value]
    return value


def _copy_entity(book, destination, mapping):
    if len(set(mapping.values())) != len(mapping) or any(len(name)>31 for name in mapping.values()):
        raise ValueError('Excel sheet namespaces must be unique and at most 31 characters')
    for source in book:
        target = destination.create_sheet(mapping[source.title])
        target.sheet_state = 'visible'
        target.freeze_panes = source.freeze_panes
        for key, dim in source.column_dimensions.items():
            target.column_dimensions[key].width = dim.width
            target.column_dimensions[key].hidden = dim.hidden
        for key, dim in source.row_dimensions.items():
            target.row_dimensions[key].height = dim.height
            target.row_dimensions[key].hidden = dim.hidden
        for cell in source._cells.values():
            value = rewrite_formula(cell.value, mapping) if cell.data_type=='f' else cell.value
            other = target.cell(cell.row, cell.column, value)
            if cell.has_style:
                other.font, other.fill, other.border = copy(cell.font), copy(cell.fill), copy(cell.border)
                other.alignment, other.protection = copy(cell.alignment), copy(cell.protection)
                other.number_format = cell.number_format
            if cell.comment is not None:
                other.comment = copy(cell.comment)
            if cell.hyperlink:
                raise ValueError('Unexpected entity hyperlink; an explicit port is required')
        for region in source.merged_cells.ranges:
            target.merge_cells(str(region))


def _mapped_address(address, mapping):
    sheet, cell = address.rsplit('!', 1)
    return mapping[sheet] + '!' + cell


def _compile_expectations(raw, spec, ledger, bindings, mapping):
    # Unrecalculated caches are intentionally absent. This invocation compiles
    # independent expected cells and verifies binding coverage, not finance proof.
    audit = audit_workbook(raw, spec, ledger, bindings)
    if not audit['all_formula_cells_independently_covered'] or not audit['all_ledger_invariants_passed']:
        raise ValueError('An entity has incomplete independent formula bindings or invalid journal')
    return { _mapped_address(row['address'], mapping): {
                'expected_independent': row['expected_independent'], 'kind': row['kind']}
            for row in audit['cell_checks'] }


def _monthly_references(bindings):
    references = {key:(value['sheet'],value['row']) for key,value in bindings['monthly'].items()}
    references.update({key:('Covenants', value['row']) for key,value in bindings.get('covenant',{}).items()})
    references.update({key:('Tax', value) for key,value in bindings.get('tax_monthly',{}).items()})
    references.update(total_cash_close=('Cash Flow',17), current_tax=('Tax',7))
    return references


def _aggregate_independent(entities):
    """Sum only independent journals; this function never reads model formulas."""
    keys = list(entities[0]['bindings']['annual'])
    keys += list(entities[0]['bindings'].get('covenant_annual',{}))
    keys += list(entities[0]['bindings'].get('advanced_tax_annual',{}))
    if len(keys)!=len(set(keys)):
        raise ValueError('Ambiguous group account bindings')
    monthly, annual = [], []
    for index in range(36):
        row = {key:sum((Decimal(str(e['ledger']['monthly'][index][key])) for e in entities),Decimal(0)) for key in keys}
        row['date'] = entities[0]['ledger']['monthly'][index]['date']
        row['group_balance_check'] = row['assets']-row['liabilities']-row['equity']
        row['group_cfo_check'] = row['cfo_direct']-row['cfo_indirect']
        row['group_operating_cash_check'] = (row['cash_open']+row['cfo_direct']+row['cfi']+row['cff']
            + sum((Decimal(str(e['ledger']['monthly'][index]['dsra_net_transfer'])) for e in entities),Decimal(0))-row['cash_close'])
        row['group_total_cash_check'] = row['cash_open']+row['dsra_open']+row['cfo_direct']+row['cfi']+row['cff']-row['total_cash_close']
        row['group_reserve_check'] = row['dsra_open']+row['dsra_funding']-row['dsra_release']-row['dsra_support']-row['dsra_close']
        row['group_retained_check'] = row['retained_open']+row['net_income']-row['dividend']-row['retained_close']
        row['group_income_check'] = row['ebt']-row['tax']-row['net_income']
        if any(value!=0 for key,value in row.items() if key.startswith('group_')):
            raise ValueError('Independent consolidated financial identity failed')
        monthly.append(row)
    for index in range(3):
        row = {key:sum((Decimal(str(e['ledger']['annual'][index][key])) for e in entities),Decimal(0)) for key in keys}
        row.update(year=index+1, start_date=entities[0]['ledger']['annual'][index]['start_date'],
                   end_date=entities[0]['ledger']['annual'][index]['end_date'])
        annual.append(row)
    valuation_keys = ('next_annual_sales','next_ebitda','enterprise_value','exit_fee','equity_exit','equity_npv','loan_a_payment')
    valuation = {key:sum((Decimal(str(e['ledger']['valuation'][key])) for e in entities),Decimal(0)) for key in valuation_keys}
    valuation['initial_owner_equity'] = sum((Decimal(str(e['spec']['parameters']['equity_paid_in'])) for e in entities),Decimal(0))
    return {'keys':keys, 'monthly':monthly, 'annual':annual, 'valuation':valuation,
            'checks':{'all_group_identities_passed':True,'entity_count':len(entities),'intercompany_eliminations':0,
                      'ownership_fraction':'1','group_balance_plug_used':False}}


def _emit_group(book, entities, group, expected):
    """Emit aggregation formulas using bindings, without journal numeric answers."""
    monthly = book['Group Statements']
    summary = book['Group Summary']
    rows = {key:index+3 for index,key in enumerate(group['keys'])}
    annual_rows = {key:index+21 for index,key in enumerate(group['keys'])}
    for key,row in rows.items():
        monthly.cell(row,1,key.replace('_',' '))
    for key,row in annual_rows.items():
        summary.cell(row,1,key.replace('_',' '))
    refs = [_monthly_references(entity['bindings']) for entity in entities]
    for index in range(36):
        c = L(index+3)
        monthly[c+'1'] = '=' + quote_sheetname(entities[0]['mapping']['Calendar'])+'!'+c+'3'
        monthly[c+'1'].number_format = 'mmm yyyy'
        expected['Group Statements!'+c+'1'] = {'expected_independent':group['monthly'][index]['date'],'kind':'date'}
        for key,row in rows.items():
            if any(key not in reference for reference in refs):
                raise ValueError('Missing monetary monthly source binding: '+key)
            cells = [quote_sheetname(e['mapping'][reference[key][0]])+'!'+c+str(reference[key][1])
                     for e,reference in zip(entities,refs)]
            monthly[c+str(row)] = '=SUM('+','.join(cells)+')'
            monthly[c+str(row)].number_format = '#,##0.00;[Red](#,##0.00)'
            expected['Group Statements!'+c+str(row)] = {'expected_independent':str(group['monthly'][index][key]),'kind':'money'}
    # These checks use the group statements, rather than summing entity checks.
    check_start = max(rows.values())+3
    checks = {
        'group_balance_check':lambda c:f'{c}{rows["assets"]}-{c}{rows["liabilities"]}-{c}{rows["equity"]}',
        'group_cfo_check':lambda c:f'{c}{rows["cfo_direct"]}-{c}{rows["cfo_indirect"]}',
        'group_operating_cash_check':lambda c:(f'{c}{rows["cash_open"]}+{c}{rows["cfo_direct"]}+{c}{rows["cfi"]}+{c}{rows["cff"]}'
                f'+{c}{rows["dsra_release"]}+{c}{rows["dsra_support"]}-{c}{rows["dsra_funding"]}-{c}{rows["cash_close"]}'),
        'group_total_cash_check':lambda c:f'{c}{rows["cash_open"]}+{c}{rows["dsra_open"]}+{c}{rows["cfo_direct"]}+{c}{rows["cfi"]}+{c}{rows["cff"]}-{c}{rows["total_cash_close"]}',
        'group_reserve_check':lambda c:f'{c}{rows["dsra_open"]}+{c}{rows["dsra_funding"]}-{c}{rows["dsra_release"]}-{c}{rows["dsra_support"]}-{c}{rows["dsra_close"]}',
        'group_retained_check':lambda c:f'{c}{rows["retained_open"]}+{c}{rows["net_income"]}-{c}{rows["dividend"]}-{c}{rows["retained_close"]}',
        'group_income_check':lambda c:f'{c}{rows["ebt"]}-{c}{rows["tax"]}-{c}{rows["net_income"]}',
    }
    for offset,(key,formula) in enumerate(checks.items()):
        row=check_start+offset
        monthly.cell(row,1,key.replace('_',' '))
        for index in range(36):
            c=L(index+3)
            monthly[c+str(row)]='='+formula(c)
            expected['Group Statements!'+c+str(row)]={'expected_independent':str(group['monthly'][index][key]),'kind':'money'}
    summary['A1']='Portfolio annual reporting and owner values'
    for index,rule in enumerate(GROUP_RULES,3):
        summary.cell(index,1,rule)
    for index in range(3):
        c=L(index+3)
        summary[c+'18']=index+1
        for target,source,key in ((19,4,'start_date'),(20,5,'end_date')):
            summary[c+str(target)]='='+quote_sheetname(entities[0]['mapping']['Annual Statements'])+'!'+c+str(source)
            summary[c+str(target)].number_format='yyyy-mm-dd'
            expected['Group Summary!'+c+str(target)]={'expected_independent':group['annual'][index][key],'kind':'date'}
        for key,row in annual_rows.items():
            cells=[]
            for entity in entities:
                binding={**entity['bindings']['annual'],**entity['bindings'].get('covenant_annual',{}),
                         **entity['bindings'].get('advanced_tax_annual',{})}
                cells.append(quote_sheetname(entity['mapping']['Annual Statements'])+'!'+c+str(binding[key]))
            summary[c+str(row)]='=SUM('+','.join(cells)+')'
            summary[c+str(row)].number_format='#,##0.00;[Red](#,##0.00)'
            expected['Group Summary!'+c+str(row)]={'expected_independent':str(group['annual'][index][key]),'kind':'money'}
    valuation_start=max(annual_rows.values())+4
    for offset,key in enumerate(group['valuation']):
        row=valuation_start+offset
        summary.cell(row,1,key.replace('_',' '))
        if key=='initial_owner_equity':
            cells=[quote_sheetname(e['mapping']['Scenario'])+'!B'+str(e['bindings']['parameter_rows']['equity_paid_in']) for e in entities]
        else:
            cells=[quote_sheetname(e['mapping']['Equity Value'])+'!'+e['bindings']['valuation'][key] for e in entities]
        summary.cell(row,3,'=SUM('+','.join(cells)+')')
        expected['Group Summary!C'+str(row)]={'expected_independent':str(group['valuation'][key]),'kind':'money'}
    for sheet in (monthly,summary):
        sheet.freeze_panes='C3'
        sheet.column_dimensions['A'].width=38
        sheet.column_dimensions['B'].width=3
        for i in range(3,39):sheet.column_dimensions[L(i)].width=17
    return {'monthly_rows':rows,'annual_rows':annual_rows,'valuation_start':valuation_start,'check_start':check_start}


def _group_expectations(group, bindings):
    """Bind the independently summed journal without reading group formulas."""
    out={}
    for index,month in enumerate(group['monthly']):
        c=L(index+3)
        out['Group Statements!'+c+'1']={'expected_independent':month['date'],'kind':'date'}
        for key,row in bindings['monthly_rows'].items():
            out['Group Statements!'+c+str(row)]={'expected_independent':str(month[key]),'kind':'money'}
        checks=[key for key in month if key.startswith('group_')]
        for offset,key in enumerate(checks):
            out['Group Statements!'+c+str(bindings['check_start']+offset)]={'expected_independent':str(month[key]),'kind':'money'}
    for index,year in enumerate(group['annual']):
        c=L(index+3)
        for row,key in ((19,'start_date'),(20,'end_date')):
            out['Group Summary!'+c+str(row)]={'expected_independent':year[key],'kind':'date'}
        for key,row in bindings['annual_rows'].items():
            out['Group Summary!'+c+str(row)]={'expected_independent':str(year[key]),'kind':'money'}
    for offset,(key,value) in enumerate(group['valuation'].items()):
        out['Group Summary!C'+str(bindings['valuation_start']+offset)]={'expected_independent':str(value),'kind':'money'}
    return out


def _load_config(root, path):
    config=json.loads(path.read_text())
    if config.get('schema_version')!=1 or config.get('ownership_fraction')!=1 or config.get('intercompany_transactions') is not False or config.get('parent_operating_balances') is not False:
        raise ValueError('Only explicit 100%-owned portfolios with no parent or intercompany balances are supported')
    adapter=_load_adapter(root)
    catalog,base,cases,base_path=adapter.load_catalog(root,config['source_catalog'])
    if (root/config['base_config']).resolve()!=base_path.resolve():
        raise ValueError('Portfolio and case catalog must use the same base contract')
    if base.get('public_presentation')!='business_brief':
        raise ValueError('The public business brief is required')
    by_id={case['id']:case for case in cases}
    selected=[]
    for item in config.get('entities',[]):
        identifier=item.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'T[0-9]{2}',identifier):
            raise ValueError('Entity IDs must be stable T01-style identifiers')
        if 'catalog_case' in item:
            if set(item)!={'id','catalog_case'} or item['catalog_case'] not in by_id:
                raise ValueError('Unknown or patched catalog case')
            case=deepcopy(by_id[item['catalog_case']]);case['id']=identifier
        else:
            case=deepcopy(item)
            if not case.get('name') or not case.get('mechanism'):
                raise ValueError('Inline cases need a name and mechanism')
            for patch,target in (('hypothetical_patch','hypothetical_parameters'),('covenant_patch','covenant_parameters'),('advanced_tax_patch','advanced_tax_parameters')):
                if not isinstance(case.get(patch),dict) or set(case[patch])-set(base[target]):
                    raise ValueError('Unknown or missing explicit patch: '+patch)
                for key,value in case[patch].items():
                    if key!='start_date':
                        for number in value if isinstance(value,list) else [value]:adapter._number(number)
            if not case.get('required_regimes') or set(case['required_regimes'])-adapter.REGIMES:
                raise ValueError('An inline case requires supported actual regimes')
        selected.append(case)
    if not selected or len({case['id'] for case in selected})!=len(selected):
        raise ValueError('Nonempty unique entity IDs are required')
    return config,base,selected,base_path,adapter


def prepare_portfolio(project_root, config_path, output):
    root,output=Path(project_root).resolve(),Path(output).resolve()
    config_path=Path(config_path)
    config_path=config_path if config_path.is_absolute() else root/config_path
    if output.exists():raise ValueError('Output exists; use a new immutable portfolio directory')
    config,base,cases,base_path,adapter=_load_config(root,config_path)
    recipe={name:_ref(root/name) for name in RECIPE_FILES}
    recipe.update(portfolio_config=_ref(config_path),source_catalog=_ref(root/config['source_catalog']),base_config=_ref(base_path))
    source=Path(base['source']['local_path']);source=source if source.is_absolute() else root/source
    if _sha(source)!=base['source']['sha256']:raise ValueError('Immutable ancestor SHA mismatch')
    output.mkdir(parents=True)
    private=output/'private';private.mkdir(mode=0o700)
    started=time.monotonic()
    book=openpyxl.Workbook();book.remove(book.active)
    for title in PUBLIC_SHEETS:book.create_sheet(title)
    index=book['Portfolio Index'];index['A1']='Hypothetical 100%-owned operating portfolio'
    for row,rule in enumerate(GROUP_RULES,3):index.cell(row,1,rule)
    index.append([])
    header_row=12
    for col,value in enumerate(('Entity ID','Public business case','Original sheet','Portfolio sheet'),1):index.cell(header_row,col,value)
    entity_records,expected,templates,formula_snapshot=[],{},[],{}
    economic_fingerprints=set()
    row=header_row+1
    for case in cases:
        directory=private/'entities'/case['id'];directory.mkdir(parents=True)
        requested=deepcopy(base);requested['scenario_id']=config['portfolio_id']+'-'+case['id'].lower()
        for patch,key in (('hypothetical_patch','hypothetical_parameters'),('covenant_patch','covenant_parameters'),('advanced_tax_patch','advanced_tax_parameters')):
            requested[key].update(deepcopy(case.get(patch,{})))
        requested['case_description']={key:case[key] for key in ('id','name','mechanism')}
        fp=json.dumps({key:requested[key] for key in ('hypothetical_parameters','covenant_parameters','advanced_tax_parameters')},sort_keys=True)
        if fp in economic_fingerprints:raise ValueError('Duplicate economic subsidiaries are not allowed')
        economic_fingerprints.add(fp)
        requested_path=directory/'requested_config.json';_write(requested_path,requested)
        spec=apply_public_presentation(resolve_spec(root,requested_path),requested['public_presentation'])
        if spec.get('presentation_version',0)<2:raise ValueError('Business brief must include the corrected capped cure counter')
        ledger=simulate(spec)
        if not ledger_invariants_pass(ledger['checks']):raise ValueError('Invalid independent entity journal: '+case['id'])
        regimes=adapter.observed_regimes(spec,ledger)
        missing=[key for key in case['required_regimes'] if not regimes[key]['observed']]
        if missing:raise ValueError('Untriggered required mechanisms for '+case['id']+': '+','.join(missing))
        raw=directory/'model_unrecalculated.xlsx';bindings=emit_workbook(spec,raw)
        original=openpyxl.load_workbook(raw,keep_links=False)
        mapping={name:case['id']+' '+name for name in original.sheetnames}
        _copy_entity(original,book,mapping)
        entity_expectations=_compile_expectations(raw,spec,ledger,bindings,mapping)
        if set(expected)&set(entity_expectations):raise ValueError('Overlapping independent expectations')
        expected.update(entity_expectations)
        fm=propose_project_task(raw,'financial_modeling')
        fm['mask_ranges']=[{**region,'sheet':mapping[region['sheet']]} for region in fm['mask_ranges']]
        for old,new in mapping.items():
            for col,value in enumerate((case['id'],case['name'],old,new),1):index.cell(row,col,value)
            row+=1
        for sheet in original:
            for cell in sheet._cells.values():
                if cell.data_type=='f':formula_snapshot[mapping[sheet.title]+'!'+cell.coordinate]=rewrite_formula(cell.value,mapping)
        original.close()
        _write(directory/'public_scenario.json',spec);_write(directory/'ledger.json',ledger)
        _write(directory/'bindings.json',bindings);_write(directory/'mapped_bindings.json',namespace_bindings(bindings,mapping))
        _write(directory/'regimes.json',regimes)
        entity={'id':case['id'],'case':case,'spec':spec,'ledger':ledger,'bindings':bindings,'mapping':mapping,'raw':str(raw.resolve())}
        entity_records.append(entity)
        templates.append({'entity_id':case['id'],'case_name':case['name'],'sheet_mapping':mapping,
                          'original_bindings':bindings,'mapped_bindings':namespace_bindings(bindings,mapping),
                          'financial_modeling_plan':fm,'debugging_plan_status':'requires_recalculated_cached_values',
                          'original_raw':_ref(raw)})
    group=_aggregate_independent(entity_records)
    group_bindings=_emit_group(book,entity_records,group,expected)
    for title in PUBLIC_SHEETS[1:]:
        for cell in book[title]._cells.values():
            if cell.data_type=='f':formula_snapshot[title+'!'+cell.coordinate]=cell.value
    if {key:value for key,value in expected.items() if key.startswith(('Group Statements!','Group Summary!'))} != _group_expectations(group,group_bindings):
        raise ValueError('Group independent bindings disagree with emitted coverage')
    raw=private/'portfolio_unrecalculated.xlsx'
    book.calculation=openpyxl.workbook.properties.CalcProperties(calcId=191029,fullCalcOnLoad=True,forceFullCalc=True)
    book.save(raw)
    all_formulas={sheet.title+'!'+cell.coordinate for sheet in book for cell in sheet._cells.values() if cell.data_type=='f'}
    if all_formulas!=set(formula_snapshot) or all_formulas-set(expected):raise ValueError('Portfolio formula coverage is incomplete')
    financial_formulas={address for address in all_formulas if expected[address]['kind'] in {'money','ratio'}
        and not any(address.startswith(e['mapping'][name]+'!') for e in entity_records for name in ('Read Me','Source Inputs','Scenario','Calendar'))}
    if len(financial_formulas)<config['minimum_numeric_financial_formulas']:raise ValueError('Portfolio has insufficient genuine numeric financial formulas')
    group_masks=[]
    for name in PUBLIC_SHEETS[1:]:
        cells={(cell.row,cell.column) for cell in book[name]._cells.values() if cell.data_type=='f' and not cell.is_date}
        group_masks.extend(_formula_rectangles(name,cells))
    index.column_dimensions['A'].width=20
    for col in ('B','C','D'):index.column_dimensions[col].width=40
    index.freeze_panes='A13'
    # Index formatting is saved with the final source too.
    book.save(raw);book.close()
    _write(private/'independent_expectations.json',expected)
    _write(private/'formula_snapshot.json',formula_snapshot)
    _write(private/'group_ledger.json',group)
    _write(private/'group_bindings.json',group_bindings)
    _write(private/'financial_formula_roots.json',sorted(financial_formulas))
    sheet_count=len(book.sheetnames)
    reconstruction={'schema_version':1,'entity_prefix_separator':' ','public_index_sheet':'Portfolio Index',
                    'entities':templates,'group_mask_ranges':group_masks,'group_bindings':group_bindings,
                    'all_formula_count':len(all_formulas),'numeric_financial_formula_count':len(financial_formulas),
                    'prepared_only':True,'qualified':False,'task_count':0}
    _write(private/'reconstruction_templates.json',reconstruction)
    public={'portfolio_id':config['portfolio_id'],'public_contract_version':7,'presentation_version':2,
            'entity_count':len(entity_records),'ownership_fraction':'1','intercompany_transactions':False,
            'parent_operating_balances':False,'public_rules':GROUP_RULES,'source_lineage':entity_records[0]['spec']['source_lineage'],
            'entities':[{'entity_id':e['id'],'sheet_mapping':e['mapping'],'public_scenario':e['spec']} for e in entity_records]}
    _write(output/'public_scenario.json',public)
    manifest={'schema_version':1,'dataset':'hypothetical_financial_portfolio','status':'prepared_pending_real_LO',
              'created_at':datetime.now(timezone.utc).isoformat(),'qualified':False,'task_count':0,'selected':[],
              'download_url':'derived-seed-pool:hypothetical-portfolio','archive_sha256':None,
              'unique_workbooks_inspected':0,'ancestor_unique_count':1,'entity_count':len(entity_records),
              'source_ancestor_sha256':base['source']['sha256'],'source_ancestor':base['source'],
              'raw_workbook':_ref(raw),'public_scenario':_ref(output/'public_scenario.json'),
              'sheet_count':sheet_count,
              'formula_count':len(all_formulas),'numeric_financial_formula_count':len(financial_formulas),
              'all_formula_cells_have_independent_expectations':True,'all_entity_ledgers_passed':True,
              'all_required_mechanisms_observed':True,'group_checks':group['checks'],
              'recipe':recipe,'config':_ref(config_path),'api_calls':0,'llm_tokens':0,
              'elapsed_seconds':round(time.monotonic()-started,6),'entities':[{'id':e['id'],'case':e['case'],
                    'sheet_mapping':e['mapping'],'public_scenario':_ref(private/'entities'/e['id']/'public_scenario.json'),
                    'ledger':_ref(private/'entities'/e['id']/'ledger.json'),
                    'bindings':_ref(private/'entities'/e['id']/'bindings.json'),
                    'mapped_bindings':_ref(private/'entities'/e['id']/'mapped_bindings.json'),
                    'regimes':_ref(private/'entities'/e['id']/'regimes.json')} for e in entity_records]}
    for key,path in [('reconstruction_templates',private/'reconstruction_templates.json'),('independent_expectations',private/'independent_expectations.json'),
                     ('formula_snapshot',private/'formula_snapshot.json'),('financial_formula_roots',private/'financial_formula_roots.json'),
                     ('group_ledger',private/'group_ledger.json'),('group_bindings',private/'group_bindings.json')]:manifest[key]=_ref(path)
    if any(_sha(Path(value['path']))!=value['sha256'] for value in recipe.values()):raise ValueError('Source recipe changed during preparation')
    _write(output/'manifest.json',manifest)
    return manifest


def _matches(got,want,kind):
    if kind=='date':
        observed=got.date().isoformat() if isinstance(got,datetime) else got.isoformat() if isinstance(got,date) else str(got)
        return observed==str(want)
    if isinstance(got,bool) or not isinstance(got,(int,float)) or not math.isfinite(got):return False
    observed,expected=Decimal(str(got)),Decimal(str(want))
    if kind in {'money','source_number'}:return posted_money_matches(observed,expected)
    if kind=='control':return observed==expected and observed==observed.to_integral_value()
    return abs(observed-expected)<=Decimal('0.0000000001' if kind=='ratio' else '0.000001')


def verify_portfolio(project_root,output):
    """Real LO verification; a failed attempt is immutable and never selected."""
    root,output=Path(project_root).resolve(),Path(output).resolve()
    manifest=json.loads((output/'manifest.json').read_text())
    if manifest['status']!='prepared_pending_real_LO':raise ValueError('Only an unattempted prepared source can be verified')
    for proof in [manifest['raw_workbook'],manifest['public_scenario'],*manifest['recipe'].values(),
                  manifest['reconstruction_templates'],manifest['independent_expectations'],manifest['formula_snapshot'],
                  manifest['financial_formula_roots'],manifest['group_ledger'],manifest['group_bindings']]:
        if _sha(proof['path'])!=proof['sha256']:raise ValueError('Immutable source or recipe changed')
    # Reproduce all journal expectations from the publicly disclosed scenarios.
    expected={}
    for record in manifest['entities']:
        for key in ('public_scenario','ledger','bindings','mapped_bindings','regimes'):
            if _sha(record[key]['path'])!=record[key]['sha256']:raise ValueError('Entity evidence changed')
        spec=json.loads(Path(record['public_scenario']['path']).read_text())
        replay=simulate(spec)
        saved=json.loads(Path(record['ledger']['path']).read_text())
        if json.loads(json.dumps(replay,default=str))!=saved or not ledger_invariants_pass(replay['checks']):raise ValueError('Entity independent journal replay failed')
        bindings=json.loads(Path(record['bindings']['path']).read_text())
        raw=Path(record['ledger']['path']).parent/'model_unrecalculated.xlsx'
        expected.update(_compile_expectations(raw,spec,replay,bindings,record['sheet_mapping']))
    saved_expected=json.loads(Path(manifest['independent_expectations']['path']).read_text())
    # Group expected values are recomputed from the replayed independent journals.
    replay_entities=[{'spec':json.loads(Path(r['public_scenario']['path']).read_text()),
                      'ledger':simulate(json.loads(Path(r['public_scenario']['path']).read_text())),
                      'bindings':json.loads(Path(r['bindings']['path']).read_text())} for r in manifest['entities']]
    group=_aggregate_independent(replay_entities)
    if json.loads(json.dumps(group,default=str))!=json.loads(Path(manifest['group_ledger']['path']).read_text()):raise ValueError('Independent group journal replay failed')
    group_bindings=json.loads(Path(manifest['group_bindings']['path']).read_text())
    expected.update(_group_expectations(group,group_bindings))
    if expected!=saved_expected:raise ValueError('Independent formula expectations differ from complete public-scenario replay')
    private=output/'private';first=private/'first_recalculation.xlsx';final=output/'portfolio_model.xlsx'
    engine=LibreOfficeEngine(root);started=time.monotonic();metadata=engine.metadata()
    manifest.update(status='verification_running',runtime=metadata)
    _write(output/'manifest.json',manifest)
    try:
        engine.recalculate(Path(manifest['raw_workbook']['path']),first)
        engine.recalculate(first,final)
        stable=compare_workbooks(first,first,final)
        cached=openpyxl.load_workbook(final,data_only=True,keep_links=False)
        formulas=openpyxl.load_workbook(final,data_only=False,keep_links=False)
        checks=[]
        for address,want in saved_expected.items():
            sheet,cell=address.rsplit('!',1);got=cached[sheet][cell].value
            checks.append({'address':address,**want,'observed':str(got),'passed':_matches(got,want['expected_independent'],want['kind'])})
        actual_formulas={sheet.title+'!'+cell.coordinate for sheet in formulas for cell in sheet._cells.values() if cell.data_type=='f'}
        raw_formulas=json.loads(Path(manifest['formula_snapshot']['path']).read_text())
        errors=[{'address':sheet.title+'!'+cell.coordinate,'value':cell.value} for sheet in cached for cell in sheet._cells.values() if cell.data_type=='e']
        invalid=[address for address in actual_formulas if cached[address.rsplit('!',1)[0]][address.rsplit('!',1)[1]].value is None]
        uncovered=sorted(actual_formulas-set(saved_expected))
        formula_cells_unchanged=actual_formulas==set(raw_formulas)
        failed=[row for row in checks if not row['passed']]
        passed=not failed and not errors and not invalid and not uncovered and formula_cells_unchanged and stable['reward']==1
        audit={'passed':passed,'checked_cells':len(checks),'formula_count':len(actual_formulas),
               'all_formula_cells_independently_covered':not uncovered,'formula_cell_set_preserved':formula_cells_unchanged,
               'uncovered_formulas':uncovered,'cached_errors':errors,'invalid_formula_values':invalid,
               'mismatches':failed,'cell_checks':checks,'all_entity_ledger_invariants_passed':True,
               'group_independent_checks':group['checks'],'two_recalculations_typed_stable':stable['reward']==1,
               'qualification':'Source validation only; no task quality or difficulty qualification is implied.'}
        _write(private/'financial_audit.json',audit);_write(private/'stability.json',stable)
        cached.close();formulas.close()
        manifest.update(status='financially_verified_planning_seed' if passed else 'rejected_financial_source',
                        financial_audit_passed=passed,financial_audit=_ref(private/'financial_audit.json'),
                        stability=_ref(private/'stability.json'),verification_elapsed_seconds=round(time.monotonic()-started,6),
                        local_path=str(final.resolve()),derived_workbook_sha256=_sha(final),unique_workbooks_inspected=1)
        if passed:
            evidence={'classification':'hypothetical_advanced_tax_covenant_portfolio','financial_modeling_eligible':True,
                'debugging_eligible':True,'finance_eligible':True,'scenario_required':False,'financial_seed_verified':True,
                'task_business_correctness_certified':False,'entity_count':manifest['entity_count'],
                'source_business_issues':[],'public_contract_version':7,'presentation_style':'business_brief',
                'audit_proofs':{key:manifest[key] for key in ('financial_audit','stability','public_scenario','group_ledger','independent_expectations')},
                'recipe_proofs':manifest['recipe'],'reconstruction_templates':manifest['reconstruction_templates'],
                'safe_modules':[{'case_id':'integrated-portfolio','business_goal':'Reconstruct or repair separately financed subsidiaries and consolidated financial statements',
                                 'candidate_regions':[], 'required_public_rules':GROUP_RULES}]}
            manifest['selected']=[{'sha256':_sha(final),'source_sha256':_sha(final),'local_path':str(final.resolve()),
                'source_kind':'derived_hypothetical_financial_portfolio','source_url':manifest['source_ancestor']['source_url'],
                'source_url_scope':'Ancestor benchmark attribution only; the portfolio is explicitly hypothetical',
                'source_ancestor_sha256':manifest['source_ancestor_sha256'],'source_lineage':json.loads(Path(manifest['public_scenario']['path']).read_text())['source_lineage'],
                'scenario_id':json.loads(Path(manifest['public_scenario']['path']).read_text())['portfolio_id'],
                'case_id':'PORTFOLIO12','sheet_count':manifest['sheet_count'],'nonempty_sheet_count':manifest['sheet_count'],
                'formula_count':manifest['formula_count'],'public_contract_version':7,'modes':['financial_modeling','debugging'],
                'financial_modeling_eligible':True,'debugging_eligible':True,'finance_eligible':True,'scenario_required':False,
                'qualified':False,'task_count':0,'finance_evidence':evidence,'verification_backend':'independent_Decimal_and_real_LibreOffice'}]
        _write(output/'manifest.json',manifest)
        return manifest
    except Exception as exc:
        manifest.update(status='verification_failed',error={'type':type(exc).__name__,'message':str(exc)},verification_elapsed_seconds=round(time.monotonic()-started,6))
        _write(output/'manifest.json',manifest)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=ROOT)
    parser.add_argument('--config',type=Path,default=Path('config/derived_portfolio_v1.json'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify-existing',type=Path)
    parser.add_argument('--recalculate',action='store_true',help='Run two real LibreOffice calculations and full independent audit')
    args=parser.parse_args(argv)
    if args.verify_existing:
        result=verify_portfolio(args.project_root,args.verify_existing)
    else:
        output=args.output or args.project_root/'outputs/research'/('portfolio_source_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        result=prepare_portfolio(args.project_root,args.config,output)
        if args.recalculate:result=verify_portfolio(args.project_root,output)
    print(json.dumps({key:result.get(key) for key in ('status','raw_workbook','local_path','entity_count','sheet_count','formula_count','numeric_financial_formula_count','financial_audit_passed','qualified','task_count','api_calls','llm_tokens')}))
    return 0 if result['status'] in {'prepared_pending_real_LO','financially_verified_planning_seed'} else 1


if __name__=='__main__':raise SystemExit(main())
