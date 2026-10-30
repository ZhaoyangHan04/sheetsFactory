"""Offline hardening state, source selection and real workbook-scope tests."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
import pytest

from sheets_factory.pipelines.hardening import HardeningPolicy,HardeningError,sha,scored_measurement
from sheets_factory.nodes.construction import prompt

ROOT=Path(__file__).resolve().parents[1]


def dump(path,data):
    path.write_text(json.dumps(data));return {'path':str(path),'sha256':sha(path)}


def measurement(tmp_path,n=3,wins=3,suffix='a'):
    tasks=[{'task_id':str(i),'mode':'financial_modeling' if i%2==0 else 'debugging',
            'task_checksum':str(i)+suffix,'revision_hash':suffix,'timeout_seconds':1800} for i in range(n)]
    selected={'tasks':tasks,'selected_task_ids':[x['task_id'] for x in tasks],
              'model':'gpt-6.1-sol','reasoning_effort':'xhigh','timeout_seconds':1800,'n_attempts':1}
    selection=dump(tmp_path/('selection'+suffix+'.json'),selected)
    attempts=[{**t,'status':'scored','reward':int(i<wins)} for i,t in enumerate(tasks)]
    evaluation={'selection_manifest':selection,'status':'completed','phase':'development',
      'model':'gpt-6.1-sol','reasoning_effort':'xhigh','timeout_seconds':1800,'n_attempts':1,
      'attempts':attempts,'score':{'total_tasks':n,'scored_tasks':n,'infrastructure_errors':0,'overall_pass_at_1':wins/n}}
    path=tmp_path/('evaluation'+suffix+'.json');dump(path,evaluation);return path


def policy():
    return HardeningPolicy(ROOT,{'enabled':True,'policy_path':'config/difficulty_hardening.yaml'})


def seed(tmp_path):
    path=tmp_path/'seed.xlsx';book=openpyxl.Workbook();book.active.title='Inputs'
    book['Inputs']['B2']=2;book['Inputs']['C2']=3
    for name in ('Forecast','Cash'):
        sheet=book.create_sheet(name)
        sheet['A2']='Forecast family' if name=='Forecast' else 'Cash family'
        for col in ('B','C'):sheet[f'{col}2']=f'=Inputs!{col}2*2' if name=='Forecast' else f'=Forecast!{col}2+1'
    book.save(path);book.close()
    temp=tmp_path/'cached.xlsx';ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as old,zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as new:
        for name in old.namelist():
            payload=old.read(name)
            if name.startswith('xl/worksheets/'):
                tree=ET.fromstring(payload)
                for c in tree.findall('.//m:c',ns):
                    if c.find('m:f',ns) is not None:c.find('m:v',ns).text='4' if c.attrib['r']=='B2' else '6'
                payload=ET.tostring(tree,encoding='utf-8')
            new.writestr(name,payload)
    temp.replace(path)
    receipt=dump(tmp_path/'compatibility.json',{'raw_sha256':sha(path),'stability':{'stable':True},'profiles':{'normalized':{'errors':[]}}})
    return {'sha256':sha(path),'local_path':str(path),'finance_evidence':{'compatibility_proof':receipt}}


def test_complete_normal_pilot_is_directional_and_immutable(tmp_path):
    path=measurement(tmp_path);before=path.read_bytes();p=policy();state,event=p.observe(p.initial_state(),path,label='prequality_development_probe')
    assert state['tier']==1 and event['measurement']['scope']=='directional_pilot'
    assert event['measurement']['measurement_label']=='prequality_development_probe'
    assert path.read_bytes()==before and event['status']=='upgrade_required'
    state2,event2=p.observe(state,path)
    assert state2['tier']==1 and event2['status']=='already_recorded'


def test_threshold_and_version_reuse_do_not_upgrade(tmp_path):
    p=policy();path=measurement(tmp_path,n=5,wins=1);state,event=p.observe(p.initial_state(),path)
    assert state['tier']==0 and not event['measurement']['exceeds_threshold']
    first=measurement(tmp_path,n=3,wins=3,suffix='b');state,_=p.observe(state,first)
    copy=tmp_path/'repeated_evaluation.json';copy.write_text(first.read_text()+' ')
    state,event=p.observe(state,copy)
    assert state['tier']==1 and event['status']=='unchanged_task_versions_not_escalated'


@pytest.mark.parametrize('change',[{'status':'infrastructure_failed'}, {'timeout_seconds':900},
    {'model':'gpt-6-sol'},{'reasoning_effort':'high'},{'n_attempts':2},
    {'score':{'total_tasks':3,'scored_tasks':3,'infrastructure_errors':0,'overall_pass_at_1':0}}])
def test_invalid_measurement_never_creates_tier(tmp_path,change):
    path=measurement(tmp_path);data=json.loads(path.read_text());data.update(change);path.write_text(json.dumps(data))
    with pytest.raises(HardeningError):policy().observe(policy().initial_state(),path)


def test_incomplete_cohort_is_not_unsuccessful_probe(tmp_path):
    path=measurement(tmp_path);data=json.loads(path.read_text());data['attempts'].pop();path.write_text(json.dumps(data))
    with pytest.raises(HardeningError,match='Incomplete'):scored_measurement(path)


def test_full_final_cohort_remains_separate(tmp_path):
    data=scored_measurement(measurement(tmp_path,n=20,wins=6))
    assert data['scope']=='full_delivery_cohort' and data['exceeds_threshold']
    assert not data['qualification_inferred']


def test_prepare_uses_actual_planner_knobs_and_prompt(tmp_path):
    source=seed(tmp_path);p=policy();state=p.initial_state();state['tier']=1
    config={'construction':{'authoring_backend':'project_template','max_edit_count':{'financial_modeling':100000}},
            'prompt_overrides':{'planning.md':'planning_hard.md'}}
    result,seeds,contract=p.prepare_round(config,[source],state,tmp_path/'round')
    assert len(seeds)==1 and contract['status']=='planned'
    assert result['construction']['authoring_backend']=='llm'
    assert result['construction']['max_edit_count']['financial_modeling']==100000
    assert 'ACTIVE STRUCTURAL HARDENING CONTRACT' in prompt(SimpleNamespace(config={**result,'project_root':str(ROOT)}),'planning.md')
    assert result['generation_feedback']['structural_hardening']['status']=='planned'
    assert config['construction']['authoring_backend']=='project_template'


def test_no_verified_cycle_source_fails_without_silent_fallback(tmp_path):
    source=seed(tmp_path);p=policy();state=p.initial_state();state['tier']=3
    with pytest.raises(HardeningError,match='No compatible source'):
        p.prepare_round({},[source],state,tmp_path/'round')
    receipt=json.loads((tmp_path/'round/hardening_sources.json').read_text())
    assert receipt['rejected'] and receipt['accepted']==[]


def test_actual_public_whole_family_and_cross_sheet_closure_required(tmp_path):
    source=seed(tmp_path);p=policy();contract=deepcopy(p.policy['tiers'][1]);goal=Path(source['local_path'])
    edits=[{'sheet':s,'cell':c,'after':None} for s in ('Forecast','Cash') for c in ('B2','C2')]
    public=tmp_path/'input.xlsx';book=openpyxl.load_workbook(goal)
    for edit in edits:book[edit['sheet']][edit['cell']]=None
    book.save(public);book.close()
    proof=p.verify_task(goal,{'edits':edits},'financial_modeling',contract,source,public)
    assert proof['status']=='applied' and not proof['difficulty_proven']
    with pytest.raises(HardeningError,match='Incomplete formula family'):
        p.verify_task(goal,{'edits':edits[:-1]},'financial_modeling',contract,source,public)
    with pytest.raises(HardeningError,match='not applied'):
        p.verify_task(goal,{'edits':edits},'financial_modeling',contract,source,goal)


def test_highest_tier_retains_measurement_and_stops(tmp_path):
    p=policy();state=p.initial_state();state['tier']=3
    state,event=p.observe(state,measurement(tmp_path))
    assert event['status']=='structural_policy_exhausted' and len(state['measurements'])==1
    with pytest.raises(HardeningError,match='Highest structural tier'):
        p.prepare_round({},[],state,tmp_path/'round')


def financial_bundle(tmp_path, *, cycle=False, group=False, with_manifest=True, cycle_targets=False):
    """Bound receipts matching current cashpool/group or explicit cycle bundles."""
    from sheets_factory.pipelines.hardening import CYCLE_CHECKS
    source=seed(tmp_path)
    if cycle_targets:
        path=Path(source['local_path']);book=openpyxl.load_workbook(path)
        book['Cash'].title='Cash Flow'
        book['Forecast'].title='Tax'
        for row in book['Cash Flow']:
            for cell in row:
                if cell.data_type=='f':cell.value=cell.value.replace('Forecast!','Tax!')
        debt=book.create_sheet('Debt');sizing=book.create_sheet('DebtSizing')
        debt['A2']='Loan cash interest'
        for col in ('B','C'):debt[f'{col}2']='=DebtSizing!$B$17*0.1'
        sizing['A1']='Underwriting outputs';sizing['A17']='sized principal'
        sizing['B17']='=ROUNDDOWN((1000+Debt!B2)/1000,0)*1000'
        sizing['A19']='unit monthly payment factor';sizing['B19']='=0.1'
        book.save(path);book.close()
        cached=tmp_path/'cycle_cached.xlsx';ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(path) as old,zipfile.ZipFile(cached,'w',zipfile.ZIP_DEFLATED) as new:
            for name in old.namelist():
                payload=old.read(name)
                if name.startswith('xl/worksheets/'):
                    tree=ET.fromstring(payload)
                    for cell in tree.findall('.//m:c',ns):
                        if cell.find('m:f',ns) is not None:
                            cell.find('m:v',ns).text={'B17':'1000','B19':'0.1'}.get(cell.attrib['r'],'100')
                    payload=ET.tostring(tree,encoding='utf-8')
                new.writestr(name,payload)
        cached.replace(path);source['sha256']=sha(path)
    cash_checks={k:True for k in ('all_double_entry_balanced','all_subsidiary_balances',
        'all_treasury_balances','all_group_balances','all_group_cash_balances',
        'all_group_income_eliminations','no_balance_plug')}
    checks=({'all_group_identities_passed':True,'entity_count':12,'group_balance_plug_used':False}
            if group else ({k:True for k in CYCLE_CHECKS} if cycle else cash_checks))
    ledger={'checks':checks,'monthly':[]}
    if cycle:
        ledger['cyclic_financing_proof']={'fixed_points':['1000'],'grid_points_checked':10,
            'mapping_monotone':True,'all_tranches_feasible':True}
        if cycle_targets:
            checks.update(tax_nol_fifo_ok=True,tax_interest_fifo_ok=True)
            ledger['tax_annual']=[{'year':1,'interest_cf_used':'10','nol_expired':'0','current_tax':'0'},
                                  {'year':2,'interest_cf_used':'0','nol_expired':'20','current_tax':'5'}]
    elif not group:
        ledger['monthly']=[{'P3':{'deposit_open':'100','term_return':'0','loan_advance':'10',
                                'new_deposit':'0'},
                            'P4':{'margin_paid':'20','capital_margin':'5','new_deposit':'1'}}]
    public=({'cyclic_financing_parameters':{'enabled':1}} if cycle else
            {'parameters':{'members':[{'id':'P3','contract':'term_depositor'},
                                      {'id':'P4','contract':'nav_borrower'}]}})
    if cycle_targets:public['advanced_tax_parameters']={'advanced_tax_enabled':1}
    audit={'passed':True,'all_formula_cells_independently_covered':True,
           'two_recalculations_typed_stable':True,'independent_ledger_checks':checks}
    if cycle:audit['all_ledger_invariants_passed']=True
    if group:audit.update(all_entity_ledger_invariants_passed=True,group_independent_checks=checks)
    stability={'reward':1,'structure_ok':True,'expected_change_count':0,'actual_change_count':0,
               'wrong_values':[],'missing_changes':[],'extra_changes':[]}
    proofs={name:dump(tmp_path/(name+'.json'),value) for name,value in
            [('ledger',ledger),('financial_audit',audit),('stability',stability),('public_scenario',public)]}
    if group:proofs['group_ledger']=proofs.pop('ledger')
    source['finance_evidence']={'audit_proofs':deepcopy(proofs)}
    if cycle:
        original=dump(tmp_path/'original_source_manifest.json',{'selected':[{'sha256':source['sha256'],
            'local_path':source['local_path'],'finance_evidence':{'financial_seed_verified':True}}]})
        bundle=dump(tmp_path/'source_bundle.json',{'source_manifest':original,
            'source_workbook':{'path':source['local_path'],'sha256':source['sha256']},'audit_proofs':proofs})
        source['finance_evidence']={'source_proof_bundle':bundle}
    elif with_manifest:
        dump(tmp_path/'manifest.json',{'derived_workbook_sha256':source['sha256'],
            'local_path':source['local_path'],'selected':[{'sha256':source['sha256'],'local_path':source['local_path']}],**proofs})
    return source


def test_current_cashpool_hash_bound_audits_and_actual_nested_regimes_are_supported(tmp_path):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    result=seed_mechanisms(financial_bundle(tmp_path))
    assert not result['verified_economic_cycle']
    assert {e['kind'] for e in result['nested_events']}=={
        'locked_deposit_and_new_member_borrowing','nav_margin_call_and_limited_partner_capital',
        'cross_member_deposits_fund_limited_advances'}
    assert all(e['period']==1 for e in result['nested_events'])
    assert any(e['path'].endswith('/manifest.json') for e in result['evidence'])


def test_current_group_audit_shape_preserves_all_entity_and_no_plug_requirements(tmp_path):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    source=financial_bundle(tmp_path,group=True)
    assert seed_mechanisms(source)['nested_events']==[]
    audit=Path(source['finance_evidence']['audit_proofs']['financial_audit']['path'])
    data=json.loads(audit.read_text());data['all_entity_ledger_invariants_passed']=False
    proof=dump(audit,data);source['finance_evidence']['audit_proofs']['financial_audit']=proof
    manifest=tmp_path/'manifest.json';data=json.loads(manifest.read_text());data['financial_audit']=proof;dump(manifest,data)
    with pytest.raises(HardeningError,match='not passing'):seed_mechanisms(source)


@pytest.mark.parametrize('failure',['missing_binding','stale_binding','tampered_audit','nonzero_stability'])
def test_new_source_proof_shapes_fail_closed_on_missing_or_inconsistent_actual_evidence(tmp_path,failure):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    source=financial_bundle(tmp_path,with_manifest=failure!='missing_binding')
    if failure=='stale_binding':
        path=tmp_path/'manifest.json';data=json.loads(path.read_text());data['derived_workbook_sha256']='0'*64;dump(path,data)
    elif failure=='tampered_audit':
        path=Path(source['finance_evidence']['audit_proofs']['financial_audit']['path']);path.write_text(path.read_text()+' ')
    elif failure=='nonzero_stability':
        path=tmp_path/'stability.json';data=json.loads(path.read_text());data['actual_change_count']=1
        proof=dump(path,data);source['finance_evidence']['audit_proofs']['stability']=proof
        manifest=tmp_path/'manifest.json';data=json.loads(manifest.read_text());data['stability']=proof;dump(manifest,data)
    with pytest.raises(HardeningError):seed_mechanisms(source)


def test_cycle_requires_hash_bound_bundle_and_uses_actual_debtsizing_sheet_name(tmp_path):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    source=financial_bundle(tmp_path,cycle=True)
    result=seed_mechanisms(source)
    assert result['verified_economic_cycle']
    assert result['cycle_kind']=='independently_verified_debt_interest_tax_fixed_point'
    assert all('DebtSizing' in event['sheets'] for event in result['nested_events'])
    assert all('Debt Sizing' not in event['sheets'] for event in result['nested_events'])
    assert result['cycle_proof_metadata']['business_boundary_count_contribution']==0
    assert len(result['nested_events'])==1
    source['finance_evidence']={'financial_audit_path':str(tmp_path/'financial_audit.json'),
        'cyclic_unique_grid_proof_path':str(tmp_path/'ledger.json')}
    with pytest.raises(HardeningError,match='hash-bound'):seed_mechanisms(source)


def test_closure_supports_large_graph_only_with_explicit_construction_limit():
    from sheets_factory.pipelines.hardening import closure
    count=78000
    graph={('Forecast',f'A{n}'):{('Forecast',f'A{n-1}')} for n in range(2,count+1)}
    graph[('Forecast','A1')]={('Inputs','B2')}
    inventory={'graph':graph,'unsupported':{}}
    with pytest.raises(HardeningError,match='configured analysis limit'):closure({('Forecast',f'A{count}')},inventory)
    inventory['analysis_limits']={'max_dependency_closure_cells':500000}
    visited,edges=closure({('Forecast',f'A{count}')},inventory)
    assert len(visited)==count+1 and ('Inputs','B2') in visited
    assert edges=={('Forecast','Inputs')}


def test_prepare_binds_configured_large_analysis_limits_and_allows_certified_native_cycles(tmp_path):
    source=seed(tmp_path);p=policy();state=p.initial_state();state['tier']=1
    config={'construction':{'max_edit_count':{'financial_modeling':100000},'analysis_limits':{
        'max_dependency_closure_cells':500000,'max_profile_cells':500000,'per_formula_reference_cells':50000}}}
    result,_,contract=p.prepare_round(config,[source],state,tmp_path/'round')
    assert contract['analysis_limits']==config['construction']['analysis_limits']
    text=Path(result['prompt_overrides']['planning.md']).read_text()
    assert 'actual iterative-runtime stability evidence' in text
    assert 'do not create native circular formulas' not in text
    assert result['construction']['max_edit_count']['financial_modeling']==100000


def test_actual_workbook_inventory_propagates_bounds_for_thirty_thousand_formula_chain(tmp_path):
    from sheets_factory.pipelines.hardening import workbook_inventory,closure
    path=tmp_path/'chain.xlsx';book=openpyxl.Workbook();sheet=book.active;sheet.title='Forecast'
    inputs=book.create_sheet('Inputs');inputs['A1']=1
    for n in range(1,30001):sheet[f'A{n}']='=Inputs!A1' if n==1 else f'=A{n-1}+1'
    sheet['B1']='=TODAY()';sheet['B1'].number_format='yyyy-mm-dd'
    book.save(path);book.close()
    inventory=workbook_inventory(path,max_dependency_closure_cells=500000,max_profile_cells=500000)
    visited,_=closure({('Forecast','A30000')},inventory)
    assert len(visited)==30001 and ('Inputs','A1') in visited
    assert inventory['analysis_limits']['max_dependency_closure_cells']==500000
    with pytest.raises(HardeningError,match='profile exceeds'):workbook_inventory(path,max_profile_cells=100)
    with pytest.raises(ValueError,match='analysis limit'):workbook_inventory(path,max_dependency_closure_cells=500001)


def test_cached_date_formulas_are_not_financial_formula_families(tmp_path):
    from sheets_factory.pipelines.hardening import workbook_inventory
    path=tmp_path/'dates.xlsx';book=openpyxl.Workbook();sheet=book.active;sheet.title='Schedule'
    for col in ('B','C'):
        sheet[f'{col}2']='=DATE(2027,1,1)';sheet[f'{col}2'].number_format='yyyy-mm-dd'
        sheet[f'{col}3']='=2+2'
    book.save(path);book.close()
    cached=tmp_path/'cached.xlsx';ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as old,zipfile.ZipFile(cached,'w',zipfile.ZIP_DEFLATED) as new:
        for name in old.namelist():
            payload=old.read(name)
            if name.startswith('xl/worksheets/'):
                tree=ET.fromstring(payload)
                for cell in tree.findall('.//m:c',ns):
                    if cell.find('m:f',ns) is not None:
                        cell.find('m:v',ns).text='46388' if cell.attrib['r'].endswith('2') else '4'
                payload=ET.tostring(tree,encoding='utf-8')
            new.writestr(name,payload)
    cached.replace(path)
    values=openpyxl.load_workbook(path,data_only=True)
    assert values['Schedule']['B2'].is_date
    values.close()
    families=workbook_inventory(path)['families']
    assert [(family['sheet'],family['row']) for family in families]==[('Schedule',3)]


@pytest.mark.parametrize('target,accepted',[('B17',True),('A17',False),('B19',False)])
def test_actual_scalar_cycle_business_target_required_without_inflating_family_sheet_minimum(tmp_path,target,accepted):
    source=financial_bundle(tmp_path,cycle=True,cycle_targets=True);goal=Path(source['local_path'])
    edits=[{'sheet':sheet,'cell':col+'2','after':None} for sheet in ('Tax','Cash Flow','Debt') for col in ('B','C')]
    edits.append({'sheet':'DebtSizing','cell':target,'after':None})
    book=openpyxl.load_workbook(goal);public=tmp_path/'public.xlsx'
    for edit in edits:book[edit['sheet']][edit['cell']]=None
    book.save(public);book.close()
    p=policy();contract=deepcopy(p.policy['tiers'][3])
    if not accepted:
        with pytest.raises(HardeningError,match='core DebtSizing business output'):
            p.verify_task(goal,{'edits':edits},'financial_modeling',contract,source,public)
        return
    receipt=p.verify_task(goal,{'edits':edits},'financial_modeling',contract,source,public)
    assert receipt['cyclic_business_targets']==[{'label':'sized principal','sheet':'DebtSizing','cell':'B17'}]
    assert receipt['whole_family_target_sheets']==['Cash Flow','Debt','Tax']
    assert receipt['target_sheets']==['Cash Flow','Debt','DebtSizing','Tax']
    reduced=[edit for edit in edits if edit['sheet']!='Debt']
    with pytest.raises(HardeningError,match='Insufficient connected target worksheets'):
        p.verify_task(goal,{'edits':reduced},'financial_modeling',contract,source,public)


def test_grid_proof_does_not_make_simple_cycle_two_business_boundaries(tmp_path):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    source=financial_bundle(tmp_path,cycle=True,cycle_targets=True)
    ref=source['finance_evidence']['source_proof_bundle'];bundle=json.loads(Path(ref['path']).read_text())
    ledger_ref=bundle['audit_proofs']['ledger'];ledger=json.loads(Path(ledger_ref['path']).read_text())
    ledger['tax_annual']=[];bundle['audit_proofs']['ledger']=dump(Path(ledger_ref['path']),ledger)
    source['finance_evidence']['source_proof_bundle']=dump(Path(ref['path']),bundle)
    mechanisms=seed_mechanisms(source)
    assert {event['kind'] for event in mechanisms['nested_events']}=={'debt_interest_tax_capacity_feedback'}
    p=policy();state=p.initial_state();state['tier']=3
    with pytest.raises(HardeningError,match='No compatible source'):
        p.prepare_round({},[source],state,tmp_path/'round')
    rejected=json.loads((tmp_path/'round/hardening_sources.json').read_text())['rejected']
    assert rejected and 'two actually triggered' in rejected[0]['reason']


def test_existing_tax_state_events_count_distinct_business_mechanisms_only(tmp_path):
    from sheets_factory.pipelines.hardening import seed_mechanisms
    source=financial_bundle(tmp_path,cycle=True,cycle_targets=True)
    mechanisms=seed_mechanisms(source)
    assert {event['kind'] for event in mechanisms['nested_events']}=={
        'nol_expiry_with_cash_tax','interest_carry_fifo_utilization','debt_interest_tax_capacity_feedback'}
    assert mechanisms['cycle_proof_metadata']['business_boundary_count_contribution']==0
