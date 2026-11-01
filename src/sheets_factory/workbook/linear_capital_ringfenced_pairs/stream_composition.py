"""Isolated streaming ancestor; only witnessed categorical text is newly accepted."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile

from .. import heterogeneous_native_merge as syntax_ancestor
from ..linear_capital_ringfenced_group import stream_composition as ancestor
from . import contract as c

CORE_SHA='7f0ff72c9a8a9cd6de949b9824d821174643453c740e8856117446cdec1094bb'
SYNTAX_SHA='38bf2e1ad2f961af08e8f9138094c88c2b14dde0d216f4c5eaced3433b1fc701'
PREFLIGHT_KIND='complete_ten_ringfenced_donor_formula_preflight'
S=ancestor.S;R=ancestor.R
LIMITS={'formulas':2600000,'nonempty':3600000,'targets':3200000}
FIXED=None


def safe_business_literal(tokens,index,sheets,defined=False):
    """Accept exactly the observed equality leaf and function argument context."""
    if defined or index<6 or index+3>=len(tokens):return False
    token=tokens[index];literal=token.value[1:-1].replace('""','"')
    column='C' if literal in {f'R{i:02d}' for i in range(1,7)} else 'D' if literal in {f'C{i:02d}' for i in range(1,9)} else None
    if column is None or token.value!='"'+literal+'"':return False
    left,op=tokens[index-2:index]
    if (left.type,left.subtype,op.value)!=('OPERAND','RANGE','=') or '!' not in left.value:return False
    if [t.value for t in tokens[index-6:index-2]]!=['-','-','(','(']:return False
    if [(t.type,t.subtype) for t in tokens[index+1:index+4]]!=[('PAREN','CLOSE'),('PAREN','CLOSE'),('FUNC','CLOSE')]:return False
    qualifier,address=left.value.rsplit('!',1);qualifier=syntax_ancestor._unquote(qualifier)
    permitted={key for key,value in sheets.items() if key=='Projects' or value=='Projects'}
    if qualifier not in permitted or address!=f'${column}$2:${column}$361':return False
    stack=[]
    for item in tokens[:index]:
        if item.type in ('FUNC','PAREN') and item.subtype=='OPEN':
            stack.append([item.type,item.value[:-1].upper() if item.type=='FUNC' else None,0])
        elif item.type in ('FUNC','PAREN') and item.subtype=='CLOSE':
            if not stack:return False
            stack.pop()
        elif item.type=='SEP' and item.subtype=='ARG':
            if not stack or stack[-1][0]!='FUNC':return False
            stack[-1][2]+=1
    return [(r[1],r[2]) for r in stack if r[0]=='FUNC']==[('IF',1),('SUMPRODUCT',2)]


def _syntax():
    c.require(c.reference(syntax_ancestor.__file__)['sha256']==SYNTAX_SHA,'Frozen syntax ancestor changed')
    tree=ast.parse(Path(syntax_ancestor.__file__).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='rewrite_formula')
    loops=guards=0
    class Narrow(ast.NodeTransformer):
        def visit_For(self,n):
            nonlocal loops
            if isinstance(n.target,ast.Name) and n.target.id=='token' and isinstance(n.iter,ast.Name) and n.iter.id=='tokens':
                loops+=1;n.target=ast.Tuple(elts=[ast.Name(id='_literal_index',ctx=ast.Store()),n.target],ctx=ast.Store())
                n.iter=ast.Call(func=ast.Name(id='enumerate',ctx=ast.Load()),args=[n.iter],keywords=[])
            return self.generic_visit(n)
        def visit_Call(self,n):
            nonlocal guards
            if isinstance(n.func,ast.Name) and n.func.id=='require' and len(n.args)>1 and isinstance(n.args[1],ast.BinOp) and isinstance(n.args[1].left,ast.Constant) and n.args[1].left.value=='Text address literal is unsupported: ':
                guards+=1;n.args[0]=ast.BoolOp(op=ast.Or(),values=[n.args[0],ast.parse('_safe_business_literal(tokens,_literal_index,sheets,defined_name)',mode='eval').body])
            return self.generic_visit(n)
    node=Narrow().visit(node);c.require((loops,guards)==(1,1),'Unknown frozen syntax acceptance sites')
    module=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(module)
    ns=dict(vars(syntax_ancestor));ns['_safe_business_literal']=safe_business_literal
    exec(compile(module,str(syntax_ancestor.__file__),'exec'),ns)
    return SimpleNamespace(**{**vars(syntax_ancestor),'rewrite_formula':ns['rewrite_formula']})


def _core():
    c.require(c.reference(ancestor.__file__)['sha256']==CORE_SHA,'Frozen streaming ancestor changed')
    ns=dict(vars(ancestor));ns.update(syntax=_syntax(),LIMITS=dict(LIMITS))
    for name,value in vars(ancestor).items():
        if isinstance(value,FunctionType) and value.__globals__ is vars(ancestor):
            clone=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__);clone.__kwdefaults__=value.__kwdefaults__;ns[name]=clone
    return ns


_N=_core()
sheet_map=_N['sheet_map'];rekey_binding=_N['rekey_binding'];_formula=_N['_formula']
_load=_N['_load'];_compose=_N['_compose'];_checked=_N['_checked'];_resolve=_N['_resolve']


def _scan(donor):
    """Read every formula and formula-bearing metadata node; allocate one row."""
    count=nonempty=criteria=other=0
    @lru_cache(maxsize=8192)
    def rewrite(text,scope,defined=False):return _formula(text,donor,scope,defined=defined)
    def check(text,sheet,defined=False):
        # With no defined names, local_sheet cannot change any RANGE resolution.
        rewrite(text,sheet if donor['names'] else None,defined)
    with ZipFile(donor['path']) as archive:
        wb=donor['workbook_tree'];names=list(donor['sheet_map'])
        for node in wb.findall('{'+S+'}definedNames/{'+S+'}definedName'):
            index=node.get('localSheetId');check(node.text or '',names[int(index)] if index is not None else None,True)
        for sheet,part in donor['sheet_parts'].items():
            with archive.open(part) as handle:
                parents=[]
                for event,node in X.iterparse(handle,events=('start','end')):
                    if event=='start':parents.append(node);continue
                    local=node.tag.rsplit('}',1)[-1]
                    if local=='c':
                        formula=node.find('{'+S+'}f')
                        if formula is not None:
                            c.require(set(formula.attrib)<={'t','aca','ca'} and formula.get('t','normal')=='normal','Unhandled shared/array/data-table formula')
                            text=formula.text or '';check(text,sheet);count+=1
                            criteria+=sum(text.count('"'+v+'"') for v in [*[f'R{i:02d}' for i in range(1,7)],*[f'C{i:02d}' for i in range(1,9)]])
                        elif node.find('{'+S+'}v') is not None or node.find('{'+S+'}is') is not None:nonempty+=1
                    elif local in ('formula','formula1','formula2') and node.text:check(node.text,sheet);other+=1
                    elif local=='hyperlink' and node.get('location'):check(node.get('location'),sheet);other+=1
                    if local=='row':
                        node.clear()
                        if len(parents)>1:parents[-2].remove(node)
                    parents.pop()
    return {'profile_id':donor['profile_id'],'workbook':donor['workbook'],'sheets':len(donor['sheet_map']),
        'physical_formulas':count,'all_formula_roundtrips_checked':True,'business_criterion_sites':criteria,
        'other_formula_elements':other,'parsed_formula_cache_bound':8192,'financial_bindings_expanded':0}


def preflight_all(prospective):
    """A real all-ten scan precedes any call to the genuine cold providers."""
    frozen=c.validate_prospective(prospective);results=[]
    for row in frozen['contexts']:
        public=c.read(row['specification'])
        c.require(public['region_ids']==[f'R{i:02d}' for i in range(1,7)] and public['sector_ids']==[f'C{i:02d}' for i in range(1,9)],'The declared categorical universe changed')
        donor={'id':'M01','profile_id':row['profile_id'],'prefix':row['profile_id'].removeprefix('L360-')+' - ','workbook':row['workbook']}
        # The frozen loader requires at least2 donors; compact metadata of an
        # adjacent fixed donor is loaded too, without scanning it twice here.
        index=list(c.PROFILE_ORDER).index(row['profile_id']);peer=frozen['contexts'][(index+1)%10]
        loaded=_load([donor,{'id':'M02','prefix':peer['profile_id'].removeprefix('L360-')+' - ','workbook':peer['workbook']}])
        report=_scan(loaded[0]);c.require(report['sheets']==370 and report['physical_formulas']==1247328
            and report['business_criterion_sites']==280,'The full fixed donor syntax census changed')
        results.append(report)
        print(json.dumps({'phase':'all_ten_formula_preflight','profile_id':row['profile_id'],
            'donors_complete':len(results),'physical_formulas_checked':sum(r['physical_formulas'] for r in results)}),flush=True)
    return {'kind':PREFLIGHT_KIND,'version':1,'prospective':prospective if isinstance(prospective,dict) else c.reference(prospective),
        'passed':True,'donors':results,'total_physical_formulas':sum(r['physical_formulas'] for r in results),
        'all_ten_donors_checked_before_hydration':True,'recipe':c.recipes(),'new_workbooks_services_forwards':0}


def compose(certificate,output,*,mode='goal',views=None):
    from . import composition
    c.require(mode=='goal' and views is None,'Future actual view linkage requires its own complete contract')
    proof=composition.validate_certificate(certificate)
    return _compose(proof['donors'],output,mode=mode,target_count=3044376,
        expected_census={'sheets':740,'formulas':2494656,'nonempty':3547132},
        ancestry={'composition_certificate':certificate,'native_source_or_quality_inherited':False})


def compose_toy(donors,output):
    c.require(len(donors)==2,'Pair toy fixtures require exactly2 mandates')
    return _N['compose_toy'](donors,output)
