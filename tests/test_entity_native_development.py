"""Small cached-value fixtures only; no source admission, LO or model calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_native_entity_development_test',ROOT/'scripts/prepare_entity_native_development.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


def workbook(path,*,new=False,goal=False,mutate=None):
    book=openpyxl.Workbook();book.remove(book.active)
    rules=book.create_sheet('Group Rules');rules['A1']='Rules';rules['B1']='Exact pence and dated policy.'
    contract=book.create_sheet('Group Contract');contract['A1']='Native documentation' if new else 'Complete JSON'
    contract['A2']='Native assumptions' if new else 'JSON part 1';contract['B2']='' if new else '{"cash":90}'
    inputs=book.create_sheet('Group Inputs');inputs['A1']='Business assumptions' if new else 'Public primitive paths'
    inputs['B1']='Values';inputs['A2']='Entity E01 — opening cash' if new else 'entities/0/opening_cash_minor';inputs['B2']=90
    close=book.create_sheet('S01 Close');close['A1']='Accounting owner / period';close['B1']='Minor units'
    close['A2']='Entity E01 — cash close' if new else 'S01/E01/2024-04-01/cash_close';close['B2']=20 if goal else 10
    close['A3']='Entity E01 — flag' if new else 'S01/E01/2024-04-01/flag';close['B3']=0 if goal else False
    close['A4']='Entity E01 — fractional test' if new else 'S01/E01/2024-04-01/fraction';close['B4']=0.002 if goal else 0.001
    close['A5']='Entity E01 — error test' if new else 'S01/E01/2024-04-01/error';close['B5']='#REF!' if goal else '#VALUE!'
    if mutate:mutate(book)
    book.save(path);book.close();return path


def pair(tmp_path):
    return [workbook(tmp_path/(name+'.xlsx'),new=new,goal=goal)
            for name,new,goal in [('old_input',False,False),('old_goal',False,True),('new_input',True,False),('new_goal',True,True)]]


def test_four_way_delta_is_recomputed_with_exact_types_and_subcent_values(tmp_path):
    paths=pair(tmp_path);value=entry.compare_pair_deltas(*paths)
    assert value['passed'] and value['original_D_recomputed_not_assumed']
    assert value['expected_changes']==['S01 Close!B2','S01 Close!B3','S01 Close!B4','S01 Close!B5']
    assert value['expected_change_count']==4 and value['cent_quantization_applied'] is False
    assert value['both_pair_texts_identical'] and value['nonpresentation_values_and_types_exact']
    assert value['financial_calculation_or_recovery_performed'] is False


@pytest.mark.parametrize('side',[2,3])
def test_nonpresentation_numeric_drift_rejected_on_either_side(tmp_path,side):
    paths=pair(tmp_path)
    paths[side]=workbook(tmp_path/'tampered.xlsx',new=True,goal=side==3,mutate=lambda b:setattr(b['S01 Close']['B2'],'value',21))
    with pytest.raises(ValueError,match='nonpresentation'):entry.compare_pair_deltas(*paths)


@pytest.mark.parametrize('side',[0,1,2,3])
def test_presentation_text_must_match_within_both_original_and_new_pairs(tmp_path,side):
    paths=pair(tmp_path)
    paths[side]=workbook(tmp_path/'tampered.xlsx',new=side>=2,goal=side in (1,3),mutate=lambda b:setattr(b['S01 Close']['A2'],'value','Different owner'))
    with pytest.raises(ValueError,match='Presentation text differs'):entry.compare_pair_deltas(*paths)


def test_sheet_order_and_protected_input_type_drift_rejected(tmp_path):
    paths=pair(tmp_path)
    paths[3]=workbook(tmp_path/'order.xlsx',new=True,goal=True,mutate=lambda b:b.move_sheet('S01 Close',offset=-1))
    with pytest.raises(ValueError,match='worksheet'):entry.compare_pair_deltas(*paths)
    paths[3]=workbook(tmp_path/'bool.xlsx',new=True,goal=True,mutate=lambda b:setattr(b['Group Inputs']['B2'],'value',True))
    with pytest.raises(ValueError,match='nonpresentation'):entry.compare_pair_deltas(*paths)


@pytest.mark.parametrize('sheet,cell,expected',[
    ('Group Inputs','A2',True),('Group Inputs','AA2',False),('Group Inputs','B2',False),
    ('Group Contract','B2',True),('Group Contract','B1',False),('Group Contract','C2',False),
    ('S01 Close','A2',True),('S01 Close','A1',False),('S04 Close','A2',False),('Group Rules','B2',False)])
def test_presentation_allowlist_uses_exact_columns_and_sheets(sheet,cell,expected):
    assert entry.presentation_cell(sheet,cell) is expected


def test_instruction_patch_preserves_every_other_byte(tmp_path):
    graph=entry.helper().FrozenFiles();old=tmp_path/'old.md';new=tmp_path/'new.md'
    text='Required scope.\n'+entry.PATCHES[0][0]+'\n'+entry.PATCHES[1][0]+'\nRetain exact whole/remainder and fixed plan.\n'
    old.write_text(text);rendered=text
    for before,after in entry.PATCHES:rendered=rendered.replace(before,after)
    new.write_text(rendered);patch={'original':graph.ref(old),'rendered':graph.ref(new),
        'exact_replacements':[{'before':a,'after':b} for a,b in entry.PATCHES],'all_other_bytes_preserved':True}
    record=tmp_path/'patch.json';record.write_text(json.dumps(patch))
    assert entry.validate_instruction_patch(graph,record,graph.ref(new),{'instruction.md':graph.ref(old)})==graph.ref(record)


def test_instruction_patch_cannot_claim_an_extra_solution_hint_is_only_locator_change(tmp_path):
    graph=entry.helper().FrozenFiles();old=tmp_path/'old.md';new=tmp_path/'new.md'
    original='\n'.join(before for before,_ in entry.PATCHES);old.write_text(original)
    text=original
    for before,after in entry.PATCHES:text=text.replace(before,after)
    new.write_text(text+'\nInspect bank_interest and current_tax first.')
    patch={'original':graph.ref(old),'rendered':graph.ref(new),
        'exact_replacements':[{'before':a,'after':b} for a,b in entry.PATCHES],'all_other_bytes_preserved':True}
    path=tmp_path/'patch.json';path.write_text(json.dumps(patch))
    with pytest.raises(ValueError,match='Additional instruction'):entry.validate_instruction_patch(graph,path,graph.ref(new),{'instruction.md':graph.ref(old)})


def test_history_rejects_same_revision_hash_without_filtering_past_successes(tmp_path):
    graph=entry.helper().FrozenFiles();p=tmp_path/'selection_manifest.json'
    p.write_text(json.dumps({'tasks':[{'task_id':'previous','revision':0,'revision_hash':'same','reward':1}]}))
    with pytest.raises(ValueError,match='resampling'):entry.selection_history('same','new-task',[tmp_path],graph)
    with pytest.raises(ValueError,match='resampling'):entry.selection_history('different','previous',[tmp_path],graph)
    assert len(entry.selection_history('different','new-task',[tmp_path],graph))==1


def transform_fixture():
    source={'path':'original-goal','sha256':'1'*64,'bytes':1};output={'path':'raw-rendered','sha256':'2'*64,'bytes':2}
    actual={'path':'new-goal','sha256':'3'*64,'bytes':3};impl={'path':'adapter','sha256':entry.ADAPTER_SHA,'bytes':4}
    call={'kind':'pinned_native_presentation_transform','role':'goal','status':'passed','timeout_seconds':900,
          'network':'none','calls_LO':0,'calls_model':0,'source':source,'output':output,'implementation':impl,
          'image_id':entry.PINNED_IMAGE_ID,'preservation_audit':'proof','container_before':'before','container_after':'after','worker_runtime':'worker'}
    allowed={'xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml','xl/worksheets/sheet4.xml','xl/worksheets/sheet5.xml','xl/worksheets/sheet6.xml','xl/sharedStrings.xml'}
    proof={'kind':'entity_group_native_business_presentation_static_audit','mode':'native_business_tables',
           'native_public_leaf_count':10620,'explicit_boolean_as_integer_count':24,'source':source,'destination':output,
           'financial_policy':{'sha256':entry.POLICY_SHA},'changed_text_cell_count':1110984,
           'static_reference_proof':{'formula_definitions':1100346,'changed_text_is_unreferenced':True},
           'agent_facing_reconstruction_reader_supplied':False,'allowed_changed_members':sorted(allowed),
           'package_members':{'xl/worksheets/sheet1.xml':{'before_sha256':'same','after_sha256':'same','allowed_text_member_change':False}}}
    proof['package_members'].update({name:{'before_sha256':'old','after_sha256':'new','allowed_text_member_change':True} for name in allowed})
    for key in ('all_native_primitive_values_preserved','all_original_phases_and_rules_preserved',
                'complete_shared_string_usage_inventory_checked','uneditable_cells_and_formulas_and_cached_values_and_styles_preserved'):proof[key]=True
    resources={'Memory':32*1024**3,'NanoCpus':2*10**9,'PidsLimit':256,'NetworkMode':'none','CapAdd':['CAP_DAC_OVERRIDE'],'CapDrop':['ALL']}
    before={'container_id':'f'*64,'image_id':entry.PINNED_IMAGE_ID,'user':'0','resources':resources}
    after={**deepcopy(before),'state':{'ExitCode':0,'OOMKilled':False,'Running':False}}
    compare={'kind':'exact_non_presentation_typed_cached_value_comparison','passed':True,'mismatch_count':0,'mismatches':[],
             'cent_quantization_applied':False,'financial_audit_transfer_claimed':False,'source':source,'output':actual,
             'checked_non_presentation_cells':1111028,'excluded_presentation_text_cells':1110984}
    records={'proof':proof,'before':before,'after':after,'worker':{'status':'passed','duration_seconds':300,'maxrss_KiB':13*1024**2},'comparison':compare}
    class Graph:
        def expected(self,record):return record
        def read(self,key):return records[key]
    return Graph(),call,{'solution/reference.xlsx':source},{'comparison':'comparison','output':actual},records


def test_presentation_receipt_validation_is_not_financial_admission():
    graph,call,inventory,new,records=transform_fixture()
    assert entry.validate_transform(graph,'goal',call,inventory,new)==records['proof']
    assert 'financial_admission' not in records['proof']


@pytest.mark.parametrize('capability',['DAC_OVERRIDE','CAP_DAC_OVERRIDE'])
def test_exact_single_capability_accepts_only_docker_canonical_aliases(capability):
    graph,call,inventory,new,records=transform_fixture()
    for key in ('before','after'):records[key]['resources']['CapAdd']=[capability]
    assert entry.validate_transform(graph,'goal',call,inventory,new)==records['proof']


@pytest.mark.parametrize('damage',[
    lambda c,r:c.update(calls_LO=False),
    lambda c,r:(c.update(image_id='sha256:'+'a'*64),r['before'].update(image_id='sha256:'+'a'*64),r['after'].update(image_id='sha256:'+'a'*64)),
    lambda c,r:r['proof'].update(all_original_phases_and_rules_preserved=False),
    lambda c,r:r['proof']['static_reference_proof'].update(changed_text_is_unreferenced=False),
    lambda c,r:r['proof']['package_members']['xl/worksheets/sheet1.xml'].update(after_sha256='changed'),
    lambda c,r:r['proof']['package_members'].pop('xl/sharedStrings.xml'),
    lambda c,r:r['after']['state'].update(OOMKilled=True),
    lambda c,r:r['after']['state'].update(ExitCode=False),
    lambda c,r:r['before']['resources'].update(Memory=8*1024**3),
    lambda c,r:r['before']['resources'].update(CapAdd=['CAP_DAC_OVERRIDE','CAP_SYS_ADMIN']),
    lambda c,r:r['comparison'].update(excluded_presentation_text_cells=1110985),
    lambda c,r:r['comparison'].update(cent_quantization_applied=True),
    lambda c,r:r['comparison'].update(financial_audit_transfer_claimed=True),
])
def test_incomplete_or_relabelled_actual_prototype_receipts_fail_closed(damage):
    graph,call,inventory,new,records=transform_fixture();damage(call,records)
    with pytest.raises(ValueError):entry.validate_transform(graph,'goal',call,inventory,new)


def test_runner_is_only_a_dormant_frozen_resource_entry_command(tmp_path):
    command=entry.runner_command(tmp_path/'probe.json',tmp_path/'evaluation')
    assert command[1]==str(ROOT/'scripts/evaluate_resource_difficulty.py')
    assert command[command.index('--phase')+1]=='development'
    assert command[command.index('--concurrency')+1]=='1'
    assert command[command.index('--max-infrastructure-retries')+1]=='0'
    assert '--resume-infrastructure' not in command and '--run' not in command
    assert entry.BUDGET['elapsed_guard_seconds']==14400 and entry.BUDGET['tool_budget_seconds']==1800
    assert 'native_public_source_recovery' in entry.PENDING and 'all_12_quality_checks' in entry.PENDING
