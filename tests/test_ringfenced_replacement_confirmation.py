from collections import Counter
from copy import deepcopy
import ast
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load():
    spec = importlib.util.spec_from_file_location('_test_ring_replacement_confirmation', ROOT/'scripts/run_ringfenced_replacement_confirmation.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


@pytest.fixture
def m(): return load()


def frozen_fake_cohort(m, monkeypatch, tmp_path):
    whole = {'path': str(tmp_path/'original.json'), 'sha256': 'f'*64, 'bytes': 12}
    retained = m.write(tmp_path/'retained.json', {'tasks': [{'mode': mode} for mode in m.COUNTS for _ in range(5)]})
    design = {'new_pairs': [{'id': p} for p in m.PAIRS], 'R2_model_results_observed_at_design_freeze': 0,
              'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'outer_retries': 0,
              'retained_ten': retained, 'original_whole_pair_pool': whole}
    record = m.write(tmp_path/'design.json', design)
    monkeypatch.setattr(m, 'DESIGN', Path(record['path'])); monkeypatch.setattr(m, 'DESIGN_SHA', record['sha256'])
    batches = []
    for pair in m.PAIRS:
        certificate = m.write(tmp_path/(pair+'-cert.json'), {'pair_id': pair, 'prospective': whole})
        prep = m.write(tmp_path/(pair+'-prep.json'), {'certificate': certificate})
        source = m.write(tmp_path/(pair+'-source.json'), {'passed': True, 'LO_calls': 3, 'preparation': prep,
                                                       'source': {'sha256': pair}})
        tasks = [{'task_id': pair+'-'+suffix, 'mode': mode, 'variant_id': pair+'-'+suffix, 'source_id': pair}
                 for mode, suffix in [('financial_modeling','FM'),('debugging','DBG')]]
        batches.append(m.write(tmp_path/(pair+'-batch.json'), {'kind': m.BATCH_KIND, 'version': 1,
            'count': 2, 'selected_task_ids': [t['task_id'] for t in tasks], 'tasks': tasks, 'source': source}))
    return batches


def test_fixed_first_five_cohort_keeps_old_ten_out_of_new_attempts(m, monkeypatch, tmp_path):
    batches = frozen_fake_cohort(m, monkeypatch, tmp_path)
    _, tasks, retained = m.cohort_tasks(batches)
    assert Counter(t['mode'] for t in tasks) == m.COUNTS
    assert {t['variant_id'] for t in tasks} == {p+'-'+s for p in m.PAIRS for s in ('FM','DBG')}
    assert len(m.read(retained)['tasks']) == 10
    assert not any('retained' in t['task_id'] for t in tasks)


@pytest.mark.parametrize('mutation', ['omit_pair','duplicate_pair','swap_pair','wrong_mode','wrong_source','wrong_certificate'])
def test_pair_membership_cannot_be_chosen_after_results(m, monkeypatch, tmp_path, mutation):
    batches = frozen_fake_cohort(m, monkeypatch, tmp_path)
    if mutation == 'omit_pair': batches.pop()
    elif mutation == 'duplicate_pair': batches[-1] = batches[0]
    else:
        b = m.read(batches[-1])
        if mutation == 'swap_pair': b['tasks'][0]['variant_id'] = 'R2-06-FM'
        if mutation == 'wrong_mode': b['tasks'][0]['mode'] = 'debugging'
        if mutation == 'wrong_source': b['tasks'][0]['source_id'] = 'not-the-goal'
        if mutation == 'wrong_certificate':
            src = m.read(b['source']); prep = m.read(src['preparation']); cert = m.read(prep['certificate'])
            cert['prospective']['sha256'] = '0'*64
            prep['certificate'] = m.write(tmp_path/'different-cert.json',cert)
            src['preparation'] = m.write(tmp_path/'different-prep.json',prep)
            b['source'] = m.write(tmp_path/'different-source.json',src)
        batches[-1] = m.write(tmp_path/'mutated-batch.json',b)
    with pytest.raises(ValueError): m.cohort_tasks(batches)


def test_new_wave_retains_exact_original_clock_agent_scoring_and_tool_budgets(m):
    from sheets_factory.evaluation import ringfenced_frontier_v6 as old
    original = {n.name:n for n in old.adapted_ast().body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    adapted = {n.name:n for n in m.runner.adapted_ast().body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    for name in original.keys()-{'freeze_selection','summarize'}:
        assert ast.dump(original[name]) == ast.dump(adapted[name]), name
    for name in ('freeze_selection','summarize'):
        clone = deepcopy(original[name])
        for part in ast.walk(clone):
            if isinstance(part,ast.Compare) and ast.unparse(part) in ('counts[mode] >= 10',"by_mode[mode]['tasks'] >= 10"):
                part.comparators[0] = ast.Constant(5)
            if isinstance(part,ast.Constant) and part.value == 'Confirmation requires at least ten tasks per category':
                part.value = 'The replacement wave requires at least five tasks per category'
        assert ast.dump(clone) == ast.dump(adapted[name])
    assert m.p.BUDGET['tool_budget_seconds'] == 1800
    assert m.p._N['RESERVATIONS'] == ROOT/'outputs/difficulty/.factory_native_phase_reservations_v1'
    assert m.recipes()['replacement_contract']['retained_results_are_historical'] is True


def test_native_summary_reports_ten_new_tasks_without_inventing_twenty_fresh_attempts(m):
    tasks = [{'task_id': mode+str(i), 'mode': mode} for mode in m.COUNTS for i in range(5)]
    selection = {'tasks':tasks, 'phase':'confirmation', 'execution_budget':m.p.BUDGET}
    attempts = [{'task_id':t['task_id'], 'mode':t['mode'], 'status':'scored', 'reward':0,
                 'tool_time':{'state':'verified','cumulative_tool_seconds':1}} for t in tasks]
    score, passed = m.runner.summarize(selection,attempts)
    assert passed is True and score['total_tasks'] == 10 and score['overall_pass_at_1'] == 0
    attempts[0]['status'] = 'infrastructure_error'
    score, passed = m.runner.summarize(selection,attempts)
    assert passed is False and score['overall_pass_at_1'] is None
    assert score['infrastructure_errors'] == 1


def test_development_provenance_is_optional_for_unseen_predeclared_holdouts(m):
    assert m._development_records([], {'x': {'sha256':'x'}}) == ([],[])


def test_unrelated_development_reward_is_rejected(m,tmp_path):
    r = m.write(tmp_path/'old.json',{'kind':'business_revision_native_frontier_terminal_v1','phase':'development',
        'selection':m.write(tmp_path/'selection.json',{}),'evaluation':m.write(tmp_path/'evaluation.json',{}),
        'results':[{'actual_attempt':{'reward':0},'material_identity':{'sha256':'other'}}]})
    with pytest.raises(ValueError, match='another replacement cohort'):
        m._development_records([r],{'x':{'sha256':'x'}})


def test_permanent_confirmation_reservation_is_not_reset_by_new_wave(m,monkeypatch,tmp_path):
    monkeypatch.setitem(m.p._N,'RESERVATIONS',tmp_path/'reservation')
    ident = {'mode':'financial_modeling','value':'same'}; ident['sha256'] = m.p.canonical(ident)
    prepared = {'phase':'confirmation','tasks':[{'task_id':'t'}], 'materials':{'t':ident}}
    witness=m.write(tmp_path/'prepared.json',{})
    m.p._N['reserve'](witness,prepared)
    with pytest.raises(ValueError,match='already reserved'):
        m.p._N['reserve'](witness,prepared)


def test_original_canonical_identity_is_not_replaced_by_file_names(m,monkeypatch):
    tasks = [{'task_id':'fm'},{'task_id':'dbg'}]
    observed = []
    monkeypatch.setitem(m.p._N,'check_task',lambda t:{'a':{'sha256':t['task_id']}})
    def material(t,cache):
        observed.append((t['task_id'],id(cache)))
        return {'sha256':t['task_id']}
    monkeypatch.setattr(m.p,'material_identity',material)
    proof = m.inspect_pair(tasks)
    assert proof['original_full_identity_algorithm'] is True
    assert observed[0][1] == observed[1][1]
    assert proof['materials'] == {'fm':{'sha256':'fm'},'dbg':{'sha256':'dbg'}}
