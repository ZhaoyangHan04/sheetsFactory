from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook
import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import excel,oracle_a,raw


def module():
    path=Path(__file__).resolve().parents[1]/'scripts/validate_waterfall_portfolios_tasks.py'
    spec=importlib.util.spec_from_file_location('_waterfall_task8_test',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    m=module();public=raw.build_spec(dimension_mode='toy',years=[2026,2027,2028])
    public['funds'][0]['scenarios'][0]['periods'][2]['realization_receipts_pence']=2*public['funds'][0]['commitment_pence']
    candidate_ref=excel.emit(public,tmp_path/'candidate');candidate=m.read(candidate_ref);binding=m.read(candidate['bindings'])
    result=oracle_a.solve(public)
    a_result=m.write(tmp_path/'A.json',result);a_terminal=m.write(tmp_path/'A_receipt.json',{'result':a_result})
    expected={}
    for point,r in binding['financial'].items():
        values=result['rows'][r['row_key']] if 'row_key' in r else result['aggregates'][r['aggregate_key']]
        value=values[r['field']]
        if r['projection']=='ratio2dp':value=Decimal(value['numerator'])/Decimal(value['denominator'])
        elif r['projection']!='bool':value=Decimal(value)*r['sign']/(100 if r['projection']=='GBP' or r.get('unit')=='GBP' else 1)
        if type(value) is bool:expected[point]={'type':'boolean','value':value}
        else:
            posted=value.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            expected[point]={'type':'number','value':'0' if not posted else format(posted.normalize(),'f')}
    original=m.read(candidate['definition'])
    goaldef={'sheetnames':original['sheetnames'],'formulas':original['formulas'],
        'literals':{p:m.base.source.typed(v['value']) for p,v in original['literals'].items()},'noncircular':True}
    definition=m.write(tmp_path/'source_definition.json',goaldef);expected_ref=m.write(tmp_path/'expected.json',expected)
    runtime=m.write(tmp_path/'runtime.json',{'cpus':2})
    sf={'candidate_manifest':candidate_ref,'definition':definition,'expected':expected_ref,'bindings':candidate['bindings'],
        'specification':candidate['specification'],'runtime_profile':runtime,'runtime_profile_value':{'cpus':2},
        'financial_evidence':{'forward_A':a_terminal}}
    sf_ref=m.write(tmp_path/'source_preparation.json',sf)
    actual={'source':candidate['source'],'preparation':sf_ref,'actual_calls':[{'output':candidate['source']}]}
    manifest=m.write(tmp_path/'source_manifest.json',actual);cold=[]
    native=m.base.source
    fake=SimpleNamespace(**vars(native))
    fake.validate_source=lambda value:(cold.append(value) or deepcopy(actual))
    fake.validate_prepared=lambda output:deepcopy(sf)
    fake.recipes=lambda:{str(tmp_path/'source_manifest.json'):manifest}
    def activate():m.source=fake;m._ns['source']=fake;return fake
    monkeypatch.setattr(m,'_activate',activate)
    monkeypatch.setattr(m,'COUNTS',{'financial':510,'forecast':340,'historical':170,'roots':2})
    def forbidden(*args,**kwargs):raise AssertionError('No actual service or engine in task preparation')
    monkeypatch.setattr(m._ns['ThreadCappedResourceLibreOfficeEngine'],'recalculate',forbidden)
    return m,tmp_path,manifest,actual,sf,binding,expected,cold,fake


def test_both_modes_six_physical_plans_before_eight_stages_and_positive_control(prepared):
    m,p,manifest,actual,sf,binding,expected,cold,fake=prepared
    f=m.read(m.prepare(manifest,p/'task'))
    assert cold==[manifest]
    assert f['financial_target_count']==510 and f['forecast_mask_count']==340
    assert f['historical_formula_count']==170 and f['DBG_formula_root_count']==2
    assert f['actual_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
    assert f['required_actual_LO_calls']==8 and f['qualified'] is False
    assert tuple(f['stage_order'])==('FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')
    assert len(f['planned_inputs'])==6 and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
    choice=f['control_root_selection']
    assert choice['declared_index']==1 and choice['preference_paid_pence']>0
    assert choice['root']==binding['DBG_root_edits'][1]
    assert m.validate_prepared(p/'task')==f


def test_FM_retains_historical_formulas_and_DBG_keeps_zero_impact_root(prepared):
    m,p,manifest,_,_,binding,_,_,_=prepared
    f=m.read(m.prepare(manifest,p/'task'));definition=m.read(f['definition']);dbg=m.read(f['DBG_definition'])
    assert len(definition['FM_mask_points'])==340 and len(binding['DBG_root_edits'])==2
    m.verify_definitions(m.checked(f['planned_inputs']['FM_input']),definition,blank=True)
    m.verify_definitions(m.checked(f['planned_inputs']['DBG_input']),dbg)
    assert all(dbg['formulas'][r['sheet']+'!'+r['cell']]==r['after'] for r in binding['DBG_root_edits'])
    original=m.base.source._book(m.checked(f['genuine_goal']));fm=m.base.source._book(m.checked(f['planned_inputs']['FM_input']))
    try:
        remaining={ws.title+'!'+c.coordinate for ws in fm for c in ws._cells.values() if c.data_type=='f'}
        assert len(remaining)==170 and not remaining&set(binding['FM_mask_points'])
        for point in remaining:
            s,c=point.rsplit('!',1);assert fm[s][c].value==original[s][c].value
    finally:original.close();fm.close()


def test_missing_genuine_source_rejects_before_any_plans(prepared):
    m,p,manifest,_,_,_,_,_,fake=prepared
    def reject(value):raise ValueError('genuine cold source rejected')
    fake.validate_source=reject
    with pytest.raises(ValueError,match='genuine cold'):m.prepare(manifest,p/'task')
    assert not (p/'task').exists()


def test_control_choice_cannot_be_changed_to_zero_impact_root(prepared):
    m,p,manifest,_,_,binding,_,_,_=prepared
    f=m.read(m.prepare(manifest,p/'task'))
    f['control_root_selection']['declared_index']=0
    f['control_root_selection']['root']=binding['DBG_root_edits'][0]
    (p/'task/preparation.json').write_text(json.dumps(f))
    with pytest.raises(ValueError,match='control root changed'):m.validate_prepared(p/'task')


def test_complete_scope_and_actual_input_literal_mutations_reject(prepared):
    m,p,manifest,_,_,_,_,_,_=prepared
    f=m.read(m.prepare(manifest,p/'task'));f['forecast_mask_count']-=1
    (p/'task/preparation.json').write_text(json.dumps(f))
    with pytest.raises(ValueError,match='scope'):m.validate_prepared(p/'task')


def test_no_positive_preference_control_rejects_without_filtering_roots(prepared):
    m,p,_,_,sf,binding,_,_,_=prepared
    values=m.read(m.read(sf['financial_evidence']['forward_A'])['result'])
    for row in values['rows'].values():row['preference_paid']=0
    result_ref=m.write(p/'zero_A.json',values);terminal=m.write(p/'zero_forward.json',{'result':result_ref})
    altered=deepcopy(sf);altered['financial_evidence']['forward_A']=terminal
    with pytest.raises(ValueError,match='No declared positive'):m._control_root(altered,binding['DBG_root_edits'])
    assert len(binding['DBG_root_edits'])==2


def test_typed_bool_and_masked_forecast_cache_rules_are_separate(prepared,monkeypatch):
    m,_,_,_,_,_,_,_,_=prepared
    expected={'S!A1':{'type':'boolean','value':True},'S!B1':{'type':'number','value':'2.00'}}
    definition={'FM_mask_points':['S!B1']}
    monkeypatch.setitem(m._ns,'snapshot',lambda *args:{'values':{'S!A1':{'type':'boolean','value':True}}})
    m.verify_input_caches(None,expected,blank=True,definition=definition)
    monkeypatch.setitem(m._ns,'snapshot',lambda *args:{'values':{'S!A1':{'type':'number','value':'1.00'}}})
    with pytest.raises(ValueError,match='wrong type'):m.verify_input_caches(None,expected,blank=True,definition=definition)
    monkeypatch.setitem(m._ns,'snapshot',lambda *args:{'values':{'S!A1':{'type':'boolean','value':False},'S!B1':{'type':'number','value':'-2.00'}}})
    m.verify_input_caches(None,expected,blank=False,definition=definition)


def test_primary_grader_is_unchanged_all_numeric_2dp(tmp_path):
    m=module();files=[]
    for name,target,rate in [('input',None,0.065),('goal',1,0.065),('output',1,0.066)]:
        w=Workbook();w.active['A1']=target;w.active['B1']=rate;p=tmp_path/(name+'.xlsx');w.save(p);w.close();files.append(p)
    assert m._ns['compare_complete'].__code__ is m.base.compare_complete.__code__
    assert m._ns['compare_complete'](*files,{})['reward']==1


def test_original_8stage_resource_cleanup_body_uses_isolated_globals():
    m=module()
    assert m._ns['_execute_prepared_base'].__globals__ is m._ns
    assert m._ns['_validate_completed_base'].__globals__ is m._ns
    assert m._ns['source'] is m.base.source
    assert m._ns['_execute_prepared_base'].__code__ is not m.base.execute_prepared.__code__
    assert m._ns['_stage_source'].__code__ is m.base._stage_source.__code__


def test_cli_never_combines_new_prepare_with_actual_run(tmp_path,monkeypatch):
    m=module()
    monkeypatch.setattr(m,'prepare',lambda *args:(_ for _ in ()).throw(AssertionError('prepare must not run')))
    with pytest.raises(ValueError,match='separate actual'):
        m.main(['--source-manifest',str(tmp_path/'source.json'),'--output',str(tmp_path/'new'),'--run'])


def test_real_revision2_source_helpers_activate_without_admitting_or_running():
    m=module();support=m._activate()
    assert support.SOURCE_KIND=='independently_checked_waterfall_portfolios_cold_source3_revision2'
    assert callable(support._book) and callable(support.formula_signature)
    assert m._ns['source'] is support
    recipe=support.recipes()
    assert recipe[str(m.SOURCE_SCRIPT)]['sha256']==m.SOURCE_SHA


def test_wrong_source_revision_bytes_cannot_activate(monkeypatch):
    m=module();monkeypatch.setattr(m,'SOURCE_SHA','0'*64)
    with pytest.raises(ValueError,match='pinned'):m._activate()
