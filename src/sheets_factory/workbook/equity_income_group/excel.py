"""Native circular formulas and unverified FM/DBG prototypes; never starts LO."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from . import spec, decimal_oracle, fraction_oracle

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ITERATIONS = 10000
ITERATION_DELTA = 1e-12


def reference(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream: json.dump(value,stream,indent=2,allow_nan=False); stream.write('\n')
    return reference(path)


def _rewrite(source, destination, edits):
    """Apply only declared cell edits/caches to a new OOXML container."""
    with ZipFile(source) as original, ZipFile(destination,'x',ZIP_DEFLATED) as target:
        sheets = ET.fromstring(original.read('xl/workbook.xml')).find('{*}sheets')
        parts = {s.get('name'):f'xl/worksheets/sheet{i+1}.xml' for i,s in enumerate(sheets)}
        by_part = {parts[sheet]:cells for sheet,cells in edits.items()}
        for item in original.infolist():
            raw = original.read(item.filename)
            if item.filename in by_part:
                root = ET.fromstring(raw)
                for cell in root.findall('{*}sheetData/{*}row/{*}c'):
                    address = cell.get('r')
                    if address in by_part[item.filename]: by_part[item.filename][address](cell)
                raw = ET.tostring(root,encoding='utf-8',xml_declaration=True)
            target.writestr(item,raw)


def _no_cache(cell):
    for child in list(cell):
        if child.tag.rsplit('}',1)[-1] == 'v': cell.remove(child)


def _blank(cell):
    for child in list(cell):
        if child.tag.rsplit('}',1)[-1] in {'v','f','is'}: cell.remove(child)
    cell.attrib.pop('t',None)


def _formula(metric, row, all_rows, entity_index, column, previous):
    here = lambda key: f'{column}{row[key]}'
    opening = {'opening_cash':'F','opening_ppe':'G','opening_investment':'H','opening_retained':'I','opening_loss':'K'}
    if metric in opening:
        return (f"'Opening'!{opening[metric]}{entity_index+2}" if previous is None
            else f'{previous}{row[metric.replace("opening_","closing_")]}')
    if metric in {'debt','paid_in_capital'}:
        return f"'Opening'!{'E' if metric=='debt' else 'J'}{entity_index+2}"
    if metric == 'interest': return f"'Opening'!E{entity_index+2}*'Opening'!D{entity_index+2}/4"
    if metric == 'equity_income':
        return '+'.join(f"'Ownership'!{get_column_letter(j+2)}{entity_index+2}*{column}{r['net_income']}"
            for j,r in enumerate(all_rows)) or '0'
    h = here
    return {'operating_profit':f'{h("revenue")}-{h("cash_opex")}-{h("depreciation")}',
        'standalone_pretax':f'{h("operating_profit")}-{h("interest")}',
        'pretax_profit':f'{h("standalone_pretax")}+{h("equity_income")}',
        'taxable_profit':f'MAX(0,{h("pretax_profit")}-{h("opening_loss")})',
        'current_tax':f"'Opening'!C{entity_index+2}*{h('taxable_profit')}",
        'net_income':f'{h("pretax_profit")}-{h("current_tax")}',
        'closing_loss':f'MAX(0,{h("opening_loss")}-{h("pretax_profit")})',
        'operating_cashflow':f'{h("net_income")}-{h("equity_income")}+{h("depreciation")}',
        'closing_cash':f'{h("opening_cash")}+{h("operating_cashflow")}-{h("capex")}',
        'closing_ppe':f'{h("opening_ppe")}+{h("capex")}-{h("depreciation")}',
        'closing_investment':f'{h("opening_investment")}+{h("equity_income")}',
        'closing_retained':f'{h("opening_retained")}+{h("net_income")}',
        'assets':f'{h("closing_cash")}+{h("closing_ppe")}+{h("closing_investment")}',
        'liabilities_and_equity':f'{h("debt")}+{h("paid_in_capital")}+{h("closing_retained")}',
        'balance_residual':f'{h("assets")}-{h("liabilities_and_equity")}'}[metric]


def emit_workbook(path, public, result):
    """Write correct formulas with explicitly unverified oracle-seeded caches."""
    public = spec.validate(public); path = Path(path)
    spec.require(not path.exists() and result['specification_sha256'] == spec.canonical_sha256(public), 'Use a fresh goal and the exact specification')
    book = openpyxl.Workbook(); cover = book.active; cover.title = 'Read Me'
    cover.append(['Synthetic equity-income management group'])
    for line in spec.POLICY: cover.append([line])
    cover.column_dimensions['A'].width = 120
    opening = book.create_sheet('Opening'); opening.append(list(spec.ENTITY_FIELDS))
    for entity in public['entities']: opening.append([entity[k] if k in ('id','name') else float(Decimal(entity[k])) for k in spec.ENTITY_FIELDS])
    holdings = book.create_sheet('Ownership'); holdings.append(['Owner / investee']+result['entity_order'])
    for entity,weights in zip(public['entities'],public['ownership'],strict=True): holdings.append([entity['id']]+[float(Decimal(v)) for v in weights])
    history = book.create_sheet('History'); history.append(['Before investment arrangements','Revenue','Cash opex','Depreciation','Interest','Equity income'])
    for eid in result['entity_order']: history.append([eid]+[float(Decimal(public['history'][eid][key])) for key in ('revenue','cash_opex','depreciation','interest','equity_income')])
    caches = {}; bindings = []; root_edits = []
    for scenario,computed in zip(public['scenarios'],result['scenarios'],strict=True):
        sheet = book.create_sheet(scenario['id']+' Entities'); group = book.create_sheet(scenario['id']+' Group')
        maps = [{key:6+i*(len(spec.ENTITY_METRICS)+3)+k for k,key in enumerate(spec.ENTITY_METRICS)} for i in range(len(public['entities']))]
        gr = {key:k+5 for k,key in enumerate(spec.GROUP_METRICS)}
        for table in (sheet,group):
            table['A1'] = scenario['name']+' — GBP thousands'; table.freeze_panes = 'C5'; table.column_dimensions['A'].width = 34
            for q,label in enumerate(public['periods'],3): table.cell(3,q,label); table.column_dimensions[get_column_letter(q)].width = 16
        for entity,rows in zip(public['entities'],maps,strict=True):
            sheet.cell(min(rows.values())-1,1,entity['id']+' '+entity['name'])
            for metric,row in rows.items(): sheet.cell(row,1,'Share of profit / (loss) from holdings' if metric=='equity_income' else metric.replace('_',' ').title())
        for metric,row in gr.items(): group.cell(row,1,metric.replace('_',' ').title())
        for q,quarter in enumerate(computed['periods']):
            col = get_column_letter(q+3); previous = get_column_letter(q+2) if q else None
            for i,entity in enumerate(public['entities']):
                eid = entity['id']; rows = maps[i]
                for metric,row in rows.items():
                    cell = sheet.cell(row,q+3); cell.number_format = '#,##0.00;[Red](#,##0.00)'
                    if metric in spec.INPUT_FIELDS:
                        cell.value = float(Decimal(scenario['inputs'][eid][q][metric])); cell.font = Font(color='0000FF')
                        continue
                    cell.value = '='+_formula(metric,rows,maps,i,col,previous)
                    value = quarter['entities'][eid][metric]
                    caches.setdefault(sheet.title,{})[cell.coordinate] = value
                    binding = {'sheet':sheet.title,'cell':cell.coordinate,'scenario':scenario['id'],'period':quarter['period'],'entity':eid,'metric':metric}
                    bindings.append(binding)
                    if metric == 'net_income': root_edits.append({**binding,'before':cell.value,
                        'after':f'={col}{rows["standalone_pretax"]}-{col}{rows["equity_income"]}-{col}{rows["current_tax"]}'})
            total = lambda key: 'SUM('+','.join(f"'{sheet.title}'!{col}{row[key]}" for row in maps)+')'
            local = lambda key: f'{col}{gr[key]}'
            for metric,row in gr.items():
                if metric in {'entity_equity_income','reported_entity_net_income','entity_investments'}:
                    expression = total({'entity_equity_income':'equity_income','reported_entity_net_income':'net_income','entity_investments':'closing_investment'}[metric])
                elif metric in {'equity_income_elimination','investment_elimination'}:
                    expression = '-'+local('entity_equity_income' if metric=='equity_income_elimination' else 'entity_investments')
                elif metric == 'combined_capital': expression = total('paid_in_capital')+'+'+total('closing_retained')+'+'+local('investment_elimination')
                elif metric == 'external_net_income': expression = local('standalone_pretax')+'-'+local('current_tax')
                elif metric == 'assets': expression = local('closing_cash')+'+'+local('closing_ppe')
                elif metric == 'liabilities_and_capital': expression = local('debt')+'+'+local('combined_capital')
                elif metric == 'balance_residual': expression = local('assets')+'-'+local('liabilities_and_capital')
                elif metric == 'profit_reconciliation_residual': expression = local('reported_entity_net_income')+'+'+local('equity_income_elimination')+'-'+local('external_net_income')
                elif metric == 'cash_reconciliation_residual': expression = local('closing_cash')+'-'+local('opening_cash')+'-('+local('operating_cashflow')+'-'+local('capex')+')'
                else: expression = total(metric)
                cell = group.cell(row,q+3,'='+expression); cell.number_format = '#,##0.00;[Red](#,##0.00)'
                caches.setdefault(group.title,{})[cell.coordinate] = quarter['group'][metric]
                bindings.append({'sheet':group.title,'cell':cell.coordinate,'scenario':scenario['id'],'period':quarter['period'],'entity':None,'metric':metric})
    book.calculation = CalcProperties(calcMode='auto',fullCalcOnLoad=True,forceFullCalc=True,
        iterate=True,iterateCount=ITERATIONS,iterateDelta=ITERATION_DELTA)
    temporary = path.with_name(path.name+'.uncached.xlsx'); book.save(temporary); book.close()
    edits = {}
    for sheet,rows in caches.items():
        edits[sheet] = {}
        for cell,value in rows.items():
            def seed(node,value=value):
                _no_cache(node); node.attrib.pop('t',None); ET.SubElement(node,'{'+S+'}v').text = format(value,'f')
            edits[sheet][cell] = seed
    _rewrite(temporary,path,edits); temporary.unlink()
    return {'bindings':bindings,'DBG_root_edits':root_edits,'oracle_seeded_caches_unverified':True,
        'actual_LO_calls':0,'native_feedback_convergence_verified':False,'qualified':False}


def build_views(output, public=None):
    """Pure preparation: cross-check A/B, emit goal, FM mask and DBG sign fault."""
    output = Path(output).resolve(); spec.require(not output.exists(),'Use a fresh prototype output')
    public = spec.build_spec() if public is None else spec.validate(public)
    a = decimal_oracle.solve(public); b = fraction_oracle.solve(public)
    checked = 0
    for sa,sb in zip(a['scenarios'],b['scenarios'],strict=True):
        for qa,qb in zip(sa['periods'],sb['periods'],strict=True):
            for ra,rb in [(qa['entities'][eid],qb['entities'][eid]) for eid in a['entity_order']]+[(qa['group'],qb['group'])]:
                for key in ra:
                    spec.require(Decimal(decimal_oracle.display(ra[key])) == Decimal(fraction_oracle.display(rb[key])), 'The two independent financial oracles disagree')
                    checked += 1
    output.mkdir(parents=True); raw = write(output/'private/specification.json',public)
    goal = output/'private/goal_seeded_unverified.xlsx'; bindings = emit_workbook(goal,public,a)
    expected = {}
    lookup = {scenario['id']:{q['period']:q for q in scenario['periods']} for scenario in b['scenarios']}
    for row in bindings['bindings']:
        q = lookup[row['scenario']][row['period']]; values = q['entities'][row['entity']] if row['entity'] else q['group']
        expected[row['sheet']+'!'+row['cell']] = {'type':'number','value':fraction_oracle.display(values[row['metric']])}
    views = {}; root_lookup = {(r['sheet'],r['cell']):r for r in bindings['DBG_root_edits']}
    for mode in ('financial_modeling','debugging'):
        folder = output/mode; folder.mkdir(); edits = {}
        for row in bindings['bindings']:
            key = row['sheet'],row['cell']
            if mode == 'financial_modeling': operation = _blank
            elif key in root_lookup:
                def operation(cell,formula=root_lookup[key]['after']):
                    cell.find('{*}f').text = formula[1:]; _no_cache(cell)
            else: operation = _no_cache
            edits.setdefault(row['sheet'],{})[row['cell']] = operation
        _rewrite(goal,folder/'input.xlsx',edits)
        text = ('Complete every forecast entity and management-group statement.' if mode=='financial_modeling'
            else 'Audit and repair the forecast entity and management-group statements so that the stated policies and all reconciliations hold.')
        instruction = (text+'\n\n'+f"Cover {public['periods'][0]} through {public['periods'][-1]} for every listed entity and independent scenario. "
            'Use the supplied opening balances, operating assumptions and ownership data. '
            'The Read Me sheet states the business policies and reporting convention. The supplied data are synthetic.\n')
        (folder/'instruction.md').write_text(instruction)
        views[mode] = {'input':reference(folder/'input.xlsx'),'instruction':reference(folder/'instruction.md')}
    return write(output/'preparation.json',{'kind':'prepared_unverified_synthetic_equity_income_group_pair','version':1,
        'specification':raw,'specification_sha256':spec.canonical_sha256(public),'goal':reference(goal),'views':views,
        'bindings':write(output/'private/bindings.json',bindings),'independent_expected':write(output/'private/expected_normalized.json',expected),
        'dimensions':{'entities':len(public['entities']),'quarters':len(public['periods']),'scenarios':len(public['scenarios'])},
        'independent_oracle_cells_crosschecked':checked,'FM_mask_count':len(bindings['bindings']),'DBG_root_count':len(bindings['DBG_root_edits']),
        'iteration_settings':{'enabled':True,'count':ITERATIONS,'delta':ITERATION_DELTA},
        'recipe_sha256':{str(Path(m.__file__).resolve()):reference(m.__file__)['sha256'] for m in (spec,decimal_oracle,fraction_oracle)},
        'emitter':reference(__file__),'source_type':'new_synthetic','official_workbook_seed_used':False,
        'oracle_seeded_goal_is_not_native_validation':True,'native_feedback_convergence_verified':False,
        'actual_LO_calls':0,'model_calls':0,'qualified':False,'normal_quality_or_difficulty_certified':False})
