"""Engineering lifecycle tests with explicit fake engine/resource boundaries."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


@pytest.fixture
def setup(tmp_path,monkeypatch):
    m=module('period_validation',ROOT/'scripts/validate_period_boundary_candidate.py')
    b=m.builder();candidate=b.build(m.spec.prototype(),tmp_path/'candidate')
    def forbidden(*a,**kw):raise AssertionError('Actual Docker/LO/process service is forbidden in focused tests')
    monkeypatch.setattr(m.subprocess,'run',forbidden)
    return SimpleNamespace(m=m,b=b,candidate=candidate,root=tmp_path)


def test_prepare_freezes_both_modes_and_all_ten_calls_without_engine(setup,monkeypatch):
    c=setup;m=c.m
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**k:pytest.fail('prepare cannot instantiate an engine'))
    r=m.prepare(c.candidate,c.root/'engineering');f=m.read(r)
    assert f['mode_order']==['financial_modeling','debugging'] and f['stage_order']==list(m.STAGES)
    assert f['required_actual_LO_calls']==10 and f['actual_LO_calls']==0
    assert f['all_mode_and_control_plans_frozen_before_first_actual_call']
    assert f['expected_FM_D']==657 and f['expected_DBG_D']==397
    assert m.validate_prepared(c.root/'engineering')==f
    missing=next(x for x in f['control_edits'] if x['output']['path'].endswith('DBG_missed_root.xlsx'))
    assert missing['exact_cell_changes'][0]['cell']=='C7'  # Actual February midperiod maturity, not an inactive/equivalent month.
    assert len(f['planned_inputs'])==7


def test_pure_XML_control_changes_only_declared_cell_and_member(setup):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'engineering');f=m.validate_prepared(c.root/'engineering')
    for change in f['control_edits']:
        with zipfile.ZipFile(change['source']['path']) as a,zipfile.ZipFile(change['output']['path']) as b:
            assert a.namelist()==b.namelist()
            assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==change['changed_members']
            assert len(change['changed_members'])==1
        before=openpyxl.load_workbook(change['source']['path']);after=openpyxl.load_workbook(change['output']['path'])
        points={(x['sheet'],x['cell']) for x in change['exact_cell_changes']}
        for ws in before:
            for cell in ws._cells.values():
                actual=after[ws.title][cell.coordinate]
                if (ws.title,cell.coordinate) not in points:assert cell.value==actual.value
                assert cell._style==actual._style
        before.close();after.close()


def test_strict_oracle_audit_rejects_bool_as_number_and_changed_public_policy(setup):
    c=setup;m=c.m;manifest=m.read(c.candidate);bindings=m.read(Path(manifest['gold']['path']).parent/'bindings.private.json')
    public=m.spec.load_spec(m.checked(manifest['source_specification']));result=m.oracle.simulate(public)
    literals=m.literal_inventory(manifest['gold']['path'],bindings)
    assert m.audit_workbook(manifest['gold']['path'],bindings,result,literals)['passed']
    p=c.root/'tampered.xlsx'
    m.patch_cells(manifest['gold']['path'],p,{('Business Policies','A1'):('text','Different policy')})
    assert not m.audit_workbook(p,bindings,result,literals)['passed']
    assert m.typed(True)!=m.typed(1)


def test_prepared_input_bytes_cannot_change_or_rerun_silently(setup):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'engineering');f=m.validate_prepared(c.root/'engineering')
    Path(f['planned_inputs']['goal']['path']).write_bytes(b'Changed')
    with pytest.raises(ValueError,match='Frozen reference'):m.validate_prepared(c.root/'engineering')


def install_mock_runtime(c,monkeypatch,*,fail_at=None):
    m=c.m;engines=[]
    class Engine:
        def __init__(self,*args,**kw):self.history=[];self.ensure_calls=0;engines.append(self)
        def ensure_image(self):self.ensure_calls+=1
        def recalculate(self,source,destination):
            name=Path(destination).stem;assert name==m.STAGES[len(self.history)]
            if name==fail_at:raise RuntimeError('Explicit mocked source failure')
            if name=='equivalent':
                manifest=m.read(c.candidate);bindings=m.read(Path(manifest['gold']['path']).parent/'bindings.private.json')
                s=m.spec.load_spec(m.checked(manifest['source_specification']))
                c.b.seed_oracle_caches(source,destination,bindings,c.b.expected_values(bindings,m.oracle.simulate(s)))
            else:shutil.copyfile(source,destination)
            runtime=m.write(Path(destination).with_suffix('.mock_resource.json'),{'TEST_ONLY':True,'source':m.reference(source),'container_id':f'{len(self.history)+1:064x}'})
            self.history.append(runtime);return Path(destination)
        def metadata(self):return {'actual_resource_receipts':self.history}
    class Server:
        def __init__(self,*a,**kw):pass
        def start(self):return 'mock://service-free-dashboard'
        def stop(self):pass
    def validation(call,runtime,frozen):return {'terminal':runtime,'container_id':m.read(runtime)['container_id'],'TEST_ONLY':True}
    def cleanup(calls):return {'all_owned_containers_absent':True,'daemon_reachable':True,'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in calls],'TEST_ONLY':True}
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine);monkeypatch.setattr(m,'DashboardServer',Server)
    monkeypatch.setattr(m,'validate_call',validation);monkeypatch.setattr(m,'owned_absence',cleanup)
    return engines


def test_mock_lifecycle_ten_shared_calls_cold_gate_and_retry_zero(setup,monkeypatch):
    c=setup;m=c.m;output=c.root/'engineering';m.prepare(c.candidate,output)
    engines=install_mock_runtime(c,monkeypatch);terminal=m.execute_prepared(output);t=m.read(terminal)
    assert len(engines)==1 and len(engines[0].history)==10 and engines[0].ensure_calls==1
    assert [x['role'] for x in t['actual_calls']]==list(m.STAGES)
    assert t['passed'] and not t['qualified'] and not t['difficulty_claimed']
    assert all(x['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0} for x in t['records']['modes'].values())
    assert m.validate_completed(terminal)==t
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(output)
    Path(t['records']['goal_stability']['path']).write_text('{}')
    with pytest.raises(ValueError):m.validate_completed(terminal)


def test_first_mock_failure_is_retained_without_later_calls_or_retry(setup,monkeypatch):
    c=setup;m=c.m;output=c.root/'engineering';m.prepare(c.candidate,output)
    engines=install_mock_runtime(c,monkeypatch,fail_at='goal2')
    with pytest.raises(RuntimeError,match='preserve terminal'):m.execute_prepared(output)
    terminal=m.read(output/'terminal.json')
    assert not terminal['passed'] and terminal['actual_LO_calls_started']==2 and terminal['actual_LO_calls_completed']==1
    assert len(engines[0].history)==1 and terminal['failure']['type']=='RuntimeError'
    assert (output/'goal2_terminal.json').is_file() and (output/'failure.json').is_file()
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(output)
