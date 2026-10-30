"""Offline entry checks; mocked admissions certify no financial workbook."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.reporting import read_run
from sheets_factory.resume import ProducerLease
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.task_adapters.public_input_priority import canonical,ref,sha

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full_graph_entry',ROOT/'scripts/run_full_graph_quality.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return ref(path)


def source_fixture(folder,index=0):
    folder.mkdir(parents=True);book=folder/'source.xlsx';book.write_bytes(('Unit source'+str(index)).encode())
    original=folder/'original.xlsx';original.write_bytes(('Unit original'+str(index)).encode())
    audit=dump(folder/'audit.json',{'unit_fixture':True});scenarios=dump(folder/'scenarios.json',{})
    manifest=dump(folder/'manifest.json',{'public_scenarios':scenarios})
    financial=dump(folder/'financial.json',{'original_source':ref(original),'actual_stability':audit,
        'original_independent_audits':{'fixture':audit},'financial_validation_method':'unit_fixture'})
    binding={'source':ref(book),'source_manifest':manifest,'scope_inventory':audit,
        'financial_admission':financial,'public_input_priority_audit':audit}
    handoff=dump(folder/'handoff.json',{'status':'actual_source_financial_and_public_numeric_timing_certificates_complete','source_binding':binding})
    code=folder/'compiler.py';code.write_text('# Offline fixture\n');policy=dump(folder/'policy.json',{'version':2})
    edits_hash=canonical([index])
    compiler=dump(folder/'compiler_handoff.json',{'recipe':{'src/sheets_factory/task_adapters/composite_full_family_v2.py':ref(code)},
        'policy':policy,'edits_sha256':edits_hash,'root_count':1})
    probe=dump(folder/'engineering_receipt.json',{'edits_sha256':edits_hash,'root_count':1})
    calls=dump(folder/'engine_calls.json',[])
    return {'source_handoff':handoff,'compiler_handoff':compiler,'joint_engineering_probe':probe,
        'joint_engine_calls':calls,'profile_id':'C'+str(index+1).zfill(2)},ref(original)


@pytest.fixture
def environment(tmp_path,monkeypatch):
    source,original=source_fixture(tmp_path/'source')
    monkeypatch.setattr(entry,'validate_joint_seed',lambda seed,settings:{'workbook':seed['scc_activity_binding']['source'],'unit_admission':True})
    monkeypatch.setattr(entry,'recipe_files',lambda:{str(ROOT/'config/nodes.yaml'):sha(ROOT/'config/nodes.yaml')})
    return source,original


def prepare_one(tmp_path,environment):
    source,_=environment;output=tmp_path/'prepared'
    frozen=entry.prepare(output,source_handoff=source['source_handoff']['path'],
        compiler_handoff=source['compiler_handoff']['path'],joint_probe=source['joint_engineering_probe']['path'])
    return output,frozen


def test_prepare_only_has_dev_targets_full_quality_data_temp_and_no_lease(tmp_path,monkeypatch,environment):
    monkeypatch.setattr(entry.cohort.ProducerLease,'acquire',lambda *a:pytest.fail('Prepare may not take lease'))
    before=os.environ.get('TMPDIR');output,frozen=prepare_one(tmp_path,environment)
    config=yaml.safe_load((output/'resolved_config.yaml').read_text())
    assert config['run']['targets']=={'financial_modeling':0,'debugging':1}
    assert config['agents']['model']=='gpt-6-sol' and config['agents']['reasoning_effort']=='high'
    assert config['agents']['max_parallel_calls']==config['run']['max_parallel_sources']==4
    assert config['construction']['max_edit_count']['debugging']==100000
    assert config['diagnosis']['selection']=={'include':'all','exclude':[]}
    assert config['diagnosis']['reference_evidence_policy']=='independent_public_recovery'
    assert config['harbor']['execute_controls'] is True
    assert config[entry.JOINT_SETTING]['contract']==entry.JOINT_METHOD
    assert config['prompt_overrides']['diagnosis.md']=='diagnosis_joint_financial.md'
    assert frozen['host_runtime']['temporary_directory']==str(output/'temporary')
    assert os.environ.get('TMPDIR')==before and frozen['actual_model_calls']==frozen['actual_LO_calls']==0
    assert not frozen['qualified'] and entry.validate_prepared(output)==frozen


def test_prepared_manifest_supports_real_factory_load_seeds(tmp_path,environment):
    output,_=prepare_one(tmp_path,environment)
    config=yaml.safe_load((output/'resolved_config.yaml').read_text())
    updates=[]
    factory=object.__new__(FactoryPipeline);factory.config=config;factory.targets=config['run']['targets']
    factory.audit=type('ReadOnlyAudit',(),{'update_run':lambda self,**kwargs:updates.append(kwargs)})()
    seeds=FactoryPipeline.load_seeds(factory)
    assert len(seeds)==1 and updates[-1]['discovered_sources']==1
    assert updates[-1]['source_archive'].startswith('private-full-financial-graph:')
    assert updates[-1]['source_archive_sha256'] is None


def test_cli_never_executes_without_explicit_run(tmp_path,monkeypatch,environment):
    source,_=environment
    monkeypatch.setattr(entry,'execute_prepared',lambda *a,**k:pytest.fail('Explicit --run required'))
    assert entry.main(['--source-handoff',source['source_handoff']['path'],'--compiler-handoff',source['compiler_handoff']['path'],
        '--joint-probe',source['joint_engineering_probe']['path'],'--output',str(tmp_path/'prepared')])==0


@pytest.mark.parametrize('defect',['source','recipe','config','order'])
def test_prepared_sources_recipe_config_and_order_cannot_change(tmp_path,environment,defect):
    output,frozen=prepare_one(tmp_path,environment)
    if defect=='source':Path(environment[0]['source_handoff']['path']).write_text('{}')
    elif defect=='recipe':frozen['recipe_sha256'][str(ROOT/'config/nodes.yaml')]='0'*64;dump(output/'preflight_manifest.json',frozen)
    elif defect=='config':(output/'resolved_config.yaml').write_text('run: {}')
    else:frozen['source_order']=['0'*64];dump(output/'preflight_manifest.json',frozen)
    with pytest.raises(ValueError):entry.validate_prepared(output)


@pytest.mark.parametrize('count',[0,2,9,11,True])
def test_only_one_or_ten_sources_are_supported(count):
    with pytest.raises(ValueError):entry.selected_specs(count=count)


def prepare_ten(tmp_path,monkeypatch,wrong_order=False):
    specs=[];originals=[]
    for index in range(10):
        source,original=source_fixture(tmp_path/('source10_'+str(index)),index);specs.append(source);originals.append(original)
    selection=dump(tmp_path/'selection.json',{'kind':'full_graph_joint_quality_source_selection','model_scores_consulted':False,'selected':specs})
    selected=[{'sha256':original['sha256'],'profile_id':source['profile_id']} for source,original in zip(specs,originals)]
    if wrong_order:selected.reverse()
    batch=dump(tmp_path/'original_batch.json',{'selected':selected})
    monkeypatch.setattr(entry.cohort,'validate_batch',lambda d,b:d['selected'])
    output=tmp_path/'prepared10'
    return output,entry.prepare(output,count=10,source_selection=selection['path'],original_batch=batch['path'])


def test_final_ten_requires_complete_original_source_order_and_main_resume(tmp_path,monkeypatch,environment):
    output,frozen=prepare_ten(tmp_path,monkeypatch)
    assert frozen['targets']=={'financial_modeling':10,'debugging':10} and not frozen['development_only']
    with pytest.raises(ValueError,match='terminal main continuation'):entry.execute_prepared(output)


def test_final_ten_cannot_substitute_or_reorder_original_profiles(tmp_path,monkeypatch,environment):
    with pytest.raises(ValueError,match='frozen order'):prepare_ten(tmp_path,monkeypatch,True)


def test_development_candidate_cannot_be_added_to_formal_main(tmp_path,environment):
    output,_=prepare_one(tmp_path,environment)
    with pytest.raises(ValueError,match='development runs are separate'):entry.execute_prepared(output,resume=tmp_path/'main')


def stubs(monkeypatch,observed,fail=False):
    class Backend:
        def __init__(self,*a):pass
        def _credentials(self):
            if fail:raise RuntimeError('Unit setup failure; no network')
    class Engine:
        def __init__(self,*a):pass
        def metadata(self):return {'image_id':entry.cohort.IMAGE_ID}
    class Dashboard:
        def __init__(self,*a,**k):pass
        def start(self):return 'http://unit.invalid/'
        def stop(self):observed.append('stopped')
    class Factory:
        def __init__(self,config,audit,*a,**k):observed.append(deepcopy(config));self.audit=audit
        def run(self):self.audit.update_run(status='shortfall');return False
    monkeypatch.setattr(entry.cohort,'CohortCodex',Backend);monkeypatch.setattr(entry.cohort,'LibreOfficeEngine',Engine)
    monkeypatch.setattr(entry.cohort,'DashboardServer',Dashboard);monkeypatch.setattr(entry,'SCCActivityFactory',Factory)


@pytest.mark.parametrize('fail',[False,True])
def test_explicit_run_and_setup_failure_release_resources_and_temp(tmp_path,monkeypatch,environment,fail):
    output,_=prepare_one(tmp_path,environment);observed=[];stubs(monkeypatch,observed,fail)
    before=os.environ.get('TMPDIR')
    if fail:
        with pytest.raises(RuntimeError,match='Unit setup'):entry.execute_prepared(output)
    else:assert entry.execute_prepared(output)==2
    assert 'stopped' in observed and os.environ.get('TMPDIR')==before
    assert read_run(output)['run']['producer_active'] is False
    with ProducerLease(output):pass


def test_terminal_resume_keeps_budgets_agents_targets_and_exact_history(tmp_path,monkeypatch,environment):
    output,_=prepare_ten(tmp_path,monkeypatch);main=tmp_path/'main';main.mkdir()
    config=yaml.safe_load((output/'resolved_config.yaml').read_text());config['run_dir']=str(main)
    config['host_runtime']=entry.cohort.host_runtime_settings(main)
    seeds=dump(main/'seed_manifest.json',{'selected':[]});config['run']['seed_manifest']=seeds['path']
    config['agents']['max_parallel_calls']=2;config['run']['max_parallel_sources']=2;config['run']['max_sources']=10
    config.pop(entry.JOINT_SETTING);config.pop('pipeline')
    (main/'resolved_config.yaml').write_text(yaml.safe_dump(config));before=deepcopy(config)
    dump(main/'preflight_manifest.json',{'recipe_sha256':{str(ROOT/'config/nodes.yaml'):sha(ROOT/'config/nodes.yaml')},
        'source_artifacts_sha256':{},'prepared_seed_manifest':seeds,'host_runtime':entry.cohort.host_runtime_settings(main)})
    original=(main/'preflight_manifest.json').read_bytes()
    AuditStore(main,{'id':'main','status':'cancelled','producer_active':False,'wall_seconds':1})
    observed=[];stubs(monkeypatch,observed)
    assert entry.execute_prepared(output,resume=main)==2
    after=yaml.safe_load((main/'resolved_config.yaml').read_text())
    assert after['run']['targets']==before['run']['targets']=={'financial_modeling':10,'debugging':10}
    assert all(after['run'].get(k)==before['run'].get(k) for k in entry.PROTECTED_BUDGETS)
    old_agents=deepcopy(before['agents']);new_agents=deepcopy(after['agents'])
    assert old_agents.pop('max_parallel_calls')==2 and new_agents.pop('max_parallel_calls')==4 and old_agents==new_agents
    assert (main/'preflight_manifest.json').read_bytes()==original
    assert len(list((main/'private/resume').glob('resolved_config_*_*.yaml')))==2
    addendum=json.loads(next((main/'runtime_supplements').glob('full_graph_joint_*.json')).read_text())
    assert addendum['old_task_and_content_evidence_infrastructure_budgets_preserved'] and addendum['old_config_hashes_are_historical']
