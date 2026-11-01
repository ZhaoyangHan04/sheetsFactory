import importlib.util
from pathlib import Path
from types import FunctionType

from openpyxl import load_workbook
import pytest


ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def context(tmp_path,monkeypatch):
    helper=load(ROOT/'tests/test_waterfall_portfolios_tasks.py','_original_waterfall_task_fixture')
    old,p,manifest,actual,sf,binding,expected,cold,fake=helper.prepared.__wrapped__(tmp_path,monkeypatch)
    m=load(ROOT/'scripts/validate_waterfall_portfolios_tasks_revision2.py','_waterfall_boolean_task_revision')
    def activate():m._private['source']=fake;m._private['_ns']['source']=fake;return fake
    monkeypatch.setitem(m._private,'_activate',activate)
    monkeypatch.setitem(m._private,'COUNTS',old.COUNTS)
    monkeypatch.setattr(m,'GIVEN_BOOLEAN_COUNT',2)
    definition=old.read(sf['definition']);definition['FM_mask_points']=binding['FM_mask_points']
    definition['Boolean_General_points']=[p for p,v in expected.items() if v['type']=='boolean']
    source=load(ROOT/'scripts/build_waterfall_portfolios_source_revision3.py','_waterfall_source_boolean_classifier')
    classifier=source.classify_formula_scope
    namespace={**classifier.__globals__,'GIVEN_BOOLEANS':{p:v for p,v in definition['literals'].items() if v['type']=='boolean'}}
    fake.classify_formula_scope=FunctionType(classifier.__code__,namespace,classifier.__name__)
    return m,old,p,manifest,sf,definition,binding,fake


def rewrite(context,changes,name):
    m,old,p,_,sf,_,_,_=context;candidate=old.read(sf['candidate_manifest'])
    wb=load_workbook(candidate['source']['path'])
    for point,value in changes.items():
        sheet,cell=point.rsplit('!',1);wb[sheet][cell]=value
    path=p/(name+'.xlsx');wb.save(path);wb.close();return path


def test_only_prebound_correct_constant_formulas_are_given_not_financial(context):
    m,_,_,_,_,definition,_,_=context
    given=m.given_boolean_points(definition)
    path=rewrite(context,{p:('=TRUE()' if v else '=FALSE()') for p,v in given.items()},'native_given_boolean')
    m.verify_definitions(path,definition)
    assert len(given)==2 and not set(given)&set(definition['formulas'])


def test_source_classifier_preserves_full_and_partial_FM_scope(context):
    m,_,p,manifest,_,definition,_,fake=context
    f=m.read(m.prepare(manifest,p/'partial_scope'))
    path=m.checked(f['planned_inputs']['FM_input']);wb=fake._book(path)
    for point,value in m.given_boolean_points(definition).items():
        sheet,cell=point.rsplit('!',1);wb[sheet][cell]='=TRUE()' if value else '=FALSE()'
    partial=p/'partial_native_given_constants.xlsx';wb.save(partial);wb.close()
    m.verify_definitions(partial,definition,blank=True);wb=fake._book(partial)
    try:
        classified=fake.classify_formula_scope(wb,definition)
        assert len(classified['financial_formulas'])==170
        assert len(classified['provided_boolean_constant_formulas'])==2
        assert classified['physical_formula_count']==172
        assert not set(classified['financial_formulas'])&set(definition['FM_mask_points'])
    finally:wb.close()


@pytest.mark.parametrize('formula',['=TRUE(1)','=FALSE(0)','=TRUE()+0','=1+FALSE()','=NOT(FALSE())','=IF(1,TRUE(),FALSE())'])
def test_args_arithmetic_and_other_functions_rejected_at_given_site(context,formula):
    m,_,_,_,_,definition,_,_=context;point=next(iter(m.given_boolean_points(definition)))
    path=rewrite(context,{point:formula},'hostile_given')
    with pytest.raises(ValueError,match='exact matching'):m.verify_definitions(path,definition)


def test_wrong_constant_and_wrong_cell_reject(context):
    m,_,_,_,_,definition,_,_=context;given=m.given_boolean_points(definition);point=next(iter(given))
    path=rewrite(context,{point:'=FALSE()' if given[point] else '=TRUE()'},'wrong_boolean')
    with pytest.raises(ValueError,match='exact matching'):m.verify_definitions(path,definition)
    path=rewrite(context,{'Read Me!A1':'=TRUE()'},'wrong_cell')
    with pytest.raises(ValueError,match='financial formula'):m.verify_definitions(path,definition)


def test_financial_OR_cannot_be_replaced_by_constant_even_if_same_result(context):
    m,_,_,_,_,definition,_,_=context;point=definition['Boolean_General_points'][0]
    path=rewrite(context,{point:'=TRUE()'},'financial_boolean_not_given')
    with pytest.raises(ValueError,match='financial formula'):m.verify_definitions(path,definition)


def test_exact_given_site_census_and_disjoint_financial_scope(context):
    m,_,_,_,_,definition,_,_=context
    malformed={**definition,'literals':dict(definition['literals'])}
    point=next(iter(m.given_boolean_points(definition)));malformed['literals'].pop(point)
    with pytest.raises(ValueError,match='prebound'):m.given_boolean_points(malformed)


def test_revision_is_distinct_full_old_new_recipe_and_no_actual_calls(context):
    m,old,p,manifest,_,_,_,_=context
    r=m.prepare(manifest,p/'revision2_task');f=m.read(r)
    assert f['kind']==m.KIND=='prepared_waterfall_portfolios_task_engineering_revision2'
    assert m.TERMINAL_KIND=='complete_waterfall_portfolios_task_engineering_revision2'
    assert f['financial_target_count']==510 and f['forecast_mask_count']==340 and f['DBG_formula_root_count']==2
    assert f['actual_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
    assert f['recipe'][str(m.UPSTREAM)]['sha256']==m.UPSTREAM_SHA
    assert str(Path(m.__file__).resolve()) in f['recipe']
    assert m.validate_prepared(p/'revision2_task')==f
    assert m._private['_ns']['_execute_prepared_base'].__code__.co_code==old._ns['_execute_prepared_base'].__code__.co_code


def test_source_revision_remains_fail_closed_until_final_pin():
    m=load(ROOT/'scripts/validate_waterfall_portfolios_tasks_revision2.py','_waterfall_revision_pending_source')
    if m.SOURCE_SHA=='PENDING_SOURCE_REVISION_PIN':
        with pytest.raises(ValueError,match='pinned'):m._private['_activate']()
    else:
        support=m._private['_activate']()
        assert 'revision3' in support.SOURCE_KIND
