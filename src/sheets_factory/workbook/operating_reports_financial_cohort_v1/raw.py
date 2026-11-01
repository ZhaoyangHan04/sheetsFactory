"""Reserve and freeze all nine exact raw contracts before financial forwards."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path

from . import schema as s

KIND='complete_predeclared_operating_reports_financial_cohort_raw_inventory'


def _write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return s.reference(path)


def axis_assignment(identity):
    entry=s.candidate(identity);frozen=json.loads(s.checked_source('design').read_bytes())
    axes=frozen['artifacts']['axis_assignment.json']['value']['entities']
    selected=[];tail=axes[6:];offset=entry['axis_rotation_offset']
    for index,destination in enumerate(axes):
        row=deepcopy(destination if index<6 else tail[(index-6+offset)%len(tail)])
        row['id']=destination['id'];row['name']=entry['company_brand_prefix']+' '+row['name'];selected.append(row)
    return selected


def _namespace(identity):
    entry=s.candidate(identity);source=s.checked_source('raw');tree=ast.parse(source.read_bytes())
    imports=[node for node in tree.body if isinstance(node,ast.ImportFrom) and node.level==1
        and node.module is None and [(v.name,v.asname) for v in node.names]==[('schema','s')]]
    if len(imports)!=1:raise ValueError('The exact original raw schema-import seam changed')
    tree.body.remove(imports[0]);namespace={'__file__':str(source),'__name__':'_cohort_raw_'+entry['candidate_id'],'s':s.for_seed(entry['seed'])}
    exec(compile(ast.fix_missing_locations(tree),str(source),'exec'),namespace)
    original_design=namespace['design']
    def design():
        value=original_design();value['artifacts']['axis_assignment.json']['value']['entities']=axis_assignment(identity)
        return value
    namespace['design']=design
    return namespace


def build_spec(identity):
    """One explicitly called raw generation; no financial module is imported."""
    result=_namespace(identity)['build_spec']()
    if result['dimension_mode']!='production':raise ValueError('The fixed cohort requires a complete production raw contract')
    return result


def freeze_all(output):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    entries=s.contract()['entries'][1:];recipe=s.recipes()
    started={'kind':'predeclared_operating_reports_financial_cohort_raw_generation_started','version':1,
        'contract':s.reference(s.CONTRACT),'candidate_ids':[row['candidate_id'] for row in entries],
        'seeds':[row['seed'] for row in entries],'recipe':recipe,'financial_forwards':0,
        'reserved_at':datetime.now(timezone.utc).isoformat()}
    cohort_start=_write(output/'cohort_started.json',started)
    reservations={}
    # Reserve every logical case before the first raw generator is invoked.
    for row in entries:
        folder=output/row['candidate_id'];folder.mkdir()
        reservations[row['candidate_id']]=_write(folder/'generation_started.json',{
            'kind':'predeclared_financial_cohort_raw_case_started','version':1,'entry':row,
            'cohort_start':cohort_start,'raw_forward_limit':1,'financial_forwards':0})
    cases=[]
    for row in entries:
        identity=row['candidate_id'];folder=output/identity
        try:
            public=build_spec(identity);s.validate_spec(public)
            if public['seed']!=row['seed'] or public['dimension_mode']!='production':
                raise ValueError('The generated raw case identity or production dimension changed')
            specification=_write(folder/'public_specification.json',public)
            receipt=_write(folder/'generation_receipt.json',{'kind':'predeclared_financial_cohort_raw_case_complete','version':1,
                'entry':row,'specification':specification,'canonical_specification_sha256':s.canonical_sha256(public),
                'generation_started':reservations[identity],'raw_forwards':1,'financial_forwards':0,'services':0})
            cases.append({'candidate_id':identity,'seed':row['seed'],'passed':True,
                'generation_started':reservations[identity],'specification':specification,'generation_receipt':receipt})
        except Exception as error:
            failure=_write(folder/'failure.json',{'kind':'predeclared_financial_cohort_raw_case_failed','version':1,
                'entry':row,'generation_started':reservations[identity],'error_type':type(error).__name__,
                'error':str(error),'raw_attempts':1,'financial_forwards':0,'retry_permitted':False})
            cases.append({'candidate_id':identity,'seed':row['seed'],'passed':False,
                'generation_started':reservations[identity],'failure':failure})
    return _write(output/'raw_inventory.json',{'kind':KIND,'version':1,'contract':s.reference(s.CONTRACT),
        'cohort_start':cohort_start,'recipe':recipe,'cases':cases,'passed':all(row['passed'] for row in cases),
        'all_nine_reserved_before_generation':True,'new_raw_attempts':len(entries),'financial_forwards':0,
        'services':0,'qualified':False})


def _read(record):
    if set(record)!={'path','sha256','bytes'} or s.reference(record['path'])!=record:
        raise ValueError('An immutable complete raw inventory artifact changed')
    value=json.loads(Path(record['path']).read_text())
    if s.reference(record['path'])!=record:raise ValueError('A frozen raw artifact changed during reading')
    return value


def validate_all(inventory):
    value=_read(inventory);entries=s.contract()['entries'][1:];root=Path(inventory['path']).parent
    if (value.get('kind')!=KIND or value.get('version')!=1 or value.get('contract')!=s.reference(s.CONTRACT)
        or value.get('recipe')!=s.recipes() or value.get('passed')is not True
        or value.get('all_nine_reserved_before_generation')is not True or value.get('new_raw_attempts')!=9
        or value.get('financial_forwards')!=0 or value.get('services')!=0 or value.get('qualified')is not False
        or [row.get('candidate_id') for row in value.get('cases',[])]!=[row['candidate_id'] for row in entries]):
        raise ValueError('A complete unchanged all-nine predeclared raw inventory is required')
    started=_read(value['cohort_start'])
    if (Path(value['cohort_start']['path'])!=root/'cohort_started.json'
        or started.get('kind')!='predeclared_operating_reports_financial_cohort_raw_generation_started'
        or started.get('version')!=1 or started.get('contract')!=s.reference(s.CONTRACT) or started.get('recipe')!=value['recipe']
        or started.get('candidate_ids')!=[row['candidate_id'] for row in entries]
        or started.get('seeds')!=[row['seed'] for row in entries] or started.get('financial_forwards')!=0):
        raise ValueError('The original common raw reservation changed')
    publics={}
    for case,entry in zip(value['cases'],entries):
        identity=entry['candidate_id'];folder=root/identity
        if (case.get('passed')is not True or case.get('seed')!=entry['seed']
            or Path(case['generation_started']['path'])!=folder/'generation_started.json'
            or Path(case['specification']['path'])!=folder/'public_specification.json'
            or Path(case['generation_receipt']['path'])!=folder/'generation_receipt.json'):
            raise ValueError('A raw case was replaced, failed, moved or reordered')
        reservation=_read(case['generation_started']);receipt=_read(case['generation_receipt']);public=_read(case['specification'])
        if (reservation.get('kind')!='predeclared_financial_cohort_raw_case_started' or reservation.get('version')!=1
            or receipt.get('kind')!='predeclared_financial_cohort_raw_case_complete' or receipt.get('version')!=1
            or reservation.get('entry')!=entry or reservation.get('cohort_start')!=value['cohort_start']
            or reservation.get('raw_forward_limit')!=1 or reservation.get('financial_forwards')!=0
            or receipt.get('entry')!=entry or receipt.get('specification')!=case['specification']
            or receipt.get('generation_started')!=case['generation_started'] or receipt.get('raw_forwards')!=1
            or receipt.get('financial_forwards')!=0 or receipt.get('services')!=0):
            raise ValueError('A fixed raw reservation or generation receipt changed')
        s.validate_spec(public)
        if (public['seed']!=entry['seed'] or public['dimension_mode']!='production'
            or receipt.get('canonical_specification_sha256')!=s.canonical_sha256(public)):
            raise ValueError('The complete production specification identity changed')
        axes=axis_assignment(identity)
        if any(any(entity[key]!=axis[key] for key in ('id','name','division','layout','line_order','money_unit','rate_unit','statement_sign','forecast_reference'))
            or entity['driver_form_by_year']!={str(year):axis['FY'+str(year)+'_driver_form'] for year in (2026,2027)}
            for entity,axis in zip(public['entities'],axes)):
            raise ValueError('The complete predeclared entity convention assignment changed')
        publics[identity]=public
    return {'inventory':value,'specifications':publics}
