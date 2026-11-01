#!/usr/bin/env python3
"""Cold source3 validation using stored independent waterfall ledgers, no forwards."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook.waterfall_portfolios_v1 import schema

ANCESTOR = ROOT / 'scripts/build_equity_income_group_source.py'
ANCESTOR_SHA = '1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690'
FIRST_RAW_SHA = '2dc3d88fab5afc26d036b8f566e30d3a02fd9a09f2756e29cebd8f2f09dcacb4'
FIRST_COMPARE_SHA = 'ac2989a10b0a385ba64ff7471e643e29ac6169c2d6692c35cd5fbec02449b9dc'
FIRST_A_FORWARD_SHA = '0926aa9a3f9587725a96b6259758514ff756f6e5e728ba4c255c2ac70cfb51de'
FIRST_B_FORWARD_SHA = '02ecc6091dac7fa132a1e3904970c43cf71fd0092f569ac87da809a145655314'
KIND = 'prepared_waterfall_portfolios_cold_source3'
SOURCE_KIND = 'independently_checked_waterfall_portfolios_cold_source3'
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
EMITTER = ROOT / 'src/sheets_factory/workbook/waterfall_portfolios_v1/excel.py'
EMITTER_SHA = 'c24e47da24e6898326927a3ca8f09bfb7bae5d0eca9f1e5d36880722433d3571'
USES = {'investment_cash_use':'asset_investment', 'management_fee_cash_use':'management_fee',
    'operating_cost_cash_use':'operating_cost', 'capital_cash_use':'capital_paid',
    'preference_cash_use':'preference_paid', 'catchup_cash_use':'catchup_paid',
    'lp_promote_cash_use':'lp_promote_cash', 'gp_promote_cash_use':'gp_promote_cash'}


def _load_ancestor():
    raw = ANCESTOR.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ANCESTOR_SHA:
        raise ValueError('The frozen genuine source3 lifecycle changed')
    tree = ast.parse(raw); removed = 0; check_calls = 0; early = 0; settings = 0; inserted = 0; terminal = 0
    omitted = {'recipes','crosscheck','source_definition','prepare','validate_prepared','main'}
    keep = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'sheets_factory.workbook.equity_income_group':
            removed += 1; continue
        if isinstance(node, ast.FunctionDef) and node.name in omitted:
            continue
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and ast.unparse(node.test) == "__name__ == '__main__'":
            continue
        keep.append(node)
    tree.body = keep

    class Adapt(ast.NodeTransformer):
        scope = None

        def visit_FunctionDef(self,node):
            previous=self.scope;self.scope=node.name
            node=self.generic_visit(node);self.scope=previous
            return node

        def visit_Constant(self, node):
            if isinstance(node.value, str):
                value = node.value.replace('equity_source.', 'waterfall_source.').replace('_equity_group_resource_support','_waterfall_resource_support')
                value = value.replace('Equity-income cold-start source','Waterfall stored-ledger cold-start source')
                value = value.replace('full_independent_equity_income_native_cache_audit','full_independent_waterfall_native_cache_audit')
                if value == 'prepared_equity_income_group_cold_start_source': value = KIND
                if value == 'independently_checked_equity_income_group_iterative_source': value = SOURCE_KIND
                node.value = value
            return node

        def visit_Assign(self, node):
            nonlocal early
            if self.scope=='execute_prepared' and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='f' and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='validate_prepared':
                early += 1; node.value.func.id='_metadata_prepared'
            return self.generic_visit(node)

        def visit_Call(self, node):
            nonlocal check_calls, settings, terminal
            if isinstance(node.func,ast.Name) and node.func.id=='crosscheck':
                check_calls += 1
                return ast.copy_location(ast.Call(func=ast.Name(id='_crosscheck_prepared',ctx=ast.Load()),args=[ast.Name(id='f',ctx=ast.Load())],keywords=[]),node)
            if isinstance(node.func,ast.Name) and node.func.id=='require' and len(node.args)>1 and isinstance(node.args[1],ast.Constant) and node.args[1].value=='Native iteration settings changed':
                settings += 1
                return ast.copy_location(ast.Call(func=ast.Name(id='_require_noncircular',ctx=ast.Load()),args=[ast.Name(id='f',ctx=ast.Load())],keywords=[]),node)
            if (self.scope=='execute_prepared' and isinstance(node.func,ast.Name) and node.func.id=='write'
                    and len(node.args)==2 and isinstance(node.args[0],ast.BinOp)
                    and isinstance(node.args[0].right,ast.Constant) and node.args[0].right.value=='source_manifest.json'
                    and isinstance(node.args[1],ast.Dict)):
                terminal+=1
                for key,value in (('memoized_independent_ledgers',True),('new_financial_forwards',0)):
                    node.args[1].keys.append(ast.Constant(key));node.args[1].values.append(ast.Constant(value))
            return self.generic_visit(node)

        def visit_With(self,node):
            nonlocal inserted
            node=self.generic_visit(node)
            if len(node.items)==1 and isinstance(node.items[0].context_expr,ast.Call):
                call=node.items[0].context_expr
                if isinstance(call.func,ast.Name) and call.func.id=='stage' and len(call.args)>1 and isinstance(call.args[1],ast.Constant) and call.args[1].value=='independent_AB_financial_check':
                    inserted += 1
                    node.body.insert(0,ast.parse('f = validate_prepared(output)').body[0])
            return node

    tree=Adapt().visit(tree);ast.fix_missing_locations(tree)
    if (removed,check_calls,early,settings,inserted,terminal)!=(1,2,1,1,1,1):
        raise ValueError('Unrecognized source3 family adaptation sites')
    private={'__name__':'_isolated_waterfall_source3_lifecycle','__file__':str(Path(__file__).resolve())}
    exec(compile(tree,str(ANCESTOR),'exec'),private)
    return private


_N = _load_ancestor()
for _name in ('require','reference','checked','read','write','typed','runtime','clear_all_formula_caches','compare_typed','owned_absence','validate_call','stage'):
    globals()[_name] = _N[_name]


def _ref(value): return dict(value) if isinstance(value,dict) else reference(value)


def _check_refs(value):
    if type(value) is dict:
        if set(value)=={'path','sha256','bytes'}:
            checked(value)
        else:
            for item in value.values():_check_refs(item)
    elif type(value) is list:
        for item in value:_check_refs(item)


def _path_value(public,path):
    require(type(path) is list and path and all(type(k) in (str,int) for k in path),'A raw fact needs an explicit public path')
    value=public
    for key in path:value=value[key]
    require(type(value) in (str,int,bool),'A provided fact must be a scalar public assumption')
    return value


def _fact_paths(value,path=()):
    if type(value) is dict:
        return set().union(*(_fact_paths(v,(*path,k)) for k,v in value.items())) if value else set()
    if type(value) is list:
        return set().union(*(_fact_paths(v,(*path,i)) for i,v in enumerate(value))) if value else set()
    return {path}


def _number(numerator,denominator=1):
    require(type(numerator) is int and type(denominator) is int and denominator>0,'Exact linear projections require integer operands')
    with localcontext() as context:
        context.prec=60
        value=(Decimal(numerator)/Decimal(denominator)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        return {'type':'number','value':'0' if not value else format(value.normalize(),'f')}


def _forward_evidence(evidence, comparison):
    for value in evidence.values():checked(value)
    require(evidence['forward_A']['sha256']==FIRST_A_FORWARD_SHA and evidence['forward_B']['sha256']==FIRST_B_FORWARD_SHA,
        'Use the two exact retained original forward receipts, not fabricated passed wrappers')
    a=read(evidence['forward_A']);b=read(evidence['forward_B'])
    require(a['kind']=='complete_single_original_waterfall_independent_A_forward' and a['version']==1
        and a['passed'] is True and a['financial_forward_calls']==1 and a['qualified'] is False
        and a['public_specification']==comparison['specification'] and a['result']==comparison['A'], 'Bind the actual original independent A forward')
    require(b['kind']=='complete_once_independent_B_waterfall_forward' and b['version']==1
        and b['passed'] is True and b['failure'] is None and b['logical_full_forward_invocations']==1
        and b['retries']==0 and b['raw_resampled'] is False and b['qualified'] is False
        and b['records']['result']==comparison['B'], 'Bind the actual original independent B forward')
    pa,pb=read(a['prospective']),read(b['prospective'])
    _check_refs(pa);_check_refs(pb);_check_refs(a);_check_refs(b)
    require(pa['implementation']=='A' and pa['public_specification']==comparison['specification']
        and pa['maximum_this_attempt_forward_calls']==1 and pa['prior_production_A_forwards']==0
        and pb['frozen_inputs_and_code']['raw']==comparison['specification'], 'Both actual forwards must bind the same once-frozen raw')
    a_codes=[v for k,v in pa['recipe'].items() if Path(k).name=='oracle_a.py']
    require(len(a_codes)==1 and a_codes[0]['sha256']==a['A_code_sha256'], 'Frozen A source hash must match its actual forward; never import A')
    require(read(b['records']['checks'])['passed'] is True, 'Actual B invariants receipt is required')
    return {'forward_A':evidence['forward_A'],'forward_B':evidence['forward_B'],
        'prospective_A':a['prospective'],'prospective_B':b['prospective'],'code_A_hash_only':a_codes[0],
        'code_B_hash_only':pb['frozen_inputs_and_code']['oracle_B']}


def compare_stored(public,comparison):
    """Compare complete stored ledgers; this function never executes an oracle."""
    schema.validate_spec(public)
    require(comparison['kind']=='complete_stored_independent_waterfall_A_B_comparison'
        and comparison['passed'] is True and comparison['differences']==[]
        and comparison['same_raw_no_resampling'] is True
        and comparison['new_financial_forward_calls_by_comparator']==0, 'A full stored comparison is required')
    a,b=read(comparison['A']),read(comparison['B'])
    row_order=[f"{f['id']}/{s['id']}/{p['year']}" for f in public['funds'] for s in f['scenarios'] for p in s['periods']]
    ag_order=[f'{s}/{y}' for s in public['scenario_ids'] for y in public['years']]
    canonical=schema.canonical_sha256(public)
    for implementation,result in (('A',a),('B',b)):
        require(result['kind']==schema.RESULT_KIND and result['version']==1 and result['implementation']==implementation
            and result['specification_sha256']==canonical and result['row_order']==row_order
            and result['aggregate_order']==ag_order and set(result['rows'])==set(row_order)
            and set(result['aggregates'])==set(ag_order),'Complete independent stored result identities are required')
    for key in row_order:
        left,right=a['rows'][key],b['rows'][key]
        require(set(left)==set(right)==set(schema.ROW_FIELDS)|{'lp_distribution_multiple','capital_and_pref_shortfall'},'Incomplete row field coverage')
        for field in schema.ROW_FIELDS:
            require(type(left[field]) is int and type(right[field]) is int and left[field]==right[field],'An exact independent posting differs')
        require(all(left[f]==0 for f in schema.INVARIANT_FIELDS),'All cash and principal/preference residuals must be zero')
        for row in (left,right):
            require(type(row['capital_and_pref_shortfall']) is bool and row['capital_and_pref_shortfall']==bool(row['closing_unreturned_capital'] or row['closing_unpaid_preference']), 'Typed shortfall Boolean differs')
            pair=row['lp_distribution_multiple']
            require(type(pair) is dict and set(pair)=={'numerator','denominator'}
                and all(type(v) is int for v in pair.values())
                and pair=={'numerator':row['cumulative_lp_distributions'],'denominator':row['cumulative_lp_paid_in']}
                and row['cumulative_lp_paid_in']>0, 'Exact unreduced LP multiple identity differs')
        require(left['capital_and_pref_shortfall']==right['capital_and_pref_shortfall'],'Independent shortfall differs')
    for key in ag_order:
        require(set(a['aggregates'][key])==set(b['aggregates'][key])==set(schema.AGGREGATE_FIELDS),'Incomplete aggregate fields')
        for field in schema.AGGREGATE_FIELDS:
            va,vb=a['aggregates'][key][field],b['aggregates'][key][field]
            require(type(va) is int and type(vb) is int and va==vb==sum(b['rows'][f"{f['id']}/{key}"][field] for f in public['funds']), 'Whole independent aggregate differs')
    require(comparison['row_count']==len(row_order) and comparison['aggregate_count']==len(ag_order)
        and comparison['integer_pence_fields_compared']==len(row_order)*56
        and comparison['integer_aggregate_pence_fields_compared']==len(ag_order)*20
        and comparison['LP_ratio_pairs_compared']==comparison['boolean_fields_compared']==len(row_order), 'The original full comparison census differs')
    return a,b


def project_expected(public,bindings,a,b):
    financial=bindings['financial'];expected={};coverage=Counter();seen=Counter()
    require(type(financial) is dict and financial,'All physical formula bindings are required')
    for point,entry in financial.items():
        require(point==entry['sheet']+'!'+entry['cell'] and type(entry['formula']) is str and entry['formula'].startswith('='),'A physical formula binding is malformed')
        require(('row_key' in entry)^('aggregate_key' in entry),'Exactly one independent row or aggregate key is required')
        is_row='row_key' in entry; key=entry['row_key'] if is_row else entry['aggregate_key'];field=entry['field'];projection=entry['projection']
        left=(a['rows'] if is_row else a['aggregates'])[key];right=(b['rows'] if is_row else b['aggregates'])[key]
        sign=entry['sign'];require(type(sign) is int and sign in (-1,1),'A presentation sign must be an exact +1 or -1')
        if projection=='bool':
            require(is_row and field=='capital_and_pref_shortfall' and sign==1,'Only the declared shortfall may be a Boolean projection')
            wanted=[{'type':'boolean','value':row[field]} for row in (left,right)]
        elif projection=='ratio2dp':
            require(is_row and field=='lp_distribution_multiple' and sign==1,'Only the declared LP multiple is a ratio projection')
            wanted=[_number(row[field]['numerator'],row[field]['denominator']) for row in (left,right)]
        else:
            require(field in (schema.ROW_FIELDS if is_row else schema.AGGREGATE_FIELDS),'Unknown monetary posting')
            if projection=='presentation_sign':
                require(is_row and entry.get('metric') in USES and USES[entry['metric']]==field
                    and entry['unit'] in ('pence','GBP'),'Unknown cash-use alias')
                fund=next(f for f in public['funds'] if f['id']==key.split('/')[0])
                require(sign==(-1 if fund['fund_ledger_sign']=='signed_cash_uses' else 1),'The public fund sign regime differs')
                denominator=100 if entry['unit']=='GBP' else 1
            else:
                require(projection in ('pence','GBP') and sign==1,'Unknown monetary projection or hidden sign reversal')
                denominator=100 if projection=='GBP' else 1
            wanted=[_number(sign*row[field],denominator) for row in (left,right)]
        require(wanted[0]==wanted[1], 'Independent projected physical values differ')
        expected[point]=wanted[0];coverage['row' if is_row else 'aggregate']+=1
        slot=(is_row,key,field,projection,entry.get('unit'));seen[slot]+=1
    for key in b['rows']:
        for field in schema.ROW_FIELDS:
            require(seen[True,key,field,'pence',None]==seen[True,key,field,'GBP',None]==1,'Each business posting needs one pence and one GBP cell')
        for field in USES.values():
            require(seen[True,key,field,'presentation_sign','pence']==seen[True,key,field,'presentation_sign','GBP']==1,'Each use needs both sign-aware displays')
        require(seen[True,key,'lp_distribution_multiple','ratio2dp',None]==1
            and seen[True,key,'capital_and_pref_shortfall','bool',None]==1,'Every row needs its typed ratio and Boolean')
    for key in b['aggregates']:
        for field in schema.AGGREGATE_FIELDS:
            require(seen[False,key,field,'pence',None]==seen[False,key,field,'GBP',None]==1,'Each aggregate needs pence and GBP cells')
    require(len(expected)==len(b['rows'])*130+len(b['aggregates'])*40,'The complete physical formula census differs')
    return expected


def _crosscheck_prepared(f):
    public=schema.validate_spec(read(f['specification']));comparison=read(f['financial_evidence']['comparison'])
    require(f['financial_evidence']['comparison']['sha256']==FIRST_COMPARE_SHA
        and comparison['specification']==f['specification'] and f['specification']['sha256']==FIRST_RAW_SHA,'Keep the fixed original raw and full independent comparison')
    lineage=_forward_evidence(f['financial_evidence'],comparison);a,b=compare_stored(public,comparison)
    expected=project_expected(public,read(f['bindings']),a,b)
    return expected,{'kind':'complete_memoized_independent_waterfall_source_projection','version':1,'passed':True,
        'comparison':f['financial_evidence']['comparison'],'original_forward_lineage':lineage,
        'row_count':len(b['rows']),'aggregate_count':len(b['aggregates']), 'complete_integer_row_values':len(b['rows'])*56,
        'complete_integer_aggregate_values':len(b['aggregates'])*20,'ratio_pairs':len(b['rows']),'shortfall_booleans':len(b['rows']),
        'physical_typed_formula_expectations':len(expected),'memoized_independent_ledgers':True,
        'new_financial_forwards':0,'shared_financial_state_or_tier_implementation':False,'qualified':False}


def _original_raw(candidate,comparison):
    """Retain both real files: the renderer copy never replaces the original raw REF."""
    public=schema.validate_spec(read(comparison['specification']))
    copied=schema.validate_spec(read(candidate['specification']))
    require(public==copied and candidate['specification_sha256']==schema.canonical_sha256(public),
        'The renderer specification copy must exactly equal the original once-frozen raw')
    return public,comparison['specification']


def _renderer_scope(candidate,bindings,definition):
    require(candidate['formula_count']==len(bindings['financial'])==len(definition['formulas'])==189600
        and candidate['sheet_count']==len(definition['sheetnames'])==100
        and candidate['FM_mask_count']==len(bindings['FM_mask_points'])==170640
        and candidate['DBG_root_count']==len(bindings['DBG_root_edits'])==1296,
        'Retain the complete fixed24-fund source and both planned task scopes')
    forecast={point for point,row in bindings['financial'].items()
        if int(row.get('row_key',row.get('aggregate_key')).split('/')[-1])>=2027}
    require(len(set(bindings['FM_mask_points']))==170640 and set(bindings['FM_mask_points'])==forecast
        and definition['FM_mask_points']==bindings['FM_mask_points'] and definition['DBG_root_edits']==bindings['DBG_root_edits'],
        'The entire forecast formula/helper/display mask and fixed root plan changed')
    root_keys=[]
    for root in bindings['DBG_root_edits']:
        point=root['sheet']+'!'+root['cell'];record=bindings['financial'][point]
        require(record['field']=='after_preference_cash' and record['projection']=='pence'
            and record['row_key']==root['row_key'] and root['before']==record['formula'],
            'Each fixed forecast root must bind its original positive posting definition')
        root_keys.append(record['row_key'])
    require(len(set(root_keys))==1296 and all(int(key.split('/')[-1])>=2027 for key in root_keys),'The forecast root inventory differs')


def _require_noncircular(book):
    require(book.calculation is not None and book.calculation.iterate in (None,False),'Waterfall source formulas must be noncircular')


def recipes():
    from sheets_factory.workbook import resource_engine,thread_capped_resource_engine,engine
    from sheets_factory.workbook.linear_capital_portfolio import formula_identity
    from sheets_factory.task_adapters import heterogeneous_formula_identity
    from sheets_factory.core import audit
    from sheets_factory.dashboard import server
    from sheets_factory import resume
    paths=[Path(__file__),ANCESTOR,PROFILE,schema.CONTRACT_PATH,Path(schema.__file__),EMITTER,
        ROOT/'scripts/build_heterogeneous_source.py', ROOT/'src/sheets_factory/workbook/uno_recalculate.py',
        *(Path(m.__file__) for m in (resource_engine,thread_capped_resource_engine,engine,formula_identity,heterogeneous_formula_identity,audit,server,resume))]
    require(reference(ANCESTOR)['sha256']==ANCESTOR_SHA,'The original source3 driver changed')
    require(reference(EMITTER)['sha256']==EMITTER_SHA,'The frozen waterfall renderer changed')
    return {str(p.resolve()):reference(p) for p in paths}


def source_definition(path,bindings,public):
    book=_N['_book'](path);formulas={};literals={};represented=set();policies=[]
    try:
        _require_noncircular(book)
        for sheet in book:
            for cell in sheet._cells.values():
                point=sheet.title+'!'+cell.coordinate
                if cell.data_type=='f':formulas[point]=cell.value
                elif cell.value is not None:literals[point]=typed(cell.value)
        require(set(formulas)==set(bindings['financial']) and all(formulas[p]==r['formula'] and len(formulas[p])<=8192 for p,r in bindings['financial'].items()),'The entire formula scope must equal the independent physical bindings')
        require(set(literals)==set(bindings['provided']),'Every nonformula literal must have a protected provided binding')
        for point,record in bindings['provided'].items():
            require(point==record['sheet']+'!'+record['cell'] and literals[point]==typed(record['value']),'A protected label or fact differs')
            if 'path' in record:
                value=_path_value(public,record['path'])
                require(type(value) is type(record['value']) and value==record['value'],'A physical provided fact differs from the frozen raw')
                represented.add(tuple(record['path']))
            else:
                require(record.get('contextkind') in ('label','policy','layout'),'Undeclared literal context')
                if record['contextkind']=='policy':policies.append(record['value'])
        wanted=_fact_paths(public['funds'],('funds',))
        require(wanted<=represented,'All public fund terms, openings, scenarios, dates and cash facts must be physically supplied')
        require(set(schema.contract()['business_policies'])<=set(policies),'The whole frozen public waterfall policy must be present')
        return {'sheetnames':book.sheetnames,'formulas':formulas,'literals':literals,
            'provided_financial_inputs':{},'raw_fact_paths_checked':len(wanted),'noncircular':True}
    finally:book.close()


def _physical_empty(path):
    count=0
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not (name.startswith('xl/worksheets/') and name.endswith('.xml')):continue
            root=X.fromstring(archive.read(name))
            for cell in root.iter('{'+_N['NS']+'}c'):
                if cell.find('{'+_N['NS']+'}f') is not None:
                    require(cell.find('{'+_N['NS']+'}v') is None and cell.find('{'+_N['NS']+'}is') is None,'Every physical formula cache must be absent, not merely empty')
                    count+=1
    return count


def _metadata_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1,'Use the new waterfall source3 preparation only')
    return f


def prepare(candidate_manifest,output,*,independent_comparison,forward_A,forward_B,profile=PROFILE):
    """Zero-service preparation; all independent values come from immutable ledgers."""
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh source directory')
    output.mkdir(parents=True)
    audit=_N['AuditStore'](output/'prepare_audit',{'id':output.name+'-prepare','name':'Waterfall source preparation; stored ledgers, 0 forwards','status':'running','qualified':False,'target_count':0})
    server=_N['DashboardServer'](audit.snapshot,audit.events,host='127.0.0.1',port=0);failure=None
    try:
        url=server.start();write(output/'prepare_started.json',{'at':_N['now'](),'dashboard_url':url,'pid':_N['os'].getpid(),'native_LO_calls':0})
        print(_N['json'].dumps({'dashboard_url':url,'phase':'source_prepare','pid':_N['os'].getpid()}),flush=True)
        with stage(audit,'memoized_independent_ledger_cold_validation'):
            candidate=read(candidate_manifest)
            require(candidate['kind']=='pure_waterfall_portfolios_native_emission' and candidate['version']==1
                and candidate['qualified'] is False,'Require this unverified renderer family, never an old source pass')
            _check_refs(candidate)
            require(candidate['all_formula_caches_absent'] is True and candidate['actual_D_unknown'] is True
                and candidate['independent_financial_expected_in_workbook'] is False and candidate['model_LO_solver_calls']==0,
                'Unverified cache-free construction is required; no source or task qualification is inherited')
            evidence={'comparison':_ref(independent_comparison),'forward_A':_ref(forward_A),'forward_B':_ref(forward_B)}
            public,original_raw=_original_raw(candidate,read(evidence['comparison']))
            require(public['dimension_mode']=='production','Production source admission retains all24 funds/20years/3scenarios')
            f={'specification':original_raw,'bindings':candidate['bindings'],'financial_evidence':evidence}
            expected,comparison=_crosscheck_prepared(f);bindings=read(candidate['bindings'])
            definition=source_definition(checked(candidate['source']),bindings,public)
            original=read(candidate['definition'])
            _renderer_scope(candidate,bindings,original)
            require(original['formulas']==definition['formulas'] and original['sheetnames']==definition['sheetnames'],'The frozen renderer definition differs')
            require(set(original['literals'])==set(definition['literals']) and all(typed(v['value'])==definition['literals'][p] for p,v in original['literals'].items()),'Original renderer literals differ')
        with stage(audit,'cold_start_all_formula_caches'):
            require(_physical_empty(checked(candidate['source']))==len(expected),'The frozen renderer source must really be cache-free')
            r,p=runtime(profile);cold=output/'cold_start.xlsx';clear=clear_all_formula_caches(checked(candidate['source']),cold)
            require(_physical_empty(cold)==clear['all_formula_caches_cleared']==len(expected),'The complete source must start physically unseeded')
            cold_audit=_N['audit_workbook'](cold,definition,expected,empty_caches=True);require(cold_audit['passed'],'Cold definitions, literal or cache audit failed')
            refs={'definition':write(output/'definition.private.json',definition),'expected':write(output/'expected.private.json',expected),
                'independent_comparison':write(output/'memoized_AB_comparison.json',comparison),'cold_start_audit':write(output/'cold_start_audit.json',cold_audit)}
            prepared=write(output/'preparation.json',{'kind':KIND,'version':1,'candidate_manifest':_ref(candidate_manifest),
                **f,'specification_sha256':schema.canonical_sha256(public),'cold_start':reference(cold),**refs,
                'cache_clearance':clear,'runtime_profile':r,'runtime_profile_value':p,'recipe':recipes(),
                'stage_order':list(_N['STAGES']),'required_actual_LO_calls':3,'cold_start_is_unseeded':True,
                'actual_LO_calls':0,'new_financial_forwards':0,'model_calls':0,'qualified':False})
            return prepared
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)}
        write(output/'preparation_failure.json',failure);raise
    finally:
        audit.update_run(status='failed' if failure else 'passed',producer_active=False);audit.export()
        server.stop();audit.db.close()


def validate_prepared(output):
    f=_metadata_prepared(output)
    require(f['recipe']==recipes() and f['stage_order']==list(_N['STAGES']) and f['required_actual_LO_calls']==3
        and f['cold_start_is_unseeded'] is True and f['new_financial_forwards']==0,'Exact source3 recipe, stages and stored-ledger policy required')
    _check_refs(f)
    require(runtime(checked(f['runtime_profile']))==(f['runtime_profile'],f['runtime_profile_value']),'Pinned actual hardware profile changed')
    expected,comparison=_crosscheck_prepared(f)
    require(expected==read(f['expected']) and comparison==read(f['independent_comparison']),'Complete stored independent projections changed')
    public=schema.validate_spec(read(f['specification']));candidate=read(f['candidate_manifest']);bindings=read(f['bindings'])
    _check_refs(candidate)
    copied,original_ref=_original_raw(candidate,read(f['financial_evidence']['comparison']))
    require(copied==public and original_ref==f['specification'] and candidate['bindings']==f['bindings'],'Original raw and unchanged renderer references differ')
    _renderer_scope(candidate,bindings,read(candidate['definition']))
    definition=source_definition(checked(candidate['source']),bindings,public)
    require(definition==read(f['definition']),'Cold original formulas, public facts or literals changed')
    require(_physical_empty(checked(candidate['source']))==len(expected),'The original renderer source gained formula caches')
    cold=_N['audit_workbook'](checked(f['cold_start']),definition,expected,empty_caches=True)
    require(cold['passed'] and cold==read(f['cold_start_audit']) and f['cache_clearance']['output']==f['cold_start']
        and _physical_empty(f['cold_start']['path'])==f['cache_clearance']['all_formula_caches_cleared']==len(expected),'Full cold input audit changed')
    return f


_N.update(KIND=KIND,SOURCE_KIND=SOURCE_KIND,recipes=recipes,source_definition=source_definition,
    validate_prepared=validate_prepared,_metadata_prepared=_metadata_prepared,_crosscheck_prepared=_crosscheck_prepared,
    _require_noncircular=_require_noncircular,spec=SimpleNamespace(validate=schema.validate_spec,canonical_sha256=schema.canonical_sha256))
execute_prepared=_N['execute_prepared']


def validate_source(value):
    terminal=_N['validate_source'](value)
    require(terminal['memoized_independent_ledgers'] is True and terminal['new_financial_forwards']==0,
        'Source3 must reuse whole genuine independent ledgers without new forwards')
    return terminal


validate_completed=validate_source


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('candidate','output','independent-comparison','forward-A','forward-B','prepared'):
        parser.add_argument('--'+key,type=Path)
    parser.add_argument('--profile',type=Path,default=PROFILE);parser.add_argument('--run',action='store_true');args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.candidate,args.output,args.independent_comparison,args.forward_A,args.forward_B)),'Use the exact frozen source preparation')
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(all((args.candidate,args.output,args.independent_comparison,args.forward_A,args.forward_B)),'Supply renderer, both genuine forward receipts, full comparison and fresh output')
        result=prepare(args.candidate,args.output,independent_comparison=args.independent_comparison,forward_A=args.forward_A,forward_B=args.forward_B,profile=args.profile)
        if args.run:result=execute_prepared(args.output)
    print(_N['json'].dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
