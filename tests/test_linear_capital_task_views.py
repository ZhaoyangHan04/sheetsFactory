"""Tiny view scope, deterministic fault definitions and honest pending gates."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.linear_capital_portfolio import excel, task_views
from sheets_factory.workbook.linear_capital_portfolio.spec import canonical_sha256

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('linear_task_view_public_inputs',ROOT/'tests/test_linear_capital_portfolio_ledger.py')
inputs=importlib.util.module_from_spec(loader);loader.loader.exec_module(inputs)


def source(tmp_path,*,years=5,scenarios=3):
    public=inputs.fixture(projects=2,years=years,scenarios=scenarios)
    public['projects'][1]['debt_policy']='BULLET'
    path=tmp_path/'source.xlsx';binding=excel.emit_workbook(path,public,plan={'P001':1,'P002':0})
    return public,path,binding


def cells(path):
    book=openpyxl.load_workbook(path,data_only=False)
    result={(sheet.title,c.coordinate):c.value for sheet in book for row in sheet for c in row if c.value is not None}
    names=book.sheetnames;book.close();return names,result


def coord(row):return row['sheet'],row['cell']


def assert_provided(plan,current):
    for r in plan['provided_cells']:
        assert type(current[coord(r)]) is type(r['value']) and current[coord(r)]==r['value']


def test_FM_masks_all_financial_identity_zeroes_aliases_formulas_flags_FIFO_and_choices(tmp_path):
    public,path,binding=source(tmp_path);original=path.read_bytes();_,before=cells(path)
    plan=task_views.plan_task_view(path,public,binding,mode='financial_modeling')
    target={coord(r) for r in plan['masked_targets']}
    assert target==set.union(*(set(coord(r) for r in binding[name]) for name in
        ('financial_bindings','arithmetic_bindings','decision_bindings')))
    financial_zero=[r for r in binding['financial_bindings'] if r['formula'] is None and r['expression']==0]
    aliases=[r for r in binding['financial_bindings'] if r['semantic_role']['schedule']=='portfolio_candidate_alias']
    assert financial_zero and aliases
    assert all(coord(r) in target for r in financial_zero+aliases)
    manifest=task_views.materialize_view(plan,tmp_path/'FM')
    names,after=cells(manifest['input']['path'])
    assert names==binding['sheetnames'] and set(before)-set(after)==target
    assert_provided(plan,after)
    assert all(not (type(v) is str and v.startswith('=')) for v in after.values())
    assert Path(manifest['goal']['path']).read_bytes()==original==path.read_bytes()
    assert manifest['family_inputs']=={} and manifest['temporary_plan_only'] is None
    # Financial assumptions that happen to be0 are still supplied primitives.
    zero_inputs=[r for r in plan['provided_cells'] if type(r['value']) is int and r['value']==0]
    assert zero_inputs and all(after[coord(r)]==0 for r in zero_inputs)


def test_DBG_primary_faults_and_family_variants_share_the_same_complete_zero_plan(tmp_path):
    public,path,binding=source(tmp_path);_,before=cells(path)
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    assert plan['temporary_plan']=={'P001':0,'P002':0}
    assert set(plan['family_physical_edit_counts'])==set(task_views.FAMILIES)
    assert all(n>0 for n in plan['family_physical_edit_counts'].values())
    manifest=task_views.materialize_view(plan,tmp_path/'DBG')
    _,base=cells(manifest['temporary_plan_only']['path'])
    _,joint=cells(manifest['input']['path'])
    edits={coord(r):r for r in plan['formula_edits']}
    for row in plan['choice_edits']:
        assert base[coord(row)]==joint[coord(row)]==0
    for family,reference in manifest['family_inputs'].items():
        _,variant=cells(reference['path']);assert_provided(plan,variant)
        changed={key for key in set(base)|set(variant) if base.get(key)!=variant.get(key)}
        expected={key for key,row in edits.items() if row['family']==family}
        assert changed==expected
        assert all(variant[key]==edits[key]['after'] for key in expected)
        assert all(variant[coord(r)]==0 for r in plan['choice_edits'])
    assert {key for key in joint if joint[key]!=base.get(key)}==set(edits)
    assert all(edits[key]['semantic_role']['schedule'] in ('annual','tax_vintages') for key in edits)
    assert_provided(plan,joint)
    assert Path(manifest['goal']['path']).read_bytes()==path.read_bytes()
    assert set(manifest['family_inputs'])==set(task_views.FAMILIES)


def test_three_fault_definitions_change_the_real_primary_contract_nodes(tmp_path):
    public,path,binding=source(tmp_path)
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    rows={coord(r):r for r in binding['financial_bindings']}
    for edit in plan['formula_edits']:
        row=rows[coord(edit)];path=row['expected_path'];role=row['semantic_role']
        if edit['family']=='closing_debt_interest':
            assert role['field']=='bank_interest' and role['schedule']=='annual'
            year=path[5]+1;pid=path[1];sid=path[3]
            closing=next(r for r in binding['financial_bindings'] if r['expected_path']==['projects',pid,'scenarios',sid,'annual',year-1,'debt_close'])
            opening=next(r for r in binding['financial_bindings'] if r['expected_path']==['projects',pid,'scenarios',sid,'annual',year-1,'debt_open'])
            assert task_views._point(closing) in edit['after'] and task_views._point(opening) not in edit['after']
        elif edit['family']=='scenario_base_feedback':
            assert role['field']=='revenue_base'
            previous=next(r for r in binding['financial_bindings'] if r['expected_path']==path[:5]+[path[5]-1,'revenue'])
            assert task_views._point(previous) in edit['after']
        else:
            assert row['vintage_year']-row['origin_year']==3
            if row['vintage_field']=='expired':
                assert edit['before_kind']=='financial_identity_literal_zero' and edit['before']==0
                assert edit['after'].startswith("='")
            else:assert edit['after']=='=0'
    assert any(e['before_kind']=='financial_identity_literal_zero' for e in plan['formula_edits'])
    assert all(e['individual_activity_claimed'] is False for e in plan['formula_edits'])


def test_selectors_do_not_use_cached_activity_and_zero_eligible_family_is_retained(tmp_path):
    public,path,binding=source(tmp_path,years=3,scenarios=1)
    # No last-valid FY4 vintage exists. The policy remains declared with0 edits;
    # the implementation must not seek an alternative observed-active root.
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    assert plan['family_physical_edit_counts']['early_loss_expiry']==0
    assert 'no observed activity' in plan['family_selection_policy']['basis']
    assert plan['actual_family_effects_verified'] is False


def test_public_inventory_and_short_instructions_never_export_private_faults_or_source_goal(tmp_path):
    public,path,binding=source(tmp_path)
    for mode in ('financial_modeling','debugging'):
        plan=task_views.plan_task_view(path,public,binding,mode=mode)
        out=tmp_path/mode;manifest=task_views.materialize_view(plan,out)
        assert {p.name for p in (out/'public').iterdir()}=={'input.xlsx','instruction.md'}
        text=(out/'public/instruction.md').read_text()
        assert text==plan['instruction'] and len(text)<1000
        for word in ['preserve','worksheet order','helper','standalone','GBP pence','/app/output.xlsx']:
            assert word.lower() in text.lower()
        for private in ['closing_debt_interest','early_loss_expiry','scenario_base_feedback','expected_path','winner','ROUND(','SUMPRODUCT(']:
            assert private not in text
        assert not any(e['cell'] in text for e in plan['formula_edits'])
        assert manifest['actual_family_effects_verified'] is False
        assert manifest['actual_joint_full_D_verified'] is False
        assert manifest['actual_input_stability_verified'] is False
        assert manifest['actual_controls_verified'] is False
        assert manifest['source_financial_admission_claimed'] is False
        assert manifest['quality_recovery_Harbor_difficulty_certified'] is False
        assert manifest['new_financial_forwards_optimizer_LO_models']==0


def test_source_binding_uses_exact_narrow_LO_formula_token_identity(tmp_path):
    public,path,binding=source(tmp_path)
    row=next(r for r in binding['financial_bindings'] if r['semantic_role']['schedule']=='annual' and r['semantic_role']['field']=='bank_interest')
    book=openpyxl.load_workbook(path);cell=book[row['sheet']][row['cell']]
    cell.value=cell.value.replace("'Projects'!",'Projects!').replace('10000','1E4')
    book.save(path);book.close()
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    assert plan['formula_edits'] and plan['source']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('change',['operator','primitive','missing_formula','extra_cell','financial_input_overlap','unbound_alias'])
def test_wrong_source_definition_scope_or_provided_primitive_fails_closed(tmp_path,change):
    public,path,binding=source(tmp_path,scenarios=1)
    if change in ('operator','primitive','missing_formula','extra_cell'):
        book=openpyxl.load_workbook(path)
        if change=='operator':
            row=next(r for r in binding['financial_bindings'] if r['formula'] and r['semantic_role']['field']=='bank_interest')
            book[row['sheet']][row['cell']]=row['formula'].replace('*','+',1)
        elif change=='primitive':
            row=next(r for r in binding['input_bindings'] if r['path']==['projects',0,'asset_cost_pence']);book[row['sheet']][row['cell']]=1001
        elif change=='missing_formula':
            row=binding['arithmetic_bindings'][0];book[row['sheet']][row['cell']]=None
        else:book['Portfolio']['A500']='Unauthorised extra helper'
        book.save(path);book.close()
    elif change=='financial_input_overlap':binding['financial_bindings'].append(deepcopy(binding['input_bindings'][0]))
    else:
        row=next(r for r in binding['financial_bindings'] if r['semantic_role']['schedule']=='portfolio_candidate_alias')
        binding['financial_bindings'].remove(row)
    with pytest.raises(ValueError):task_views.plan_task_view(path,public,binding,mode='financial_modeling')


def test_temporary_choice_is_complete_typed_and_only_accepted_in_DBG(tmp_path):
    public,path,binding=source(tmp_path)
    for plan in ({'P001':0},{'P001':True,'P002':0},{'P001':2,'P002':0}):
        with pytest.raises(ValueError):task_views.plan_task_view(path,public,binding,mode='debugging',temporary_plan=plan)
    with pytest.raises(ValueError):task_views.plan_task_view(path,public,binding,mode='financial_modeling',temporary_plan={'P001':0,'P002':0})
    custom=task_views.plan_task_view(path,public,binding,mode='debugging',temporary_plan={'P001':0,'P002':1})
    task_views.materialize_variant(custom,tmp_path/'custom.xlsx')
    _,actual=cells(tmp_path/'custom.xlsx')
    assert all(actual[coord(r)]==r['after'] for r in custom['choice_edits'])


def test_plan_source_and_recipe_changes_never_overwrite_artifacts(tmp_path):
    public,path,binding=source(tmp_path)
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    bad=deepcopy(plan);bad['formula_edits'][0]['after']='=1'
    with pytest.raises(ValueError,match='plan changed'):task_views.materialize_view(bad,tmp_path/'changed')
    assert not (tmp_path/'changed').exists()
    target=tmp_path/'existing.xlsx';target.write_bytes(b'preserved')
    with pytest.raises(ValueError,match='Preserve'):task_views.materialize_variant(plan,target)
    assert target.read_bytes()==b'preserved'
    with pytest.raises(ValueError):task_views.materialize_variant(plan,tmp_path/'unknown.xlsx',families=('not-a-family',))
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='source workbook changed'):task_views.materialize_view(plan,tmp_path/'source_changed')
    assert not (tmp_path/'source_changed').exists()


def test_plan_is_roundtrippable_and_source_with_blank_choices_is_rejected(tmp_path):
    public,path,binding=source(tmp_path)
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    plain=json.loads(json.dumps(plan));assert plain==plan
    task_views.materialize_variant(plain,tmp_path/'roundtrip.xlsx',families=task_views.FAMILIES)
    empty=tmp_path/'empty_source.xlsx';blank=excel.emit_workbook(empty,public)
    with pytest.raises(ValueError,match='explicit private plan'):task_views.plan_task_view(empty,public,blank,mode='financial_modeling')


def test_provided_guard_still_rejects_rehashed_plan_attempt_to_edit_raw_zero(tmp_path):
    public,path,binding=source(tmp_path)
    plan=task_views.plan_task_view(path,public,binding,mode='debugging')
    target=next(r for r in plan['provided_cells'] if type(r['value']) is int and r['value']==0)
    plan['formula_edits'].append({'family':task_views.FAMILIES[0],**{k:target[k] for k in ['sheet','cell']},'before':0,'after':'=1'})
    plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'})
    with pytest.raises(ValueError,match='provided input or label'):task_views.materialize_variant(plan,tmp_path/'forbidden.xlsx',families=(task_views.FAMILIES[0],))
    assert not (tmp_path/'forbidden.xlsx').exists()
