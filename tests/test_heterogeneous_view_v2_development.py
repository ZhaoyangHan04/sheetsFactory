"""Versioned development entry tests do not build a production workbook."""
import ast
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


def load(name,file):
    definition=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
    return module


builder=load('unit_heterogeneous_v2_development','prepare_heterogeneous_view_v2_development.py')
previous=load('unit_heterogeneous_v1_development_unchanged','prepare_heterogeneous_view_development.py')


def test_view_adapter_namespaces_and_default_off_policies_are_distinct():
    assert builder.view.ADAPTER_ID=='heterogeneous_business_financial_view_v2'
    assert previous.view.ADAPTER_ID=='heterogeneous_business_financial_view_v1'
    assert builder.view.setting()['enabled'] is previous.view.setting()['enabled'] is False


def test_actual_controls_calculations_and_score_paths_are_identical_to_predecessor():
    parent=ast.parse(builder._TEMPLATE.read_text())
    changed=builder.adapted_ast()
    old={n.name:n for n in parent.body if isinstance(n,ast.FunctionDef)}
    new={n.name:n for n in changed.body if isinstance(n,ast.FunctionDef)}
    permitted={'recipes','prepare','check_preparation','freeze_snapshot'}
    assert old.keys()==new.keys()
    for name in old.keys()-permitted:
        assert ast.dump(old[name])==ast.dump(new[name]),name
    assert builder.CONTROL_REWARDS==previous.CONTROL_REWARDS
    assert builder.BUDGET==previous.BUDGET
    assert builder.PENDING==previous.PENDING


def test_every_parent_and_new_recipe_is_frozen():
    files=builder.recipes()
    expected=[ROOT/'scripts/prepare_heterogeneous_view_development.py',
        ROOT/'scripts/prepare_heterogeneous_view_v2_development.py',
        ROOT/'src/sheets_factory/task_adapters/heterogeneous_financial_view.py',
        ROOT/'src/sheets_factory/task_adapters/heterogeneous_financial_view_v2.py',
        ROOT/'config/task_adapters/heterogeneous_financial_view_v1.json',
        ROOT/'config/task_adapters/heterogeneous_financial_view_v2.json']
    assert all(str(p) in files for p in expected)
    assert files[str(builder._TEMPLATE)]==builder._TEMPLATE_SHA256


def test_predecessor_script_drift_fails_before_any_source_or_engine(monkeypatch):
    monkeypatch.setattr(builder,'_TEMPLATE_SHA256','0'*64)
    with pytest.raises(ValueError,match='predecessor development builder changed'):
        builder.adapted_ast()


def test_v1_preparation_cannot_enter_v2_execute(monkeypatch,tmp_path):
    helper=builder.support()
    monkeypatch.setattr(helper,'read',lambda _: {'kind':'prepared_heterogeneous_business_view_development',
        'recipe':builder.recipes()})
    monkeypatch.setattr(builder,'support',lambda:helper)
    monkeypatch.setattr(builder.view,'validate_source',lambda _:pytest.fail('Old preparation must fail before admission'))
    with pytest.raises(ValueError,match='frozen development recipe changed'):
        builder.check_preparation(tmp_path)


def test_v2_preparation_is_a_separate_version_and_no_model_or_workbook(monkeypatch,tmp_path):
    source=tmp_path/'UNIT-source.json';source.write_text('{}');output=tmp_path/'UNIT-prepared'
    helper=builder.support()
    monkeypatch.setattr(helper,'_output',lambda path,**_:Path(path))
    monkeypatch.setattr(builder,'support',lambda:helper)
    monkeypatch.setattr(builder.view,'validate_source',lambda _:{'UNIT_mock_only':True})
    result=builder.prepare(source,output)
    record=helper.read(result)
    assert record['kind']=='prepared_heterogeneous_business_view_v2_development'
    assert record['model_calls']==record['new_LO_calls']==record['task_count']==0
    assert record['qualified'] is False and not list(output.rglob('*.xlsx'))


def test_cli_retains_explicit_run_requirement(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(builder,'prepare',lambda *a:calls.append('prepare') or {'UNIT':True})
    monkeypatch.setattr(builder,'execute_prepared',lambda *a,**k:pytest.fail('No explicit run'))
    builder.main(['--source-manifest','UNIT-source.json','--output',str(tmp_path/'UNIT')])
    assert calls==['prepare']
