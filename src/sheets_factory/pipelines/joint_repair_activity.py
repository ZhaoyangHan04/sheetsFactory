"""Explicit joint-workbook repair evidence; no isolated fault claims."""
from __future__ import annotations

from pathlib import Path
import time

import openpyxl
from openpyxl.formula import Tokenizer

from ..checkers.native_error_dependencies import validate_static_reference_syntax
from ..checkers.separated_roots import _cell_definition, _formula_tokens, _names
from ..checkers.shadow_roots import _visibility
from ..task_adapters.lease_family import compare_exact_typed
from ..task_adapters.public_input_priority import canonical, checked, ref, require, sha, write
from ..workbook import compare_workbooks

SETTING = 'joint_repair_activity'
METHOD = 'full_workbook_joint_repair'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'


def validate_physical_edits(goal, candidate, edits):
    """Check all definitions/literals and only the declared physical formulas."""
    before = openpyxl.load_workbook(goal, keep_links=False)
    after = openpyxl.load_workbook(candidate, keep_links=False)
    try:
        require(before.sheetnames == after.sheetnames and before.epoch == after.epoch
                and _names(before) == _names(after) and _visibility(before) == _visibility(after),
                'Joint repair changed workbook structure, dates, names, visibility, merges or filters')
        require(all(getattr(before.calculation,k,None) == getattr(after.calculation,k,None)
                    for k in ('iterate','iterateCount','iterateDelta','fullPrecision','refMode')),
                'Joint repair changed the financial calculation settings')
        expected = {(e['sheet'],e['cell']):e for e in edits}
        require(len(expected) == len(edits), 'Joint repair contains duplicate physical edits')
        for (sheet,cell), edit in expected.items():
            left,right = before[sheet][cell],after[sheet][cell]
            require(left.data_type == right.data_type == 'f' and left.value == edit['before']
                    and isinstance(edit.get('after'),str) and edit['after'].startswith('=')
                    and edit['after'] != edit['before'] and isinstance(right.value,str)
                    and _formula_tokens(right.value) == _formula_tokens(edit['after']),
                    'Joint repair before/after formula assertion differs: '+sheet+'!'+cell)
        unchanged = 0
        for sheet in before:
            other = after[sheet.title]
            for coordinate in set(sheet._cells) | set(other._cells):
                left,right = sheet._cells.get(coordinate),other._cells.get(coordinate)
                if (left is None or left.value is None) and (right is None or right.value is None):
                    continue
                address = (left or right).coordinate
                if (sheet.title,address) in expected:
                    continue
                require(left is not None and right is not None and _cell_definition(left) == _cell_definition(right),
                        'Joint repair changed an unapproved definition or typed literal: '+sheet.title+'!'+address)
                if left.data_type == 'f' and isinstance(left.value,str) and isinstance(right.value,str) and left.value != right.value:
                    whitespace = lambda text:[(index,t.value) for index,t in enumerate(Tokenizer(text).items) if t.type=='WHITE-SPACE']
                    require(whitespace(left.value) == whitespace(right.value),
                            'Joint repair cannot prove non-root formula lexical equivalence')
                unchanged += 1
        return {'physical_formula_mutation_count':len(edits),'all_before_after_assertions_verified':True,
                'all_outside_definitions_and_typed_literals_unchanged':True,'unchanged_definition_count':unchanged,
                'workbook_structure_and_calculation_settings_unchanged':True}
    finally:
        before.close();after.close()


def describe_joint_delta(goal, combined_input, edits, delta):
    actual = compare_workbooks(combined_input,goal,goal)
    declared = delta.get('expected_changes',[])
    require(actual.get('structure_ok') is True and actual.get('expected_change_count',0) > 0
            and isinstance(declared,list) and len(declared) == len(set(declared))
            and set(actual.get('expected_changes',[])) == set(declared)
            and actual['expected_change_count'] == delta.get('expected_change_count'),
            'Joint repair must retain the complete actual workbook changed-value set')
    physical = [e['sheet']+'!'+e['cell'] for e in edits]
    changed = set(actual['expected_changes']);observed = sorted(set(physical)&changed)
    unobservable = sorted(set(physical)-changed)
    errors = [];goal_errors = []
    for path, target in ((combined_input,errors),(goal,goal_errors)):
        book = openpyxl.load_workbook(path,data_only=True,keep_links=False)
        try:
            for sheet in book:
                target.extend({'cell':sheet.title+'!'+c.coordinate,'value':c.value} for c in sheet._cells.values()
                              if c.data_type == 'e')
        finally:
            book.close()
    require(not any(error['cell'] in changed for error in goal_errors), 'A native reference error contaminates the complete required D')
    return {'physical_formula_mutation_count':len(physical),'physical_formula_mutations':physical,
        'physical_edits_in_actual_D_count':len(observed),'physical_edits_in_actual_D':observed,
        'unobservable_physical_edit_count':len(unobservable),'unobservable_physical_edits':unobservable,
        'complete_required_D_count':actual['expected_change_count'],'complete_required_D':actual['expected_changes'],
        'native_input_errors':errors,'native_goal_errors':goal_errors,
        'all_physical_edits_have_individual_activity_claimed':False,
        'individual_or_marginal_activity_claimed':False,'counterfactual_uniqueness_claimed':False,
        'full_counterfactual_convergence_claimed':False,'joint_input_global_uniqueness_claimed':False}


def prove_joint_repair(*,goal,combined_input,raw_mutation,edits,delta,engine,directory):
    """Complete the second actual pass after ordinary Construct made the first."""
    directory = Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    started = time.monotonic();runtime = engine.metadata()
    require(runtime.get('backend') == 'libreoffice_uno_docker' and runtime.get('network') == 'none'
            and runtime.get('image_id') == IMAGE_ID,'Joint repair requires the pinned network-isolated actual runtime')
    certificate = {'version':1,'activity_contract':METHOD,'state':'checking','passed':False,'blocking':True,
        'goal':ref(goal),'combined_input':ref(combined_input),'raw_mutation':ref(raw_mutation),
        'edits_sha256':canonical(edits),'implementation_sha256':sha(__file__),'runtime':runtime,
        'actual_joint_workbook_LO_started_count':1,'actual_joint_workbook_LO_execution_count':1,
        'first_execution':'ordinary Construct raw mutation recalculation',
        'quality_recovery_difficulty_certified':False,'five_local_controls_claimed':False,
        'engine_calls':[{'input':ref(raw_mutation),'output':ref(combined_input),'completed':True}]}
    executing = False
    try:
        validate_physical_edits(goal,raw_mutation,edits)
        certificate['physical_edit_validation'] = validate_physical_edits(goal,combined_input,edits)
        certificate['joint_delta'] = describe_joint_delta(goal,combined_input,edits,delta)
        certificate['actual_joint_workbook_LO_started_count'] += 1;executing = True
        stable = engine.recalculate(combined_input,directory/'actual_joint_pass2.xlsx')
        executing = False;certificate['actual_joint_workbook_LO_execution_count'] += 1
        certificate['engine_calls'].append({'input':ref(combined_input),'output':ref(stable),'completed':True})
        certificate['stable_pass2'] = ref(stable)
        certificate['exact_typed_two_pass_stability'] = compare_exact_typed(combined_input,stable)
        certificate['stable_definitions_validation'] = validate_physical_edits(combined_input,stable,[])
        require(certificate['exact_typed_two_pass_stability'].get('passed') is True,
                'The actual joint input is not exact typed stable across its two executed passes')
        certificate.update(state='verified_joint_workbook_repair',passed=True,blocking=False)
    except Exception as exc:
        certificate.update(state='execution_error' if executing else 'rejected',reason=str(exc),error_type=type(exc).__name__)
    certificate['duration_ms'] = round((time.monotonic()-started)*1000)
    write(directory/'joint_repair_certificate.json',certificate)
    return certificate


def validate_joint_certificate(certificate,goal,combined_input,edits,delta):
    c = certificate
    require(c.get('version') == 1 and c.get('activity_contract') == METHOD
            and c.get('state') == 'verified_joint_workbook_repair' and c.get('passed') is True and c.get('blocking') is False,
            'The joint-workbook repair proof is incomplete')
    require(c.get('quality_recovery_difficulty_certified') is False and c.get('five_local_controls_claimed') is False,
            'Joint construction proof cannot claim the pending controls, recovery, quality or difficulty')
    require(c.get('implementation_sha256') == sha(__file__)
            and checked(c['goal']) == Path(goal).resolve() and checked(c['combined_input']) == Path(combined_input).resolve()
            and c.get('edits_sha256') == canonical(edits),'The joint proof source, input, edits or implementation changed')
    require(type(c.get('actual_joint_workbook_LO_started_count')) is int and c['actual_joint_workbook_LO_started_count'] == 2
            and type(c.get('actual_joint_workbook_LO_execution_count')) is int and c['actual_joint_workbook_LO_execution_count'] == 2,
            'Joint input stability requires two actual whole-workbook executions')
    runtime = c.get('runtime',{})
    require(runtime.get('backend') == 'libreoffice_uno_docker' and runtime.get('network') == 'none'
            and runtime.get('image_id') == IMAGE_ID,'The actual joint runtime differs')
    calls = c.get('engine_calls',[])
    require(len(calls) == 2 and all(call.get('completed') is True for call in calls), 'Joint actual execution chain is incomplete')
    for call in calls:
        checked(call['input']);checked(call['output'])
    require(calls[0]['input'] == c['raw_mutation'] and calls[0]['output'] == c['combined_input']
            and calls[1]['input'] == c['combined_input'] and calls[1]['output'] == c['stable_pass2'],
            'Joint actual execution artifact chain differs')
    require(c.get('physical_edit_validation') == validate_physical_edits(goal,combined_input,edits)
            and c.get('joint_delta') == describe_joint_delta(goal,combined_input,edits,delta),
            'Joint physical mutations or complete D evidence differs')
    validate_physical_edits(goal,checked(c['raw_mutation']),edits)
    stability = compare_exact_typed(combined_input,checked(c['stable_pass2']))
    require(c.get('exact_typed_two_pass_stability') == stability and stability.get('passed') is True
            and c.get('stable_definitions_validation') == validate_physical_edits(combined_input,checked(c['stable_pass2']),[]),
            'Joint exact typed values or definitions are not stable')
    return c['joint_delta']
