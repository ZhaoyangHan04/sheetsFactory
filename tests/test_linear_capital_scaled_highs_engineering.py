"""Pure matrix audits and mocked HiGHS calls; no actual optimizer executes."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from sheets_factory.workbook.linear_capital_portfolio import model_a as original_model
from sheets_factory.workbook.linear_capital_scaled import highs_engineering as engineering
from sheets_factory.workbook.linear_capital_scaled import model_a, spec


def row(identity, coefficients, limit, family='resource'):
    return {'id':identity, 'family':family, 'scenario_id':None, 'year':None,
        'coefficients':coefficients, 'limit':limit}


def matrix(*, production=None, legacy=False):
    n = production or 2
    counts = original_model.PRODUCTION_COUNTS if legacy else spec.PRODUCTION_COUNTS
    rows = ([row(f'{family}:{i:03d}', [1]+[0]*(n-1), 1, family)
        for family,count in counts.items() for i in range(count)] if production else [
        row('a:budget',[1,1],1), row('b:duplicate',[1,1],1,'annual_new_lp'),
        row('c:prerequisite',[1,-1],0,'prerequisite'), row('d:zero',[0,0],0)])
    return {'kind':engineering.LEGACY_KIND if legacy else model_a.KIND,
        'version':1 if legacy else 2, 'project_ids':[f'P{i+1:03d}' for i in range(n)],
        'objective_pence':[4_000_001,9_000_007]+[1]*(n-2),
        'rows':sorted(rows,key=lambda r:r['id']),
        'specification_sha256':'a'*64, 'universe_sha256':'b'*64}


@pytest.mark.parametrize('legacy,n,rows', [(False,360,941),(True,240,881)])
def test_both_production_contracts_require_every_family_before_any_row_drop(legacy,n,rows):
    public = matrix(production=n,legacy=legacy)
    before = deepcopy(public)
    assert engineering.validate_model(public) == public
    scaled = engineering.scaled_model(public)
    assert scaled['original_row_count'] == rows
    assert len(scaled['rows'])+len(scaled['dropped_rows']) == rows
    assert public == before
    incomplete = deepcopy(public); incomplete['rows'].pop()
    with pytest.raises(ValueError, match='complete production model'):
        engineering.scaled_model(incomplete)
    wrong_family = deepcopy(public); wrong_family['rows'][-1]['family'] = 'initial_sponsor_equity'
    with pytest.raises(ValueError, match='complete production model'):
        engineering.scaled_model(wrong_family)


def test_exact_row_deduplication_preserves_proportional_distinct_and_impossible_zero_rows():
    public = matrix()
    public['rows'] = [row('a',[4,-2],2),row('b',[4,-2],2),row('c',[2,-1],1),
        row('d',[0,0],0),row('e',[0,0],5),row('f',[0,0],-1),row('g',[1,0],3)]
    result = engineering.scaled_model(public)
    assert [r['id'] for r in result['rows']] == ['a','c','f','g']
    assert result['dropped_rows'] == [
        {'id':'b','reason':'exact_duplicate','retained_id':'a'},
        {'id':'d','reason':'satisfied_zero_row'}, {'id':'e','reason':'satisfied_zero_row'}]
    assert [r['divisor'] for r in result['rows']] == [4,2,1,3]
    assert result['rows'][0]['coefficients'] == [1.0,-0.5]
    assert result['rows'][0]['limit'] == 0.5
    assert result['rows'][2]['limit'] == -1.0
    assert result['objective'] == [4.000001,9.000007]
    assert result['original_model_sha256'] == hashlib.sha256(engineering.canonical(public)).hexdigest()
    assert result['incumbent_seed'] is result['known_objective_cut'] is None
    assert result['reference_admission'] is result['reference_admission_permitted'] is False


def test_exact_audit_checks_all_original_rows_including_deduplicated_rows():
    public = matrix()
    accepted = engineering.exact_plan_check(public,[0,1])
    assert accepted['passed'] and accepted['complete'] and accepted['integer_arithmetic']
    assert accepted['all_integer_rows_checked'] == 4
    assert accepted['objective_pence'] == 9_000_007
    assert [r['id'] for r in accepted['rows']] == [r['id'] for r in public['rows']]
    rejected = engineering.exact_plan_check(public,[1,1])
    assert not rejected['passed'] and rejected['violations'] == ['a:budget','b:duplicate']
    assert rejected['all_integer_rows_checked'] == 4


@pytest.mark.parametrize('attack', ['unknown_kind','extra_field','boolean_version','wrong_version',
    'wrong_n','noninteger','unsafe_sum','missing_digest','unsorted','unknown_family'])
def test_unknown_incomplete_or_nonexact_schema_is_rejected(attack):
    public = matrix()
    if attack == 'unknown_kind': public['kind'] = 'arbitrary_binary_model'
    elif attack == 'extra_field': public['gold_objective'] = 1
    elif attack == 'boolean_version': public['version'] = True
    elif attack == 'wrong_version': public['version'] = 1
    elif attack == 'wrong_n': public['project_ids'].append('P003')
    elif attack == 'noninteger': public['rows'][0]['coefficients'][0] = 1.0
    elif attack == 'unsafe_sum': public['objective_pence'] = [2**52,2**52]
    elif attack == 'missing_digest': public['universe_sha256'] = None
    elif attack == 'unsorted': public['rows'].reverse()
    elif attack == 'unknown_family': public['rows'][0]['family'] = 'custom'
    with pytest.raises(ValueError): engineering.scaled_model(public)


@pytest.mark.parametrize('values', [[1], [True,0], [1.0,0], [2,0], {'P001':0,'P002':1}])
def test_exact_candidate_requires_complete_integer_binary_vector(values):
    with pytest.raises(ValueError, match='complete exact binary'):
        engineering.exact_plan_check(matrix(),values)


class FakeHighs:
    """Return a predeclared vector and record API calls; do no search."""
    def __init__(self, *, values=(0.0,1.0), valid=True, rejected_option=None):
        self.values = values; self.valid = valid; self.rejected_option = rejected_option
        self.calls = []; self.options = {}; self.row_count = 0; self.run_count = 0
    def setOptionValue(self,name,value):
        self.calls.append(('option',name)); self.options[name] = value
        return 'error' if name == self.rejected_option else 'ok'
    def addVars(self,count,lower,upper):
        self.calls.append(('variables',count)); self.bounds = (list(lower),list(upper)); return 'ok'
    def changeColsCost(self,count,indices,costs):
        self.calls.append(('costs',count)); self.costs = list(costs); return 'ok'
    def changeColsIntegrality(self,count,indices,types):
        self.calls.append(('integrality',count)); return 'ok'
    def setMaximize(self): self.calls.append(('maximize',)); return 'ok'
    def addRow(self,lower,upper,count,indices,values):
        self.calls.append(('row',)); self.row_count += 1; return 'ok'
    def writeModel(self,path):
        self.calls.append(('write',)); Path(path).write_text('mock model; no solver execution'); return 'ok'
    def run(self): self.calls.append(('run',)); self.run_count += 1; return 'ok'
    def getSolution(self): return SimpleNamespace(col_value=self.values,value_valid=self.valid)
    def getInfo(self): return SimpleNamespace(mip_gap=0.0,mip_dual_bound=9.000007,mip_node_count=7)
    def getModelStatus(self): return 'HighsModelStatus.kOptimal'
    def getRunTime(self): return 0.25


def mocked(monkeypatch, **kwargs):
    native = FakeHighs(**kwargs); created = []
    def create(): created.append(native); return native
    class Array(list):
        def astype(self, dtype): return self
        def __getitem__(self, index):
            if isinstance(index,list): return Array([super(Array,self).__getitem__(i) for i in index])
            return super().__getitem__(index)
    # Exercise the API boundary without importing or installing native NumPy
    # or HiGHS. This stub performs only deterministic list construction.
    numpy = SimpleNamespace(int32=int, arange=lambda n,**kwargs:Array(range(n)),
        zeros=lambda n:Array([0.0]*n), ones=lambda n:Array([1.0]*n), array=Array,
        flatnonzero=lambda values:Array(i for i,v in enumerate(values) if v))
    module = SimpleNamespace(Highs=create,HighsStatus=SimpleNamespace(kOk='ok',kWarning='warning',kError='error'),
        HighsVarType=SimpleNamespace(kInteger=1),kHighsInf=float('inf'))
    monkeypatch.setitem(sys.modules,'numpy',numpy)
    monkeypatch.setitem(sys.modules,'highspy',module)
    return native,created


def solve(public,tmp_path,**kwargs):
    return engineering.solve_highs(public,log_path=tmp_path/'native.log',model_path=tmp_path/'native.mps',**kwargs)


@pytest.mark.parametrize('legacy', [False,True])
@pytest.mark.parametrize('seconds', [1.5,800,1800])
def test_one_unseeded_two_thread_mock_attempt_can_never_admit_even_native_optimal(monkeypatch,tmp_path,legacy,seconds):
    native,created = mocked(monkeypatch)
    result = solve(matrix(legacy=legacy),tmp_path,time_limit_seconds=seconds)
    assert created == [native] and native.run_count == 1
    assert native.bounds == ([0.0,0.0],[1.0,1.0])
    assert native.row_count == 2 and native.costs == [4.000001,9.000007]
    assert native.options == {'time_limit':float(seconds),'threads':2,'mip_rel_gap':0.0,
        'mip_abs_gap':0.0,'mip_feasibility_tolerance':1e-9,'log_file':str(tmp_path/'native.log')}
    assert result['raw_status'] == 'HighsModelStatus.kOptimal'
    assert result['plan'] == {'P001':0,'P002':1} and result['objective_pence'] == 9_000_007
    assert result['exact_integer_check']['all_integer_rows_checked'] == 4
    assert result['checked_optimal'] is result['reference_admission'] is False
    assert result['reference_admission_permitted'] is result['formal_global_certificate_claimed'] is False
    assert result['optimizer_calls'] == 1 and result['retry_count'] == 0
    assert result['incumbent_seed'] is result['known_objective_cut'] is result['exclude_plan'] is None
    assert result['route_evidence']['observed_absolute_gap'] == 1e-7
    assert result['route_evidence']['requested_absolute_gap'] == 0.0
    assert original_model.KIND == engineering.LEGACY_KIND and len(original_model.PRODUCTION_COUNTS) == 8


def test_one_penny_integer_violation_is_retained_and_never_a_returned_plan(monkeypatch,tmp_path):
    native,_ = mocked(monkeypatch,values=(1.0,1.0))
    public = matrix(); public['rows'][0].update(coefficients=[10**12,1],limit=10**12)
    result = solve(public,tmp_path)
    assert native.run_count == 1 and result['plan'] is result['objective_pence'] is None
    assert not result['exact_integer_check']['passed']
    assert result['exact_integer_check']['rows'][0]['slack'] == -1
    assert result['exact_integer_check']['all_integer_rows_checked'] == 4
    assert result['native_solution_values'] == [1.0,1.0]
    assert 'original exact integer row' in result['incomplete_reason']


@pytest.mark.parametrize('values,reason', [((0.0,),'incomplete or nonfinite'),((float('nan'),1.0),'incomplete or nonfinite'),
    ((2.0,0.0),'outside the binary domain')])
def test_bad_native_primal_is_retained_without_admission(monkeypatch,tmp_path,values,reason):
    native,_ = mocked(monkeypatch,values=values)
    result = solve(matrix(),tmp_path)
    assert result['plan'] is None and reason in result['incomplete_reason']
    assert not result['checked_optimal'] and not result['reference_admission']
    assert native.run_count == 1
    engineering.canonical(result)  # Nonfinite raw observations are serialized as null.


@pytest.mark.parametrize('values', [(0.0,0.99999999),(0.49,1.0)])
def test_exact_feasible_rounded_candidate_is_retained_despite_native_integrality_distance(monkeypatch,tmp_path,values):
    native,_ = mocked(monkeypatch,values=values)
    result = solve(matrix(),tmp_path)
    assert result['plan'] == {'P001':0,'P002':1} and result['objective_pence'] == 9_000_007
    assert result['native_primal_within_integrality_tolerance'] is False
    assert result['candidate_from_rounded_primal'] is True
    assert result['native_solution_values'] == list(values)
    assert result['exact_integer_check']['all_integer_rows_checked'] == 4
    assert not result['checked_optimal'] and not result['reference_admission']
    assert native.run_count == 1


def test_infeasible_rounding_remains_rejected_when_native_integrality_distance_is_large(monkeypatch,tmp_path):
    mocked(monkeypatch,values=(0.99999999,1.0))
    result = solve(matrix(),tmp_path)
    assert result['native_primal_within_integrality_tolerance'] is False
    assert result['candidate_from_rounded_primal'] is False and result['plan'] is None
    assert result['exact_integer_check']['violations'] == ['a:budget','b:duplicate']


def test_no_native_primal_and_native_option_rejection_have_no_retry(monkeypatch,tmp_path):
    native,_ = mocked(monkeypatch,valid=False)
    result = solve(matrix(),tmp_path)
    assert native.run_count == 1 and result['plan'] is None
    assert 'no valid primal' in result['incomplete_reason']
    native,_ = mocked(monkeypatch,rejected_option='threads')
    with pytest.raises(ValueError,match='option was rejected'):
        solve(matrix(),tmp_path/'second')
    assert native.run_count == 0


@pytest.mark.parametrize('seconds', [True,0,-1,1800.01,float('inf'),float('nan'),'800'])
def test_invalid_attempt_limits_fail_before_native_construction(monkeypatch,tmp_path,seconds):
    _,created = mocked(monkeypatch)
    with pytest.raises(ValueError,match='limit at most1800'):
        solve(matrix(),tmp_path,time_limit_seconds=seconds)
    assert created == []


@pytest.mark.parametrize('kwargs', [{'threads':1},{'threads':16},{'threads':True},
    {'exclude_plan':{'P001':0,'P002':1}}])
def test_resource_or_warm_start_changes_fail_before_native_construction(monkeypatch,tmp_path,kwargs):
    _,created = mocked(monkeypatch)
    with pytest.raises(ValueError,match='exactly two threads'):
        solve(matrix(),tmp_path,**kwargs)
    assert created == []


def test_artifact_alias_existing_and_symlink_paths_are_rejected(monkeypatch,tmp_path):
    _,created = mocked(monkeypatch); shared = tmp_path/'shared'
    with pytest.raises(ValueError,match='distinct'):
        engineering.solve_highs(matrix(),log_path=shared,model_path=shared)
    shared.write_text('keep existing evidence')
    with pytest.raises(ValueError,match='Fresh nonsymlink'):
        engineering.solve_highs(matrix(),log_path=shared,model_path=tmp_path/'model')
    alias = tmp_path/'alias'; alias.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='Fresh nonsymlink'):
        engineering.solve_highs(matrix(),log_path=alias/'log',model_path=tmp_path/'model')
    assert shared.read_text() == 'keep existing evidence' and created == []
