from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_test_factory_final_quality_join', ROOT/'scripts/join_operating_reports_factory_final_quality.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    def put(name, value):
        path = tmp_path/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value)); return m.reference(path)
    def blob(name, value):
        path = tmp_path/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value); return m.reference(path)
    goal = blob('goal.xlsx', b'UNIT TEST ONLY goal')
    monkeypatch.setattr(m, 'GOAL', goal['sha256'])
    profile = m.load_runtime_profile(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    profile_ref = m.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    dataset = tmp_path/'SpreadsheetEval'; dataset.mkdir()
    selected = []; all_cases = {}; payloads = []; source_receipts = []
    for mode in ('financial_modeling', 'debugging'):
        cases = []
        for index in range(20):
            tid = mode+'-'+str(index)
            prefix = 'SpreadsheetEval/'+tid if index < 10 else 'not_selected/'+tid
            input_ref = blob(prefix+'/environment/input.xlsx', ('UNIT TEST ONLY '+tid).encode())
            goal_ref = blob(prefix+'/tests/reference.xlsx', b'UNIT TEST ONLY goal')
            brief = blob(prefix+'/instruction.md', b'Complete the workbook.')
            for number in range(14): blob(prefix+'/support'+str(number), b'UNIT TEST ONLY support')
            points = ['Report!A'+str(i) for i in range(1, 101)]
            plan = {'mask_points': points} if mode == 'financial_modeling' else {'DBG_faults': {p:{'sheet':'Report','cell':p.split('!')[1]} for p in points}}
            plan_ref = put('private/'+tid+'/plan.json', plan)
            source = put('private/'+tid+'/source.json', {'role':'source','status':'completed',
                'actual_resources_verified':True,'thread_cap_verified':True,'profile':profile_ref,
                'requested_resources':profile['docker_resources']['source'],
                'actual_resources':{'cpus_nanoseconds':2_000_000_000,'memory_bytes':34359738368,'pids_limit':256},
                'image_id':profile['image']['id'],'output':input_ref})
            source_receipts.append(source)
            engineering = put('private/'+tid+'/individual.json', {'passed':True,'native_error_count':0,
                'given_literals_unchanged':True,'sheet_structure_unchanged':True,
                'programmatic_oracle_reward':1,'programmatic_nop_reward':0,
                'complete_primary_difference':points,'complete_primary_difference_count':100,
                'native_call_metadata':{'actual_resource_receipts':[source],'runtime_profile':profile}})
            cases.append({'task_id':tid,'individual_engineering':engineering,'private_plan':plan_ref,
                'input':input_ref,'goal':goal_ref,'instruction':brief})
            if index < 10:
                binding = {'task_id':tid}
                selected.append({'task_id':tid,'mode':mode,'harbor_export_binding':binding})
                task = tmp_path/prefix
                payloads.append({'task_id':tid,'mode':mode,'harbor_export_binding':binding,
                    'payload_files':{str(p.relative_to(task)):m.reference(p)['sha256'] for p in task.rglob('*') if p.is_file()}})
        all_cases[mode] = cases
    joins = {}
    shared_source = put('shared_source.json', {'passed':True,'actual_LO_calls_started':3,'actual_LO_calls_completed':3,
        'actual_calls':[{'role':role,'completed':True} for role in ('source1','source2','source3')], 'source':goal})
    for mode, cases in all_cases.items():
        assessment = {k:{'state':'clear' if k in m.SEMANTIC else 'not_applicable' if k=='Q08' else 'unknown',
            'reason':'Unit shared business evidence'} for k in m.CHECKS}
        reviews = {role:put('review/'+mode+'/'+role+'.json', {'issues':[]}) for role in ('public','reference')}
        dispatch = put('review/'+mode+'/dispatch.json', {'workspace_inventories':{'reference':{'source_manifest.private.json':shared_source}}})
        original = put('review/'+mode+'/terminal.json', {'failures':{},'assessments':assessment,
            'usage':{'llm_calls':2,'unknown_usage_calls':0},'review_results':reviews,'shared_semantic_passed':False,'dispatch':dispatch})
        joins[mode] = put('review/'+mode+'/native_join.json', {'candidate_count':20,'business_semantic_passed':True,
            'retained_original_model_review':original,'cases':cases})
    cohort = put('cohort.json', {'count':20,'tasks':selected,'selection_uses_confirmation_results':False})
    manifest = put('SpreadsheetEval/dataset_manifest.json', {'task_count':20,'selected_task_ids':[r['task_id'] for r in selected],
        'cohort_freeze':cohort,'tasks':payloads})
    def resource(role, tid, reward):
        result = put('actual/'+role+'/'+tid+'/result.json', {'finished_at':'unit','exception_info':None,
            'config':{'agent':{'name':role},'task':{'path':str(dataset/tid)}},'agent_info':{'name':role},
            'verifier_result':{'rewards':{'reward':reward}}})
        config = put('actual/'+role+'/'+tid+'/config.json', {'TEST_ONLY':True})
        return {'passed':True,'complete':True,'roles_observed':['agent','verifier'],'trial_config':config,'result':result}
    observation = put('observation.json', {'TEST_ONLY':True})
    commands = {}; command_resources = {}
    for role, reward in [('oracle',1),('nop',0)]:
        validations = [resource(role,t['task_id'],reward) for t in selected]
        trials = [{'task_id':t['task_id'],'result_file':r['result']['path'],'result_sha256':r['result']['sha256'],
            'reward':reward,'exception_info':None,'resolved_task_path':str(dataset/t['task_id'])} for t,r in zip(selected,validations)]
        whole = put('controls/'+role+'_whole.json', {'status':'passed','agent':role,
            'dataset_manifest_sha256':manifest['sha256'],'counts':{'dataset_tasks':20,'trial_results':20,
            'matched_rewards':20,'exceptions':0,'missing':0,'unknown':0,'duplicates':0},'trials':trials})
        resources = put('controls/'+role+'_resources.json', {'passed':True,'validations':validations})
        command_resources[role] = resources
        commands[role] = put('controls/'+role+'_command.json', {'argv':['harbor','run','-p','SpreadsheetEval','-a',role],
            'returncode':0,'cwd':str(tmp_path),'dataset_manifest':manifest,'whole_job_audit':whole,
            'actual_resources':resources,'resource_observation_receipts':[observation]})
    controls = put('controls/terminal.json', {'kind':'complete_exact_twenty_root_controls','passed':True,
        'dataset_manifest':manifest,'oracle_all20_reward':1,'nop_all20_reward':0,
        'actual_role_resources_checked':True,'command_receipts':commands})
    confirmation_resources = put('confirmation/resources.json', {'passed':True,'complete':True,'observation_receipts':[observation]})
    confirmation = put('confirmation/terminal.json', {'kind':'operating_reports_factory_frontier_terminal_v6',
        'phase':'confirmation','outer_retries':0,'resources':confirmation_resources,'results':[
            {'task_id':t['task_id'],'mode':t['mode'],'actual_attempt':{'TEST_ONLY':True},
             'score':{'state':'complete','effective_reward':0},'resources':resource('strong',t['task_id'],0)} for t in selected]})
    monkeypatch.setattr(m, 'inspect_resource_export', lambda p:{'task_id':Path(p).name})
    monkeypatch.setattr(m, 'validate_trial_observations', lambda *a,**k:{'passed':True,'complete':True})
    return {'cohort':cohort,'joins':joins,'controls':controls,'confirmation':confirmation,'dataset':dataset,
        'put':put,'source_receipts':source_receipts,'command_resources':command_resources}


def run(bundle):
    return m.build(bundle['cohort']['path'],bundle['joins']['financial_modeling']['path'],
        bundle['joins']['debugging']['path'],bundle['controls']['path'],bundle['confirmation']['path'],bundle['dataset'])


def test_all12_join_accepts_actual_individual_proofs_without_rewriting_original_unknowns(bundle):
    originals = {k:Path(v['path']).read_bytes() for k,v in bundle['joins'].items()}
    report = run(bundle)
    assert report['passed'],report.get('failure')
    assert report['kind']=='operating_report_factory_final_quality_join' and report['task_count']==20
    assert len(report['individual_engineering'])==len(report['tasks'])==20
    for task in report['tasks']:
        assert task['passed'] and set(task['assessments'])==set(m.CHECKS)
        assert task['assessments']['Q08']['state']=='not_applicable'
        assert all(a['evidence'] and a['state'] in ('clear','not_applicable') for a in task['assessments'].values())
    assert all(Path(bundle['joins'][k]['path']).read_bytes()==v for k,v in originals.items())
    assert report['new_model_LO_Harbor_calls']==0 and report['quality_is_not_difficulty_confirmation']


@pytest.mark.parametrize('defect',['control_pending','source_unverified','resource_missing_role','unknown_confirmation',
    'development_as_confirmation','missing_source_receipt','wrong_native_delta','shared_semantic_flag','extra_root_entry'])
def test_missing_or_conflicting_final_evidence_never_passes(bundle,defect):
    put=bundle['put']
    def change(record, mutate):
        data=m.read(record);mutate(data);new=put(str(Path(record['path']).relative_to(bundle['dataset'].parent)),data)
        return new
    if defect=='control_pending':change(bundle['controls'],lambda d:d.update(passed=False))
    elif defect=='source_unverified':
        change(bundle['source_receipts'][0],lambda d:d.update(actual_resources_verified=False))
    elif defect=='resource_missing_role':
        change(bundle['command_resources']['oracle'],lambda d:d['validations'][0].update(roles_observed=['agent']))
    elif defect=='unknown_confirmation':change(bundle['confirmation'],lambda d:d['results'][0]['score'].update(state='unknown',effective_reward=None))
    elif defect=='development_as_confirmation':change(bundle['confirmation'],lambda d:d.update(phase='development'))
    elif defect=='missing_source_receipt':Path(bundle['source_receipts'][0]['path']).unlink()
    elif defect=='wrong_native_delta':
        case=m.read(bundle['joins']['financial_modeling'])['cases'][0]
        change(case['individual_engineering'],lambda d:d['complete_primary_difference'].pop())
    elif defect=='shared_semantic_flag':change(bundle['joins']['financial_modeling'],lambda d:d.update(business_semantic_passed=False))
    else:(bundle['dataset']/'unexpected-task').mkdir()
    report=run(bundle)
    assert report['passed'] is False and report.get('failure')


def test_actual_resource_revalidation_failure_is_not_waived(bundle,monkeypatch):
    monkeypatch.setattr(m,'validate_trial_observations',lambda *a,**kw:{'passed':False,'complete':False})
    report=run(bundle)
    assert not report['passed'] and 'observations' in report['failure']['reason']


def test_a_currently_bound_unverified_source_receipt_is_rejected_by_its_actual_state(bundle):
    family=m.read(bundle['joins']['financial_modeling']);case=deepcopy(family['cases'][0]);engineering=m.read(case['individual_engineering'])
    source=m.read(engineering['native_call_metadata']['actual_resource_receipts'][0]);source['actual_resources_verified']=False
    new_source=bundle['put']('modified/source.json',source)
    engineering['native_call_metadata']['actual_resource_receipts']=[new_source]
    case['individual_engineering']=bundle['put']('modified/individual.json',engineering)
    task=m.read(bundle['cohort'])['tasks'][0]
    with pytest.raises(ValueError,match='source calculation'):
        m._individual(case,task,bundle['dataset'])


def test_current_resource_row_cannot_claim_only_agent_observed(bundle):
    resources=m.read(bundle['command_resources']['oracle']);row=deepcopy(resources['validations'][0]);row['roles_observed']=['agent']
    with pytest.raises(ValueError,match='Both actual resource roles'):
        m._resources(row,[])
