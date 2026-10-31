"""D02 envelope/phase fixtures only; no production search, workbook, LO or model."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    definition=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(definition);definition.loader.exec_module(value);return value


builder=load('_constrained_source_entry_tests',ROOT/'scripts/build_constrained_capital_source.py')
old_tests=load('_constrained_source_shared_mock_fixture',ROOT/'tests/test_scaled_capital_source.py')
CATALOG=ROOT/'outputs/research/constrained_capital_D02_fixed_actual_20261031T001535Z/public_specs/catalog_manifest.json'


def write(path,value):return builder.write_new(path,value)
def read(ref):return json.loads(Path(ref['path']).read_text())


def context():
    manifest=json.loads(CATALOG.read_text());source=manifest['specifications'][0]['spec']
    return builder._catalog_context(source['path'],CATALOG,builder.Evidence())


def test_actual_frozen_raw_catalogue_and_contract_are_D02_without_financial_execution():
    public,source,manifest_ref,manifest,artifacts=context()
    assert len(public['projects'])==30 and manifest_ref['sha256']==builder.CATALOG_SHA256
    assert manifest['profile_order']==list(builder.catalog.PROFILE_ORDER) and len(manifest['specifications'])==11
    assert set(artifacts)==set(builder.PUBLIC_ARTIFACTS) and artifacts['spec']==source
    assert read(artifacts['candidate_contract'])['profile_id']=='30-D02'
    assert 'engineering_inventory' not in artifacts
    assert hashlib.sha256(Path(artifacts['candidate_contract_markdown']['path']).read_bytes()).hexdigest()==\
        'a965864eae7490a2185d1e3030fc8b56c69ea08bfb5b936df59816ed21f7b4e4'


def test_old_D01_and_confirmation_raw_sources_cannot_enter_the_new_route():
    manifest=json.loads(CATALOG.read_text())
    with pytest.raises(ValueError,match='D02 development'):
        builder._catalog_context(manifest['specifications'][1]['spec']['path'],CATALOG,builder.Evidence())
    with pytest.raises(ValueError,match='eleven-profile'):
        builder._catalog_context(manifest['specifications'][0]['spec']['path'],old_tests.CATALOG,builder.Evidence())


@pytest.fixture
def proof(tmp_path,monkeypatch):
    """All enumeration/financial result claims below are explicit test doubles."""
    public,source,catalog_ref,manifest,artifacts=context();record=manifest['specifications'][0]
    inventory=read(record['engineering_inventory']);root=tmp_path/'UNIT_MOCKED_dual';root.mkdir()
    b_prep=builder.search_b.prepare(public,root/'B');b_frozen=read(b_prep)
    rank={'feasible_count':builder.COUNT,'best_count':1,'best_mask':3,'objective_pence':1000,
        'runnerup_mask':1,'runnerup_objective_pence':900,'gap_pence':100,'unique_best':True,'best_full_mask':3,
        'best_plan':{p['id']:(3>>i)&1 for i,p in enumerate(public['projects'])}}
    fake_driver=SimpleNamespace(TERMINAL_KIND='complete_constrained_scaled_capital_dual_search',recipe=lambda:{},
        _catalogue=builder._driver()._catalogue)
    driver_prepared={'profile_id':'30-D02','public_specification':source,'catalog_manifest':catalog_ref,
        'public_contract_artifacts':record,'recipe':{},'engineering_provenance':{'UNIT_FIXTURE':True},
        'engineering_provenance_summary':{'original_predeclared_three_pair_gate_passed':False}}
    preparation_ref=write(root/'driver_preparation.json',driver_prepared)
    def checked_preparation(ref):
        assert ref==preparation_ref
        return deepcopy(driver_prepared),deepcopy(public),deepcopy(inventory)
    fake_driver.validate_prepared=checked_preparation
    monkeypatch.setattr(builder,'_driver',lambda:fake_driver)
    chunks=[{'start_mask':i,'end_mask_exclusive':i+builder.spec.CHUNK_RECORDS,'record_count':builder.spec.CHUNK_RECORDS,
        'bytes':builder.spec.CHUNK_RECORDS*32,'sha256':'d'*64} for i in range(0,builder.COUNT,builder.spec.CHUNK_RECORDS)]
    binary=root/'UNIT_not_executed_binary';binary.write_text('not a kernel')
    compilation=write(root/'compilation.json',{'UNIT_FIXTURE':True,'kind':'capital_scaled_A_compilation',
        'returncode':0,'implementation':builder.reference(builder.search_a.SOURCE),'binary':builder.reference(binary)})
    raw=root/'A_raw.txt';raw.write_text(builder.search_a.raw_primitives(public,list(range(30))))
    native={}
    for name,kind in (('A','capital_scaled_A_complete_enumeration'),('B','capital_allocation_scaled_independent_B_execution')):
        path=root/(name+'_UNIT_RECORD_STUB.bin');path.write_text('Not a complete stream; stream verifier is mocked only here')
        records={'path':str(path),'sha256':'f'*64,'bytes':builder.RECORD_BYTES}
        result={'UNIT_FIXTURE':True,'kind':kind,'status':'completed',**rank,'plan_count':builder.COUNT,
            'project_count':30,'full_enumeration':True,'toy_only':False,'active_project_ids':list(builder.spec.project_ids(30)),
            'spec_sha256':builder.spec.canonical_sha(public),'public_spec':b_frozen['public_spec'],
            'record_format':builder.spec.RECORD_FORMAT,'record_bytes':32,'chunk_records':builder.spec.CHUNK_RECORDS,
            'null_npv':builder.spec.NULL_NPV,'records':records,'chunks':chunks}
        if name=='A':
            result.update(recipe=builder.search_a.recipe(),raw_primitives=builder.reference(raw),compilation=compilation,
                kernel_result={**{k:rank[k] for k in builder.search_a.RANK_FIELDS},'plan_count':builder.COUNT,'scenario_evaluations':builder.COUNT*3})
        else:
            result.update(recipe_sha256=builder.search_b._recipe(),preparation=b_prep,kernel_implementation=builder.reference(builder.search_b.KERNEL),
                wrapper_implementation=builder.reference(builder.search_b.__file__),shared_financial_calculation_helper=False,
                independent_raw_public_primitives_precompilation=True,compiled_binary=builder.reference(binary),
                kernel_command=[str(binary),b_frozen['raw_wire']['path'],records['path']],
                kernel_statistics={'plan_count':builder.COUNT,'scenario_evaluations':builder.COUNT*3,'feasible_count':rank['feasible_count']})
        native[name]=write(root/(name+'_UNIT_result.json'),result)
    comparison=write(root/'comparison.json',{'kind':'complete_constrained_independent_ordinal_record_equality',
        'records_equal_complete':True,'rankings_equal':True,'all_chunk_hashes_equal':True,'plan_count':builder.COUNT,
        'record_bytes_per_kernel':builder.RECORD_BYTES,'chunk_count_per_kernel':16384,
        'A_records':read(native['A'])['records'],'B_records':read(native['B'])['records'],
        'kernel_A_result':native['A'],'kernel_B_result':native['B'],'rank_fields':rank})
    plans=[{'id':'best_mask','plan':rank['best_plan']},{'id':'runnerup_mask','plan':{p['id']:(1>>i)&1 for i,p in enumerate(public['projects'])}},*inventory['plans']]
    rows=[];selected_npvs={};best=None
    for i,row in enumerate(plans):
        mask=sum(row['plan'][p['id']]<<j for j,p in enumerate(public['projects']));value=1000 if mask==3 else 900 if mask==1 else 100-mask%50
        npvs=[value+2,value+1,value];selected_npvs[mask]=(7,npvs)
        forward={'UNIT_FIXTURE':True,'plan':row['plan'],'feasible':True,'objective_pence':value,
            'scenarios':{sid:{'feasible':True,'all_journals_balance':True,'npv_pence':npvs[j]} for j,sid in enumerate(builder.spec.SCENARIO_IDS)}}
        if i==0:best=forward
        rows.append({'id':row['id'],'mask':mask,'ledger':write(root/'Decimal'/(str(i)+'.json'),forward),
            'record_matches':True,'all_journals_balance':True,'feasible':True,'objective_pence':value})
    decimal=write(root/'forward_checks.json',{'kind':'constrained_forward_best_runnerup_and_complete_declared_fixed_inventory',
        'passed':True,'checks':rows,'declared_fixed_plan_count':44,'all_declared_fixed_plans_preserved':True,
        'optimisation_performed':False,'independent_global_optimality_claimed':False})
    started=write(root/'started.json',{'kind':'started_constrained_capital_dual_search','preparation':preparation_ref,
        'expected_plan_count_per_kernel':builder.COUNT,'concurrent_kernels':2,'timeout_seconds_per_kernel':14400,'recipe':{}})
    terminal=write(root/'receipt.json',{'kind':fake_driver.TERMINAL_KIND,'version':1,'UNIT_FIXTURE':True,'status':'completed',
        'passed':True,'profile_id':'30-D02','complete_independent_search_finished':True,'records_equal_complete':True,
        'full_enumeration':True,'toy_only':False,'count':builder.COUNT,'plan_count':builder.COUNT,
        'preparation':preparation_ref,'public_specification':source,'catalog_manifest':catalog_ref,'public_contract_artifacts':record,
        'engineering_provenance':driver_prepared['engineering_provenance'],'engineering_provenance_summary':driver_prepared['engineering_provenance_summary'],
        'started':started,'recipe':{},'kernel_A_result':native['A'],'kernel_B_result':native['B'],
        'complete_record_comparison':comparison,'independent_decimal_validation':decimal,**rank})
    scanned=[]
    def mock_huge(record,chunks,count,progress=None):
        assert count==builder.COUNT and len(chunks)==16384 and record['bytes']==builder.RECORD_BYTES
        scanned.append(record['path']);return record
    monkeypatch.setattr(builder,'stream_records',mock_huge)
    monkeypatch.setattr(builder,'_selected_record',lambda path,mask:selected_npvs[mask])
    return SimpleNamespace(public=public,specification=source,catalog=catalog_ref,artifacts=artifacts,terminal=terminal,
        root=root,native=native,rank=rank,scanned=scanned,best_ledger=best)


def validate(proof):return builder.validate_dual_proof(proof.public,proof.specification,proof.catalog,proof.artifacts,proof.terminal)
def prepare(proof,output):return builder.prepare(proof.specification['path'],proof.catalog['path'],proof.terminal['path'],output)


def test_actual_D02_envelope_and_all46_forward_checks_are_understood_without_D01_relabelling(proof):
    result=validate(proof)
    assert result['rank']==proof.rank and len(proof.scanned)==2
    assert result['terminal']['kind']=='complete_constrained_scaled_capital_dual_search'
    assert result['selected_plan_decimal_checks_are_not_an_independent_global_search'] is True


@pytest.mark.parametrize('field,value',[('profile_id','30-D01'),('status','running'),('passed',False),
    ('full_enumeration',False),('toy_only',True),('plan_count',1<<18),('gap_pence',0),('unique_best',False),('best_mask',True)])
def test_incomplete_tied_old_profile_or_toy_terminal_is_rejected(proof,field,value):
    bad=read(proof.terminal);bad[field]=value;proof.terminal=write(proof.root/'bad_terminal.json',bad)
    with pytest.raises(ValueError):validate(proof)


@pytest.mark.parametrize('change',['old_kind','missing_fixed','reordered_fixed','rewritten_history','comparison_kind','comparison_rank','A_wire','B_source'])
def test_real_receipt_shapes_complete_fixed_inventory_and_history_cannot_be_rewritten(proof,change):
    terminal=read(proof.terminal)
    if change=='old_kind':terminal['kind']='complete_scaled_capital_dual_search'
    elif change in ('missing_fixed','reordered_fixed'):
        rows=read(terminal['independent_decimal_validation'])
        if change=='missing_fixed':rows['checks'].pop()
        else:rows['checks'][2],rows['checks'][3]=rows['checks'][3],rows['checks'][2]
        terminal['independent_decimal_validation']=write(proof.root/'wrong_rows.json',rows)
    elif change=='rewritten_history':terminal['engineering_provenance_summary']['original_predeclared_three_pair_gate_passed']=True
    elif change in ('comparison_kind','comparison_rank'):
        comparison=read(terminal['complete_record_comparison'])
        if change=='comparison_kind':comparison['kind']='complete_independent_ordinal_record_equality'
        else:comparison['rank_fields']['gap_pence']+=1
        terminal['complete_record_comparison']=write(proof.root/'wrong_comparison.json',comparison)
    elif change=='A_wire':Path(read(proof.native['A'])['raw_primitives']['path']).write_text('wrong raw primitives')
    else:
        b=read(proof.native['B']);b['spec_sha256']='0'*64;terminal['kernel_B_result']=write(proof.root/'wrong_B.json',b)
    proof.terminal=write(proof.root/'wrong_terminal.json',terminal)
    with pytest.raises(ValueError):validate(proof)


def test_source_preparation_is_zero_execution_and_copies_only_four_answer_free_sidecars(proof,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('Default source preparation cannot construct or calculate a workbook/search')
    monkeypatch.setattr(builder.openpyxl,'Workbook',forbidden)
    monkeypatch.setattr(builder.ledger,'simulate',forbidden)
    monkeypatch.setattr(builder.search_a,'execute_prepared',forbidden)
    monkeypatch.setattr(builder.search_b,'execute_prepared',forbidden)
    monkeypatch.setattr(builder,'ResourceLibreOfficeEngine',forbidden)
    output=tmp_path/'source';ref=prepare(proof,output);frozen=builder.validate_prepared(output)
    assert frozen==read(ref) and frozen['profile_id']=='30-D02' and frozen['kind']==builder.KIND
    assert frozen['actual_LO_calls']==frozen['actual_new_enumerations']==frozen['model_calls']==0
    assert len(list((output/'public').iterdir()))==4 and not list(output.rglob('*.xlsx'))
    assert all('"best_plan"' not in path.read_text() for path in (output/'public').iterdir())
    assert not any('engineering_inventory' in path.name for path in (output/'public').iterdir())


def test_actual_build_loop_and_preparation_guards_have_exact_frozen_parity_except_identity_strings():
    changes={'scaled_capital_source_attempt':'constrained_capital_source_attempt',
        'Scaled capital source engineering':'Constrained capital source engineering',
        'independently_verified_scaled_capital_allocation_source':'independently_verified_constrained_capital_allocation_source',
        'derived_scaled_capital_allocation_source':'derived_constrained_capital_allocation_source'}
    class Identity(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in changes:node.value=changes[node.value]
            return node
    for name in ('execute_prepared','prepare','validate_prepared','main'):
        old=ast.parse(inspect.getsource(getattr(builder.base,name)));new=ast.parse(inspect.getsource(getattr(builder,name)))
        assert ast.dump(Identity().visit(old))==ast.dump(new)
    assert builder.stream_records is builder.base.stream_records
    assert builder._rank_fields is builder.base._rank_fields
    assert builder._selected_record is builder.base._selected_record
    assert builder.base.PROFILE_ID=='30-D01' and builder.PROFILE_ID=='30-D02'


@pytest.mark.parametrize('failure,expected',[ (None,3),('engine2',2),('audit2',2),('truncated_audit',1),('stability',3)])
def test_explicit_phase_uses_tiny_mocked_engine_and_preserves_failure_cleanup(proof,tmp_path,monkeypatch,failure,expected):
    output=tmp_path/'source';prepare(proof,output)
    # Reuse only the old test fixture implementation. Production module globals
    # and all source/math files remain unchanged.
    monkeypatch.setattr(old_tests,'builder',builder)
    state=old_tests.fake_pipeline(proof,monkeypatch,failure=failure)
    if failure is None:
        result=read(builder.execute_prepared(output))
        assert result['kind']=='independently_verified_constrained_capital_allocation_source'
        assert result['profile_id']=='30-D02' and len(result['financial_audits'])==3 and result['actual_LO_recalculations']==3
        assert result['quality_or_difficulty_certified'] is False and result['qualified'] is False
        assert state['audits']==3 and len(result['engine_calls'])==3
    else:
        with pytest.raises((ValueError,RuntimeError)):builder.execute_prepared(output)
        assert not (output/'seed_manifest.json').exists()
        terminal=json.loads(next((output/'private/build_attempts').glob('*/terminal.json')).read_text())
        assert terminal['status']=='failed' and terminal['all_partial_artifacts_preserved'] is True
    assert state['calls']==expected and state['server_stopped'] is True
    assert json.loads((output/'producer.lock').read_text())['status']=='released'
