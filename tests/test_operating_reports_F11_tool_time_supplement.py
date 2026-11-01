import importlib.util
from pathlib import Path
import socket
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
m = load('_F11_supplement', ROOT/'scripts/supplement_operating_reports_F11_tool_time.py')
helper = load('_F11_clock_fixture', ROOT/'tests/test_tool_time_clock_bounds.py')


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def fail(*a, **k):raise AssertionError('Timing proof cannot start a process or network connection')
    monkeypatch.setattr(subprocess,'run',fail);monkeypatch.setattr(subprocess,'Popen',fail)
    monkeypatch.setattr(socket,'create_connection',fail)


def fanout(n=2, suffix='rr.forEach(r=>text(r));'):
    return 'const rr=await Promise.allSettled(['+','.join('tools.exec_command({cmd:"echo '+str(i)+'"})'for i in range(n))+']);'+suffix


def test_new_logging_is_exactly_two_existing_literal_primitives():
    code=fanout()
    with pytest.raises(ValueError):m.prior.static_calls(code)
    assert m.static_calls(code)==[{'kind':'CommandExecution','command':'echo 0'},{'kind':'CommandExecution','command':'echo 1'}]
    assert len(m.static_calls(fanout(32)))==32
    with pytest.raises(ValueError):m.static_calls(fanout(33))


@pytest.mark.parametrize('suffix',[
    'rr.forEach(r=>text(r.output));','rr.forEach(r=>{text(r)});',
    'rr.forEach(r=>text(tools.exec_command({cmd:"hidden"})));',
    'rr.forEach(r=>eval(r));','rr.forEach(text=>text(text));',
    'rr.forEach(rr=>text(rr));','other.forEach(r=>text(r));',
    'rr.forEach(r=>text(r));text(await tools.exec_command({cmd:"hidden"}));',
    'rr.forEach(r=>text(r()));'])
def test_arbitrary_callbacks_calls_properties_and_aliases_stay_unknown(suffix):
    with pytest.raises(ValueError):m.static_calls(fanout(suffix=suffix))


def test_dynamic_arguments_and_unknown_tools_are_not_added():
    with pytest.raises(ValueError):m.static_calls('const rr=await Promise.allSettled([tools.exec_command(dynamic)]);rr.forEach(r=>text(r));')
    with pytest.raises(ValueError):m.static_calls('const rr=await Promise.allSettled([tools.view_image({path:"x"})]);rr.forEach(r=>text(r));')


def scenario(tmp_path):
    paths,data=helper.fixture(tmp_path,parallel=True)
    helper.tools(data)[1]['item']['duration']=helper.duration(1_000_000_000)
    data['native'][1]['payload']['input']='const rr=await Promise.allSettled([tools.exec_command({cmd:"echo first"}),tools.exec_command({cmd:"echo second"})]);rr.forEach(r=>text(r));'
    helper.save(paths,data);return paths,data


def test_complete_prior_ownership_sum_overlap_and_bytes_are_unchanged(tmp_path):
    paths,data=scenario(tmp_path);before={p:p.read_bytes()for p in paths.values()}
    assert m.prior.account_complete_clock_overlap(paths['result'])['state']=='unknown'
    z=m.measure(paths['result'])
    assert z['complete'] and z['passed'] is True
    assert z['coverage']['native_tool_count']==z['coverage']['stream_tool_count']==2
    assert z['primitive_upper_sum_ns']==2_024_000_000
    assert z['wrapper_upper_sum_ns']==1_192_000_000
    assert z['overlap_credit_ns']==996_000_000
    assert z['cumulative_upper_bound_ns']==2_220_000_000
    assert {p:p.read_bytes()for p in paths.values()}==before
    assert not z['original_v6_result_modified'] and not z['qualification_claimed']


@pytest.mark.parametrize('budget,passed',[('2.220000001',True),('2.22',None),('2.1',None)])
def test_strict_threshold_is_unchanged(tmp_path,budget,passed):
    paths,_=scenario(tmp_path)
    assert m.measure(paths['result'],budget_seconds=budget)['passed'] is passed


def test_missing_stream_coverage_stays_unknown(tmp_path):
    paths,data=scenario(tmp_path);data['stream'].pop();helper.save(paths,data)
    z=m.measure(paths['result']);assert z['passed'] is None and not z['complete']


def test_old_globals_and_old_parser_do_not_change():
    original=m.prior._static_namespace();original_suffix=original['_v5_display_suffix']
    assert m.static_calls('text(await tools.exec_command({cmd:"x"}));')==m.prior.static_calls('text(await tools.exec_command({cmd:"x"}));')
    assert m.prior._static_namespace()['_v5_display_suffix']is original_suffix
    with pytest.raises(ValueError):m.prior.static_calls(fanout())
