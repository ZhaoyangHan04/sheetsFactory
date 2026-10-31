"""Explicit source9 opt-in to the genuine retained-eight/SCIP reference gate.

The frozen source translator runs in a separate function namespace. Its default
reference module and every original function/global remain unchanged. No JSON
pass receipt bypasses reference_revision2.validate_completed.
"""
import ast
from collections import Counter
from pathlib import Path
from types import FunctionType, SimpleNamespace

from . import source9 as original, excel9, reference_revision2 as revision2

PINS={Path(original.__file__):'d01d8cc371320971be74b078217d458d5258a3bc48242328dd707c263cbaabd9',
      Path(excel9.__file__):'136f13ad01e848d29e06931573dc0e488089213780e62704cb239222da7897a2',
      Path(revision2.__file__):'19362a29d785d6cff78497afae66c1f40e66e6cf29255e537a06aefddcd65b77'}
KIND='unverified_shared_ledger_nine_case_source_candidate_revision2'
EXPECTED_KIND='complete_shared_ledger_nine_case_independent_expected_values_revision2'
require=original.require


def guard():
    for path,digest in PINS.items():
        require(revision2.reference(path)['sha256']==digest,'A frozen source9/reference ancestor changed')


def recipes():
    guard()
    return {**original.recipes(),**revision2.recipes(),str(Path(__file__)):revision2.reference(__file__)}


def _genuine_reference(value):
    # This actual API is the only admission path. The returned logical cursor
    # selects the original common matrices/finance, while keeping the complete
    # new terminal as genuine_reference and explicitly retaining its ancestry.
    actual=revision2.validate_completed(value)
    require(actual['kind']==revision2.KIND and type(actual['version'])is int and actual['version']==2
        and actual['passed'] is True and actual['qualified'] is False and len(actual['cases'])==9,
        'Only the genuine complete revision-two nine-case reference is supported')
    prepared=reference.read(actual['preparation']);prospective=reference.read(prepared['prospective'])
    return {**actual,'preparation':prospective['original_preparation']}


reference=SimpleNamespace(ROOT=revision2.ROOT,validate_completed=_genuine_reference,
    read=revision2.read,write=revision2.write,reference=revision2.reference,_refs=revision2._refs,
    _financial_projection=revision2.prior._financial_projection,recipes=revision2.recipes)
_namespace={**vars(original),'__file__':__file__,'reference':reference,'recipes':recipes}


def _clone(name):
    old=getattr(original,name)
    function=FunctionType(old.__code__,_namespace,name,old.__defaults__,old.__closure__)
    function.__kwdefaults__=old.__kwdefaults__
    return function


for _name in ('at','resolve_expected','expected_values','_expected_rows'):
    _namespace[_name]=_clone(_name)
_original_join=_clone('join_reference')


def join_reference(value):
    guard()
    record=reference.reference(value) if isinstance(value,(str,Path)) else value
    joined=_original_join(record)
    # Every read below is bound to the same already cold-admitted terminal.
    actual=reference.read(record);prepared=reference.read(actual['preparation'])
    prospective=reference.read(prepared['prospective'])
    joined['kind']='joined_all_nine_independent_financial_source_inputs_revision2'
    joined['version']=2
    joined['references'].update(revision2_preparation=actual['preparation'],
        revision2_prospective=prepared['prospective'],
        original_failed_observation=prospective['original_complete_failed_observation'])
    joined['reference_validator_protocol']=revision2.KIND
    reference._refs(joined['references'])
    return joined


_namespace['join_reference']=join_reference


def adapted_ast():
    """Only the new candidate/expected envelope identities and versions change."""
    guard();tree=ast.parse(Path(original.__file__).read_bytes());hits=Counter()
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('build_candidate','validate_candidate')]
    require({n.name for n in tree.body}=={'build_candidate','validate_candidate'},'Frozen source entry functions changed')
    class Adapt(ast.NodeTransformer):
        def visit_Dict(self,node):
            keys=[getattr(k,'value',None) for k in node.keys]
            if 'kind'in keys and 'version'in keys:
                kind=node.values[keys.index('kind')]
                require(isinstance(kind,ast.Constant) and kind.value in (
                    'unverified_shared_ledger_nine_case_source_candidate',
                    'complete_shared_ledger_nine_case_independent_expected_values'), 'Unexpected frozen source envelope')
                require(node.values[keys.index('version')].value==1,'Frozen source envelope version changed')
                node.values[keys.index('version')]=ast.Constant(2);hits['envelope_version']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='unverified_shared_ledger_nine_case_source_candidate':node.value=KIND;hits['candidate_kind']+=1
            elif node.value=='complete_shared_ledger_nine_case_independent_expected_values':node.value=EXPECTED_KIND;hits['expected_kind']+=1
            return node
        def visit_Compare(self,node):
            if ast.unparse(node)=="candidate['version'] == 1":
                node.comparators[0]=ast.Constant(2);hits['candidate_version_guard']+=1
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    require(hits==Counter(dict(envelope_version=2,candidate_kind=2,expected_kind=1,candidate_version_guard=1)),
            'The exact isolated source9 identity substitutions changed: '+str(hits))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),_namespace)
build_candidate=_namespace['build_candidate']
validate_candidate=_namespace['validate_candidate']
expected_values=_namespace['expected_values']


def geometry(public):
    """Algebraic point census only; allocates no workbook or financial journal.

    Financial values and decision values are numeric typed cells. Given facts
    and descriptive labels outside this scope require their separate full audit.
    This census is neither a source materialization nor a proof of any winner.
    """
    public=original.contract.spec.load_spec(public);spec=original.contract.spec
    n=len(public['project_ids']);s=len(public['scenario_ids']);y=len(public['years']);c=9
    annual=len(spec.ANNUAL_FIELDS)+2;vintage=len(spec.VINTAGE_FIELDS)
    valid_origins=sum(min(year,5) for year in public['years'])
    vintage_formulas=sum(2+3*min(year-1,3)+(2 if year>=5 else 0) for year in public['years'])
    standalone_values=len(spec.T0_FIELDS)+y*annual+valid_origins*vintage+2
    standalone_formulas=len(spec.T0_FIELDS)+y*annual-2*(y-1)+vintage_formulas+2
    aliases=n*(2*s+1+s*y*len(spec.GROUP_FIELDS))
    cash=c*s*y*len(spec.GROUP_FIELDS);checks=c*spec.expected_constraint_count(public)*4
    financial=n*s*standalone_values+aliases+cash+checks+2*c
    formulas=n*s*standalone_formulas+aliases+cash+checks+4*c
    return {'kind':'algebraic_unmaterialized_nine_case_financial_point_census','version':2,
        'projects':n,'project_ledger_copies':1,'worksheet_count':n+14,'choice_vectors':c,
        'decision_numeric_points':c*n,'case_cash_rows':c*s*y,
        'case_constraint_rows':c*spec.expected_constraint_count(public),
        'formula_points':formulas,'independent_numeric_financial_points':financial,
        'independent_input_only_formula_points':2*c,
        'provided_pre_FY1_NA_text_points':n*s*(5*y-valid_origins)*vintage,
        'FM_mask_points':financial+2*c+c*n,'actual_full_D_count_claimed':False,
        'other_provided_facts_and_labels_need_separate_exact_construction_audit':True,
        'workbook_materializations':0,'financial_forwards':0,'optimizer_LO_model_calls':0,
        'source_engine_verified':False,'qualified':False}
