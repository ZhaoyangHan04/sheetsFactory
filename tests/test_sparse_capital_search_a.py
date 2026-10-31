"""Real native sparse search on hand-solvable full-dimension fixtures.

Each instance has two investable projects and hard cash-infeasible alternatives.
No production model, workbook, LibreOffice or forty-bit brute-force loop runs.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

import pytest

from sheets_factory.workbook.capital_allocation_sparse import search_a, bounds, spec, ledger, coverage


def public(n=40):
    annual=lambda amount:{str(y):amount for y in spec.YEARS}
    projects=[]
    for j,pid in enumerate(spec.project_ids(n)):
        revenue=annual(0)
        if j<2:revenue['2025']=(200,140)[j]
        projects.append({'id':pid,'commission_year':2024,'sale_year':2025,
            'acquisition_cost_pence':(100,80)[j] if j<2 else 1000000000,
            'depreciation_years':1,'annual_revenue_pence':revenue,'annual_opex_pence':annual(0),
            'sale_proceeds_pence':0})
    scenarios=[{'id':sid,**{k:annual(spec.SCALE) for k in ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12')},
                'bank_rates_p12':annual(0),'haircuts_p12':annual(0)} for sid in spec.SCENARIO_IDS]
    return {'schema_version':1,'currency':'GBP','monetary_unit':'pence','years':list(spec.YEARS),
        'opening_cash_pence':1000,'minimum_cash_pence':0,'lp_commitment_pence':0,'facility_limit_pence':0,
        'advance_rate_p12':0,'tax_rate_p12':0,'tax_loss_carry_years':2,'discount_factors_p12':annual(spec.SCALE),
        'projects':projects,'scenarios':scenarios,
        'provenance':{'kind':'synthetic_capital_allocation_extension','raw_ancestors':deepcopy(spec.RAW_ANCESTORS)}}


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    search_a.assert_template();directory=tmp_path_factory.mktemp('native-sparse-a');path=directory/'sparse_a'
    result=subprocess.run(['g++','-O3','-std=c++17','-static',str(search_a.KERNEL),'-o',str(path)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return path


def run(binary,tmp_path,value,order=None,nodes=100000,ms=60000):
    directory=tmp_path/'prepared';prepared=search_a.prepare_inputs(value,directory,branch_order=order)
    partition=directory/'partition.tsv';summary=directory/'summary.json'
    result=subprocess.run([str(binary),str(directory/'public_a.txt'),str(directory/'safe_integer_bounds.txt'),
        str(partition),str(summary),str(nodes),str(ms)],capture_output=True,text=True,timeout=90)
    return result,prepared,json.loads(summary.read_text()),partition


@pytest.mark.parametrize('n',[40,48,56])
def test_native_full_dimension_coverage_and_hand_computed_best_runnerup(binary,tmp_path,n):
    value=public(n);result,prepared,summary,partition=run(binary,tmp_path,value)
    assert result.returncode==0,result.stderr
    assert summary['status']=='completed_intermediate'
    assert summary['best']=={'mask_hex':'0x0000000000000003','objective_pence':'160','scenario_npvs_pence':dict.fromkeys(spec.SCENARIO_IDS,'160')}
    assert summary['runnerup']=={'mask_hex':'0x0000000000000001','objective_pence':'100','scenario_npvs_pence':dict.fromkeys(spec.SCENARIO_IDS,'100')}
    assert summary['gap_pence']=='60' and summary['covered_plan_count']==str(1<<n)
    assert int(summary['visited_nodes'])<1000 and int(summary['forward_evaluations'])<n+20
    assert int(summary['seed_forward_evaluations'])==n+1
    checked=coverage.verify_partition(n,search_a.read_partition_wire(partition,n),branch_order=prepared['branch_project_order'])
    assert checked['complete_disjoint_structural_coverage'] and checked['covered_plan_count']==str(1<<n)
    assert not checked['unique_optimum_or_runnerup_proven']
    assert summary['semantic_certificate_verified'] is summary['independent_comparison_completed'] is summary['source_quality_or_difficulty_certified'] is False
    leaves=[r for r in search_a.read_partition_wire(partition,n) if r['kind']=='leaf']
    assert {row['evidence']['intermediate_native_wire_fields'][0] for row in leaves}=={'0x0000000000000003','0x0000000000000001','0x0000000000000002'}
    for row in leaves:
        fields=row['evidence']['intermediate_native_wire_fields'];plan=spec.plan_from_mask_hex(value,fields[0])
        forward=ledger.simulate(value,plan)  # Exactly three fixed Decimal checks per dimension; the 100p bound cushion retains one suboptimal leaf.
        assert forward['feasible'] and str(forward['objective_pence'])==min(fields[2:],key=int)
        assert [str(forward['scenarios'][sid]['npv_pence']) for sid in spec.SCENARIO_IDS]==fields[2:]


def test_high_bit_branch_order_preserves_canonical_masks_and_complete_partition(binary,tmp_path):
    value=public(56);ids=list(spec.project_ids(56));order=list(reversed(ids))
    result,prepared,summary,partition=run(binary,tmp_path,value,order)
    assert result.returncode==0 and summary['best']['mask_hex']=='0x0000000000000003'
    checked=coverage.verify_partition(56,search_a.read_partition_wire(partition,56),branch_order=prepared['branch_project_order'])
    assert checked['complete_disjoint_structural_coverage']
    leaf=next(r for r in search_a.read_partition_wire(partition,56) if r['kind']=='leaf')
    assert coverage.describe_prefix(56,leaf['prefix'],branch_order=order)['value_mask_hex']==leaf['evidence']['intermediate_native_wire_fields'][0]


def test_tied_best_is_not_misreported_as_unique(binary,tmp_path):
    value=public();value['projects'][1]['annual_revenue_pence']['2025']=80
    result,_,summary,_=run(binary,tmp_path,value)
    assert result.returncode==0
    assert summary['best']['objective_pence']==summary['runnerup']['objective_pence']=='100'
    assert summary['gap_pence']=='0' and not summary['semantic_certificate_verified']


def test_node_budget_preserves_partial_evidence_and_is_not_a_completed_search(binary,tmp_path):
    result,_,summary,partition=run(binary,tmp_path,public(),nodes=1)
    assert result.returncode==2 and summary['status']=='incomplete' and summary['stop_reason']=='node_limit'
    assert not summary['partition_coverage_complete'] and not summary['semantic_certificate_verified']
    assert partition.exists()
    with pytest.raises(ValueError,match='truncated or incomplete'):
        coverage.verify_partition(40,search_a.read_partition_wire(partition,40))


def test_integer_envelopes_are_optimistic_for_each_exact_coefficient_and_necessary_cut():
    value=public();value['discount_factors_p12']={str(y):spec.SCALE*97**(i+1)//100**(i+1) for i,y in enumerate(spec.YEARS)}
    value['tax_rate_p12']=spec.SCALE//3;value['advance_rate_p12']=spec.SCALE*3//4
    for scenario in value['scenarios']:scenario['haircuts_p12']={str(y):spec.SCALE//7 for y in spec.YEARS}
    model=bounds.prepare_bounds(value);envelope=search_a.integer_envelope(value)
    assert all(integer>=actual for integer,actual in zip(envelope['constants'],model.constants))
    assert all(envelope['coefficients_by_project'][j][s]>=model.coefficients[s][j] for j in range(40) for s in range(3))
    for integer,actual in zip(envelope['necessary_cuts'],model.cuts):
        assert integer['id']==actual.id and integer['capacity']>=actual.capacity
        assert all(w<=exact for w,exact in zip(integer['weights'],actual.weights))
    assert not envelope['region_bounds_or_optimum_verified']


def test_public_wire_preparation_is_bound_fresh_and_never_runs_optimizer(tmp_path,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('Preparation must not run a subprocess'))
    value=public();before=deepcopy(value);p=tmp_path/'prepared';result=search_a.prepare_inputs(value,p)
    assert value==before and result['optimizer_runs']==result['compiler_runs']==result['model_calls']==result['LO_calls']==0
    assert result['complete_plan_count']==str(1<<40) and result['public_spec_sha256']==spec.canonical_sha(value)
    assert result['frozen_financial_forward']['sha256']==search_a.TEMPLATE_SHA256
    for name,ref in result['raw_files'].items():assert hashlib.sha256((p/name).read_bytes()).hexdigest()==ref['sha256']
    with pytest.raises(ValueError,match='fresh'):search_a.prepare_inputs(value,p)


def test_branch_order_and_frozen_template_drift_reject_before_execution(tmp_path,monkeypatch):
    value=public()
    with pytest.raises(ValueError,match='branch order'):search_a.prepare_inputs(value,tmp_path/'invalid',branch_order=['P01']*40)
    assert not(tmp_path/'invalid').exists()
    fake=tmp_path/'fake.cpp';fake.write_text('// changed original forward')
    monkeypatch.setattr(search_a,'TEMPLATE',fake)
    with pytest.raises(ValueError,match='forward template changed'):search_a.prepare_inputs(value,tmp_path/'drift')


@pytest.mark.parametrize('line',[
    'B\t-\t1', 'B\t-\t+1\n', 'I\t-\tmissing\n', 'L\t0\t0x0000000000000000\t7\t1\t1\t1\n',
    'L\t'+'0'*40+'\t0x0000000000000000\t7\tnull\t1\t1\n',
    'L\t'+'0'*40+'\t0x0000000000000000\t0\t1\tnull\tnull\n',
    'L\t'+'0'*40+'\t0x8000000000000000\t7\t1\t1\t1\n'])
def test_partial_or_malformed_native_regions_fail_closed(tmp_path,line):
    p=tmp_path/'bad.tsv';p.write_text(line)
    with pytest.raises(ValueError):list(search_a.read_partition_wire(p,40))


def test_raw_reader_rejects_trailing_or_wrong_public_wire(binary,tmp_path):
    value=public();directory=tmp_path/'prepared';search_a.prepare_inputs(value,directory)
    with (directory/'public_a.txt').open('a') as stream:stream.write('private_answer 42\n')
    result=subprocess.run([str(binary),str(directory/'public_a.txt'),str(directory/'safe_integer_bounds.txt'),str(directory/'p.tsv'),str(directory/'s.json'),'10000','10000'],capture_output=True,text=True)
    assert result.returncode==1 and 'Trailing public primitives' in result.stderr
    assert not(directory/'s.json').exists()


def test_selected_fifty_sixth_bit_is_exact_without_a_numeric_JSON_mask(binary,tmp_path):
    value=public(56)
    selected=deepcopy(value['projects'][1]);selected['id']='P56'
    expensive=deepcopy(value['projects'][-1]);expensive['id']='P02'
    value['projects'][1]=expensive;value['projects'][-1]=selected
    result,prepared,summary,partition=run(binary,tmp_path,value)
    assert result.returncode==0,result.stderr
    mask=(1<<55)|1
    assert summary['best']['mask_hex']=='0x'+format(mask,'016x')
    assert summary['best']['objective_pence']=='160'
    plan=spec.plan_from_mask_hex(value,summary['best']['mask_hex'])
    actual=ledger.simulate(value,plan)  # One additional fixed Decimal forward.
    assert actual['feasible'] and actual['objective_pence']==160 and plan['P56']==1
    for row in search_a.read_partition_wire(partition,56):
        if row['kind']=='leaf':
            assert coverage.describe_prefix(56,row['prefix'],branch_order=prepared['branch_project_order'])['value_mask_hex']==row['evidence']['intermediate_native_wire_fields'][0]


def test_native_tax_financing_FIFO_optimum_matches_sixteen_independent_fixed_forwards(binary,tmp_path):
    import importlib.util
    location=Path(__file__).with_name('test_sparse_capital_bounds.py')
    module_spec=importlib.util.spec_from_file_location('_fixed_sparse_bound_test_data',location)
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    value=module.public(40,stress=True)
    monetary=('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence')
    for key in monetary:value[key]*=10000
    for index,project in enumerate(value['projects']):
        if index<4:
            project['acquisition_cost_pence']*=10000;project['sale_proceeds_pence']*=10000
            for field in ('annual_revenue_pence','annual_opex_pence'):
                project[field]={year:amount*10000 for year,amount in project[field].items()}
        else:
            project['acquisition_cost_pence']=1000000000;project['sale_proceeds_pence']=0
            for field in ('annual_revenue_pence','annual_opex_pence'):project[field]=dict.fromkeys(map(str,spec.YEARS),0)
    ranked=[]
    for bits in itertools.product((0,1),repeat=4):
        plan={pid:(bits[index] if index<4 else 0) for index,pid in enumerate(spec.project_ids(40))}
        actual=ledger.simulate(value,plan)  # Exactly sixteen fixed forwards; no forty-bit brute force.
        if actual['feasible']:ranked.append((actual['objective_pence'],int(spec.mask_hex(value,plan),16)))
    ranked.sort(key=lambda pair:(-pair[0],pair[1]));assert len(ranked)>=2
    result,_,summary,partition=run(binary,tmp_path,value)
    assert result.returncode==0,result.stderr
    assert [(int(summary[key]['objective_pence']),int(summary[key]['mask_hex'],16)) for key in ('best','runnerup')]==ranked[:2]
    assert coverage.verify_partition(40,search_a.read_partition_wire(partition,40))['complete_disjoint_structural_coverage']


def test_output_backpressure_counts_toward_elapsed_guard_before_completion(binary,tmp_path):
    import fcntl,os,time
    value=public(56);directory=tmp_path/'prepared';search_a.prepare_inputs(value,directory)
    fifo=directory/'partition.tsv';os.mkfifo(fifo)
    descriptor=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK)
    try:
        fcntl.fcntl(descriptor,fcntl.F_SETPIPE_SZ,4096)
        summary=directory/'summary.json'
        process=subprocess.Popen([str(binary),str(directory/'public_a.txt'),str(directory/'safe_integer_bounds.txt'),
            str(fifo),str(summary),'100000','50'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        # Wait for the output pipe to fill without consuming it. This stalls a
        # small proof well after its node-one check and below4096 total nodes.
        time.sleep(0.20)
        observed=bytearray()
        deadline=time.monotonic()+10
        while process.poll() is None and time.monotonic()<deadline:
            try:observed.extend(os.read(descriptor,65536))
            except BlockingIOError:pass
            time.sleep(0.001)
        try:
            while True:
                block=os.read(descriptor,65536)
                if not block:break
                observed.extend(block)
        except BlockingIOError:pass
        stdout,stderr=process.communicate(timeout=10)
        result=json.loads(summary.read_text())
        assert process.returncode==2,(stdout,stderr,result)
        assert result['stop_reason']=='elapsed_limit' and not result['partition_coverage_complete']
        assert int(result['visited_nodes'])<4096 and len(observed)>4096
        assert not result['semantic_certificate_verified']
    finally:os.close(descriptor)
