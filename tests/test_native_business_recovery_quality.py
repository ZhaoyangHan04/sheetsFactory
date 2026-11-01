"""Fixed old FM material, genuine opaque admission, all12 and actual role gates."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace

import pytest
import yaml

from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
from test_reference_review_reporting import reviewed_run
from test_reference_evidence_policy import context as reference_context
from test_heterogeneous_native_quality import scoped_goal
import test_operating_reports_financial_cohort_quality as transport

ROOT=Path(__file__).resolve().parents[1]


def entry():
    loader=importlib.util.spec_from_file_location('_native_business_recovery_test',ROOT/'scripts/run_native_business_recovery_quality.py')
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module


def configuration(module,out):
    value=yaml.safe_load(module.DEFAULT_CONFIG.read_text())
    value.update(project_root=str(ROOT),run_dir=str(out),pipeline={'node_registry':str(module.REGISTRY)})
    value[module.original.SETTING]=module.setting();return value


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    """A fake cold provider replaces the expensive source replay only."""
    module=entry()
    def save(name,data):return files.write(tmp_path/name,data)
    def raw(name,data):
        path=tmp_path/name;path.write_bytes(data);return files.reference(path)
    inp=raw('input.xlsx',b'the original masked workbook');goal=raw('goal.xlsx',b'the original healthy workbook')
    brief=raw('brief.md',b'B'*1246+b'\n');other=save('other.json',{'pure':'source replay mocked'})
    rows=[{'sheet':'Report','cell':'A'+str(i)} for i in range(1,767)]
    plan={'financial_scope':[[r['sheet'],r['cell']] for r in rows],'faults':[], 'known_protected_points':other}
    material=save('material.json',{'review_scope':other})
    actual={'mode':'financial_modeling','input':inp,'goal':goal,'instruction':brief,
        'complete_actual_D':other,'independent_scope_coverage':other}
    terminal=save('terminal.json',actual)
    evidence={'actual_ref':terminal,'actual':actual,'material_ref':material,'material':{'review_scope':other},
        'preparation':{'config':other},'source_ref':goal,'profile_ref':files.reference(module.original.PROFILE),
        'plan':plan,'delta':{'actual_change_count':766,'expected_changes':rows,'expected_fixed_errors':[]}}
    evidence_ref=save('fake_cold_evidence.json',evidence)
    provider=tmp_path/'cold_provider.py'
    provider.write_text('import json\nfrom pathlib import Path\n'
        +'def checked_material(ref):\n return json.loads(Path('+repr(evidence_ref['path'])+').read_text())\n'
        +'def recipes():\n return {'+repr(other['path'])+':'+repr(other['sha256'])+'}\n'
        +'def read(ref):\n return json.loads(Path(ref["path"]).read_text())\n')
    monkeypatch.setattr(module.original,'BOUNDARY',provider)
    dev=save('probe.json',{'actual_task_validation':terminal,'complete_changed_value_set_count':766,
        'material_task_version':{'sha256':'3b26ea9e5605ca452a462a37ffea412c789bd5bb3fe9f73c662280813748a737'},
        'tasks':[{'harbor_export_binding':{'resource_runtime':{'source_artifacts':{'input':inp,'goal':goal,'instruction':brief}}}}]})
    for key,val in {'ACTUAL_SHA':terminal['sha256'],'INPUT_SHA':inp['sha256'],'GOAL_SHA':goal['sha256'],
        'INSTRUCTION_SHA':brief['sha256'],'DEV_PROBE':Path(dev['path']),'DEV_SHA':dev['sha256']}.items():monkeypatch.setattr(module,key,val)
    return SimpleNamespace(module=module,terminal=terminal,inp=inp,goal=goal,brief=brief,other=other,
        evidence=evidence,evidence_ref=evidence_ref,provider=provider,dev=dev)


def test_original_live_opaque766_gate_and_first_material_byte_join(boundary):
    f=boundary;m=f.module;live=m.native_admission(f.terminal);proof=m.admission(live)
    assert type(live) is m.original.NativeScopeAdmission and proof['mode']=='financial_modeling'
    assert proof['independent_scope_count']==766 and len(Path(proof['instruction']['path']).read_bytes())==1247
    assert proof['input']==f.inp and proof['goal']==f.goal and proof['instruction']==f.brief
    for fake in (proof,object.__new__(m.original.NativeScopeAdmission)):
        with pytest.raises(ValueError):m.admission(fake)
    Path(f.provider).write_text('changed current provider')
    with pytest.raises(ValueError):m.admission(live)


@pytest.mark.parametrize('problem',['terminal','FM','D','input','goal','brief','snapshot'])
def test_wrong_case_scope_or_changed_material_cannot_enter(boundary,problem):
    f=boundary;m=f.module
    if problem=='terminal':m.ACTUAL_SHA='0'*64
    elif problem=='snapshot':Path(f.dev['path']).write_text('{}')
    else:
        if problem=='FM':f.evidence['actual']['mode']='debugging'
        elif problem=='D':f.evidence['delta']['actual_change_count']=765
        else:f.evidence['actual'][{'input':'input','goal':'goal','brief':'instruction'}[problem]]={**f.other}
        Path(f.evidence_ref['path']).write_text(json.dumps(f.evidence))
    with pytest.raises(ValueError):m.native_admission(f.terminal)


def test_all12_professional_profile_and_private_node_registry_are_real(tmp_path):
    from sheets_factory.checkers import DiagnosisRunner
    from sheets_factory.nodes.construction import prompt
    m=entry();config=configuration(m,tmp_path)
    assert m.validate_configuration(config)['id']=='entity_group_large_v2'
    assert DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids']==[f'Q{i:02d}' for i in range(1,13)]
    assert prompt(SimpleNamespace(config=config),'diagnosis.md')==(ROOT/'prompts/diagnosis_professional_review_v1.md').read_text()
    cls=m.NativeQualityFactory
    assert cls.run_phase.__code__ is m.original.NativeQualityFactory.run_phase.__code__
    assert cls.run_phase.__globals__ is not m.original.NativeQualityFactory.run_phase.__globals__
    assert m.ConstructNode.execute.__code__ is m.original_nodes.NativeConstructNode.execute.__code__
    assert m.ConstructNode.execute.__globals__ is not m.original_nodes.NativeConstructNode.execute.__globals__
    registry=yaml.safe_load(m.REGISTRY.read_text())['nodes']
    assert len(registry)==11 and registry['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    factory=object.__new__(m.NativeQualityFactory);factory.node_registry=registry
    for node in registry:assert factory.load_node(node).node_id is not None
    assert m.original.REGISTRY!=m.REGISTRY and m.original_nodes.setting()==m.original.setting()


@pytest.mark.parametrize('change',['checks','policy','Harbor','model','CPU','memory','scope','registry','prompt','DBG','filter'])
def test_no_normal_gate_or_resource_reduction(tmp_path,change):
    m=entry();c=configuration(m,tmp_path)
    if change=='checks':c['diagnosis']['selection']['exclude']=['Q04']
    elif change=='policy':c['diagnosis']['reference_evidence_policy']='independent_public_recovery'
    elif change=='Harbor':c['harbor']['execute_controls']=False
    elif change=='model':c['agents']['model']='gpt-6.1-sol'
    elif change=='CPU':c['agents']['container_cpus']=1
    elif change=='memory':c['agents']['container_memory']='64g'
    elif change=='scope':c['construction']['analysis_limits']['max_profile_cells']=100
    elif change=='registry':c['pipeline']['node_registry']='another'
    elif change=='prompt':c['prompt_overrides']['diagnosis.md']='diagnosis.md'
    elif change=='DBG':c['run']['targets']['debugging']=1
    else:c['run']['source_filter']='different source'
    with pytest.raises(ValueError):m.validate_configuration(c)


def test_prepare_warm_cold_zero_services_one_fixed_inventory(boundary,tmp_path,monkeypatch):
    f=boundary;m=f.module;out=tmp_path/'normal'
    monkeypatch.setitem(m._namespace,'configure',lambda p,o,proofs:{**configuration(m,o),'host_runtime':{'fixture':True},
        'run':{**configuration(m,o)['run'],'seed_manifest':str(o/'seed_manifest.json')}})
    monkeypatch.setitem(m._namespace,'recipes',lambda *a:{f.other['path']:f.other['sha256']})
    # The pipeline facade points to the actual wrapper function, retaining all
    # checks while the source cold provider itself is the explicit fixture.
    monkeypatch.setattr(m,'execute_prepared',lambda *a,**k:pytest.fail('No services in prepare'))
    ref=m.prepare([f.terminal],out);record=files.read(ref)
    assert record['targets']=={'financial_modeling':1,'debugging':0} and record['count']==1
    assert all(record[k]==0 for k in ('actual_models','actual_LO_calls','actual_Harbor_jobs'))
    assert m.validate_prepared(out)[0]==record
    m._namespace['_SESSIONS'].clear();assert m.validate_prepared(out)[0]==record
    seed=files.read(record['prepared_seed_manifest'])['selected'][0]
    assert seed['modes']==['financial_modeling'] and not seed['finance_evidence']['debugging_eligible']
    assert not record['existing_development_score_transferred']


def test_brief_repair_is_forbidden_and_current_context_rejects_changed_bytes(boundary,tmp_path):
    f=boundary;m=f.module;live=m.native_admission(f.terminal);proof=m.admission(live)
    ctx=SimpleNamespace(config=configuration(m,tmp_path),mode='financial_modeling',source=Path(proof['workbook']['path']),
        data={'_native_scope_admission':live,'plan':{'public_instruction':Path(f.brief['path']).read_text()}})
    m.context(ctx)
    with pytest.raises(m.TaskRejected,match='explicit new'):m.RepairNode().execute(ctx)
    ctx.data['plan']['public_instruction']='changed brief'
    with pytest.raises(ValueError,match='1247-byte'):m.context(ctx)


def test_partial_source_scope_keeps_expected_offscope_errors_visible(scoped_goal):
    m=entry();goal,proof,value,_=scoped_goal
    receipt=m._nns['scoped_native_evidence'](value,proof,goal,['Business!B1','Business!B2'],3)
    assert receipt['blocking'] is False and receipt['retained_offscope_errors']==[['Provided Context','A1','#DIV/0!']]
    assert receipt['goal_sha256']==files.reference(goal)['sha256']
    assert not receipt['whole_source_business_correctness_certified']


# Run repaired resource/report guards through this new namespace and registry.
def rebound(fn):return FunctionType(fn.__code__,{**fn.__globals__,'entry':entry},fn.__name__,fn.__defaults__,fn.__closure__)


@pytest.fixture
def resource_case(tmp_path,monkeypatch):return rebound(transport.resource_case.__wrapped__)(tmp_path,monkeypatch)


@pytest.mark.parametrize('shape',['base5','rich7'])
def test_actual_Harbor_sparse_rich_and_complete_export_binding(resource_case,shape):
    transport.test_real_resource_package_accepts_exact_base_and_rich_bindings(resource_case,shape)


@pytest.mark.parametrize('problem',['missing_observer','wrong_agent','resource_package'])
def test_actual_Harbor_gap_keeps_reward_and_withdraws_qualification(resource_case,monkeypatch,problem):
    transport.test_actual_resource_gap_quarantines_only_original_and_retains_raw_rewards(resource_case,monkeypatch,problem)


@pytest.mark.parametrize('compact',[True,False])
def test_full_artifact_or_compact_context_reports_exact_supported_evidence(reviewed_run,compact):
    rebound(transport.test_private_reporter_validates_genuine_full_and_compact_transport_without_old_globals)(reviewed_run,compact)


@pytest.mark.parametrize('problem',['inventory','full','binding'])
def test_unbound_current_reference_context_cannot_pass(reviewed_run,problem):
    rebound(transport.test_reporter_rejects_changed_full_compact_inventory_or_binding)(reviewed_run,problem)


def test_early_panel_precedes_any_actual_cold_gate(tmp_path,monkeypatch):
    m=entry();events=[]
    @contextmanager
    def monitor(*a,**k):events.append('panel');yield {}
    monkeypatch.setattr(m,'admission_monitor',monitor)
    monkeypatch.setattr(m,'prepare',lambda *a,**k:events.append('prepare') or {'fixture':True})
    monkeypatch.setattr(m,'execute_prepared',lambda *a,**k:events.append('run') or 0)
    assert m.main(['--actual-terminal','/exact','--output',str(tmp_path/'new'),'--run'])==0
    assert events==['panel','prepare','run']


@pytest.mark.parametrize('problem',[None,'unreleasable','stale_binding','missing_Q04','disabled_Q12'])
def test_complete_supported_Q04_and_Q12_gate_is_retained(reference_context,problem):
    transport.test_original_complete_supported_reference_gate_remains_decisive(reference_context,problem)
