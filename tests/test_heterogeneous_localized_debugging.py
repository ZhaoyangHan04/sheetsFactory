"""Small uncalculated binding fixtures; no production workbook or engine."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from sheets_factory.task_adapters import heterogeneous_localized_debugging as provider
from sheets_factory.workbook.heterogeneous_contracts import excel


@pytest.fixture
def graph():
    public={'months':[f'{2027+i//12:04d}-{i%12+1:02d}-01' for i in range(24)],
            'entities':[{'id':f'E{i:02d}'} for i in range(1,7)],
            'scenarios':[{'id':f'S{i:02d}'} for i in range(1,4)]}
    binding={'arithmetic_bindings':[],'financial_bindings':[], 'input_bindings':[], 'literal_bindings':[]}
    rows={};counters={};inputs={}
    def add(sid,owner,label,expression,expected=None,**metadata):
        sheet=sid+' Calculations';n=counters.get(sheet,0)+1;counters[sheet]=n
        row={'sheet':sheet,'cell':f'B{n}','expression':deepcopy(expression),
             'formula':'='+excel.expression_formula(expression),'semantic_owner':owner,'is_complete_answer':False}
        binding['arithmetic_bindings'].append(row)
        binding['literal_bindings'].append({'sheet':sheet,'cell':f'A{n}','value':label,'kind':'text'})
        if expected is not None:
            binding['financial_bindings'].append({**deepcopy(row),'expected_path':expected,
                'kind':'money_pence','worksheet_scale':1,**metadata})
        return row
    def field(sid,eid,t,name,expression=None):
        key=(sid,eid,t,name)
        if key not in rows:
            path=['scenarios',sid,'entities',eid,'monthly',t,name]
            rows[key]=add(sid,path,f'{eid} {public["months"][t]} {name}',0 if expression is None else expression,path)
        elif expression is not None:
            row=rows[key];row['expression']=deepcopy(expression);row['formula']='='+excel.expression_formula(expression)
            target=next(r for r in binding['financial_bindings'] if r['sheet']==row['sheet'] and r['cell']==row['cell'])
            target.update(expression=deepcopy(expression),formula=row['formula'])
        return rows[key]
    def input_ref(path):
        if tuple(path) not in inputs:
            row={'sheet':'Native inputs','cell':f'B{len(inputs)+1}','path':path,'kind':'integer','worksheet_scale':1}
            binding['input_bindings'].append(row);inputs[tuple(path)]=row
        return provider._ref(inputs[tuple(path)])
    for identifier,family,sid,eid,t,name,role in provider.SELECTORS:
        r=lambda f:provider._ref(field(sid,eid,t,f))
        month=public['months'][t];owner=['scenarios',sid,'entities',eid,'monthly',t,name]
        if identifier=='Q01':expr=['if',1,['sum',r('interest_payable_open'),r('interest_accrual')],0]
        elif identifier in {'Q02','Q03'}:
            selected=add(sid,['scenarios',sid,'entities',eid,'monthly',t,'term_id'],f'L06 {month} effective next_coupon_month',0)
            target=provider._ref(selected);date=input_ref(['calendar',t]);period=lambda d:['sum',['mul',['year',d],12],['month',d]]
            calendar=['and',['ge',date,target],['eq',['mod',['sub',period(date),period(target)],3],0]]
            expr=['if',1,['if',0,1,['if',1,['if',calendar,1,0],1]],0]
            row=add(sid,owner,f'{eid} {month} coupon due',expr)
            input_ref(['loans',5,'terms',0,'next_coupon_month'])
            field(sid,eid,t,'cash_coupon',['if',provider._ref(row),['sum',r('interest_payable_open'),r('interest_accrual')],0])
            continue
        elif identifier=='Q04':expr=['sub',['sum',r('interest_payable_open'),r('interest_accrual')],r('cash_coupon')]
        elif identifier in {'T01','T02'}:expr=['if',['eq',r('tax_policy'),'ACCRUAL_MONTHLY'],r('interest_accrual'),r('cash_coupon')]
        elif identifier in {'T03','T04'}:
            carry='interest_carry_months' if identifier=='T03' else 'loss_carry_months'
            expr=['if',['lt',input_ref(['entities',int(eid[1:])-1,carry]),['sub',6 if identifier=='T03' else 12,0]],123,0]
            path=['scenarios',sid,name,eid,'monthly',t]
            add(sid,[*path,'origin','2027-01-01','expired'],f'{eid} {month} expiry',expr,path,
                vintage_origin='2027-01-01',vintage_field='expired')
            continue
        elif identifier in {'V01','V02'}:
            failure=['and',r('test_applicable'),['eq',r('test_pass'),0]]
            expr=['if',['or',0,r('facility_closed_open')],0,
                  ['if',['eq',r('dscr_policy'),'MONTHLY_CURRENT'],['if',['or',r('trap_open'),failure],1,0],r('trap_open')]]
        else:
            cure=add(sid,['scenarios',sid,'entities',eid,'monthly',t,'cure_next'],f'{eid} {month} provisional cure next',1)
            failure=['and',r('test_applicable'),['eq',r('test_pass'),0]]
            expr=['if',r('facility_closed_open'),0,['if',r('test_applicable'),
                  ['if',failure,1,['if',['and',r('trap_open'),['lt',provider._ref(cure),2]],1,0]],r('trap_open')]]
            row=add(sid,owner,f'{eid} {month} provisional restriction next',expr)
            field(sid,eid,t,'trap_next',provider._ref(row));continue
        field(sid,eid,t,name,expr)
    binding['formula_count']=len(binding['arithmetic_bindings'])
    return public,binding


def test_default_is_off_and_exact_opt_in():
    with pytest.raises(ValueError,match='disabled'):provider.validate_setting(provider.setting())
    assert provider.validate_setting(provider.setting(enabled=True))['enabled'] is True
    for field,value in [('enabled',1),('version',True),('physical_roots',13),('design_sha256','0'*64)]:
        bad=provider.setting(enabled=True);bad[field]=value
        with pytest.raises(ValueError):provider.validate_setting(bad)
    with pytest.raises(ValueError):provider.setting(enabled=1)


def test_twelve_causal_edits_and_three_families_no_workbook_write(graph):
    public,binding=graph;before=provider.canonical(binding)
    edits,roots=provider.compile_mutations(public,binding)
    assert len(edits)==12 and len({(e['sheet'],e['cell']) for e in edits})==12
    assert {r['family'] for r in roots}=={'quarter_coupon','tax_FIFO','covenant_timing_cure'}
    assert all(e['cell'].startswith('B') and e['before']!=e['after'] for e in edits)
    assert not any(r['individual_activity_claimed'] for r in roots)
    assert provider.canonical(binding)==before
    # Apply only to a tiny in-memory fixture: exact before assertions and all
    # surviving physical formulas/literals are preserved. No file is saved.
    book=Workbook();book.remove(book.active)
    for row in binding['arithmetic_bindings']:
        if row['sheet'] not in book:book.create_sheet(row['sheet'])
        book[row['sheet']][row['cell']]=row['formula']
    changed={(e['sheet'],e['cell']):e for e in edits}
    for row in binding['arithmetic_bindings']:
        key=(row['sheet'],row['cell']);cell=book[row['sheet']][row['cell']]
        if key in changed:
            assert cell.value==changed[key]['before'];cell.value=changed[key]['after']
        assert cell.value==(changed[key]['after'] if key in changed else row['formula'])


@pytest.mark.parametrize('identifier',['Q01','Q02','Q03','Q04','T01','T02','T03','T04','V01','V02','V03','V04'])
def test_each_prescribed_edit_is_a_local_policy_change(graph,identifier):
    public,binding=graph;edits,roots=provider.compile_mutations(public,binding)
    edit=edits[[r['id'] for r in roots].index(identifier)]
    assert provider._signature(edit['before'])!=provider._signature(edit['after'])
    if identifier in {'T03','T04'}:
        assert '<=' not in edit['before'] and '<=' in edit['after']
    if identifier=='Q02':
        assert edit['after'].count("'Native inputs'!$B")>edit['before'].count("'Native inputs'!$B")
    if identifier=='V03':assert '<2' in edit['before'] and '<1' in edit['after']


@pytest.mark.parametrize('corruption',['duplicate_physical','duplicate_financial','duplicate_label','no_ancestor','D_alias','wrong_before','wrong_scope','missing_vintage'])
def test_fail_closed_locator_and_binding_corruptions(graph,corruption):
    public,binding=graph
    if corruption=='duplicate_physical':binding['arithmetic_bindings'].append(deepcopy(binding['arithmetic_bindings'][0]))
    elif corruption=='duplicate_financial':binding['financial_bindings'].append(deepcopy(binding['financial_bindings'][0]))
    elif corruption=='duplicate_label':binding['literal_bindings'].append(deepcopy(binding['literal_bindings'][0]))
    elif corruption=='wrong_scope':public['months'].pop()
    elif corruption=='missing_vintage':binding['financial_bindings']=[r for r in binding['financial_bindings'] if r.get('vintage_field')!='expired']
    elif corruption=='wrong_before':binding['arithmetic_bindings'][0]['formula']='=999'
    elif corruption=='D_alias':
        # Removing internal aliases must never silently select an intact D value.
        row=next(r for r in binding['financial_bindings'] if r['expected_path'][-1]=='cash_coupon')
        binding['financial_bindings'].remove(row);row['cell']='D999';binding['financial_bindings'].append(row)
    else:
        key=next(r for r in binding['financial_bindings'] if r['expected_path']==['scenarios','S02','entities','E06','monthly',5,'cash_coupon'])
        physical=next(r for r in binding['arithmetic_bindings'] if r['sheet']==key['sheet'] and r['cell']==key['cell'])
        for row in (key,physical):row.update(expression=0,formula='=0')
    with pytest.raises(ValueError):provider.compile_mutations(public,binding)


def test_effect_claims_and_public_privacy_remain_pending(graph,monkeypatch):
    public,binding=graph
    monkeypatch.setattr(provider,'reference',lambda p:{'path':str(p),'sha256':'a'*64,'bytes':1})
    monkeypatch.setattr(provider,'_source',lambda p,n:({'path':'private/source.json','sha256':'a'*64,'bytes':1},
        {'workbook':{'path':'private/goal.xlsx'},'bindings':{'path':'private/bindings.json'}},public,binding))
    monkeypatch.setattr(provider,'_assert_current_source',lambda *args:None)
    monkeypatch.setattr(provider,'_formula_subset',lambda p,loc:{(r['sheet'],r['cell']):r['formula']
        for r in binding['arithmetic_bindings'] if (r['sheet'],r['cell']) in loc})
    plan=provider.propose_debugging_task('mock-source',provider.setting(enabled=True),source_proof='mock-proof')
    assert 'mask_ranges' not in plan
    evidence=plan['family_adapter']
    assert all(evidence['pending'].values()) and not evidence['quality_or_difficulty_certified']
    assert evidence['edits_sha256']==provider.canonical(plan['edits'])
    assert not evidence['individual_root_activity_claimed']
    public_text=plan['public_instruction']+''.join(plan['public_rules'])
    for root in evidence['roots']:
        assert root['cell'] not in public_text and root['id'] not in public_text
    assert 'private/' not in public_text and 'cash_coupon' not in public_text


def test_wrong_manifest_rejected_before_file_or_source_read(tmp_path):
    path=tmp_path/'manifest.json';path.write_text('{}')
    with pytest.raises(ValueError,match='bound actual v2'):provider._source(provider.reference(path),path)


def test_current_reference_detects_tamper_symlink_and_bool_size(tmp_path):
    p=tmp_path/'artifact';p.write_text('first');ref=provider.reference(p)
    assert provider.checked(ref)==p
    p.write_text('other')
    with pytest.raises(ValueError):provider.checked(ref)
    link=tmp_path/'alias';link.symlink_to(p)
    with pytest.raises(ValueError):provider.reference(link)
    with pytest.raises(ValueError):provider.checked({'path':str(p),'sha256':'a'*64,'bytes':True})


def test_before_lexical_equivalence_only():
    assert provider._signature('=IF(A1>0,0.0,1.000)')==provider._signature('=IF(A1>0,0,1)')
    assert provider._signature('=IF(A1>0,0,1)')!=provider._signature('=IF(A2>0,0,1)')
    assert provider._signature('="0.0"')!=provider._signature('="0"')


def test_zip_formula_subset_missing_nonformula_and_numeric_spelling(tmp_path):
    book=Workbook();sheet=book.active;sheet.title='S01 Calculations'
    sheet['B1']='=1+0.0';sheet['B2']=10
    path=tmp_path/'small.xlsx';book.save(path)
    assert provider._formula_subset(path,{(sheet.title,'B1')})=={(sheet.title,'B1'):'=1+0.0'}
    with pytest.raises(ValueError):provider._formula_subset(path,{(sheet.title,'B2')})
    with pytest.raises(ValueError):provider._formula_subset(path,{(sheet.title,'B3')})


@pytest.fixture
def source_fixture(tmp_path,graph,monkeypatch):
    public,binding=graph
    binding['specification_sha256']=provider.canonical(public)
    def write(name,value):
        p=tmp_path/name
        p.write_text(json.dumps(value) if isinstance(value,dict) else value)
        return provider.reference(p)
    public_ref=write('spec.json',public);bindings_ref=write('bindings.json',binding)
    profile=write('profile.json',{'id':'entity_group_large_v2'})
    recipe={}
    for i in range(6):
        r=write(f'recipe{i}.py',f'# frozen recipe {i}');recipe[r['path']]=r['sha256']
    outputs=[write(f'pass{i}.xlsx',f'not a real workbook, source evidence fixture {i}') for i in range(3)]
    raw=write('raw.xlsx','raw fixture');calls=[];audits=[]
    for i in range(3):
        src=raw if i==0 else outputs[i-1];dest=outputs[i]
        resource={'actual_resources_verified':True,'source':src,'output':dest,'profile':profile,'image_id':'fixture-image',
            'actual_resources':{'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256}}
        evidence={'started':write(f'engine-start-{i}.json',{}),'terminal':write(f'engine-end-{i}.json',resource)}
        calls.append({'index':i+1,'completed':True,'input':src,'output':dest,'actual_resource_evidence':evidence,
            'started_receipt':write(f'call-start-{i}.json',{}),'terminal_receipt':write(f'call-end-{i}.json',{})})
        audits.append(write(f'audit{i}.json',{'passed':True,'all_values_checked':True,'mismatch_count':0,'native_error_count':0,
            'audited_file':dest,'bindings_sha256':provider.canonical(binding),'specification_sha256':provider.canonical(public),
            'physical_formulas_checked':binding['formula_count'],'financial_journal_fields_checked':len(binding['financial_bindings'])}))
    comparisons=[{'left':outputs[0],'right':outputs[i],'comparison':{'passed':True,'entire_value_union_checked':True,
        'typed_value_mismatches':0,'union_cells_checked':100}} for i in [1,2]]
    manifest={'kind':'independently_verified_heterogeneous_contract_source','version':1,
        'scope':{'entities':6,'months':24,'scenarios':3},'actual_LO_recalculations':3,'qualified':False,
        'workbook':outputs[0],'source_recipe_sha256':recipe,'source_recipe_digest':provider.canonical(recipe),
        'private_specification':public_ref,'bindings':bindings_ref,'specification_sha256':provider.canonical(public),
        'independent_ledger':write('ledger.json',{}),'source_preparation':write('prepared.json',{}),
        'geometry':write('geometry.json',{}),'mechanism_coverage':write('mechanisms.json',{}),
        'runtime_profile':profile,'runtime':{'image_id':'fixture-image'},'engine_calls':calls,'financial_audits':audits,
        'stability':write('stability.json',{'kind':'three_actual_pass_full_typed_stability','stable':True,'comparisons':comparisons})}
    manifest_ref=write('manifest.json',manifest)
    monkeypatch.setattr(provider,'SOURCE_MANIFEST_SHA256',manifest_ref['sha256'])
    monkeypatch.setattr(provider,'SOURCE_WORKBOOK_SHA256',outputs[0]['sha256'])
    return manifest,manifest_ref,write


def test_exact_copied_audited_source_is_allowed(source_fixture,tmp_path):
    manifest,ref,_=source_fixture
    copy=tmp_path/'normalized-copy.xlsx';copy.write_bytes(Path(manifest['workbook']['path']).read_bytes())
    _,actual,public,binding=provider._source(ref,copy)
    assert actual==manifest and binding['specification_sha256']==provider.canonical(public)
    provider._assert_current_source(ref,manifest,copy)
    copy.write_text('changed while planning')
    with pytest.raises(ValueError):provider._assert_current_source(ref,manifest,copy)


@pytest.mark.parametrize('corruption',['broken_chain','no_third_call','audit_wrong_book','audit_incomplete',
    'stability_wrong_pass','stability_partial','resource_wrong_profile','resource_wrong_memory','recipe_changed','binding_changed'])
def test_source_evidence_requires_complete_exact_current_chain(source_fixture,monkeypatch,corruption):
    manifest,ref,write=source_fixture
    if corruption=='broken_chain':manifest['engine_calls'][1]['input']=manifest['engine_calls'][0]['input']
    elif corruption=='no_third_call':manifest['engine_calls'].pop()
    elif corruption.startswith('audit_'):
        report=provider._read(manifest['financial_audits'][1])
        if corruption=='audit_wrong_book':report['audited_file']=manifest['workbook']
        else:report['all_values_checked']=False
        manifest['financial_audits'][1]=write('corrupt-audit.json',report)
    elif corruption.startswith('stability_'):
        stable=provider._read(manifest['stability'])
        if corruption=='stability_wrong_pass':stable['comparisons'][0]['right']=manifest['workbook']
        else:stable['comparisons'][0]['comparison']['entire_value_union_checked']=False
        manifest['stability']=write('corrupt-stable.json',stable)
    elif corruption.startswith('resource_'):
        evidence=manifest['engine_calls'][0]['actual_resource_evidence'];actual=provider._read(evidence['terminal'])
        if corruption=='resource_wrong_profile':actual['profile']=manifest['bindings']
        else:actual['actual_resources']['memory_bytes']=2*1024**3
        evidence['terminal']=write('corrupt-resource.json',actual)
    elif corruption=='recipe_changed':Path(next(iter(manifest['source_recipe_sha256']))).write_text('# tampered')
    else:Path(manifest['bindings']['path']).write_text('{}')
    updated=write('modified-manifest.json',manifest)
    monkeypatch.setattr(provider,'SOURCE_MANIFEST_SHA256',updated['sha256'])
    with pytest.raises(ValueError):provider._source(updated,manifest['workbook']['path'])
