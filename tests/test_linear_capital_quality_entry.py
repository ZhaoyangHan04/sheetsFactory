"""Prepare-only and startup lifecycle tests; no external services are invoked."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import linear_capital_quality as pipeline
from sheets_factory.task_adapters import linear_capital_portfolio as adapter
from sheets_factory.workbook import linear_capital_public_recovery as recovery

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    loader=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module

entry=load('_linear_normal_quality_entry_test',ROOT/'scripts/run_linear_capital_quality.py')
f=load('_linear_normal_entry_actual_value_fixtures',ROOT/'tests/test_linear_capital_quality_view_admission.py')
provider=f.provider
completed_view=f.completed_view
r=load('_linear_normal_entry_public_runtime_fixtures',ROOT/'tests/test_linear_capital_public_recovery.py')
tiny_runtime=r.tiny_runtime


@pytest.fixture
def prepared(completed_view,tiny_runtime,tmp_path,monkeypatch):
    root,source,terminal,result,_=completed_view
    # Financial and engine trust boundaries are fixture implementations. The
    # complete real view protocol and current-value checks still execute.
    monkeypatch.setattr(pipeline,'validate_configuration',lambda config:{'fixture':True})
    runtime=recovery.prepare_public_runtime(tmp_path/'generic-runtime')
    entry._PREPARED_SESSIONS.clear();before=source.helper.calls
    out=tmp_path/'normal-quality'
    receipt=entry.prepare(source.source_manifest,terminal,out,source_provider='fixture',
        provider_registry=source.providers.reference,public_runtime_preparation=runtime)
    return out,receipt,source,before


def test_prepare_and_guard_are_zero_service_and_cold_source_is_not_repeated(prepared,monkeypatch):
    out,receipt,source,before=prepared
    assert source.helper.calls==before+1
    def forbidden(*args,**kwargs):raise AssertionError('No external engine/model/solver in prepare-only validation')
    monkeypatch.setattr(entry,'ThreadCappedResourceLibreOfficeEngine',forbidden)
    monkeypatch.setattr(entry,'LinearCohortCodex',forbidden)
    frozen,config,admissions=entry.validate_prepared(out)
    for _ in range(3):entry.validate_prepared(out)
    assert source.helper.calls==before+1
    assert frozen['count']==1 and frozen['actual_models']==frozen['actual_LO_calls']==frozen['actual_solver_calls']==frozen['actual_Harbor_jobs']==0
    assert frozen['targets']=={'financial_modeling':1,'debugging':0}
    assert frozen['protected_task_budgets']=={'max_steps':3,'max_evidence_rounds_per_revision':2,
        'infrastructure_retries_per_stage':2,'max_additional_trials_per_revision':0}
    assert config['diagnosis']['selection']=={'include':'all','exclude':[]}
    assert config['diagnosis']['execution']['reference_evidence_transport']=='audited_summary'
    assert config['harbor']['execute_controls'] is True
    assert config['recovery']['offline_public_recovery']['cpus']==16
    assert config['agents']['container_cpus']==2 and config['agents']['container_memory']=='32g'
    assert not (out/'run.sqlite').exists() and not (out/'started.json').exists()
    assert all(isinstance(item,pipeline.LinearViewAdmission) for item in admissions)


def test_fresh_cold_read_revalidates_once_without_rederiving_source_per_node(prepared):
    out,_,source,_=prepared;before=source.helper.calls
    entry._PREPARED_SESSIONS.clear()
    frozen,_,sessions=entry.validate_prepared(out)
    assert source.helper.calls==before+1
    for _ in range(4):sessions[0].guard()
    assert source.helper.calls==before+1 and frozen['qualified'] is False


def test_cached_configuration_cannot_be_changed_by_caller(prepared):
    out,_,_,_=prepared
    frozen,config,sessions=entry.validate_prepared(out);config['run']['max_steps']=999;frozen['count']=999
    actual,config2,_=entry.validate_prepared(out)
    assert actual['count']==1 and config2['run']['max_steps']==3 and type(sessions) is tuple


def test_preparation_failure_keeps_a_zero_service_terminal(completed_view,tmp_path,monkeypatch):
    _,source,terminal,_,_=completed_view;out=tmp_path/'failure'
    monkeypatch.setattr(recovery,'validate_public_runtime',lambda value:(_ for _ in ()).throw(ValueError('runtime mismatch')))
    with pytest.raises(ValueError,match='runtime mismatch'):
        entry.prepare(source.source_manifest,terminal,out,source_provider='fixture',
            provider_registry=source.providers.reference,public_runtime_preparation=source.source_manifest)
    failed=json.loads((out/'preparation_failure.json').read_text())
    assert failed['models']==failed['LO_calls']==failed['solver_calls']==failed['Harbor_jobs']==0
    assert not (out/'preflight_manifest.json').exists()
    with pytest.raises(ValueError,match='Preserve'):entry.prepare(source.source_manifest,terminal,out,public_runtime_preparation={})


def test_resource_config_can_be_validated_without_any_services(tiny_runtime,tmp_path):
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    profile=pipeline.reference(adapter.PROFILE);registry=pipeline.reference(pipeline.DEFAULT_PROVIDERS)
    config,_=entry._configuration(entry.DEFAULT_CONFIG,tmp_path/'run',[{'runtime_profile':profile,'workbook':{'sha256':'a'*64},
        'mode':'financial_modeling'}],registry,runtime)
    assert pipeline.validate_configuration(config)['id']=='entity_group_large_v2'
    bad=deepcopy(config);bad['agents']['container_memory']='2g'
    with pytest.raises(ValueError,match='separate'):pipeline.validate_configuration(bad)


def test_true_factory_constructor_loads_normal_templates_without_engine_or_model(tiny_runtime,tmp_path,monkeypatch):
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    profile=pipeline.reference(adapter.PROFILE);registry=pipeline.reference(pipeline.DEFAULT_PROVIDERS)
    p={'runtime_profile':profile,'provider_registry':registry,'workbook':{'sha256':'a'*64},'mode':'financial_modeling'}
    config,_=entry._configuration(entry.DEFAULT_CONFIG,tmp_path/'run',[p],registry,runtime)
    opaque=object();monkeypatch.setattr(pipeline,'require_view_admission',lambda obj:p if obj is opaque else (_ for _ in ()).throw(ValueError()))
    factory=pipeline.LinearCapitalQualityFactory(config,SimpleNamespace(),None,SimpleNamespace(),admissions=[opaque])
    assert factory.templates['financial_modeling']['phases']['revision']==[
        'construct','instruction','precheck','independent_recovery','trajectory','diagnose']
    assert factory.templates['financial_modeling']['phases']['diagnosis_retry']==['diagnose']
    assert factory.load_node('trajectory').__class__.__module__=='sheets_factory.nodes.quality'


def test_isolated_quality_command_adds_only_worker_environment(tmp_path):
    instance=entry.LinearCohortCodex(ROOT,tmp_path,None,{'container_memory':'32g','container_cpus':2})
    parent=entry.cohort.CohortCodex._build_command(instance,tmp_path,'http://localhost/v1',True,'owned-test')
    command=instance._build_command(tmp_path,'http://localhost/v1',True,'owned-test')
    assert command==parent[:2]+['--env','MAX_CONCURRENCY=2']+parent[2:]
    assert command[command.index('--cpus')+1]=='2' and command[command.index('--memory')+1]=='32g'
    assert instance._build_command(tmp_path,'http://localhost/v1',False,'private-test')==entry.cohort.CohortCodex._build_command(
        instance,tmp_path,'http://localhost/v1',False,'private-test')


@pytest.mark.parametrize('fail_engine',[False,True])
def test_execute_setup_uses_real_audit_and_lease_and_cleans_every_owned_service(prepared,monkeypatch,fail_engine):
    out,_,_,_=prepared;events=[]
    class Server:
        def __init__(self,*args,**kwargs):events.append('server-created')
        def start(self):events.append('server-start');return 'http://127.0.0.1:0/'
        def stop(self):events.append('server-stop')
    class Engine:
        def __init__(self,*args,**kwargs):events.append('engine-created')
        def ensure_image(self):
            events.append('engine-check')
            if fail_engine:raise ValueError('stub infrastructure preflight failure')
    class LLM:
        def __init__(self,*args,**kwargs):events.append('llm-created')
        def _credentials(self):events.append('stub-credentials')
    class Observer:
        receipt=None
        def __init__(self,*args,**kwargs):events.append('observer-created')
        def __enter__(self):events.append('observer-start');return self
        def __exit__(self,*args):events.append('observer-stop')
    class Factory:
        def __init__(self,*args,**kwargs):events.append('factory-created')
        def run(self):events.append('factory-run');return True
    monkeypatch.setattr(entry.cohort,'DashboardServer',Server)
    monkeypatch.setattr(entry,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setattr(entry,'LinearCohortCodex',LLM)
    monkeypatch.setattr(entry,'ResourceObserver',Observer)
    monkeypatch.setattr(pipeline,'LinearCapitalQualityFactory',Factory)
    if fail_engine:
        with pytest.raises(ValueError,match='stub infrastructure'):entry.execute_prepared(out)
    else:assert entry.execute_prepared(out)==0
    assert events[-1]=='server-stop' and (out/'run.sqlite').is_file() and (out/'started.json').is_file()
    # The actual lease has been released even when engine setup fails.
    lease=entry.cohort.ProducerLease(out).acquire();lease.release()
    with pytest.raises(ValueError,match='first normal attempt'):entry.execute_prepared(out)


def test_cli_requires_preparation_review_before_explicit_run(tmp_path):
    with pytest.raises(ValueError,match='Prepare and review'):
        entry.main(['--source-manifest','x','--validation-terminal','y','--output',str(tmp_path/'run'),
            '--public-runtime-preparation','z','--run'])


def test_real_factory_loads_exact_seed_and_keeps_original_overlap_claims(prepared,monkeypatch):
    out,_,_,_=prepared;_,config,sessions=entry.validate_prepared(out)
    tasks=[]
    audit=SimpleNamespace(snapshot=lambda:{'tasks':[]},task=lambda identity,**values:tasks.append((identity,values)),
        update_run=lambda **values:None,emit=lambda *args,**kwargs:None)
    factory=pipeline.LinearCapitalQualityFactory(config,audit,None,SimpleNamespace(),admissions=sessions)
    seeds=factory.load_seeds();assert len(seeds)==1 and seeds[0]['modes']==['financial_modeling']
    proof=sessions[0].guard()
    ctx=SimpleNamespace(task_id='normal-a',mode='financial_modeling',data={'_linear_admission':sessions[0],
        'source_id':proof['workbook']['sha256'],'plan':{'edits':[{'sheet':'Sheet','cell':'A2'}]}})
    # The fixture resource file is not a production runtime profile. This
    # assertion uses the actual loaded seed/routing and a fixed explicit cap.
    from sheets_factory.workbook import resource_engine
    monkeypatch.setattr(resource_engine,'load_runtime_profile',lambda path:{'limits':{'full_target_cells':2_000_000}})
    factory._claim_targets(ctx)
    assert tasks[-1][1]['targets']==[('Sheet','A2')]
    ctx.task_id='normal-b'
    from sheets_factory.core.node import TaskRejected
    with pytest.raises(TaskRejected,match='overlapping'):factory._claim_targets(ctx)
    ctx.data['plan']['mask_ranges']=[]
    with pytest.raises(ValueError,match='range masking'):factory._claim_targets(ctx)


@pytest.mark.parametrize('unique_sources,configured,expected',[(5,4,4),(1,4,1),(5,1,1)])
def test_configuration_preserves_requested_source_concurrency_with_unique_source_clamp(tiny_runtime,tmp_path,unique_sources,configured,expected):
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    public_config=yaml.safe_load(entry.DEFAULT_CONFIG.read_text());public_config['run']['max_parallel_sources']=configured
    path=tmp_path/'configuration.yaml';path.write_text(yaml.safe_dump(public_config))
    profile=pipeline.reference(adapter.PROFILE);registry=pipeline.reference(pipeline.DEFAULT_PROVIDERS)
    proofs=[{'runtime_profile':profile,'workbook':{'sha256':f'{i:064x}'},'mode':'financial_modeling'} for i in range(unique_sources)]
    config,protected=entry._configuration(path,tmp_path/'run',proofs,registry,runtime)
    assert config['run']['max_parallel_sources']==expected and config['run']['max_sources']==unique_sources
    assert config['agents']['max_parallel_calls']==public_config['agents']['max_parallel_calls']==1
    assert protected=={key:public_config['run'][key] for key in entry.PROTECTED_BUDGETS}


@pytest.mark.parametrize('value',[0,True])
def test_configuration_rejects_nonpositive_or_boolean_source_concurrency(tiny_runtime,tmp_path,value):
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    public_config=yaml.safe_load(entry.DEFAULT_CONFIG.read_text());public_config['run']['max_parallel_sources']=value
    path=tmp_path/'configuration.yaml';path.write_text(yaml.safe_dump(public_config))
    with pytest.raises(ValueError,match='positive integer source concurrency'):
        entry._configuration(path,tmp_path/'run',[{'runtime_profile':pipeline.reference(adapter.PROFILE),
            'workbook':{'sha256':'a'*64},'mode':'financial_modeling'}],pipeline.reference(pipeline.DEFAULT_PROVIDERS),runtime)
