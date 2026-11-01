"""Pure boundary and temporary-artifact tests; no native services are invoked."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('confirmation_zero_analysis', ROOT/'scripts/analyze_ringfenced_confirmation_zeros.py')
m = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)
B6 = m.BOOLEAN_POINT
OTHER = 'P01 - Portfolio!B370'


def cell(value, formula=None, data_type='n'):
    return {'value': value, 'formula': formula, 'data_type': data_type}


def diag(*points, missing=(), extra=()):
    return {'reward': 0, 'reason': 'value_or_modified_set_mismatch', 'wrong_values': list(points),
        'missing_changes': list(missing), 'extra_changes': list(extra)}


def row(raw=0, *, seconds=12, bound=False):
    clock = {'state': 'verified_owned_overlap_bound' if bound else 'verified', 'policy_version': 6,
        'budget_seconds': 1800, 'strict_less_than': True, 'model_response_time_included': False,
        'parallel_executions': 'sum', 'passed': seconds < 1800}
    if bound: clock.update(cumulative_lower_bound_seconds=seconds-1, cumulative_upper_bound_seconds=seconds)
    else: clock['cumulative_tool_seconds'] = seconds
    budget = seconds >= 1800
    return {'task_id': 'test-FM', 'mode': 'financial_modeling', 'resources': {'passed': True, 'complete': True},
        'actual_attempt': {'status': 'scored', 'raw_verifier_reward': raw, 'reward': raw, 'tool_time': clock,
            'failure_kind': 'cumulative_tool_budget_exhausted' if budget else None},
        'score': {'effective_reward': 0 if budget else raw, 'state': 'known_tool_budget_failure' if budget else 'complete'}}


@pytest.mark.parametrize('value', [1, 1.0])
def test_literal_numeric_one_boolean_flag_is_zero_call_evidence(value):
    got = m.classify(diag(B6), {B6: cell(True)}, {B6: cell(value)})
    assert got['complete'] and got['classification'] == 'pure_reporting_boolean_only'
    assert got['full_mismatch_coverage'] and got['differences'][0]['actual_type'] == 'number'


@pytest.mark.parametrize('actual', [cell(True), cell(0), cell('1'), cell(None), cell(1, '=1')])
def test_boolean_fast_path_never_conflates_boolean_text_blank_or_saved_formula(actual):
    got = m.classify(diag(B6), {B6: cell(True)}, {B6: actual})
    assert got['classification'] == 'HOLD' and got['complete'] is False


@pytest.mark.parametrize('part', ['missing', 'extra'])
def test_boolean_modified_set_fault_is_not_fast_path(part):
    d = diag(B6, **{part: [B6]})
    assert m.classify(d, {B6: cell(True)}, {B6: cell(1)})['classification'] == 'HOLD'


def test_formula_cache_empty_is_never_a_missing_value_witness():
    got = m.classify(diag(OTHER), {OTHER: cell(100, '=SUM(A1:A4)')}, {OTHER: cell(None, '=A1')}, output_recalculated=True)
    assert got['classification'] == 'HOLD' and got['differences'] == []
    assert got['unresolved'] == [{'coordinate': OTHER, 'reason': 'formula_cache_empty'}]


def test_saved_formula_cache_is_unproven_until_actual_recalculation():
    args = (diag(OTHER), {OTHER: cell(100)}, {OTHER: cell(90, '=A1')})
    assert m.classify(*args)['complete'] is False
    assert m.classify(*args, output_recalculated=True)['classification'] == 'material_business_value_failure'


@pytest.mark.parametrize('difference,classification', [('0.01', 'pure_numeric_rounding_only'), ('0.010001', 'material_business_value_failure')])
def test_exact_decimal_numeric_boundary(difference, classification):
    assert m.classify(diag(OTHER), {OTHER: cell(float(difference))}, {OTHER: cell(0)})['classification'] == classification


def test_numeric_rounding_needs_every_native_mismatch_and_nonzero_difference():
    d = diag(OTHER, 'Other!A1')
    g = {OTHER: cell(.01), 'Other!A1': cell(1)}
    assert m.classify(d, g, {OTHER: cell(0), 'Other!A1': cell(None, '=A1')})['complete'] is False
    assert m.classify(diag(OTHER), {OTHER: cell(1)}, {OTHER: cell(1)})['complete'] is False
    assert m.classify(d, g, {OTHER: cell(0), 'Other!A1': cell(1.005)})['classification'] == 'pure_numeric_rounding_only'


def test_single_material_witness_is_sufficient_without_claiming_full_coverage():
    got = m.classify(diag(OTHER, 'Other!A1'), {OTHER: cell(100), 'Other!A1': cell(5)},
        {OTHER: cell(90), 'Other!A1': cell(None, '=A1')})
    assert got['classification'] == 'material_business_value_failure' and got['complete']
    assert not got['full_mismatch_coverage'] and got['concrete_nonboundary_witness_count'] == 1


@pytest.mark.parametrize('actual', [None, cell(None), cell('#DIV/0!', data_type='e'), cell('bad'), cell(True), cell(float('inf'))])
def test_real_nonformula_missing_or_invalid_nonflag_witness_is_coverage(actual):
    assert m.classify(diag(OTHER), {OTHER: cell(100)}, {OTHER: actual})['classification'] == 'coverage_failure'


def test_no_healthy_goal_cache_means_hold():
    assert not m.classify(diag(OTHER), {OTHER: cell(None, '=A1')}, {OTHER: cell(100)})['complete']


@pytest.mark.parametrize('change', [dict(reward=1), dict(reason='matched'), dict(truncated=True),
    dict(differences_truncated=True), dict(wrong_values=[OTHER, OTHER]), dict(missing_changes=None)])
def test_incomplete_or_foreign_diagnostic_rejected(change):
    d = diag(OTHER); d.update(change)
    with pytest.raises(ValueError, match='HOLD'): m.mismatch_points(d)


@pytest.mark.parametrize('raw,seconds,bound,expected', [(1,12,False,'skip_primary_success'),
    (1,20,True,'skip_primary_success'), (0,12,False,'analyze_complete_primary_zero'),
    (0,20,True,'analyze_complete_primary_zero'), (1,1800,False,'skip_verified_budget_failure'),
    (0,1801,False,'skip_verified_budget_failure')])
def test_primary_success_and_verified_budget_failure_skip_analyses(raw,seconds,bound,expected):
    assert m.disposition(row(raw,seconds=seconds,bound=bound)) == expected


def test_proven_lower_budget_branch_skips_analysis():
    r = row(seconds=1801, bound=True); r['actual_attempt']['tool_time']['state'] = 'verified_tool_budget_lower_bound'
    assert m.disposition(r) == 'skip_verified_budget_failure'


@pytest.mark.parametrize('mutate', [lambda r:r['resources'].update(complete=False),
    lambda r:r['score'].update(effective_reward=1), lambda r:r['actual_attempt']['tool_time'].update(state='unknown'),
    lambda r:r['actual_attempt']['tool_time'].update(policy_version=5),
    lambda r:r['actual_attempt']['tool_time'].update(parallel_executions='wall'),
    lambda r:r['actual_attempt'].update(failure_kind='infrastructure_failure'),
    lambda r:r['actual_attempt']['tool_time'].update(cumulative_tool_seconds=float('nan'))])
def test_unknown_or_inconsistent_primary_evidence_is_not_zero(mutate):
    r = row(); mutate(r)
    with pytest.raises(ValueError, match='HOLD'): m.disposition(r)


def test_real_dual_reader_preserves_blank_formula_literal_bool_and_error(tmp_path):
    path = tmp_path/'tiny.xlsx'; book = Workbook(); sheet = book.active; sheet.title = 'Group reporting'
    sheet['B6'] = 1; sheet['B7'] = '=1'; sheet['B8'] = True; sheet['B8'].number_format = 'General'
    sheet['B9'] = '#DIV/0!'; book.save(path); book.close()
    support = m.load(m.SUPPORT, '_test_zero_reader_support')
    got = m.point_values(path, {'Group reporting!B'+str(i) for i in range(6,11)}, support)
    assert m._typed(got['Group reporting!B6']) == ('number',1)
    assert got['Group reporting!B7']['formula'] == '=1' and got['Group reporting!B7']['value'] is None
    assert m._typed(got['Group reporting!B8']) == ('boolean',True)
    assert m._typed(got['Group reporting!B9'])[0] == 'invalid'
    assert 'Group reporting!B10' not in got


class Audit:
    def __init__(self,*a,**kw): self.db = SimpleNamespace(close=lambda:None)
    def snapshot(self): return {}
    def events(self): return []
    def update_run(self,**kw): pass
    def task(self,*a,**kw): pass
    def export(self): pass


class Panel:
    def __init__(self,*a,**kw): pass
    def start(self): return 'mock://no-service'
    def stop(self): pass


def context(tmp_path, *, zero=None, formula=False):
    recipes = [m.write(tmp_path/'recipe.json', {'fixture':True})]
    shared = m.write(tmp_path/'native_source.json', {'fixture':'native source boundary explicitly mocked'})
    prepared = m.write(tmp_path/'prepared.json', {'fixture':'complete ten identity boundary explicitly mocked'})
    terminal = m.write(tmp_path/'original_terminal.json', {'fixture':True})
    observations = m.write(tmp_path/'observation.json', {'fixture':'actual resource boundary explicitly mocked'})
    rows = {}; snapshots = {}; tasks = {}; sources = {}
    for i in range(10):
        identity = f'task{i}'; trial = tmp_path/identity; trial.mkdir()
        result = m.write(trial/'result.json', {'exception_info':None,'finished_at':'2026-11-01T09:00:00Z',
            'verifier_result':{'rewards':{'reward':0 if i==zero else 1}}})
        if i == zero:
            m.write(trial/'verifier/diagnostics.json', diag(B6 if not formula else OTHER))
            (trial/'artifacts/app').mkdir(parents=True); (trial/'artifacts/app/output.xlsx').write_bytes(b'fixture-saved-output')
        r = row(0 if i == zero else 1); r['task_id'] = identity
        r['actual_attempt'].update(result_file=result['path'],result_sha256=result['sha256'])
        rows[identity] = r; snapshots[identity] = {'task_directory':str(trial/'staged')}; tasks[identity] = {'task_id':identity}
        sources[identity] = {'goal':shared,'source':shared}
    support = SimpleNamespace(engine_class=lambda:pytest.fail('No output call is authorized'))
    return recipes, {'prepared':prepared, 'terminal':terminal, 'rows':rows, 'tasks':tasks, 'snapshots':snapshots,
        'sources':sources,'guards':[prepared,terminal,shared], 'resources':{'observation_receipts':[observations]},'support':support}


def mock_boundaries(monkeypatch, recipes, ctx):
    monkeypatch.setattr(m,'AuditStore',Audit); monkeypatch.setattr(m,'DashboardServer',Panel)
    monkeypatch.setattr(m,'recipes',lambda:deepcopy(recipes)); monkeypatch.setattr(m,'admit',lambda *a:ctx)
    monkeypatch.setattr(m.observer,'validate_trial_observations',lambda config,result,**kw:
        deepcopy(next(r['resources'] for r in ctx['rows'].values() if r['actual_attempt']['result_file']==result['path'])))


def test_workflow_skips_successes_and_budget_failures_without_output_reads(tmp_path,monkeypatch):
    recipes, ctx = context(tmp_path); r = row(1,seconds=1800); ctx['rows']['task0'].update(r)
    mock_boundaries(monkeypatch,recipes,ctx)
    monkeypatch.setattr(m,'point_values',lambda *a,**k:pytest.fail('Skipped cases must not read outputs'))
    original = deepcopy(ctx['rows']); final = m.read(m.analyze('unused','unused',tmp_path/'analysis'))
    assert final['analyses'] == [] and final['actual_output_LO_calls'] == 0
    assert ctx['rows'] == original and len(final['records']) == 10


def test_workflow_boolean_evidence_matches_publisher_schema_and_preserves_scores(tmp_path,monkeypatch):
    recipes, ctx = context(tmp_path,zero=3); mock_boundaries(monkeypatch,recipes,ctx)
    monkeypatch.setattr(m,'point_values',lambda path,*a,**kw:{B6:cell(True if path==ctx['sources']['task3']['goal']['path'] else 1)})
    original = deepcopy(ctx['rows']); final = m.read(m.analyze('unused','unused',tmp_path/'analysis'))
    assert len(final['analyses']) == 1 and final['actual_output_LO_calls'] == 0 and ctx['rows'] == original
    a = m.read(final['analyses'][0]); assert a['kind'] == 'native_confirmation_nonboundary_analysis_v1'
    assert a['complete'] and a['classification'] == 'pure_reporting_boolean_only'
    assert a['task_id'] == 'task3' and a['result_sha256'] == ctx['rows']['task3']['actual_attempt']['result_sha256']
    assert all(m.ref(r['path'])==r for r in a['evidence']) and a['original_primary_score_modified'] is False


def test_workflow_formula_empty_is_hold_without_implicit_native_call(tmp_path,monkeypatch):
    recipes, ctx = context(tmp_path,zero=0,formula=True); mock_boundaries(monkeypatch,recipes,ctx)
    monkeypatch.setattr(m,'point_values',lambda path,*a,**kw:{OTHER:cell(100) if path==ctx['sources']['task0']['goal']['path'] else cell(None,'=A1')})
    final = m.read(m.analyze('unused','unused',tmp_path/'analysis'))
    assert final['HOLD_count'] == 1 and final['actual_output_LO_calls'] == 0
    assert m.read(final['analyses'][0])['complete'] is False


def test_result_reward_mismatch_fails_before_any_output_inspection(tmp_path,monkeypatch):
    recipes, ctx = context(tmp_path,zero=0); mock_boundaries(monkeypatch,recipes,ctx)
    result = Path(ctx['rows']['task0']['actual_attempt']['result_file']); value=json.loads(result.read_text()); value['verifier_result']['rewards']['reward']=1
    result.write_text(json.dumps(value)); ctx['rows']['task0']['actual_attempt']['result_sha256']=m.ref(result)['sha256']
    monkeypatch.setattr(m,'point_values',lambda *a,**kw:pytest.fail('Reject mismatched reward before opening O'))
    with pytest.raises(ValueError,match='zero result changed'): m.analyze('unused','unused',tmp_path/'analysis')
    assert m.read(tmp_path/'analysis/failure.json')['actual_output_LO_calls'] == 0


def test_explicit_single_output_recalculation_reserves_once_and_never_recalculates_input_goal(tmp_path,monkeypatch):
    recipes, ctx = context(tmp_path,zero=0,formula=True); mock_boundaries(monkeypatch,recipes,ctx)
    monkeypatch.setattr(m,'ROOT',tmp_path)
    saved = Path(ctx['rows']['task0']['actual_attempt']['result_file']).parent/'artifacts/app/output.xlsx'
    invoked=[]; receipt=[]
    class Engine:
        def __init__(self,root,profile,*,role,receipt_directory):
            assert role=='verifier'; self.directory=receipt_directory
        def recalculate(self,source,output):
            invoked.append((Path(source),Path(output))); assert Path(source)==saved
            output.parent.mkdir(parents=True,exist_ok=True); output.write_bytes(b'one mock native O')
            receipt.append(m.write(self.directory/'receipt.json',{'fixture':'native resource boundary explicitly mocked'}))
            return output
        def metadata(self): return {'actual_resource_receipts':receipt}
    def resource_check(record,source,output,role):
        assert source==m.ref(saved) and output==m.ref(invoked[-1][1]) and role=='verifier'
    ctx['support'] = SimpleNamespace(engine_class=lambda:Engine,PROFILE='ring-profile',resource_check=resource_check,
        owned_absence=lambda calls:{'daemon_reachable':True,'all_owned_containers_absent':True})
    def values(path,*a,**kw):
        return {OTHER:cell(100) if path==ctx['sources']['task0']['goal']['path'] else
            cell(90,'=A1') if Path(path).name=='output.native.xlsx' else cell(None,'=A1')}
    monkeypatch.setattr(m,'point_values',values)
    final=m.read(m.analyze('unused','unused',tmp_path/'analysis',recalculate=['task0']))
    a=m.read(final['analyses'][0]); assert a['classification']=='material_business_value_failure'
    assert len(invoked)==final['actual_output_LO_calls']==1
    assert a['new_output_LO_calls']==1 and a['original_primary_score_modified'] is False
    with pytest.raises(FileExistsError): m.analyze('unused','unused',tmp_path/'second',recalculate=['task0'])
    assert len(invoked)==1 and m.read(tmp_path/'second/failure.json')['actual_output_LO_calls']==0


def test_original_evaluation_result_and_snapshot_binding_rejects_reward_projection(tmp_path):
    recipes,ctx=context(tmp_path)
    for identity,r in ctx['rows'].items():
        path=Path(r['actual_attempt']['result_file']); result=json.loads(path.read_text()); result['task_name']='sheetsfactory/'+identity
        path.write_text(json.dumps(result)); result_ref=m.ref(path); r['actual_attempt']['result_sha256']=result_ref['sha256'];r['resources']['result']=result_ref
    selection=m.write(tmp_path/'selection.json',{'fixture':True})
    ev={'attempts':[deepcopy(r['actual_attempt'])|{'task_id':identity} for identity,r in ctx['rows'].items()],
        'infra_history':[],'infrastructure_retries':[]}
    for identity,r in ctx['rows'].items(): r['actual_attempt']['task_id']=identity
    er=m.write(tmp_path/'evaluation.json',ev)
    actual={'evaluation':er,'selection':selection,'results':list(ctx['rows'].values())}
    selected={'tasks':[{'task_id':identity} for identity in ctx['rows']]}
    resources={'passed':True,'complete':True,'selection':selection,'evaluation':er,
        'trials':[r['resources'] for r in ctx['rows'].values()]}
    assert m.bind_original_rows(actual,selected,resources)==ev
    forged=deepcopy(actual); forged['results'][0]['actual_attempt']['raw_verifier_reward']=0
    with pytest.raises(ValueError,match='immutable original evaluation'):m.bind_original_rows(forged,selected,resources)
    # Even changing the runner attempt and row together cannot override actual result reward.
    forged_ev=deepcopy(ev); forged_ev['attempts'][0]['raw_verifier_reward']=0
    forged_ref=m.write(tmp_path/'forged_evaluation.json',forged_ev);forged['evaluation']=forged_ref
    forged_resources=deepcopy(resources);forged_resources['evaluation']=forged_ref
    with pytest.raises(ValueError,match='actual result identity, reward'):m.bind_original_rows(forged,selected,forged_resources)


@pytest.mark.parametrize('change', ['task_name','exception','finished','resource','duplicate_snapshot','retry'])
def test_immutable_evaluation_full_count_role_and_result_guards(tmp_path,change):
    _,ctx=context(tmp_path)
    for identity,r in ctx['rows'].items():
        path=Path(r['actual_attempt']['result_file']); result=json.loads(path.read_text()); result['task_name']='sheetsfactory/'+identity
        if identity=='task0':
            if change=='task_name':result['task_name']='sheetsfactory/foreign'
            if change=='exception':result['exception_info']={'error':'fixture'}
            if change=='finished':result['finished_at']=None
        path.write_text(json.dumps(result)); rr=m.ref(path);r['actual_attempt'].update(result_sha256=rr['sha256'],task_id=identity)
        r['resources']['result']=rr
    selection=m.write(tmp_path/'sel.json',{'fixture':True})
    ev={'attempts':[r['actual_attempt'] for r in ctx['rows'].values()], 'infra_history':[],
        'infrastructure_retries':[{}] if change=='retry' else []}
    er=m.write(tmp_path/'eval.json',ev)
    actual={'evaluation':er,'selection':selection,'results':list(ctx['rows'].values())}
    selected={'tasks':[{'task_id':identity} for identity in ctx['rows']]}
    resources={'passed':True,'complete':True,'selection':selection,'evaluation':er,'trials':deepcopy([r['resources'] for r in ctx['rows'].values()])}
    if change=='resource':resources['trials'][0]['passed']=False
    if change=='duplicate_snapshot':selected['tasks'][-1]={'task_id':'task0'}
    with pytest.raises(ValueError,match='HOLD'):m.bind_original_rows(actual,selected,resources)
