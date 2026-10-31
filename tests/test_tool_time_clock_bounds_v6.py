"""Prospective bounded display grammar; no processes, services or score changes."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import socket
import subprocess

import pytest

from sheets_factory.evaluation import tool_time_clock_bounds_v5 as prior
from sheets_factory.evaluation import tool_time_clock_bounds_v6 as clock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_clock_v6_fixture', ROOT/'tests/test_tool_time_clock_bounds.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a, **k): raise AssertionError('Clock parser tests cannot start services or processes')
    monkeypatch.setattr(subprocess, 'run', forbidden); monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def metadata(*, reverse=False, mapping=True, sliced=True, flags='i'):
    fields = "x.description+' '+x.name" if reverse else 'x.name+" "+x.description'
    tail = '.map(v=>({name:v.name,description:v.description.slice(0,180)}))' if mapping else ''
    if sliced: tail += '.slice(0,100)'
    return f'text(ALL_TOOLS.filter(x=>/spreadsheet|file/{flags}.test({fields})){tail});'


def fanout(count=2):
    return ('const results=await Promise.allSettled(['+','.join(
        f'tools.exec_command({{cmd:"echo {i}"}})' for i in range(count))+
        ']);results.forEach((r,i)=>text({i,...r}));')


@pytest.mark.parametrize('reverse,mapping,sliced,flags', [
    (r,m,s,f) for r in (False,True) for m in (False,True) for s in (False,True) for f in ('','i')])
def test_literal_metadata_orders_optional_map_and_slice(reverse,mapping,sliced,flags):
    code = metadata(reverse=reverse,mapping=mapping,sliced=sliced,flags=flags)
    assert clock.static_calls(code) == []
    assert clock.static_calls(code+'text(await tools.exec_command({cmd:"echo x"}));') == [
        {'kind':'CommandExecution','command':'echo x'}]


def test_metadata_after_indexed_logging_is_removed_before_terminal_suffix_validation():
    code = fanout()+metadata(reverse=True)
    with pytest.raises(ValueError): prior.static_calls(code)
    assert clock.static_calls(code) == [{'kind':'CommandExecution','command':'echo 0'},
                                      {'kind':'CommandExecution','command':'echo 1'}]
    assert len(clock.static_calls(fanout(32)+metadata())) == 32
    with pytest.raises(ValueError,match='fanout'): clock.static_calls(fanout(33)+metadata())


@pytest.mark.parametrize('code', [
    'const result=await tools.exec_command({cmd:"echo x"});text(result.output);',
    'text((await tools.exec_command({cmd:"echo x"})).output);',
    'const result=await tools.write_stdin({session_id:42,chars:""});text(result.output);',
    'text((await tools.write_stdin({session_id:42,chars:""})).output);',
])
def test_only_literal_tool_output_projection_is_added(code):
    with pytest.raises(ValueError): prior.static_calls(code)
    expected = {'kind':'poll','process_id':'42'} if 'write_stdin' in code else {'kind':'CommandExecution','command':'echo x'}
    assert clock.static_calls(code) == [expected]


@pytest.mark.parametrize('code', [
    'const result=await tools.exec_command(dynamic);text(result.output);',
    'const result=await tools.exec_command({cmd:"x"});text(result.output());',
    'const result=await tools.exec_command({cmd:"x"});text(result.constructor);',
    'const text=await tools.exec_command({cmd:"x"});text(text.output);',
    'const result=await Promise.all([tools.exec_command({cmd:"x"})]);text(result.output);',
    'text((await tools.exec_command({cmd:"x"})).output.hidden);',
    'text((await tools.exec_command({cmd:eval("x")})).output);',
    'text((await tools.view_image({path:"/app/a.png"})).output);',
    'text((await tools.WebSearch({query:"x"})).output);',
    'text((await tools.exec_command({cmd:"x"})).output);eval("hidden");',
])
def test_dynamic_properties_calls_unknown_tools_and_extra_code_stay_unknown(code):
    with pytest.raises(ValueError): clock.static_calls(code)


@pytest.mark.parametrize('bad', [
    lambda: metadata(flags='g'),
    lambda: metadata(flags='ii'),
    lambda: metadata().replace('x.name+" "+x.description','x.name+" "+x.name'),
    lambda: metadata().replace('.slice(0,100)', '.slice(0,-1)'),
    lambda: metadata().replace('.slice(0,100)', '.slice(0,2.0)'),
    lambda: metadata().replace('.slice(0,100)', '.slice(0,limit)'),
    lambda: metadata().replace('.slice(0,100)', '.slice(0,9007199254740992)'),
    lambda: metadata().replace('name:v.name','name:tools.exec_command({cmd:"hidden"})'),
    lambda: metadata().replace('x=>','tools=>'),
    lambda: metadata()+'setTimeout(()=>tools.exec_command({cmd:"hidden"}),0);',
])
def test_metadata_is_finite_read_only_literal_grammar(bad):
    with pytest.raises(ValueError): clock.static_calls(bad())


def test_metadata_text_inside_strings_comments_and_nested_expressions_is_never_stripped():
    # Single quotes surround the command, so the metadata's double-quote form
    # must use an identifier-space ordering free of embedded single quotes.
    meta = metadata().replace("' '",'" "')
    literal = 'text(await tools.exec_command({cmd:'+__import__('json').dumps(meta)+'}));'
    assert clock.static_calls(literal) == [{'kind':'CommandExecution','command':meta}]
    commented = '//'+metadata()+'\n/*'+metadata()+'*/\n'
    transformed,count = clock._preprocess(commented)
    assert transformed == commented and count == 0
    with pytest.raises(ValueError,match='no supported'): clock.static_calls(commented)
    nested = 'text(await tools.exec_command({cmd:"x",extra:['+metadata().rstrip(';')+']}));'
    transformed,count = clock._preprocess(nested)
    assert transformed == nested and count == 0
    with pytest.raises(ValueError): clock.static_calls(nested)
    with pytest.raises(ValueError): clock.static_calls('`'+metadata()+'`;')
    for prefix in ('\"', '/*'):
        with pytest.raises(ValueError): clock.static_calls(prefix+metadata())


def scenario(tmp_path, *, metadata_wrapper=False):
    paths,data = helper.fixture(tmp_path,parallel=True)
    helper.tools(data)[1]['item']['duration'] = helper.duration(1_000_000_000)
    data['native'][1]['payload']['input'] = (
        'const results=await Promise.allSettled([tools.exec_command({cmd:"echo first"}),'
        'tools.exec_command({cmd:"echo second"})]);results.forEach((r,i)=>text({i,...r}));'+metadata(reverse=True))
    if metadata_wrapper:
        data['native'][1:1] = [
            {'timestamp':helper.stamp(helper.BASE_MS+2),'type':'response_item','payload':{
                'type':'custom_tool_call','call_id':'metadata','name':'exec','input':metadata()}},
            {'timestamp':helper.stamp(helper.BASE_MS+5),'type':'response_item','payload':{
                'type':'custom_tool_call_output','call_id':'metadata','output':[{'type':'input_text','text':'Script completed\n'}]}}]
    helper.save(paths,data)
    return paths,data


def test_full_prior_census_ownership_sum_overlap_and_artifact_bytes_unchanged(tmp_path):
    paths,data = scenario(tmp_path)
    before = {p:p.read_bytes() for p in paths.values()}
    assert prior.account_complete_clock_overlap(paths['result'])['state'] == 'unknown'
    receipt = clock.account_complete_clock_overlap(paths['result'])
    assert receipt['state'] == 'verified_owned_overlap_bound' and receipt['passed'] is True
    assert receipt['version'] == receipt['policy_version'] == 6
    assert receipt['coverage']['native_tool_count'] == receipt['coverage']['stream_tool_count'] == 2
    assert receipt['primitive_upper_sum_ns'] == 2_024_000_000
    assert receipt['wrapper_upper_sum_ns'] == 1_192_000_000
    assert receipt['overlap_credit_ns'] == 996_000_000
    assert receipt['cumulative_upper_bound_ns'] == 2_220_000_000
    assert receipt['uncredited_conservative_upper_ns'] == 3_216_000_000
    assert receipt['cumulative_exact_ns'] is receipt['cumulative_tool_seconds'] is None
    assert {p:p.read_bytes() for p in paths.values()} == before
    assert receipt['historical_result_modified'] is receipt['qualification_claimed'] is False


def test_zero_inner_metadata_wrapper_retains_its_entire_wall_and_primitive_ownership(tmp_path):
    paths,data = scenario(tmp_path,metadata_wrapper=True)
    receipt = clock.account_complete_clock_overlap(paths['result'])
    assert receipt['complete'] and receipt['passed'] is True
    assert receipt['coverage']['wrapper_call_count'] == 2
    wrapper = next(w for w in receipt['wrappers'] if w['call_id'] == 'metadata')
    assert wrapper['static_calls'] == []
    assert wrapper['full_wall_ns'] == 3_000_000
    assert wrapper['upper_ns'] == wrapper['uncovered_upper_ns'] == 5_000_000
    assert wrapper['overlap_credit_ns'] == 0
    assert receipt['cumulative_upper_bound_ns'] == 2_225_000_000


@pytest.mark.parametrize('budget,state,passed', [('2.220000001','verified_owned_overlap_bound',True),
    ('2.22','unknown',None), ('2.1','unknown',None), ('1','verified_tool_budget_lower_bound',False)])
def test_strict_boundary_and_complete_known_lower_bound_are_unchanged(tmp_path,monkeypatch,budget,state,passed):
    paths,data = scenario(tmp_path)
    monkeypatch.setattr(clock,'_prior_account',lambda *a,**k:{'state':'unknown','passed':None})
    receipt = clock.account_trial_tool_time_v6(paths['result'],budget_seconds=budget)
    assert receipt['state'] == state and receipt['passed'] is passed
    assert receipt['cumulative_exact_ns'] is receipt['cumulative_tool_seconds'] is None


@pytest.mark.parametrize('old', [{'state':'verified','passed':False,'cumulative_tool_seconds':1800},
                               {'state':'verified_owned_overlap_bound','passed':True}])
def test_every_known_v5_branch_is_retained_without_fallback(tmp_path,monkeypatch,old):
    monkeypatch.setattr(clock,'_prior_account',lambda *a,**k:deepcopy(old))
    monkeypatch.setattr(clock,'account_complete_clock_overlap',lambda *a,**k:pytest.fail('Known evidence cannot be replaced'))
    receipt = clock.account_trial_tool_time_v6(tmp_path/'not_read.json')
    assert receipt['base_policy_v5_receipt'] == old and receipt['passed'] is old['passed']
    assert receipt['measurement_branch'] == 'unchanged_v5_exact_or_bound'


@pytest.mark.parametrize('mutate', [lambda d:d['native'].pop(), lambda d:d['stream'].pop(),
    lambda d:helper.tools(d)[1]['item'].update(id='n0'),
    lambda d:helper.completed(d)[1].update(exit_code=7),
    lambda d:d['native'][1]['payload'].update(input=metadata()),
    lambda d:d['result'].update(exception_info={'exception_type':'Timeout'})])
def test_all_incomplete_mismatched_or_unowned_evidence_remains_unknown(tmp_path,mutate):
    paths,data = scenario(tmp_path);mutate(data);helper.save(paths,data)
    receipt = clock.account_complete_clock_overlap(paths['result'])
    assert receipt['state'] == 'unknown' and receipt['passed'] is None and receipt['problems']


def test_no_original_globals_or_prior_fixture_grammar_changed(monkeypatch):
    before = (prior._static_namespace,prior.static_calls,prior.account_complete_clock_overlap)
    supported = 'text(await tools.exec_command({cmd:"x"}));'
    assert clock.static_calls(supported) == prior.static_calls(supported)
    assert (prior._static_namespace,prior.static_calls,prior.account_complete_clock_overlap) == before
    assert clock.POLICY_V6['complete_clock_metadata_regex_flags'] is not prior.POLICY_V5['complete_clock_metadata_regex_flags']
    monkeypatch.setattr(clock,'V5_SHA256','0'*64)
    with pytest.raises(ValueError,match='frozen v5'): clock.static_calls(supported)
