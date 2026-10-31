"""Thread-cap lifecycle and strict receipt tests; no actual Docker or LO."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.workbook import resource_engine as base
from sheets_factory.workbook import thread_capped_resource_engine as capped
from sheets_factory.workbook.engine import LibreOfficeEngine, WorkbookEngineError

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'


class Docker:
    def __init__(self):
        self.events=[]; self.container_id='a'*64
        self.environments=[['MAX_CONCURRENCY=2'],['MAX_CONCURRENCY=2']]
        self.env_ids=[self.container_id,self.container_id]; self.inspect_count=0
        self.exit_code='0'; self.start_fails=False

    def run(self,command,timeout):
        self.events.append((list(command),timeout))
        if command[:3]==['docker','image','inspect']:
            return base.load_runtime_profile(PROFILE)['image']['id']+'\n'
        if command[:2]==['docker','create']:return self.container_id+'\n'
        if command[:2]==['docker','inspect']:
            if command[-1]==capped.ENV_FORMAT:
                index=self.inspect_count;self.inspect_count+=1
                return '\n'.join([self.env_ids[index],*self.environments[index]])+'\n'
            if command[-1]=='{{.State.ExitCode}}':return self.exit_code+'\n'
            return self.container_id+'\n'+json.dumps({'NanoCpus':2*10**9,'Memory':32*1024**3,'PidsLimit':256})
        if command[:2]==['docker','start']:
            if self.start_fails:raise WorkbookEngineError('Mock 600 s failure')
            return ''
        if command[:2]==['docker','cp']:
            if command[2].endswith(':/tmp/result.xlsx'):Path(command[3]).write_bytes(b'PK'+b'x'*200)
            return ''
        raise AssertionError(command)

    def cleanup(self,command,**kwargs):
        assert command[:3]==['docker','rm','--force']
        self.events.append((list(command),kwargs['timeout']))
        return SimpleNamespace(returncode=0,stdout='',stderr='')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    docker=Docker()
    monkeypatch.setattr(base.shutil,'which',lambda name:'/usr/bin/docker')
    monkeypatch.setattr(LibreOfficeEngine,'_run',staticmethod(docker.run))
    monkeypatch.setattr(base.original_engine.subprocess,'run',docker.cleanup)
    source=tmp_path/'input.xlsx';source.write_bytes(b'PK'+b'i'*200)
    engine=capped.ThreadCappedResourceLibreOfficeEngine(tmp_path,PROFILE,receipt_directory=tmp_path/'resources')
    return engine,docker,source,tmp_path


def terminal(directory):
    path=next((directory/'resources').glob('*.terminal.json'))
    return path,json.loads(path.read_text())


def test_only_create_environment_changes_with_before_after_fullid_inspections_and_base_cleanup(setup):
    engine,docker,source,directory=setup
    result=engine.recalculate(source,directory/'output.xlsx')
    path,record=terminal(directory)
    create=next(c for c,_ in docker.events if c[:2]==['docker','create'])
    assert create[create.index('--env')+1]=='MAX_CONCURRENCY=2' and create.count('--env')==1
    assert create[create.index('--cpus')+1]=='2' and create[create.index('--memory')+1]==str(32*1024**3)
    assert create[create.index('--network')+1]=='none' and create[create.index('--pids-limit')+1]=='256'
    assert record['implementation']==base._reference(base.__file__)
    assert record['thread_cap_adapter']==base._reference(capped.__file__)
    assert record['thread_cap_verified'] is True and record['status']=='completed'
    before,after=[i for i,(c,_) in enumerate(docker.events) if c[-1:]==[capped.ENV_FORMAT]]
    start=next(i for i,(c,_) in enumerate(docker.events) if c[:2]==['docker','start'])
    exit_check=next(i for i,(c,_) in enumerate(docker.events) if c[-1:]==['{{.State.ExitCode}}'])
    copyout=next(i for i,(c,_) in enumerate(docker.events) if c[:2]==['docker','cp'] and c[2].endswith(':/tmp/result.xlsx'))
    assert before<start<exit_check<after<copyout
    assert all(docker.events[i][0][2]==docker.container_id for i in (before,after))
    assert docker.events[start][1]==600 and docker.events[-1][0][:3]==['docker','rm','--force']
    assert record['thread_cap_after']['exit_code_observed']=='0' and result.is_file()
    assert not list(directory.glob('*.tmp')) and getattr(engine._local,'record',None) is None


@pytest.mark.parametrize('environment',[[],['MAX_CONCURRENCY=3'],['MAX_CONCURRENCY=2','MAX_CONCURRENCY=2'],['MAX_CONCURRENCY=02'],['MAX_CONCURRENCY=2.0'],['MAX_CONCURRENCY=2 ']])
@pytest.mark.parametrize('stage',[0,1])
def test_absent_duplicate_or_nonexact_cap_rejects_and_preserves_failure_cleanup(setup,environment,stage):
    engine,docker,source,directory=setup;docker.environments[stage]=environment
    with pytest.raises(WorkbookEngineError,match='exactly one MAX_CONCURRENCY=2'):
        engine.recalculate(source,directory/'failed.xlsx')
    _,record=terminal(directory)
    assert record['status']=='failed' and record['thread_cap_verified'] is False
    assert record['thread_cap_'+('before' if stage==0 else 'after')]['values']==environment
    assert not any(c[:2]==['docker','cp'] and c[2].endswith(':/tmp/result.xlsx') for c,_ in docker.events)
    assert any(c[:3]==['docker','rm','--force'] for c,_ in docker.events)
    if stage==0:assert not any(c[:2]==['docker','start'] for c,_ in docker.events)


@pytest.mark.parametrize('stage',[0,1])
def test_inspection_foreign_fullid_is_not_accepted(setup,stage):
    engine,docker,source,directory=setup;docker.env_ids[stage]='b'*64
    with pytest.raises(WorkbookEngineError):engine.recalculate(source,directory/'failed.xlsx')
    assert terminal(directory)[1]['status']=='failed'


@pytest.mark.parametrize('flag',['--env','--env=','-e','-eMAX_CONCURRENCY=3'])
def test_create_does_not_override_an_existing_assignment(setup,flag):
    engine,docker,_,_=setup;engine._local.record={}
    env=[flag,'MAX_CONCURRENCY=3'] if flag in ('--env','-e') else [flag+'MAX_CONCURRENCY=3'] if flag=='--env=' else [flag]
    with pytest.raises(WorkbookEngineError,match='already supplies'):
        engine._run(['docker','create',*env,engine.profile['image']['id']],30)
    assert not docker.events


def source_module():
    loader=importlib.util.spec_from_file_location('_linear_cap_test_builder',ROOT/'scripts/build_linear_capital_source.py')
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module


def test_existing_resource_validator_and_cap_validator_both_required(setup):
    engine,_,source,directory=setup;output=engine.recalculate(source,directory/'output.xlsx')
    module=source_module();path,record=terminal(directory)
    call={'input':module.reference(source),'output':module.reference(output)}
    frozen={'runtime_profile':module.reference(PROFILE),'runtime_profile_value':base.load_runtime_profile(PROFILE)}
    evidence=module.validate_actual_call(call,module.reference(path),frozen)
    assert evidence['actual_resources']==record['actual_resources'] and evidence['thread_cap_verified'] is True
    assert evidence['container_id']==record['container_id'] and evidence['thread_cap_after']==record['thread_cap_after']
    assert str(Path(capped.__file__).resolve()) in module.recipes()


@pytest.mark.parametrize('mutation',['absent','duplicate','number','foreign_id','foreign_command','adapter','unverified','reversed_time','bad_exit','base_resources'])
def test_cold_validation_rejects_incomplete_cap_or_original_resource_proof(setup,mutation):
    engine,_,source,directory=setup;output=engine.recalculate(source,directory/'output.xlsx')
    module=source_module();path,record=terminal(directory)
    call={'input':module.reference(source),'output':module.reference(output)}
    frozen={'runtime_profile':module.reference(PROFILE),'runtime_profile_value':base.load_runtime_profile(PROFILE)}
    if mutation=='absent':record.pop('thread_cap_before')
    elif mutation=='duplicate':record['thread_cap_after']['values']*=2
    elif mutation=='number':record['thread_cap_before']['values']=['MAX_CONCURRENCY=2.0']
    elif mutation=='foreign_id':record['thread_cap_after']['container_id']='b'*64
    elif mutation=='foreign_command':record['thread_cap_before']['inspect_command'][2]='b'*64
    elif mutation=='adapter':record['thread_cap_adapter']['sha256']='0'*64
    elif mutation=='unverified':record['thread_cap_verified']=False
    elif mutation=='reversed_time':record['thread_cap_after']['inspected_at']=record['started_at']
    elif mutation=='bad_exit':record['thread_cap_after']['exit_code_observed']='1'
    else:record['actual_resources']['memory_bytes']=2**30
    changed=path.with_name('mutated_terminal.json');changed.write_text(json.dumps(record))
    with pytest.raises((WorkbookEngineError,ValueError)):
        module.validate_actual_call(call,module.reference(changed),frozen)


def test_start_failure_uses_original_cleanup_and_never_claims_after_evidence(setup):
    engine,docker,source,directory=setup;docker.start_fails=True
    with pytest.raises(WorkbookEngineError):engine.recalculate(source,directory/'failed.xlsx')
    record=terminal(directory)[1]
    assert record['thread_cap_verified'] is False and 'thread_cap_after' not in record
    assert record['status']=='failed' and docker.events[-1][0][:3]==['docker','rm','--force']


def test_upstream_arithmetic_and_cleanup_implementations_are_sha_bound_unchanged():
    assert base._reference(base.__file__)['sha256']==capped.RESOURCE_ENGINE_SHA256
    assert base._reference(base.original_engine.__file__)['sha256']==base.UPSTREAM_SHA256
    assert capped.ThreadCappedResourceLibreOfficeEngine.recalculate is base.ResourceLibreOfficeEngine.recalculate
    assert capped.ThreadCappedResourceLibreOfficeEngine.metadata is base.ResourceLibreOfficeEngine.metadata
