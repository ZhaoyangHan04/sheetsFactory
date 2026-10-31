"""Categorical-policy partial compilation of private expression bindings.

No workbook, specification, journal, cache or output values are arguments.
Only the three provided text categories may supply specialization facts. Other
primitive records are copied/hashed opaquely, never evaluated financially.
This is structural compilation, not financial equivalence or source admission.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .excel import REF, expression_formula

POLICIES = {
 ('loans','type'):frozenset({'BULLET_MONTHLY','LEVEL_PRINCIPAL_MONTHLY','BULLET_QUARTERLY_ACCRUAL'}),
 ('entities','tax_policy'):frozenset({'ACCRUAL_MONTHLY','CASH_COUPON_QUARTERLY'}),
 ('entities','dscr_policy'):frozenset({'MONTHLY_CURRENT','QUARTERLY_LAGGED'}),
}
TEXTS=frozenset().union(*POLICIES.values())
BOOL_OPS=frozenset({'eq','lt','le','ge','and','or'})


def _require(condition,message):
    if not condition:raise ValueError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _reference(row):
    import re
    match=re.fullmatch(r'([A-Z]+)([1-9][0-9]*)',row['cell'])
    _require(match is not None,'A single physical A1 address is required')
    return "'"+row['sheet'].replace("'","''")+"'!$"+match[1]+'$'+match[2]


def _tree(value):
    return [_tree(x) for x in value] if isinstance(value,(tuple,list)) else value


def _refs(expression):
    stack=[expression];result=set()
    while stack:
        node=stack.pop()
        if isinstance(node,(list,tuple)):stack.extend(node)
        elif isinstance(node,str) and REF.fullmatch(node):result.add(node)
    return result


@dataclass(frozen=True)
class _Fact:
    value:object
    kind:str
    origins:frozenset


def _boolean(expression,facts):
    if type(expression) is int:return expression in (0,1)
    if type(expression) is bool:return True
    if isinstance(expression,str):return expression in facts and facts[expression].kind=='boolean'
    if not isinstance(expression,(list,tuple)) or not expression:return False
    if expression[0] in BOOL_OPS:return True
    return expression[0]=='if' and len(expression)==4 and _boolean(expression[2],facts) and _boolean(expression[3],facts)


def _reduce(expression,facts):
    """Only text-policy comparisons and Boolean policy facts are interpreted."""
    if isinstance(expression,str):
        return expression,facts.get(expression) or (_Fact(expression,'text_literal',frozenset()) if expression in TEXTS else None),frozenset()
    if type(expression) in (int,bool):
        fact=_Fact(bool(expression),'boolean_literal',frozenset()) if expression in (0,1) else None
        return expression,fact,frozenset()
    _require(isinstance(expression,(tuple,list)) and expression,'An expression AST is required')
    op,*args=expression
    reduced=[_reduce(arg,facts) for arg in args]
    values=[item[0] for item in reduced];known=[item[1] for item in reduced]
    used=frozenset().union(*(item[2] for item in reduced))
    result=[op,*values];fact=None
    if op=='eq' and len(args)==2 and all(known):
        provenance=known[0].origins|known[1].origins
        left,right=known
        comparable=({left.kind,right.kind}<={'policy_text','text_literal'} or
                    {left.kind,right.kind}<={'boolean','boolean_literal'})
        if provenance and comparable:
            answer=left.value==right.value
            return int(answer),_Fact(answer,'boolean',provenance),used|provenance
    elif op in {'and','or'}:
        booleans=[k for k in known if k is not None and k.kind in {'boolean','boolean_literal'}]
        provenance=frozenset().union(*(k.origins for k in booleans))
        decisive=any(k.value==(op=='or') for k in booleans)
        if provenance and decisive:
            answer=op=='or'
            return int(answer),_Fact(answer,'boolean',provenance),used|provenance
        remaining=[(v,k) for v,k in zip(values,known) if not (k is not None and k.kind=='boolean' and k.origins and k.value==(op=='and'))]
        dropped=frozenset().union(*(k.origins for k in booleans if k.origins and k.value==(op=='and')))
        if dropped:
            used|=dropped
            if not remaining:
                answer=op=='and'
                return int(answer),_Fact(answer,'boolean',dropped),used
            if len(remaining)==1:return remaining[0][0],remaining[0][1],used
            result=[op,*[v for v,_ in remaining]]
    elif op=='if' and len(args)==3:
        condition=known[0]
        if condition is not None and condition.kind in {'boolean','boolean_literal'} and condition.origins:
            index=1 if condition.value else 2
            chosen=known[index]
            if chosen is not None and _boolean(expression,facts):
                fact=_Fact(chosen.value,'boolean',condition.origins|chosen.origins)
            elif chosen is not None and chosen.kind in {'policy_text','text_literal'}:
                fact=_Fact(chosen.value,'policy_text',condition.origins|chosen.origins)
            return values[index],fact,used|condition.origins
    # No numeric operation, date join, comparison of amounts, or unknown-state
    # IF (even identical arms) is evaluated by this compiler.
    return result,fact,used


def _graph(rows,available):
    byref={};locations=set()
    for row in rows:
        location=(row['sheet'],row['cell']);ref=_reference(row)
        _require(location not in locations and ref not in available and ref not in byref,'Duplicate physical formula/input/literal cell')
        locations.add(location);byref[ref]=row
        _require(row['formula']=='='+expression_formula(row['expression']),'Physical formula differs from its expression')
    dependencies={ref:_refs(row['expression']) for ref,row in byref.items()}
    universe=set(byref)|available
    _require(all(refs<=universe for refs in dependencies.values()),'An expression reference is not closed over physical bindings')
    return byref,dependencies


def _order(byref,dependencies):
    degree={ref:len(refs&byref.keys()) for ref,refs in dependencies.items()};reverse={ref:[] for ref in byref}
    for ref,refs in dependencies.items():
        for parent in refs&byref.keys():reverse[parent].append(ref)
    ready=deque(ref for ref in byref if degree[ref]==0);result=[]
    while ready:
        ref=ready.popleft();result.append(ref)
        for child in reverse[ref]:
            degree[child]-=1
            if degree[child]==0:ready.append(child)
    _require(len(result)==len(byref),'The physical expression graph contains a cycle')
    return result


def _identity(row):
    return {key:deepcopy(value) for key,value in row.items() if key not in {'expression','formula'}}


def specialize_bindings(bindings,*,enabled=False):
    """Return NEW private bindings/report; never alter the caller's bindings.

    All financial physical aliases are roots, including flags, nullable values,
    sparse-vintage rows and internal totals. Unresolved state conditions remain.
    A future builder must materialize only retained definitions into a fresh
    workbook, then obtain a new independent audit and three actual LO passes.
    """
    _require(type(enabled) is bool and enabled,'Policy specialization requires explicit opt-in')
    _require(type(bindings.get('binding_version')) is int and bindings['binding_version']==1,'Unsupported bindings schema')
    rows=bindings['arithmetic_bindings'];inputs=bindings['input_bindings'];literals=bindings['literal_bindings'];financial=bindings['financial_bindings']
    _require(type(bindings.get('formula_count')) is int and bindings['formula_count']==len(rows),'The complete physical formula count differs')
    available={};input_paths=set();facts={};seeds=[]
    for row in inputs:
        ref=_reference(row);path=tuple(row['path'])
        _require(ref not in available and path not in input_paths,'Duplicate native input cell/path')
        available[ref]=row;input_paths.add(path)
        category=(path[0],path[2]) if len(path)==3 and type(path[1]) is int else None
        if category in POLICIES:
            value=row.get('stored_value')
            _require(row.get('kind')=='text' and type(row.get('worksheet_scale')) is int and row['worksheet_scale']==1 and type(value) is str and value in POLICIES[category],
                'A specialization seed must be an exact provided policy text')
            fact=_Fact(value,'policy_text',frozenset({path}));facts[ref]=fact
            seeds.append({'path':list(path),'sheet':row['sheet'],'cell':row['cell'],'provided_text':value})
    _require(seeds,'No permitted provided policy categories are available')
    for row in literals:
        ref=_reference(row)
        _require(ref not in available,'Native literals overlap another physical input/literal')
        available[ref]=row
    byref,dependencies=_graph(rows,set(available));order=_order(byref,dependencies)
    roots=set();financial_identity=[];financial_kinds={}
    for row in financial:
        ref=_reference(row)
        _require(ref in byref and row['formula']==byref[ref]['formula'] and _tree(row['expression'])==_tree(byref[ref]['expression']),
            'A financial binding differs from its physical arithmetic definition')
        _require(ref not in roots,'Duplicate financial physical alias')
        roots.add(ref);financial_identity.append(_identity(row));financial_kinds[ref]=row['kind']
    _require(roots,'Complete financial roots are required')
    transformed={};changes=[]
    for ref in order:
        row=byref[ref];expression,fact,used=_reduce(row['expression'],facts)
        if fact is not None:
            kind=financial_kinds.get(ref)
            allowed=(fact.kind=='policy_text' and (kind is None or kind=='text')) or (
                fact.kind=='boolean' and (kind in {'flag','nullable_flag'} or kind is None and _boolean(row['expression'],facts)))
            if allowed:facts[ref]=fact
        changed=deepcopy(row);changed['expression']=expression;changed['formula']='='+expression_formula(expression)
        transformed[ref]=changed
        if _tree(expression)!=_tree(row['expression']):
            _require(used,'An AST changed without a permitted policy justification')
            changes.append({'sheet':row['sheet'],'cell':row['cell'],'before_expression_sha256':canonical(row['expression']),
                'after_expression_sha256':canonical(expression),'provided_policy_paths':[list(path) for path in sorted(used)]})
    new_dependencies={ref:_refs(row['expression']) for ref,row in transformed.items()}
    retained=set(roots);stack=list(roots)
    while stack:
        ref=stack.pop()
        for parent in new_dependencies[ref]&transformed.keys():
            if parent not in retained:retained.add(parent);stack.append(parent)
    removed=set(byref)-retained
    referenced_literals=set().union(*(new_dependencies[ref]&available.keys() for ref in retained))
    dead_label_cells={(byref[ref]['sheet'],'A'+byref[ref]['cell'][1:]) for ref in removed if byref[ref]['cell'].startswith('B')}
    new_literals=[deepcopy(row) for row in literals if (row['sheet'],row['cell']) not in dead_label_cells or _reference(row) in referenced_literals]
    result=deepcopy(bindings)
    result['arithmetic_bindings']=[transformed[_reference(row)] for row in rows if _reference(row) in retained]
    result['financial_bindings']=[{**deepcopy(row),'expression':deepcopy(transformed[_reference(row)]['expression']),
        'formula':transformed[_reference(row)]['formula']} for row in financial]
    result['literal_bindings']=new_literals;result['formula_count']=len(retained)
    new_available={_reference(row) for row in result['input_bindings']+new_literals}
    final_graph,final_dependencies=_graph(result['arithmetic_bindings'],new_available)
    _order(final_graph,final_dependencies)
    _require([_identity(row) for row in result['financial_bindings']]==financial_identity,'A financial identity, owner, type or unit changed')
    _require(result['input_bindings']==inputs,'A native primitive changed')
    _require(set(final_graph)==retained and roots<=retained,'Complete financial roots or reference closure changed')
    implementation={'path':str(Path(__file__).resolve()),'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    result['implementation']=implementation
    result['policy_specialization']={'version':1,'implementation':implementation,'upstream_implementation':deepcopy(bindings.get('implementation')),
        'financial_physical_aliases_preserved':len(roots),'policy_seed_count':len(seeds),'changed_physical_definitions':len(changes),
        'pruned_arithmetic_definitions':len(removed),'financial_equivalence_or_source_qualification_claimed':False}
    report={'kind':'categorical_policy_structural_compilation','version':1,'implementation':implementation,
        'source_bindings_sha256':canonical(bindings),'new_bindings_sha256':canonical(result),'permitted_seeds':seeds,
        'original_formula_count':len(rows),'new_formula_count':len(retained),'pruned_arithmetic_count':len(removed),
        'pruned_literal_helper_count':len(literals)-len(new_literals),'rewritten_definitions':changes,
        'financial_identity_metadata_sha256':canonical(financial_identity),'financial_physical_alias_count':len(roots),
        'all_financial_paths_units_and_semantic_owners_preserved':True,'all_native_primitives_preserved':True,
        'all_retained_references_closed':True,'unknown_state_conditions_evaluated':False,
        'numeric_rate_date_join_or_financial_arithmetic_evaluated':False,'ledger_or_cache_read':False,
        'public_source_template_archive_created':False,'workbooks_created':0,'LO_calls':0,'models':0,
        'financial_equivalence_or_source_qualification_claimed':False,
        'limitations':['Unknown active/closed/test-applicable state branches remain. No complete-template-donor elimination is certified.',
            'This private report contains hashes of original expressions, not an old-template archive for publication.',
            'A fresh public workbook must be materialized solely from NEW bindings and independently audited/recalculated; no such workbook was produced.']}
    return result,report
