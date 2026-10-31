"""Offline receipt fixtures: no source audit, Docker, LO, model, or production snapshot."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
from zipfile import ZipFile,ZIP_DEFLATED
import xml.etree.ElementTree as ET

import openpyxl
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_entity_early_development_test',ROOT/'scripts/prepare_entity_early_development.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def ref(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value));return ref(path)


def workbook(path,first,second):
    book=openpyxl.Workbook();book.active.title='Finance'
    book.active['A1']='='+str(first);book.active['B1']='='+str(second);book.active['A2']='Provided public input'
    book.save(path);book.close()
    # Only a tiny offline cached-value fixture; this does not simulate LO.
    with ZipFile(path) as archive:parts={name:archive.read(name) for name in archive.namelist()}
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    document=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
    for cell in document.findall('.//m:c',ns):
        if cell.attrib['r'] in ('A1','B1'):
            cell.find('m:v',ns).text=str(first if cell.attrib['r']=='A1' else second)
    parts['xl/worksheets/sheet1.xml']=ET.tostring(document)
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        for name,data in parts.items():archive.writestr(name,data)
    return ref(path)


def execution_record(source,output,profile):
    return {'kind':'resource_bound_libreoffice_call','status':'completed','role':'source',
        'source':source,'output':output,'destination':output['path'],'image_id':profile['image']['id'],
        'container_id':'a'*64,'actual_resources_verified':True,
        'actual_resources':{'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256},
        'requested_resources':profile['docker_resources']['source'],'workbook_file_timeout_seconds':600,
        'solver_tool_budget':profile['solver_tool_budget'],
        'implementation':ref(ROOT/'src/sheets_factory/workbook/resource_engine.py'),
        'upstream_engine':ref(ROOT/'src/sheets_factory/workbook/engine.py'),
        'profile_canonical_sha256':probe.canonical(profile),
        'profile':{'canonical_sha256':probe.canonical(profile)},
        'create_command':['docker','create','--network','none',profile['image']['id']],
        'offline_fixture_is_not_actual_execution_evidence':True}


@pytest.fixture
def case(tmp_path,monkeypatch):
    run=tmp_path/'run';private=run/'tasks'/probe.TASK/'revisions/000/private';public=private.parent/'public'
    private.mkdir(parents=True);public.mkdir()
    goal=workbook(private/'goal.xlsx',1,2);raw=workbook(private/'mutated_unrecalculated.xlsx',3,4)
    source=workbook(public/'input.xlsx',3,4)
    monkeypatch.setattr(probe,'SOURCE_SHA',goal['sha256']);monkeypatch.setattr(probe,'MUTATIONS',2);monkeypatch.setattr(probe,'D_COUNT',2)
    profile_ref=ref(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    profile=probe.load_runtime_profile(profile_ref['path'])
    origin=tmp_path/'original_source';origin.mkdir()
    initial_raw=workbook(origin/'raw.xlsx',1,2)
    passes=[goal,workbook(origin/'pass2.xlsx',1,2),workbook(origin/'pass3.xlsx',1,2)]
    bindings=origin/'bindings.json';bindings.write_bytes(b'Explicit opaque financial bindings fixture; never parse this file')
    binding_ref=ref(bindings)
    recipe={str(ROOT/'src/sheets_factory/workbook/resource_engine.py'):ref(ROOT/'src/sheets_factory/workbook/resource_engine.py')['sha256']}
    count={'binding_encodings':{'scalar':971640,'exact_integer_pair':7290,'queues':8640},
        'physical_formula_count':1100346,'physical_nonempty_cells':2222012}
    fields=1030770;calls=[];audits=[];previous=initial_raw
    for index,output in enumerate(passes,1):
        resource=dump(origin/f'resource{index}.json',execution_record(previous,output,profile))
        started=dump(origin/f'started{index}.json',{'completed':False,'input':previous})
        call={'index':index,'completed':True,'network':'none','runtime_profile':profile_ref,
            'image_id':profile['image']['id'],'workbook_file_timeout_seconds':600,'input':previous,'output':output,
            'actual_resource_receipt':resource,'started_receipt':started}
        call['terminal_receipt']=dump(origin/f'terminal{index}.json',call);calls.append(call)
        audits.append(dump(origin/f'audit{index}.json',{'workbook':output,'passed':True,
            'all_independent_journal_fields_covered':True,'all_scenarios_feasible':True,
            'provided_fixed_plan_verified':True,'optimisation_performed':False,
            'logical_fields_checked':fields,'physical_formulas_checked':count['physical_formula_count'],
            'mismatches':[],'control_mismatches':[], 'offline_fixture_is_not_a_financial_audit':True}))
        previous=output
    stable=dump(origin/'stability.json',{'stable':True,**{key:{'passed':True,'sheet_names_equal':True,
        'mismatches':[],'checked_existing_value_cells':count['physical_nonempty_cells']}
        for key in ('first_against_goal','second_against_goal')}})
    preparation=dump(origin/'preparation.json',{'resource_count':count,'recipe_sha256':recipe})
    source_manifest=dump(origin/'seed_manifest.json',{'kind':'independently_verified_hypothetical_fixed_plan_entity_group_source',
        'financial_audit_passed':True,'actual_LO_recalculations':3,'entity_count':24,'month_count':120,'scenario_count':3,
        'provided_plan_is_protected':True,'optimisation_performed':False,'workbook':goal,'source_preparation':preparation,
        'bindings':binding_ref,'financial_audits':audits,'count':count,'source_recipe_sha256':recipe,
        'runtime_profile':profile_ref,'engine_calls':calls,'stability':stable})
    proof={'kind':'admitted_complete_fixed_plan_entity_group_financial_source','financial_seed_verified':True,
        'fixed_plan_provided_and_protected':True,'optimisation_performed':False,
        'admission_implementation':ref(ROOT/'src/sheets_factory/pipelines/entity_group_admission.py'),
        'source_manifest':source_manifest,'workbook':goal,'source_preparation':preparation,'bindings':binding_ref,
        'complete_count':count,'logical_fields_checked':fields,'financial_audits':audits,'stability':stable,
        'runtime_profile':profile_ref,'runtime_profile_value':profile,
        'artifact_sha256':{str(bindings):binding_ref['sha256']}}
    admission=dump(run/'private/source_admission.json',proof)
    seeds=dump(run/'seed_manifest.json',{'selected':[{'sha256':goal['sha256'],'modes':['debugging'],
        'source_manifest':source_manifest,'finance_evidence':{'audited_source_binding':proof}}]})
    config={'project_root':str(ROOT),'run_dir':str(run),'construction':{'instruction_style':'business_brief'},
        'run':{'max_revisions':3},'pipeline':{'node_registry':str(ROOT/'config/task_adapters/entity_group_nodes.yaml')},
        'engine':{'image':profile['image']['tag']}}
    config_path=run/'resolved_config.yaml';config_path.write_text(yaml.safe_dump(config))
    pre={'kind':probe.PREPARATION_KIND,'development_only':True,'count':1,'profile_id':'G01',
        'targets':{'financial_modeling':0,'debugging':1},'all_normal_quality_nodes_required':True,
        'recipe_sha256':recipe,'source_artifacts_sha256':{str(bindings):binding_ref['sha256']},
        'resolved_config':ref(config_path),'source_admission':admission,'prepared_seed_manifest':seeds,
        'protected_task_budgets':{'max_revisions':3},'source_manifest':source_manifest,'runtime_profile':profile_ref}
    dump(run/'preflight_manifest.json',pre)
    edits=[{'sheet':'Finance','cell':cell,'before':'='+str(before),'after':'='+str(after)}
        for cell,before,after in [('A1',1,3),('B1',2,4)]]
    family={'id':'entity_group_fixed_plan_financial_debug_v1','source_sha256':goal['sha256'],
        'activity_contract':'full_workbook_joint_repair','physical_formula_mutation_count':2,
        'physical_edits_sha256':probe.canonical(edits),'mutations_truncated':False,'selection_uses_model_outcomes':False,
        'individual_or_marginal_activity_claimed':False}
    plan={'mode':'debugging','public_instruction':'Repair the financial policies. '+probe.CLAUSES['debugging'],
        'public_rules':['The fixed investment plan is provided.'],'edits':edits,'family_adapter':family,'scenario_inputs':[]}
    dump(private/'plan.json',plan);dump(private/'entity_group_policy_inventory.json',family)
    dump(private/'edit_validation.json',{'offline_saved_assertion_fixture':True})
    delta=probe.compare_workbooks(Path(source['path']),Path(goal['path']),Path(goal['path']))
    dump(private/'expected_delta.json',delta)
    dump(private/'native_risk_guard.json',{'blocking':False,'state':'not_applicable','source_sha256':goal['sha256']})
    dump(private/'native_error_probe.json',{'blocking':False,'state':'not_applicable','source_sha256':goal['sha256'],
        'goal_sha256':goal['sha256'],'plan_sha256':probe.canonical(plan),'revision':0,
        'required_delta':delta['expected_changes'],'required_delta_sha256':probe.canonical(delta['expected_changes'])})
    mutant_receipt=dump(run/'resource_receipts/mutant.terminal.json',execution_record(raw,source,profile))
    state={'run':{'status':'running'},'tasks':[{'id':probe.TASK,'revision':0,'source_id':goal['sha256'],'mode':'debugging',
            'status':'running','revision_hash':None}],
        'nodes':[{'task_id':probe.TASK,'revision':0,'node':name,'status':'running' if name=='construct' else 'completed'}
            for name in ('normalize','profile','plan','construct')]}
    with sqlite3.connect(run/'run.sqlite') as db:
        db.execute('create table state(key text,value text)');db.execute('insert into state values(?,?)',('run',json.dumps(state['run'])))
        for table in ('tasks','nodes'):
            db.execute(f'create table {table}(payload text)')
            db.executemany(f'insert into {table} values(?)',[(json.dumps(row),) for row in state[table]])
    monkeypatch.setattr(probe,'selection_history',lambda *args:[])
    calls_observed=[]
    def base(profile_path):
        calls_observed.append('read_only_image_identity_boundary')
        return {'explicit_offline_mock_of_Docker_image_inspection':True}
    monkeypatch.setattr(probe,'verify_local_base_image',base)
    return SimpleNamespace(run=run,private=private,public=public,origin=origin,goal=goal,raw=raw,source=source,
        profile=profile,profile_ref=profile_ref,proof=proof,pre=pre,config=config,state=state,plan=plan,delta=delta,
        output=tmp_path/'snapshot',bindings=bindings,mutant_receipt=mutant_receipt,calls=calls_observed)


def test_compact_original_source_chain_and_yaml_registry_without_binding_parse(case,monkeypatch):
    original=probe.FrozenFiles.read
    def compact(self,reference,**kwargs):
        assert str(case.bindings) != (str(reference) if isinstance(reference,(str,Path)) else reference['path'])
        return original(self,reference,**kwargs)
    monkeypatch.setattr(probe.FrozenFiles,'read',compact)
    graph=probe.FrozenFiles();_,_,proof,_=probe.validate_source_receipts(case.run,graph)
    assert proof['logical_fields_checked']==1030770 and str(case.bindings) in graph.files
    assert case.calls==[]


@pytest.mark.parametrize('change',['chain','audit','audit_workbook','partial_scope','stability','missing_pass','goal','recipe'])
def test_initial_source_receipts_reject_broken_actual_financial_chain(case,change):
    manifest_path=Path(case.proof['source_manifest']['path']);manifest=json.loads(manifest_path.read_text())
    if change=='chain':manifest['engine_calls'][1]['input']=case.raw
    if change=='audit':
        path=Path(case.proof['financial_audits'][1]['path']);value=json.loads(path.read_text());value['passed']=False;dump(path,value)
    if change=='audit_workbook':manifest['financial_audits'][0]=case.proof['financial_audits'][1]
    if change=='partial_scope':manifest['count']['binding_encodings']['scalar']-=1
    if change=='stability':
        path=Path(case.proof['stability']['path']);value=json.loads(path.read_text());value['second_against_goal']['passed']=False;dump(path,value)
    if change=='missing_pass':manifest['engine_calls'].pop()
    if change=='goal':manifest['workbook']=case.source
    if change=='recipe':case.bindings.write_bytes(b'changed binding bytes')
    if change not in ('audit','stability','recipe'):dump(manifest_path,manifest)
    with pytest.raises(ValueError):probe.validate_source_receipts(case.run,probe.FrozenFiles())


@pytest.mark.parametrize('change',['failed_audit','broken_chain','incomplete_stability'])
def test_source_pass_claims_are_checked_after_all_modified_receipts_are_rehashed(case,change):
    proof=deepcopy(case.proof);manifest=json.loads(Path(proof['source_manifest']['path']).read_text())
    if change=='failed_audit':
        path=Path(proof['financial_audits'][1]['path']);audit=json.loads(path.read_text());audit['passed']=False
        proof['financial_audits'][1]=dump(path,audit);manifest['financial_audits']=proof['financial_audits']
    if change=='broken_chain':manifest['engine_calls'][1]['input']=case.raw
    if change=='incomplete_stability':
        path=Path(proof['stability']['path']);stable=json.loads(path.read_text());stable['second_against_goal']['checked_existing_value_cells']-=1
        proof['stability']=dump(path,stable);manifest['stability']=proof['stability']
    proof['source_manifest']=dump(Path(proof['source_manifest']['path']),manifest)
    pre=deepcopy(case.pre);pre['source_admission']=dump(Path(pre['source_admission']['path']),proof)
    pre['source_manifest']=proof['source_manifest']
    pre['prepared_seed_manifest']=dump(Path(pre['prepared_seed_manifest']['path']),{'selected':[{'sha256':case.goal['sha256'],
        'modes':['debugging'],'source_manifest':proof['source_manifest'],'finance_evidence':{'audited_source_binding':proof}}]})
    dump(case.run/'preflight_manifest.json',pre)
    with pytest.raises(ValueError):probe.validate_source_receipts(case.run,probe.FrozenFiles())


def test_early_snapshot_uses_real_instruction_delta_and_seventeen_file_export_with_all_quality_pending(case):
    original_db=ref(case.run/'run.sqlite')
    receipt=probe.freeze_early_probe(case.run,case.output,development_only=True)
    result=json.loads(Path(receipt['path']).read_text());target=Path(result['tasks'][0]['task_directory'])
    assert result['count']==1 and result['development_only'] is True
    assert result['qualified'] is False and result['confirmation_allowed'] is False and result['publication_allowed'] is False
    assert result['pending_normal_gates']==probe.PENDING and result['five_local_controls_certified'] is False
    assert result['zero_is_provisional_until_same_version_full_normal_quality'] is True
    assert result['success_may_reject_candidate_early'] is True and result['no_resampling_authorized'] is True
    assert result['new_LO_calls']==result['new_model_calls']==result['new_Harbor_jobs']==0
    assert result['financial_bindings_table_parsed'] is False and result['new_financial_audits']==0
    assert result['physical_formula_mutations']==result['complete_changed_value_count']==2
    assert set(result['resource_task_inventory'])==set(probe.TASK_FILES) and len(probe.TASK_FILES)==17
    assert not (case.public/'instruction.md').exists() and not (case.private/'local_controls.json').exists()
    assert ref(case.run/'run.sqlite')==original_db
    binding=probe.inspect_resource_export(target)
    assert binding==result['tasks'][0]['harbor_export_binding']
    assert (target/'environment/input.xlsx').read_bytes()==Path(case.source['path']).read_bytes()
    assert (target/'tests/reference.xlsx').read_bytes()==Path(case.goal['path']).read_bytes()
    assert not any(path.name=='reference.xlsx' for path in (target/'environment').rglob('*'))
    assert result['execution_budget']==probe.BUDGET and result['tool_time_policy_version']==2
    assert result['raw_physical_injection_assertions_checked'] is True
    identity=result['normal_quality_same_version_required']
    assert identity['input_sha256']==case.source['sha256'] and identity['goal_sha256']==case.goal['sha256']
    assert identity['resource_export_binding']==binding and identity['physical_edits_sha256']==case.plan['family_adapter']['physical_edits_sha256']
    assert case.calls==['read_only_image_identity_boundary']
    from sheets_factory.evaluation.resource_frontier import freeze_selection,FrontierError
    selected=freeze_selection(receipt['path'],case.output/'offline_selection',phase='development')
    assert selected['n_attempts']==1 and selected['execution_budget']==probe.BUDGET
    assert selected['tasks'][0]['revision_hash']==result['tasks'][0]['revision_hash']
    with pytest.raises(FrontierError,match='at least ten'):
        freeze_selection(receipt['path'],case.output/'forbidden_confirmation',phase='confirmation')


@pytest.mark.parametrize('change',['optin','new_revision','initial_node','failed_construct','cancelled_task','cancelled_run','plan_sha','goal','raw_assertion','outside_edit','blocking','missing_D','wrong_D','wrong_guard_D','missing_actual_call'])
def test_early_snapshot_rejects_wrong_current_identity_and_incomplete_evidence(case,monkeypatch,change):
    if change in ('new_revision','initial_node','failed_construct','cancelled_task','cancelled_run'):
        state=deepcopy(case.state)
        if change=='new_revision':state['tasks'][0]['revision']=1
        elif change=='initial_node':state['nodes'][0]['status']='running'
        elif change=='failed_construct':state['nodes'][-1]['status']='failed'
        elif change=='cancelled_task':state['tasks'][0]['status']='cancelled'
        else:state['run']['status']='cancelled'
        monkeypatch.setattr(probe,'read_state',lambda *args:state)
    if change=='plan_sha':
        plan=deepcopy(case.plan);plan['edits'][0]['after']='=999';dump(case.private/'plan.json',plan)
    if change=='goal':Path(case.goal['path']).write_bytes(b'changed audited goal')
    if change in ('raw_assertion','outside_edit'):
        book=openpyxl.load_workbook(case.raw['path'])
        book.active['A1' if change=='raw_assertion' else 'A2']='=999';book.save(case.raw['path']);book.close()
    if change=='blocking':dump(case.private/'native_error_probe.json',{'blocking':True})
    if change=='wrong_guard_D':
        value=json.loads((case.private/'native_error_probe.json').read_text());value['required_delta']=['Other!A1']
        dump(case.private/'native_error_probe.json',value)
    if change in ('missing_D','wrong_D'):
        value=deepcopy(case.delta)
        if change=='missing_D':value['expected_changes'].pop()
        else:value['expected_changes']=['Finance!A1','Finance!Z99']
        dump(case.private/'expected_delta.json',value)
    if change=='missing_actual_call':Path(case.mutant_receipt['path']).unlink()
    with pytest.raises(ValueError):probe.freeze_early_probe(case.run,case.output,development_only=change!='optin')
    assert not (case.output/'probe_manifest.json').exists()


@pytest.mark.parametrize('change',['RAM','CPU','network','container','image','profile','source','output','implementation'])
def test_actual_first_input_execution_cannot_be_inferred_from_settings(case,change):
    record=json.loads(Path(case.mutant_receipt['path']).read_text())
    if change=='RAM':record['actual_resources']['memory_bytes']=8*1024**3
    if change=='CPU':record['actual_resources']['cpus_nanoseconds']=10**9
    if change=='network':record['create_command']=['docker','create','--network','public',case.profile['image']['id']]
    if change=='container':record['container_id']='a'*12
    if change=='image':record['image_id']='sha256:'+'f'*64
    if change=='profile':record['profile_canonical_sha256']='f'*64
    if change=='source':record['source']=case.goal
    if change=='output':record['output']=case.goal
    if change=='implementation':record['implementation']=record['upstream_engine']
    receipt=dump(Path(case.mutant_receipt['path']),record)
    with pytest.raises(ValueError):probe.validate_calculation(probe.FrozenFiles(),receipt,case.profile,case.raw,case.source)


def test_partial_export_failure_is_retained_and_existing_output_never_overwritten(case,monkeypatch):
    def failed(*args,**kwargs):raise RuntimeError('Explicit offline packaging failure')
    monkeypatch.setattr(probe,'export_resource_harbor',failed)
    with pytest.raises(RuntimeError):probe.freeze_early_probe(case.run,case.output,development_only=True)
    failure=ref(case.output/'snapshot_failure.json')
    assert json.loads(Path(failure['path']).read_text())['all_partial_artifacts_preserved'] is True
    with pytest.raises(ValueError):probe.freeze_early_probe(case.run,case.output,development_only=True)
    assert ref(case.output/'snapshot_failure.json')==failure


@pytest.mark.parametrize('change',['new_revision','normal_instruction','new_selection','revision_hash','diagnosis'])
def test_late_current_revision_instruction_or_first_selection_race_preserves_partial_failure(case,monkeypatch,change):
    real=probe.export_resource_harbor
    def export(*args,**kwargs):
        result=real(*args,**kwargs)
        if change=='new_revision':
            next_state=deepcopy(case.state);next_state['tasks'][0]['revision']=1
            monkeypatch.setattr(probe,'read_state',lambda *args:next_state)
        if change=='revision_hash':
            next_state=deepcopy(case.state);next_state['tasks'][0]['revision_hash']='other-public-bytes'
            monkeypatch.setattr(probe,'read_state',lambda *args:next_state)
        if change=='normal_instruction':(case.public/'instruction.md').write_text('different normal revision bytes')
        if change=='new_selection':monkeypatch.setattr(probe,'selection_history',lambda *args:[{'new':'selection'}])
        if change=='diagnosis':dump(case.private/'diagnosis.json',{'issues':[{'problem_id':'Q02'}]})
        return result
    monkeypatch.setattr(probe,'export_resource_harbor',export)
    with pytest.raises(ValueError):probe.freeze_early_probe(case.run,case.output,development_only=True)
    assert (case.output/'snapshot_failure.json').exists() and not (case.output/'probe_manifest.json').exists()


def test_stream_hash_no_symlinks_no_oversized_json_and_no_changed_frozen_bytes(tmp_path):
    path=tmp_path/'opaque';path.write_bytes(b'not a parsed financial object')
    graph=probe.FrozenFiles();first=graph.ref(path)
    with pytest.raises(ValueError,match='Do not parse'):graph.read(first,max_bytes=1)
    alias=tmp_path/'alias';alias.symlink_to(path)
    with pytest.raises(ValueError,match='nonsymlink'):graph.ref(alias)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):graph.finish()


def test_default_cli_reads_status_without_creating_output_or_contacting_services(case,capsys):
    assert probe.main(['--source-run',str(case.run)])==0
    assert json.loads(capsys.readouterr().out)['snapshot_created'] is False
    assert not case.output.exists() and case.calls==[]
    with pytest.raises(ValueError,match='explicit --freeze'):probe.main(['--source-run',str(case.run),'--output',str(case.output)])


def test_history_reuses_only_existing_score_blind_first_selection_guard(tmp_path):
    dump(tmp_path/'prior/selection_manifest.json',{'tasks':[{'task_id':probe.TASK,'revision':0,'revision_hash':'other','reward':0}]})
    with pytest.raises(ValueError,match='do not resample'):probe.selection_history('new',[tmp_path])
