#!/usr/bin/env python3
"""Prospective task8 revision: only declared given Boolean constants normalize."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/validate_waterfall_portfolios_tasks.py'
UPSTREAM_SHA='8632ba14d4c2612df0e619424959a4a091290b43caafefe145aba8dccede6bfc'
SOURCE_SCRIPT=ROOT/'scripts/build_waterfall_portfolios_source_revision3.py'
SOURCE_SHA='c09e7684a62fc193c00850afc64f15ac196337f0ee9f5e30aa30e2cb2cd8a8ad'
KIND='prepared_waterfall_portfolios_task_engineering_revision2'
TERMINAL_KIND='complete_waterfall_portfolios_task_engineering_revision2'
GIVEN_BOOLEAN_COUNT=48


def _load():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:raise ValueError('The frozen original waterfall task8 changed')
    tree=ast.parse(raw);counts={};kept=[];main_count=0
    replacements={'SOURCE_SCRIPT':ast.parse('SOURCE_SCRIPT').body[0].value,
        'SOURCE_SHA':ast.Constant(SOURCE_SHA),'KIND':ast.Constant(KIND),'TERMINAL_KIND':ast.Constant(TERMINAL_KIND)}
    for node in tree.body:
        if isinstance(node,ast.If) and ast.unparse(node.test)=="__name__ == '__main__'":main_count+=1;continue
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in replacements:
            name=node.targets[0].id;node.value=replacements[name];counts[name]=counts.get(name,0)+1
        kept.append(node)
    if counts!={key:1 for key in replacements} or main_count!=1:raise ValueError('Unrecognized exact task8 revision seams')
    namespace={'__name__':'_waterfall_task8_boolean_revision2','__file__':str(Path(__file__).resolve()),'SOURCE_SCRIPT':SOURCE_SCRIPT}
    exec(compile(ast.fix_missing_locations(ast.Module(body=kept,type_ignores=[])),str(UPSTREAM),'exec'),namespace)
    return namespace


_private=_load()
reference,checked,read,write,require=(_private[n] for n in ('reference','checked','read','write','require'))
STAGES=_private['STAGES'];COUNTS=_private['COUNTS']
_old_recipes=_private['recipes']


def recipes():
    require(reference(UPSTREAM)['sha256']==UPSTREAM_SHA,'The exact original task workflow changed')
    result=_old_recipes();result[str(UPSTREAM)]=reference(UPSTREAM)
    result[str(Path(__file__).resolve())]=reference(__file__)
    return result


def given_boolean_points(definition):
    points={p:v['value'] for p,v in definition['literals'].items() if v['type']=='boolean'}
    require(len(points)==GIVEN_BOOLEAN_COUNT and all(type(v) is bool for v in points.values()),
            'Only the complete prebound provided Boolean sites may normalize')
    require(not set(points)&set(definition['formulas']),'A financial formula cannot become a provided Boolean')
    return points


def verify_definitions(path,definition,*,blank=False):
    s=_private['_activate']();book=s._book(path);given=given_boolean_points(definition)
    try:
        require(book.sheetnames==definition['sheetnames'],'Task worksheet structure changed')
        classified=s.classify_formula_scope(book,definition)
        formulas=classified['financial_formulas'];aliases=classified['provided_boolean_constant_formulas']
        require(set(aliases)<=set(given) and classified['physical_formula_count']==len(formulas)+len(aliases)
            and all(formula==('=TRUE()' if given[p] else '=FALSE()') for p,formula in aliases.items()),
            'The genuine source Boolean classification changed')
        literals={ws.title+'!'+c.coordinate:s.typed(c.value) for ws in book for c in ws._cells.values()
            if c.value is not None and c.data_type!='f'}
        literals.update({p:s.typed(given[p]) for p in aliases})
        mask=set(definition['FM_mask_points'])
        wanted={p:f for p,f in definition['formulas'].items() if not blank or p not in mask}
        require(set(formulas)==set(wanted) and all(s.formula_signature(formulas[p])==s.formula_signature(wanted[p]) for p in wanted),
                'The complete financial formula definitions or partial FM scope changed')
        require(literals==definition['literals'],'Protected Boolean values, facts, policies or labels changed')
        require(book.calculation is not None and book.calculation.iterate in (None,False),'The task must remain noncircular')
        for point in definition['Boolean_General_points']:
            if point in formulas:
                sheet,cell=point.rsplit('!',1);require(book[sheet][cell].number_format=='General','Financial Boolean status requires General format')
    finally:book.close()


_private.update(recipes=recipes,verify_definitions=verify_definitions)
_private['_ns'].update(recipes=recipes,verify_definitions=verify_definitions)
prepare=_private['prepare'];validate_prepared=_private['validate_prepared']
execute_prepared=_private['execute_prepared'];validate_completed=_private['validate_completed'];main=_private['main']


if __name__=='__main__':raise SystemExit(main())
