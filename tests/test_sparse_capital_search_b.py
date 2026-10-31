"""Independent native B on hand-solvable full-dimension sparse fixtures only."""
from copy import deepcopy
import ast
import fcntl
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from sheets_factory.workbook.capital_allocation_sparse import search_b,spec,bounds,coverage,ledger


def public(n=40):
    annual=lambda value:{str(year):value for year in spec.YEARS}
    projects=[]
    for index,pid in enumerate(spec.project_ids(n)):
        revenue=annual(0)
        if index<2:revenue['2025']=(350,240)[index]
        projects.append({'id':pid,'commission_year':2024,'sale_year':2025,'acquisition_cost_pence':(100,80)[index] if index<2 else 1000000000,
            'depreciation_years':1,'annual_revenue_pence':revenue,'annual_opex_pence':annual(0),'sale_proceeds_pence':0})
    return {'schema_version':1,'currency':'GBP','monetary_unit':'pence','years':list(spec.YEARS),
        'opening_cash_pence':1000,'minimum_cash_pence':0,'lp_commitment_pence':0,'facility_limit_pence':0,
        'advance_rate_p12':0,'tax_rate_p12':0,'tax_loss_carry_years':3,'discount_factors_p12':annual(spec.SCALE),
        'projects':projects,'scenarios':[{'id':sid,**{key:annual(spec.SCALE) for key in ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12')},
            'bank_rates_p12':annual(0),'haircuts_p12':annual(0)} for sid in spec.SCENARIO_IDS],
        'provenance':{'kind':'synthetic_capital_allocation_extension','raw_ancestors':deepcopy(spec.RAW_ANCESTORS)}}


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    search_b.assert_template();path=tmp_path_factory.mktemp('sparse-b')/'native_b'
    done=subprocess.run(['g++','-O3','-std=c++17','-static',str(search_b.KERNEL),'-o',str(path)],capture_output=True,text=True,timeout=60)
    assert done.returncode==0,done.stderr
    return path


def run(binary,tmp_path,value,*,order=None,nodes=100000,ms=60000,frontier=10000):
    folder=tmp_path/'prepared';prepared=search_b.prepare_inputs(value,folder,branch_order=order)
    partition=folder/'partition.tsv';summary=folder/'summary.json'
    command=[str(binary),str(folder/'public_b.txt'),str(folder/'safe_integer_bounds.txt'),str(partition),str(summary),str(nodes),str(ms),str(frontier)]
    done=subprocess.run(command,capture_output=True,text=True,timeout=90)
    return done,prepared,json.loads(summary.read_text()),partition


@pytest.mark.parametrize('n',[40,48,56])
def test_independent_b_native_best_runner_and_full_prefix_partition(binary,tmp_path,n):
    value=public(n);done,prepared,summary,partition=run(binary,tmp_path,value)
    assert done.returncode==0,done.stderr
    assert summary['best']['mask_hex']=='0x0000000000000003' and summary['best']['objective_pence']=='410'
    assert summary['runnerup']['mask_hex']=='0x0000000000000001' and summary['runnerup']['objective_pence']=='250'
    assert summary['gap_pence']=='160' and summary['covered_plan_count']==str(1<<n)
    assert summary['seed_forward_evaluations']==str(n+2) and int(summary['visited_nodes'])<2000
    assert prepared['branch_project_order']==list(reversed(spec.project_ids(n)))
    checked=coverage.verify_partition(n,search_b.read_partition_wire(partition,n),branch_order=prepared['branch_project_order'])
    assert checked['complete_disjoint_structural_coverage'] and checked['covered_plan_count']==str(1<<n)
    assert not summary['semantic_certificate_verified'] and not summary['source_quality_or_difficulty_certified']
    assert not summary['independent_comparison_completed'] and summary['shared_public_exact_bound_policy']
    leaves=[row for row in search_b.read_partition_wire(partition,n) if row['kind']=='leaf']
    for row in leaves:
        fields=row['evidence']['intermediate_native_wire_fields'];plan=spec.plan_from_mask_hex(value,fields[0])
        actual=ledger.simulate(value,plan)  # A few declared leaves only, never 2**N.
        assert actual['feasible'] and [str(actual['scenarios'][sid]['npv_pence']) for sid in spec.SCENARIO_IDS]==fields[2:]
        assert coverage.describe_prefix(n,row['prefix'],branch_order=prepared['branch_project_order'])['value_mask_hex']==fields[0]


def test_selected_bit_fifty_six_is_exact_and_no_json_numeric_mask(binary,tmp_path):
    value=public(56);positive=deepcopy(value['projects'][1]);positive['id']='P56'
    expensive=deepcopy(value['projects'][-1]);expensive['id']='P02';value['projects'][1]=expensive;value['projects'][-1]=positive
    done,_,summary,_=run(binary,tmp_path,value,order=list(spec.project_ids(56)))
    assert done.returncode==0 and summary['best']['mask_hex']=='0x'+format((1<<55)|1,'016x')
    plan=spec.plan_from_mask_hex(value,summary['best']['mask_hex']);actual=ledger.simulate(value,plan)
    assert plan['P56']==1 and actual['objective_pence']==410


def test_tied_best_has_gap_zero_and_no_semantic_admission(binary,tmp_path):
    value=public();value['projects'][1]['annual_revenue_pence']['2025']=80
    done,_,summary,_=run(binary,tmp_path,value)
    assert done.returncode==0 and summary['best']['objective_pence']==summary['runnerup']['objective_pence']=='250'
    assert summary['gap_pence']=='0' and not summary['semantic_certificate_verified']


def test_fewer_than_two_feasible_plans_is_incomplete_not_a_source_claim(binary,tmp_path):
    value=public()
    for project in value['projects']:
        project['acquisition_cost_pence']=1000000000
        project['annual_revenue_pence']=dict.fromkeys(map(str,spec.YEARS),0)
    done,_,summary,_=run(binary,tmp_path,value)
    assert done.returncode==2 and summary['stop_reason']=='fewer_than_two_feasible_plans'
    assert summary['best']['mask_hex']=='0x0000000000000000' and summary['runnerup'] is None
    assert summary['gap_pence'] is None and not summary['partition_coverage_complete']


@pytest.mark.parametrize('limit,reason',[('nodes','node_limit'),('frontier','frontier_limit')])
def test_node_and_queue_caps_preserve_incomplete_partition_without_false_pass(binary,tmp_path,limit,reason):
    done,_,summary,partition=run(binary,tmp_path,public(),**{limit:1})
    assert done.returncode==2 and summary['status']=='incomplete' and summary['stop_reason']==reason
    assert not summary['partition_coverage_complete'] and not summary['semantic_certificate_verified']
    assert partition.exists()


def test_deadline_after_blocked_output_close_cannot_claim_completed(binary,tmp_path):
    folder=tmp_path/'prepared';search_b.prepare_inputs(public(),folder)
    fifo=folder/'backpressured.tsv';os.mkfifo(fifo)
    fd=os.open(fifo,os.O_RDWR|os.O_NONBLOCK)
    try:
        fcntl.fcntl(fd,fcntl.F_SETPIPE_SZ,4096);os.write(fd,b'X'*4096)
        summary=folder/'summary.json'
        command=[str(binary),str(folder/'public_b.txt'),str(folder/'safe_integer_bounds.txt'),str(fifo),str(summary),'100000','200','10000']
        child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(0.4)
            assert child.poll() is None,'The real native output should be blocked by the full owned pipe'
            assert os.read(fd,4096)==b'X'*4096
            _,stderr=child.communicate(timeout=10)
            assert child.returncode==2,stderr
            result=json.loads(summary.read_text())
            assert result['status']=='incomplete' and result['stop_reason']=='elapsed_limit'
            assert not result['partition_coverage_complete'] and not result['semantic_certificate_verified']
        finally:
            if child.poll() is None:child.kill();child.wait()
    finally:os.close(fd)


def test_b_independently_serialized_envelopes_are_conservative_and_raw_preparation_is_zero_execution(tmp_path,monkeypatch):
    value=public();value['tax_rate_p12']=spec.SCALE//3
    value['discount_factors_p12']={str(y):spec.SCALE*93**(i+1)//100**(i+1) for i,y in enumerate(spec.YEARS)}
    model=bounds.prepare_bounds(value);envelope=search_b.integer_envelope(value)
    assert all(x>=y for x,y in zip(envelope['constants'],model.constants))
    for j in range(40):assert all(envelope['coefficients_by_project'][j][s]>=model.coefficients[s][j] for s in range(3))
    for row,exact in zip(envelope['necessary_cuts'],model.cuts):
        assert row['capacity']>=exact.capacity and all(a<=b for a,b in zip(row['weights'],exact.weights))
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('Preparation cannot compile or execute'))
    prepared=search_b.prepare_inputs(value,tmp_path/'prepared')
    assert prepared['optimizer_runs']==prepared['compiler_runs']==prepared['model_calls']==prepared['LO_calls']==0
    assert prepared['frozen_financial_forward']['sha256']==search_b.TEMPLATE_SHA256 and prepared['A_helper_or_answer_used'] is False
    for item in prepared['raw_files'].values():assert search_b.reference(item['path'])==item
    with pytest.raises(ValueError):search_b.prepare_inputs(value,tmp_path/'prepared')


def test_wrong_template_branch_order_and_native_raw_primitive_are_rejected(binary,tmp_path,monkeypatch):
    with pytest.raises(ValueError):search_b.prepare_inputs(public(),tmp_path/'bad',branch_order=['P01']*40)
    folder=tmp_path/'prepared';search_b.prepare_inputs(public(),folder)
    with (folder/'public_b.txt').open('a') as stream:stream.write('private_answer 99\n')
    done=subprocess.run([str(binary),str(folder/'public_b.txt'),str(folder/'safe_integer_bounds.txt'),str(folder/'p.tsv'),str(folder/'s.json'),'1000','1000','1000'],capture_output=True,text=True)
    assert done.returncode==1 and 'Trailing independent B primitive' in done.stderr
    fake=tmp_path/'fake.cpp';fake.write_text('// changed B financial algorithm')
    monkeypatch.setattr(search_b,'TEMPLATE',fake)
    with pytest.raises(ValueError,match='financial template changed'):search_b.prepare_inputs(public(),tmp_path/'bad_template')


def test_native_reader_checks_raw_monetary_bounds_independently_of_python(binary,tmp_path):
    folder=tmp_path/'prepared';search_b.prepare_inputs(public(),folder)
    wire=folder/'public_b.txt';rows=wire.read_text().splitlines();amounts=rows[2].split();amounts[0]='-1';rows[2]=' '.join(amounts)
    wire.write_text('\n'.join(rows)+'\n')
    done=subprocess.run([str(binary),str(wire),str(folder/'safe_integer_bounds.txt'),str(folder/'p.tsv'),str(folder/'s.json'),'1000','1000','1000'],capture_output=True,text=True)
    assert done.returncode==1 and 'primitive outside bounds' in done.stderr and not(folder/'s.json').exists()


@pytest.mark.parametrize('line',[
    'B\t-\t0','B\t-\t+1\n','I\t-\tunknown\n',
    'L\t0\t0x0000000000000000\t7\t1\t1\t1\n',
    'L\t'+'0'*40+'\t0x8000000000000000\t7\t1\t1\t1\n',
    'L\t'+'0'*40+'\t0x0000000000000000\t7\tnull\t1\t1\n',
])
def test_malformed_partial_native_rows_fail(tmp_path,line):
    path=tmp_path/'row.tsv';path.write_text(line)
    with pytest.raises(ValueError):list(search_b.read_partition_wire(path,40))


def test_no_A_calculation_or_answer_helper_is_imported():
    source=Path(search_b.__file__).read_text();tree=ast.parse(source)
    assert all('search_a' not in ast.unparse(node) for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)))
    native=search_b.KERNEL.read_text()
    assert '#include "../capital_allocation_scaled/search_b.cpp"' in native and 'search_a' not in native
    assert 'project_flows(p,j)' in native and 'close(p,s,flow,zero,years)' in native


def test_four_active_financing_FIFO_paths_match_independent_Decimal_ranks(binary,tmp_path):
    location=Path(__file__).with_name('test_sparse_capital_bounds.py');module_spec=importlib.util.spec_from_file_location('_b_independent_public_fixture',location)
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    value=module.public(40,stress=True)
    for key in ('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence'):value[key]*=10000
    for index,project in enumerate(value['projects']):
        if index<4:
            for key in ('acquisition_cost_pence','sale_proceeds_pence'):project[key]*=10000
            for key in ('annual_revenue_pence','annual_opex_pence'):project[key]={year:amount*10000 for year,amount in project[key].items()}
        else:
            project['acquisition_cost_pence']=1000000000;project['sale_proceeds_pence']=0
            project['annual_revenue_pence']=dict.fromkeys(map(str,spec.YEARS),0);project['annual_opex_pence']=dict.fromkeys(map(str,spec.YEARS),0)
    ranks=[]
    for bits in itertools.product((0,1),repeat=4):
        plan={pid:bits[j] if j<4 else 0 for j,pid in enumerate(spec.project_ids(40))};actual=ledger.simulate(value,plan)
        if actual['feasible']:ranks.append((actual['objective_pence'],int(spec.mask_hex(value,plan),16)))
    ranks.sort(key=lambda item:(-item[0],item[1]));assert len(ranks)>=2
    done,prepared,summary,partition=run(binary,tmp_path,value)
    assert done.returncode==0,done.stderr
    assert [(int(summary[name]['objective_pence']),int(summary[name]['mask_hex'],16)) for name in ('best','runnerup')]==ranks[:2]
    assert coverage.verify_partition(40,search_b.read_partition_wire(partition,40),branch_order=prepared['branch_project_order'])['complete_disjoint_structural_coverage']
