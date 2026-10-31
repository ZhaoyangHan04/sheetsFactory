"""Prospective logging-only grammar; no services or historical score edits."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import socket
import subprocess

import pytest

from sheets_factory.evaluation import tool_time_clock_bounds_v4 as frozen
from sheets_factory.evaluation import tool_time_clock_bounds_v5 as clock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_clock_v5_fixture', ROOT/'tests/test_tool_time_clock_bounds.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a, **k): raise AssertionError('Clock tests cannot start processes or network services')
    monkeypatch.setattr(subprocess, 'run', forbidden); monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def program(*, promise='allSettled', variable='results', value='r', index='i'):
    return (f'const {variable}=await Promise.{promise}([tools.exec_command({{cmd:"echo first"}}),'
        f'tools.exec_command({{cmd:"echo second"}})]);'
        f'{variable}.forEach(({value},{index})=>text({{{index},...{value}}}));')


def scenario(tmp_path):
    paths, data = helper.fixture(tmp_path, parallel=True)
    helper.tools(data)[1]['item']['duration'] = helper.duration(1_000_000_000)
    data['native'][1]['payload']['input'] = program()
    helper.save(paths, data)
    return paths, data


@pytest.mark.parametrize('promise,variable,value,index', [
    ('allSettled','results','r','i'), ('all','items','value','index'),
    ('allSettled','_items','$value','_index'),
])
def test_alpha_equivalent_terminal_logging_adds_no_dispatch_and_leaves_v4_unchanged(promise, variable, value, index):
    code = program(promise=promise, variable=variable, value=value, index=index)
    before = (frozen._namespace, frozen.static_calls, frozen.account_complete_clock_overlap)
    with pytest.raises(ValueError, match='Unsupported local result'): frozen.static_calls(code)
    assert clock.static_calls(code) == [{'kind':'CommandExecution','command':'echo first'}, {'kind':'CommandExecution','command':'echo second'}]
    assert (frozen._namespace, frozen.static_calls, frozen.account_complete_clock_overlap) == before
    with pytest.raises(ValueError, match='Unsupported local result'): frozen.static_calls(code)


@pytest.mark.parametrize('suffix', [
    'results.forEach((r,i)=>tools.exec_command({cmd:"hidden"}));',
    'results.forEach((r,i)=>text(eval(r)));',
    'results.forEach(async(r,i)=>text({i,...r}));',
    'results.forEach((r,i)=>{text({i,...r});});',
    'results.forEach((r,i)=>{text({i,...r});tools.exec_command({cmd:"x"});});',
    'results.forEach((r,i)=>text({i,...r,hidden:tools.exec_command({cmd:"x"})}));',
    'results.forEach((r,i)=>text({i,...r}));text(await tools.exec_command({cmd:"extra"}));',
    'results.forEach((r,i)=>text({i,...r}));results.length=0;',
    'results.forEach((r,i)=>text({i,...r}));setTimeout(()=>tools.exec_command({cmd:"late"}),0);',
    'results.forEach((r,i)=>text({i,...results[i]}));',
    'results.forEach((r,i)=>text({i,...r.value}));',
])
def test_tools_eval_mutation_extra_statements_and_other_callbacks_stay_rejected(suffix):
    prefix = program().split('results.forEach',1)[0]
    with pytest.raises(ValueError): clock.static_calls(prefix+suffix)


@pytest.mark.parametrize('value,index', [('r','r'), ('text','i'), ('r','text'), ('eval','i'), ('for','index')])
def test_callback_bindings_cannot_shadow_text_or_use_reserved_identifiers(value, index):
    with pytest.raises(ValueError): clock.static_calls(program(value=value, index=index))


def test_new_logging_requires_awaited_literal_Promise_array_and_bound32():
    suffix = 'results.forEach((r,i)=>text({i,...r}));'
    for prefix in ('const results=await tools.exec_command({cmd:"x"});',
                   'const results=await Promise.all(commands);',
                   'const results=await Promise.all([1,2].map(x=>tools.exec_command({cmd:"x"})));'):
        with pytest.raises(ValueError): clock.static_calls(prefix+suffix)
    prefix = 'const results=await Promise.all(['+','.join('tools.exec_command({cmd:"x"})' for _ in range(32))+']);'
    assert len(clock.static_calls(prefix+suffix)) == 32
    with pytest.raises(ValueError): clock.static_calls(prefix.replace(']);',',tools.exec_command({cmd:"overflow"})]);')+suffix)


def test_old_supported_logging_and_metadata_remain_identical():
    code = 'text(ALL_TOOLS.filter(x=>/file/i.test(x.name+" "+x.description)));const r=await Promise.all([tools.exec_command({cmd:"echo first"})]);r.forEach(text);'
    assert clock.static_calls(code) == frozen.static_calls(code)
    assert clock.POLICY_V5['complete_clock_metadata_regex_flags'] == clock.prior.POLICY_V4['complete_clock_metadata_regex_flags']
    assert clock.POLICY_V5['complete_clock_metadata_regex_flags'] is not clock.prior.POLICY_V4['complete_clock_metadata_regex_flags']


def test_full_census_sum_ownership_credit_and_input_bytes_are_preserved(tmp_path):
    paths, data = scenario(tmp_path); before = {p:p.read_bytes() for p in paths.values()}
    old = frozen.account_complete_clock_overlap(paths['result']); assert old['state'] == 'unknown'
    receipt = clock.account_complete_clock_overlap(paths['result'])
    assert receipt['version'] == receipt['policy_version'] == 5
    assert receipt['state'] == 'verified_owned_overlap_bound' and receipt['passed'] is True
    assert receipt['coverage']['native_tool_count'] == receipt['coverage']['stream_tool_count'] == 2
    assert receipt['coverage']['wrapper_call_count'] == 1
    assert receipt['primitive_upper_sum_ns'] == 2_024_000_000
    assert receipt['wrapper_upper_sum_ns'] == 1_192_000_000
    assert receipt['overlap_credit_ns'] == 996_000_000
    assert receipt['cumulative_upper_bound_ns'] == 2_220_000_000
    assert receipt['uncredited_conservative_upper_ns'] == 3_216_000_000
    assert receipt['cumulative_exact_ns'] is receipt['cumulative_tool_seconds'] is None
    assert {p:p.read_bytes() for p in paths.values()} == before
    assert receipt['historical_result_modified'] is receipt['qualification_claimed'] is False


@pytest.mark.parametrize('budget,state,passed', [('2.220000001','verified_owned_overlap_bound',True),
    ('2.22','unknown',None), ('2.1','unknown',None), ('1','verified_tool_budget_lower_bound',False)])
def test_strict_under_exact_boundary_and_proven_lower_failure_stay_distinct(tmp_path, monkeypatch, budget, state, passed):
    paths, data = scenario(tmp_path)
    monkeypatch.setattr(clock, '_prior_account', lambda *a, **k: {'state':'unknown','passed':None})
    receipt = clock.account_trial_tool_time_v5(paths['result'], budget_seconds=budget)
    assert receipt['state'] == state and receipt['passed'] is passed
    assert receipt['cumulative_exact_ns'] is receipt['cumulative_tool_seconds'] is None


def test_known_exact_over_budget_failure_cannot_use_a_new_display_fallback(tmp_path, monkeypatch):
    exact = {'state':'verified','passed':False,'cumulative_tool_seconds':1800,'raw_verifier_reward':1}
    monkeypatch.setattr(clock, '_prior_account', lambda *a, **k: deepcopy(exact))
    monkeypatch.setattr(clock, 'account_complete_clock_overlap', lambda *a, **k: pytest.fail('Do not replace known exact failure'))
    receipt = clock.account_trial_tool_time_v5(tmp_path/'not_needed.json')
    assert receipt['passed'] is False and receipt['raw_verifier_reward'] == 1
    assert receipt['base_policy_v4_receipt'] == exact
    assert receipt['measurement_branch'] == 'unchanged_v4_exact_or_bound'


@pytest.mark.parametrize('mutate', [
    lambda d:d['native'].pop(), lambda d:d['stream'].pop(),
    lambda d:helper.tools(d)[1]['item'].update(id='n0'),
    lambda d:d['native'].pop(-2),
    lambda d:d['result'].update(exception_info={'exception_type':'Timeout'}),
    lambda d:helper.completed(d)[1].update(exit_code=7),
])
def test_incomplete_tails_duplicate_primitives_or_mismatches_remain_unknown(tmp_path, mutate):
    paths, data = scenario(tmp_path); mutate(data); helper.save(paths, data)
    receipt = clock.account_complete_clock_overlap(paths['result'])
    assert receipt['state'] == 'unknown' and receipt['passed'] is None and receipt['problems']


def test_frozen_dependency_drift_fails_before_shadow_or_future_accounting(monkeypatch):
    monkeypatch.setattr(clock, 'V4_SHA256', '0'*64)
    with pytest.raises(ValueError, match='frozen v4'): clock.static_calls(program())
