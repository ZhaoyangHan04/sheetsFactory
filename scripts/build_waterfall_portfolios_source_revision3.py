#!/usr/bin/env python3
"""Source3 revision3: recognize only exact, unchanged given Boolean constants."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/build_waterfall_portfolios_source_revision2.py'
UPSTREAM_SHA='c97e9ad53f537a2c3550599a1507d8c1f4654bcad364ba8140276c0287ec7550'
KIND='prepared_waterfall_portfolios_cold_source3_revision3'
SOURCE_KIND='independently_checked_waterfall_portfolios_cold_source3_revision3'
FAILED_SOURCE=ROOT/'outputs/research/waterfall24_source3_revision2_20261101T002002Z/prepared/source_manifest.json'
FAILED_SOURCE_SHA='a83ba6923d5395400a3e298d54bc47f3ea3a13f5c75aa55940a4069925005680'
CENSUS=ROOT/'outputs/research/waterfall_source1_complete_native_readonly_20261101T002630Z/receipt.json'
CENSUS_SHA='24b089fa3603fea557fd78da7311a7f69ec7833033752e26dfebfe2e738c0827'


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _whitelist():
    if _sha(CENSUS)!=CENSUS_SHA:raise ValueError('The complete retained native census changed')
    proof=json.loads(CENSUS.read_text());rows=proof['extra_native_formula_cells']
    if (len(rows)!=48 or len({r['point'] for r in rows})!=48
            or proof['common_formula_count']!=189600 or proof['common_raw_formula_strings_changed']!=0
            or proof['common_formula_signature_differences'] or proof['financial_value_mismatches']
            or proof['protected_literal_mismatches'] or proof['native_errors']):
        raise ValueError('The original complete Boolean-only representation proof is required')
    out={}
    for row in rows:
        original=row['original_protected_typed_literal']
        if (original['type']!='boolean' or type(original['value']) is not bool
                or row['native_typed_cache']!=original
                or row['native_formula']!=('=TRUE()' if original['value'] else '=FALSE()')):
            raise ValueError('A declared given Boolean constant witness changed')
        out[row['point']]=original
    return out


GIVEN_BOOLEANS=_whitelist()


def classify_formula_scope(book,definition):
    """Read-only syntax classification; native value checks remain mandatory."""
    declared={p:v for p,v in definition['literals'].items() if v['type']=='boolean'}
    if declared!=GIVEN_BOOLEANS:raise ValueError('Only the exact48 original provided Boolean facts may have literal/constant representations')
    financial={};aliases={};seen=set();physical=0
    for sheet in book:
        for cell in sheet._cells.values():
            point=sheet.title+'!'+cell.coordinate
            if cell.data_type=='f':physical+=1
            if point in GIVEN_BOOLEANS:
                expected=GIVEN_BOOLEANS[point];seen.add(point)
                if cell.data_type=='f':
                    if cell.value!=('=TRUE()' if expected['value'] else '=FALSE()'):
                        raise ValueError('A given Boolean must retain its exact matching constant expression')
                    aliases[point]=cell.value
                elif type(cell.value) is not bool or cell.value!=expected['value']:
                    raise ValueError('A given Boolean literal changed type or value')
            elif cell.data_type=='f':financial[point]=cell.value
    if seen!=set(GIVEN_BOOLEANS):raise ValueError('A protected Boolean fact point is missing')
    return {'financial_formulas':financial,'provided_boolean_constant_formulas':aliases,'physical_formula_count':physical}


def _load():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:raise ValueError('The frozen revision2 source driver changed')
    tree=ast.parse(raw);changed=0
    class Kinds(ast.NodeTransformer):
        def visit_Constant(self,node):
            nonlocal changed
            if node.value=='prepared_waterfall_portfolios_cold_source3_revision2':node.value=KIND;changed+=1
            elif node.value=='independently_checked_waterfall_portfolios_cold_source3_revision2':node.value=SOURCE_KIND;changed+=1
            return node
    mains=[n for n in tree.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and ast.unparse(n.test)=="__name__ == '__main__'"]
    if len(mains)!=1:raise ValueError('Unknown frozen revision2 main entry')
    tree.body=[n for n in tree.body if n not in mains]
    tree=Kinds().visit(tree);ast.fix_missing_locations(tree)
    if changed!=2:raise ValueError('Unknown frozen revision2 source kind sites')
    private={'__name__':'_isolated_waterfall_source3_revision3','__file__':str(UPSTREAM)}
    exec(compile(tree,str(UPSTREAM),'exec'),private)
    return private


_S=_load();_N=_S['_N'];_BASE_RECIPES=_S['recipes']


def _adapt_audit():
    first=_S['_P'];ancestor=first['ANCESTOR']
    if _sha(ancestor)!=first['ANCESTOR_SHA']:raise ValueError('The original genuine source audit changed')
    node=next(n for n in ast.parse(ancestor.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='audit_workbook')
    scope=0;noncircular=0;physical=0;kind=0
    class Audit(ast.NodeTransformer):
        def visit_Constant(self,n):
            nonlocal kind
            if n.value=='full_independent_equity_income_native_cache_audit':
                kind+=1;n.value='full_independent_waterfall_native_cache_audit_revision3'
            return n
        def visit_For(self,n):
            nonlocal scope
            if isinstance(n.iter,ast.Name) and n.iter.id=='f':
                scope+=1
                return ast.parse("classification=classify_formula_scope(f,definition)\nformulas=classification['financial_formulas']").body
            return self.generic_visit(n)
        def visit_Call(self,n):
            nonlocal noncircular
            if isinstance(n.func,ast.Name) and n.func.id=='require' and len(n.args)>1 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='Native iteration settings changed':
                noncircular+=1;return ast.parse('_require_noncircular(f)').body[0].value
            return self.generic_visit(n)
        def visit_Dict(self,n):
            nonlocal physical
            n=self.generic_visit(n)
            for i,key in enumerate(n.keys):
                if isinstance(key,ast.Constant) and key.value=='physical_formulas_checked':
                    physical+=1;n.values[i]=ast.parse("classification['physical_formula_count']",mode='eval').body
                    for name,expression in (
                        ('canonical_financial_formulas_checked','len(formulas)'),
                        ('provided_boolean_constant_formula_count',"len(classification['provided_boolean_constant_formulas'])"),
                        ('provided_boolean_constant_formulas',"classification['provided_boolean_constant_formulas']")):
                        n.keys.append(ast.Constant(name));n.values.append(ast.parse(expression,mode='eval').body)
            return n
    node=Audit().visit(node)
    if (scope,noncircular,physical,kind)!=(1,1,1,1):raise ValueError('Unknown complete source-audit classification sites')
    tree=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(tree)
    namespace=dict(_N);namespace['classify_formula_scope']=classify_formula_scope
    exec(compile(tree,str(ancestor),'exec'),namespace)
    return namespace['audit_workbook']


def recipes():
    if _sha(UPSTREAM)!=UPSTREAM_SHA or _sha(FAILED_SOURCE)!=FAILED_SOURCE_SHA or _sha(CENSUS)!=CENSUS_SHA:
        raise ValueError('The frozen prior source/failure/whole-value proof changed')
    return {**_BASE_RECIPES(),**{str(p.resolve()):_S['reference'](p) for p in (Path(__file__),FAILED_SOURCE,CENSUS)}}


_N['audit_workbook']=_adapt_audit()
_N['classify_formula_scope']=classify_formula_scope
_N['recipes']=recipes
_S['_P']['recipes']=recipes
_S['recipes']=recipes
for _name in ('prepare','validate_prepared','execute_prepared','validate_source','validate_completed','main','reference','checked','read','write','runtime'):
    globals()[_name]=_S[_name]


if __name__=='__main__':raise SystemExit(main())
