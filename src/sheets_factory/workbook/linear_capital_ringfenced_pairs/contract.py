"""Ten fixed pairs of unchanged synthetic, legally ringfenced N360 contexts."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ..linear_capital_ringfenced_group import contract as original

ROOT=original.ROOT
SETUP=original.SETUP
SETUP_SHA256=original.SETUP_SHA256
PROFILE_ORDER=('L360-P01','L360-P02','L360-P07','L360-P09','L360-P10',
               'L360-P14','L360-P16','L360-P17','L360-P18','L360-P20')
PAIRS=tuple((f'R2-{i+1:02d}',p,PROFILE_ORDER[(i+1)%10]) for i,p in enumerate(PROFILE_ORDER))
MANDATE_ORDER=('M01','M02')
SCENARIOS=original.SCENARIOS;YEARS=original.YEARS;GROUP_FIELDS=original.GROUP_FIELDS
POLICIES=deepcopy(original.POLICIES)
POLICIES['business_header']='Two legally ringfenced investment mandates hold separate project portfolios. Each mandate retains its own provided budgets, resources, tax accounts and funding rules. Management reports consolidate their reported amounts.'
KIND='synthetic_two_ringfenced_capital_mandates'
PROSPECTIVE_KIND='prospective_fixed_ten_ringfenced_capital_pairs'
require=original.require;reference=original.reference;checked=original.checked;read=original.read;write=original.write
canonical_sha256=original.canonical_sha256
CATALOG=ROOT/'outputs/research/linear_scaled_N360_raw_actual_20261031T121400Z/catalog_manifest.json'
CATALOG_SHA256='e83770dc74039d66b6258ddb180a60f2f0be75e433e26ee590448a59077ee4d0'
OLD_FAILURE=ROOT/'outputs/research/ringfenced_P01_P02_P07_P09_full_goal_emission_20261031T231015Z/terminal.json'
OLD_FAILURE_SHA256='da0e660f8ac55f71e1ecb1b4ea199e16a2ff8aac08ae33a635ef93605bcb99be'
OLD_CENSUS=ROOT/'outputs/research/ringfenced_literal_failure_readonly_20261031T233215Z/receipt.json'
OLD_CENSUS_SHA256='54d89ff0a1c650845ebe954669c68c80a40c447067c88d19952836f08d95cdda'


def inventory():
    """Metadata only: these records do not supply source/reference admission."""
    require(reference(SETUP)['sha256']==SETUP_SHA256 and reference(CATALOG)['sha256']==CATALOG_SHA256,
            'The original fixed context pool changed')
    setup={r['profile_id']:r for r in read(SETUP)['profiles']}
    catalog={r['profile_id']:r for r in read(CATALOG)['profiles']};result=[]
    for profile in PROFILE_ORDER:
        row=setup[profile];raw=catalog[profile]
        worker_ref=reference(SETUP.parent/'profiles'/profile/'worker_terminal.json');worker=read(worker_ref)
        require(worker['profile_id']==profile and row['specification']==raw['specification'], 'A fixed original context changed')
        source_ref=worker['records']['source_manifest'];source=read(source_ref)
        require(source['independent_reference']==row['reference'], 'Source/reference context mismatch')
        result.append({'profile_id':profile,'seed':raw['seed'],'specification':row['specification'],
            'reference':row['reference'],'source_manifest':source_ref,'workbook':source['workbook'],
            'engineering_worker':worker_ref,'engineering_pair':worker['records']['pair_terminal']})
    return result


def pair_contexts(contexts,pair_id):
    selected=next((p for p in PAIRS if p[0]==pair_id),None)
    require(selected is not None,'Use one of the ten predeclared pair identities')
    require([r['profile_id'] for r in contexts]==list(PROFILE_ORDER),'Keep the whole ten-context pool')
    lookup={r['profile_id']:r for r in contexts}
    return [{**deepcopy(lookup[p]),'id':identity} for identity,p in zip(MANDATE_ORDER,selected[1:],strict=True)]


def public_contract(contexts,pair_id):
    rows=pair_contexts(contexts,pair_id)
    return {'kind':KIND,'version':1,'pair_id':pair_id,
        'origin':'Independent synthetic certified local contexts reused unchanged',
        'mandates':[{'id':r['id'],'local_profile_id':r['profile_id'],'display_name':'Mandate '+str(i),
            'sheet_prefix':r['profile_id'].removeprefix('L360-')+' - ',
            'public_specification':r['specification']} for i,r in enumerate(rows,1)],
        'policies':deepcopy(POLICIES),'scenario_ids':list(SCENARIOS),'years':list(YEARS),
        'group_fields':list(GROUP_FIELDS),'local_projects':360,'local_integer_rows':941,
        'group_projects':720,'group_local_integer_rows':1882,'coupled_720_project_MIP_claimed':False,
        'source_or_quality_or_development_inherited':False,'difficulty_claimed':False}


def recipes():
    folder=Path(__file__).parent
    paths=[folder/name for name in ('contract.py','composition.py','stream_composition.py','group_report.py')]
    paths += [Path(original.__file__),ROOT/'src/sheets_factory/workbook/linear_capital_ringfenced_group/composition.py',
        ROOT/'src/sheets_factory/workbook/linear_capital_ringfenced_group/stream_composition.py',
        ROOT/'src/sheets_factory/workbook/linear_capital_ringfenced_group/group_report.py',
        ROOT/'src/sheets_factory/workbook/heterogeneous_native_merge.py',
        ROOT/'src/sheets_factory/workbook/linear_capital_scaled/reference.py',ROOT/'scripts/build_linear_capital_scaled_source.py']
    for path,digest in ((OLD_FAILURE,OLD_FAILURE_SHA256),(OLD_CENSUS,OLD_CENSUS_SHA256)):
        require(reference(path)['sha256']==digest,'Original failed four-context history changed');paths.append(path)
    return {str(p.resolve()):reference(p) for p in paths}


def freeze(output):
    output=Path(output).absolute()
    require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),'Use a fresh prospective pool directory')
    contexts=inventory()
    for row in contexts:
        for key in ('specification','reference','source_manifest','workbook','engineering_worker','engineering_pair'):checked(row[key])
    output.mkdir(parents=True)
    contracts={pair:write(output/(pair+'.public.json'),public_contract(contexts,pair)) for pair,*_ in PAIRS}
    return write(output/'prospective.json',{'kind':PROSPECTIVE_KIND,'version':1,'created_at':datetime.now(timezone.utc).isoformat(),
        'pairs':[{'id':p,'profiles':[a,b]} for p,a,b in PAIRS],'first_pilot':'R2-01','contexts':contexts,
        'contracts':contracts,'original_setup':reference(SETUP),'raw_catalog':reference(CATALOG),'recipe':recipes(),
        'all_assignments_fixed_before_hydration':True,'new_raw_seeds':[],
        'reference_or_source_admission_performed':False,'workbooks_written':0,'new_financial_forwards':0,
        'solver_LO_model_Harbor_calls':0,'qualified':False})


def validate_prospective(record):
    f=read(record)
    require(f['kind']==PROSPECTIVE_KIND and f['version']==1 and f['contexts']==inventory()
        and f['pairs']==[{'id':p,'profiles':[a,b]} for p,a,b in PAIRS] and f['first_pilot']=='R2-01'
        and f['original_setup']==reference(SETUP) and f['raw_catalog']==reference(CATALOG) and f['recipe']==recipes()
        and f['all_assignments_fixed_before_hydration'] is True and f['reference_or_source_admission_performed'] is False
        and f['new_raw_seeds']==[] and f['qualified'] is False and all(type(f[k]) is int and f[k]==0
        for k in ('workbooks_written','new_financial_forwards','solver_LO_model_Harbor_calls')),
        'The complete unchanged ten-pair prospective is required')
    require(set(f['contracts'])=={p for p,*_ in PAIRS},'A pair public contract is missing')
    for p,*_ in PAIRS:require(read(f['contracts'][p])==public_contract(f['contexts'],p),'The public pair contract changed')
    for row in f['contexts']:
        for key in ('specification','reference','source_manifest','workbook','engineering_worker','engineering_pair'):checked(row[key])
    return f
