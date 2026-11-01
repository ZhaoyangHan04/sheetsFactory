"""The frozen 41 guards applied only to the new Boolean-fact task8 namespace."""
import ast
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FROZEN_TEST=ROOT/'tests/test_waterfall_portfolios_development.py'
FROZEN_TEST_SHA='9e26e9716f5bcd863cd0141acfab2dc77aefb8e7fc33eca6088db77af5387a51'
ENTRY_V2=ROOT/'scripts/prepare_waterfall_portfolios_development_revision2.py'


def inherited_guard_ast():
    raw=FROZEN_TEST.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FROZEN_TEST_SHA:
        raise ValueError('The frozen first waterfall development guards changed')
    replacements={
        'scripts/prepare_waterfall_portfolios_development.py':'scripts/prepare_waterfall_portfolios_development_revision2.py',
        'scripts/validate_waterfall_portfolios_tasks.py':'scripts/validate_waterfall_portfolios_tasks_revision2.py',
        'complete_waterfall_portfolios_task_engineering':'complete_waterfall_portfolios_task_engineering_revision2',
        'prepared_waterfall_portfolios_task_engineering':'prepared_waterfall_portfolios_task_engineering_revision2',
        'task8 feature must be frozen':'task8 revision2 feature must be frozen',
    }
    counts={key:0 for key in replacements}
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value)is str and node.value in replacements:
                counts[node.value]+=1;node.value=replacements[node.value]
            return node
    tree=Adapt().visit(ast.parse(raw))
    if counts!={key:count for key,count in zip(replacements,(1,2,2,1,1),strict=True)}:
        raise ValueError('The exact test-only revision2 rewiring sites changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_tests={'__file__':str(FROZEN_TEST),'__name__':'_isolated_waterfall_revision2_guard_suite'}
exec(compile(inherited_guard_ast(),str(FROZEN_TEST),'exec'),_tests)
for _name,_value in _tests.items():
    if _name.startswith('test_') or _name=='factory':globals()[_name]=_value


def test_revision2_uses_only_its_strict_task8_namespace_and_both_recipe_ancestors(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    validator=ROOT/'scripts/validate_waterfall_portfolios_tasks_revision2.py'
    assert m._N['VALIDATOR']==validator
    assert m._N['VALIDATOR_SHA']==hashlib.sha256(validator.read_bytes()).hexdigest()
    assert m._checked_engineering.__globals__['TASK_VALIDATOR']==validator
    assert str(ROOT/'scripts/prepare_waterfall_portfolios_development.py') in f['recipe']
    assert str(ENTRY_V2) in f['recipe']
    assert str(ROOT/'scripts/prepare_operating_reports_200_development.py') in f['recipe']
    assert f['model']=='gpt-6.1-sol' and f['reasoning_effort']=='xhigh'


def test_original_task8_kind_cannot_enter_new_wrapper_even_with_complete_counts(factory):
    c=factory();value=c.m.read(c.actual);value['kind']='complete_waterfall_portfolios_task_engineering'
    other=c.m.write(c.root/'TEST_ONLY_old_kind.json',value)
    import pytest
    with pytest.raises(ValueError,match='genuine eight-call'):c.m.prepare(other,c.output)
    assert not c.output.exists()


def test_frozen_old_test_and_production_entries_stay_exact():
    assert hashlib.sha256(FROZEN_TEST.read_bytes()).hexdigest()==FROZEN_TEST_SHA
    assert hashlib.sha256((ROOT/'scripts/prepare_waterfall_portfolios_development.py').read_bytes()).hexdigest()==(
        'fe6ef34ad73178a162e943dedffb6c64f935cc52d6218004c794ddcb3146935c')
