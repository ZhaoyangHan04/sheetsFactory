"""Prospective controls opt-in changes only one node and an explicit policy."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_joint_control_quality_entry_test',ROOT/'scripts/run_joint_control_quality.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


def document(path,value):
    path.write_text(json.dumps(value));return entry.ref(path)


@pytest.fixture(params=list(entry.BACKENDS))
def base(tmp_path,request,monkeypatch):
    # Schema-only fixture; no financial source, model or runtime is admitted.
    source=tmp_path/'base';source.mkdir();kind=request.param;calls=[]
    registry=source/'registry.yaml'
    nodes=yaml.safe_load((ROOT/'config/task_adapters/semantic_graph_nodes_v3.yaml').read_text())
    registry.write_text(yaml.safe_dump(nodes,sort_keys=False))
    seed=source/'seed_manifest.json';document(seed,{'selected':[{'unit_fixture_only':True}],
        'unique_workbooks_inspected':1,'download_url':'fixture-only','archive_sha256':None})
    code=source/'legacy.py';code.write_text('# immutable old recipe\n')
    proof=source/'financial_reference.json';document(proof,{'unit_fixture_only':True})
    config={'project_root':str(ROOT),'run_dir':str(source),'run':{'targets':{'financial_modeling':0,'debugging':1},
        'seed_manifest':str(seed),'max_steps':3,'max_evidence_rounds_per_revision':2,
        'infrastructure_retries_per_stage':2,'max_additional_trials_per_revision':0,'max_parallel_sources':1},
        'agents':{'model':'gpt-6-sol','reasoning_effort':'high','timeout_seconds':1200,
            'roles':{'reference_diagnostician':{'timeout_seconds':2400}}},
        'pipeline':{'node_registry':str(registry)},'construction':{'max_edit_count':{'debugging':100000}},
        'recovery':{'compiler_backend':'composite_journal'},'engine':{'timeout_seconds':300},
        'diagnosis':{'selection':{'include':'all','exclude':[]},'reference_evidence_policy':'independent_public_recovery'},
        'harbor':{'execute_controls':True,'concurrency':2},
        'host_runtime':{'temporary_directory':str(source/'temporary'),'minimum_free_bytes':0,'low_space_policy':'warn'}}
    config_file=source/'resolved_config.yaml';config_file.write_text(yaml.safe_dump(config,sort_keys=False))
    frozen={'kind':kind,'prepared_at':'original','development_only':True,'count':1,'source_order':['fixture-source'],
        'resolved_config':entry.ref(config_file),'prepared_seed_manifest':entry.ref(seed),
        'recipe_sha256':{str(code):entry.sha(code)},'source_artifacts_sha256':{str(proof):entry.sha(proof)},
        'host_runtime':config['host_runtime'],'protected_budgets':{k:config['run'][k]for k in
            ('max_steps','max_evidence_rounds_per_revision','infrastructure_retries_per_stage','max_additional_trials_per_revision')}}
    document(source/'preflight_manifest.json',frozen)
    @contextmanager
    def temporary(output,host,**kwargs):
        (Path(output)/'temporary').mkdir(exist_ok=True)
        yield {'temporary_directory':host['temporary_directory'],'unit_fixture_only':True}
    def validate_host(output,host):assert host['temporary_directory']==str(Path(output)/'temporary')
    cohort=SimpleNamespace(host_temporary_environment=temporary,validate_host_runtime=validate_host)
    def validate(directory):
        directory=Path(directory);calls.append(directory)
        d=entry.read(entry.ref(directory/'preflight_manifest.json'))
        assert d['kind']==kind
        for group in ('recipe_sha256','source_artifacts_sha256'):
            for p,h in d[group].items():entry.require(entry.sha(p)==h,'fake base immutable artifact changed')
        entry.checked(d['resolved_config']);entry.checked(d['prepared_seed_manifest'])
        return d
    class Factory:pass
    backend=SimpleNamespace(__file__=str(code),validate_prepared=validate,cohort=cohort)
    original_backend_for=entry.backend_for
    name=entry.BACKENDS[kind][0]
    monkeypatch.setattr(entry,'backend_for',lambda selected:(name,backend,Factory)if selected==kind else original_backend_for(selected))
    before={p: p.read_bytes()for p in source.iterdir()if p.is_file()}
    return source,config,frozen,calls,before


def test_prepare_preserves_seed_models_budgets_and_every_other_normal_node(base,tmp_path):
    source,old_config,old,calls,before=base;out=tmp_path/'phase'
    result=entry.prepare(out,source);new=entry.validate_prepared(out)
    assert isinstance(new,dict)and new['kind']==old['kind']
    assert result==entry.ref(out/'preflight_manifest.json')
    phase=entry.read(new[entry.PHASE_FIELD]);config=yaml.safe_load((out/'resolved_config.yaml').read_text())
    assert (out/'seed_manifest.json').read_bytes()==(source/'seed_manifest.json').read_bytes()
    assert phase['base_preparation']==entry.ref(source/'preflight_manifest.json')
    assert phase['base_seed_manifest']==old['prepared_seed_manifest']
    assert config['run']['targets']==old_config['run']['targets']and config['agents']==old_config['agents']
    assert config['construction']==old_config['construction']and config['recovery']==old_config['recovery']
    assert config['diagnosis']==old_config['diagnosis']and config['harbor']==old_config['harbor']
    for k,v in old_config['run'].items():
        if k!='seed_manifest':assert config['run'][k]==v
    assert config['host_runtime']['minimum_free_bytes']==0
    old_nodes=yaml.safe_load((source/'registry.yaml').read_text())
    new_nodes=yaml.safe_load((out/'joint_controls_node_registry.yaml').read_text())
    assert {k:v for k,v in old_nodes['nodes'].items()if k!='precheck'}=={k:v for k,v in new_nodes['nodes'].items()if k!='precheck'}
    assert new_nodes['nodes']['precheck']==entry.CONTROL_NODE
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert source in calls and out in calls
    assert phase['actual_LO_calls']==phase['actual_model_calls']==0
    assert new['qualified']is False


@pytest.mark.parametrize('change',['model','budget','source','node','control_setting','old_artifact'])
def test_prospective_phase_rejects_unrelated_change_even_with_updated_outer_config_ref(base,tmp_path,change):
    source,_,_,_,_=base;out=tmp_path/'phase';entry.prepare(out,source)
    f=entry.read(entry.ref(out/'preflight_manifest.json'))
    c=yaml.safe_load((out/'resolved_config.yaml').read_text())
    if change=='model':c['agents']['model']='different-model'
    if change=='budget':c['run']['max_steps']=1
    if change=='control_setting':c[entry.controls_contract().SETTING]['max_missed_root_attempts']=1
    if change in {'model','budget','control_setting'}:
        (out/'resolved_config.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
        f['resolved_config']=entry.ref(out/'resolved_config.yaml')
        phase=entry.read(f[entry.PHASE_FIELD]);phase['new_resolved_config']=f['resolved_config']
        (out/'prospective_joint_controls_phase.json').write_text(json.dumps(phase))
        f[entry.PHASE_FIELD]=entry.ref(out/'prospective_joint_controls_phase.json')
        f['source_artifacts_sha256'][str(out/'prospective_joint_controls_phase.json')]=entry.sha(out/'prospective_joint_controls_phase.json')
    if change=='source':(out/'seed_manifest.json').write_text('{"selected":[]}');f['prepared_seed_manifest']=entry.ref(out/'seed_manifest.json')
    if change=='node':
        p=out/'joint_controls_node_registry.yaml';d=yaml.safe_load(p.read_text());d['nodes']['independent_recovery']=entry.CONTROL_NODE;p.write_text(yaml.safe_dump(d))
        # Bypass a mere hash rejection to exercise the strict semantic delta.
        f['source_artifacts_sha256'][str(p)]=entry.sha(p)
        phase=entry.read(f[entry.PHASE_FIELD]);phase['new_node_registry']=entry.ref(p)
        (out/'prospective_joint_controls_phase.json').write_text(json.dumps(phase))
        f[entry.PHASE_FIELD]=entry.ref(out/'prospective_joint_controls_phase.json')
        f['source_artifacts_sha256'][str(out/'prospective_joint_controls_phase.json')]=entry.sha(out/'prospective_joint_controls_phase.json')
    if change=='old_artifact':(source/'legacy.py').write_text('# changed old code\n')
    (out/'preflight_manifest.json').write_text(json.dumps(f))
    with pytest.raises((ValueError,AssertionError)):entry.validate_prepared(out)


def test_preparation_rejects_nested_phase_and_never_overwrites_old_directory(base,tmp_path):
    source,_,_,_,_=base;out=tmp_path/'phase';entry.prepare(out,source)
    with pytest.raises(ValueError,match='fresh directory'):entry.prepare(out,source)
    with pytest.raises(ValueError,match='another controls phase'):entry.prepare(tmp_path/'nested',out)


def test_actual_backend_dispatch_retains_real_factory_classes():
    for kind,(name,filename,factory_name)in entry.BACKENDS.items():
        actual,module,factory=entry.backend_for(kind)
        assert actual==name and Path(module.__file__).name==filename and factory.__name__==factory_name
        assert callable(module.validate_prepared)


def test_startup_flag_cannot_silently_launch_normal_quality(monkeypatch,tmp_path):
    monkeypatch.setattr(entry,'execute_prepared',lambda *a,**k:pytest.fail('unexpected normal quality execution'))
    with pytest.raises(SystemExit)as error:
        entry.main(['--prepared',str(tmp_path),'--startup-smoke',str(tmp_path/'smoke'),'--run'])
    assert error.value.code==2
