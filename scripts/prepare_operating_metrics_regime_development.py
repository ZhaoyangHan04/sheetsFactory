#!/usr/bin/env python3
"""Freeze the two first operating-report attempts under prospective clock v5."""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

_ROOT=_Path(__file__).resolve().parents[1]
_BASE=_ROOT/'scripts/prepare_period_boundary_development.py'
_BASE_SHA='44d87bf6fb55fde4a1b29a444ad32d472b7ebe3d7ba8379ce2395bdbf9301c2d'
_VALIDATOR=_ROOT/'scripts/validate_operating_metrics_regime_tasks.py'
_VALIDATOR_SHA='7fd898cc54d77c8e291887fb53e109bb7345c7a5b8fa48487e7062e45ec0da5c'
_RUNNER_SHA='8cba897fd4375461b9e2237a0eeb699c4629fdb4937c4363d7dc08e7ac17d8e5'


def _adapted_ast():
    if _hashlib.sha256(_BASE.read_bytes()).hexdigest()!=_BASE_SHA:
        raise ValueError('The frozen two-mode first-attempt lifecycle changed')
    tree=_ast.parse(_BASE.read_bytes());counts={}
    def mark(name):counts[name]=counts.get(name,0)+1
    replacements={
        'prequality_synthetic_period_boundary_development_pair':'prequality_synthetic_operating_metrics_regime_development_pair_v5',
        'synthetic_period_boundary_financial_portfolio':'synthetic_operating_metrics_regime_portfolio',
        'synthetic_period_boundary_prequality_development_source':'synthetic_operating_metrics_regime_prequality_development_source_v5',
        'prequality_period_boundary_native_first_attempt_terminal':'prequality_operating_metrics_regime_native_first_attempt_terminal_v5',
        'period_boundary_permanent_material_first_attempt_reservation':'operating_metrics_regime_permanent_material_first_attempt_reservation_v5',
        'period-boundary-':'operating-metrics-regime-','source_specification':'specification','candidate_manifest':'candidate_preparation'}
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.workbook.period_boundary_portfolio.spec':mark('remove_old_brief');return None
            if node.module=='sheets_factory.evaluation' and [(n.name,n.asname) for n in node.names]==[('native_transport_frontier','runner')]:
                node.names[0].name='linear_capital_scaled_frontier_v5';mark('strict_runner')
            return node
        def visit_FunctionDef(self,node):
            if node.name in ('recipes','_checked_engineering','_instruction'):mark('replace_'+node.name);return None
            return self.generic_visit(node)
        def visit_If(self,node):
            if _ast.unparse(node.test)=="__name__ == '__main__'":mark('remove_main_call');return None
            return self.generic_visit(node)
        def visit_Assign(self,node):
            names=[_ast.unparse(t) for t in node.targets]
            if names==['VALIDATOR']:node.value=_ast.Name('_VALIDATOR',_ast.Load());mark('validator_path')
            elif names==['VALIDATOR_SHA']:node.value=_ast.Name('_VALIDATOR_SHA',_ast.Load());mark('validator_sha')
            return self.generic_visit(node)
        def visit_Attribute(self,node):
            if isinstance(node.value,_ast.Name) and node.value.id=='runner':
                if node.attr=='POLICY_V3':node.attr='POLICY_V5';mark('policy_v5')
                elif node.attr=='_persist_failure':mark('private_failure_alias');return _ast.Name('_persist_failure',_ast.Load())
            return self.generic_visit(node)
        def visit_Dict(self,node):
            for key,value in zip(node.keys,node.values):
                if isinstance(key,_ast.Constant) and key.value=='tool_time_policy_version':
                    if not isinstance(value,_ast.Constant) or value.value!=3:raise ValueError('Unexpected inherited clock version')
                    value.value=5;mark('clock_version')
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in replacements:mark('string:'+node.value);node.value=replacements[node.value]
            return node
    tree=Adapt().visit(tree)
    expected={'remove_old_brief':1,'strict_runner':1,'replace_recipes':1,'replace__checked_engineering':1,
        'replace__instruction':1,'remove_main_call':1,'validator_path':1,'validator_sha':1,
        'policy_v5':1,'private_failure_alias':2,'clock_version':1,
        **{'string:'+k:n for k,n in zip(replacements,(1,2,2,1,1,1,2,2),strict=True)}}
    if counts!=expected:raise ValueError('The exact isolated family adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(_adapted_ast(),__file__,'exec'),globals())
_base_validate_prepared=validate_prepared
_persist_failure=runner._namespace['_persist_failure']


def _checked_engineering(value):
    driver=validation_driver();actual=driver.validate_completed(value)
    require(actual['kind']=='complete_operating_metrics_regime_task_engineering' and actual['version']==1
        and actual['passed'] is True and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==8
        and actual['qualified'] is False and actual['normal_all12_QA_passed'] is False,
        'Require genuine complete eight-call engineering for this family')
    prepared=read(actual['preparation']);candidate=read(prepared['candidate_preparation'])
    require(prepared['kind']=='prepared_operating_metrics_regime_task_engineering' and prepared['version']==1
        and prepared['source_manifest']==actual['source_manifest'] and prepared['financial_target_count']==1368
        and prepared['independent_business_field_count']==2052 and prepared['DBG_formula_root_count']==4
        and set(actual['records']['modes'])==set(MODES)
        and candidate['kind']=='prepared_unverified_operating_metrics_regime_pair' and candidate['version']==1
        and candidate['source_type']=='new_synthetic' and candidate['official_workbook_seed_used'] is False
        and candidate['formula_count']==1967 and candidate['dimensions']=={'entities':4,'quarters':12,'years':[2025,2026,2027],'layouts':2,'money_units':2,'sales_bases':2},
        'Keep the complete four-business, crossed-reporting-regime material')
    for mode in MODES:
        material=actual['records']['modes'][mode]
        require(material['goal']==prepared['genuine_goal'] and material['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
            and checked(material['instruction']).read_bytes()==checked(candidate['views'][mode]['instruction']).read_bytes()
            and type(material['complete_D_count']) is int and material['complete_D_count']>0
            and (mode!='financial_modeling' or material['complete_D_count']==1368),
            'Bind genuine source3, original instruction, full actual D and five actual controls')
    return actual,{**candidate,'instructions':{mode:candidate['views'][mode]['instruction'] for mode in MODES}}


def _instruction(candidate,mode):
    original=checked(candidate['views'][mode]['instruction']).read_bytes()
    require(original and len(original.split())<80 and b'Read Me' in original,'Keep the original short business request')
    appendix=b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
    return original,original+appendix


def recipes():
    from sheets_factory.evaluation import clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier
    from sheets_factory.evaluation import native_transport_frontier,native_transport_frontier_v4,clock_resource_frontier_v4,tool_time_clock_bounds_v4
    from sheets_factory.evaluation import linear_capital_scaled_frontier_v4,tool_time_clock_bounds_v5
    from sheets_factory.evaluation import resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier
    require(ref(runner.__file__)['sha256']==_RUNNER_SHA,'Freeze the new prospective v5 runner')
    runner.verify_dependencies();runner.adapted_ast();h=history_helper();driver=validation_driver()
    paths=[Path(__file__),_BASE,HISTORY,h.SHARED,ROOT/'scripts/prepare_linear_capital_development.py',PROFILE,runner.PROFILE_PATH,
        *[Path(m.__file__) for m in (runner,clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier,
            native_transport_frontier,native_transport_frontier_v4,clock_resource_frontier_v4,tool_time_clock_bounds_v4,
            linear_capital_scaled_frontier_v4,tool_time_clock_bounds_v5,resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier)]]
    return {**driver.recipes(),**{str(p.resolve()):ref(p) for p in paths}}


def validate_prepared(prepared):
    frozen=_base_validate_prepared(prepared)
    for mode in MODES:
        source=read(frozen['modes'][mode]['source_view'])
        require(source['tool_time_policy_version']==5 and source['tool_time_policy']==dict(runner.POLICY_V5),
            'Freeze prospective strict cumulative v5 before either first attempt')
    return frozen


if __name__=='__main__':raise SystemExit(main())
