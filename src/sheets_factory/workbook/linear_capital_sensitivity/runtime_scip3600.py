"""Opt-in N360 ninth-case SCIP3600 resource lifecycle in a private namespace."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

from ..linear_capital_scaled import optimization_runtime as base, model_a, model_b, spec
from . import backend_scip as backend

ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT/'config/runtime_profiles/linear_capital_sensitivity9_SCIP3600_revision2.json'
BASE_SHA = '45f841e9d33917b8ac469694b5ef335311479aa9de98aad72207a358744e2d54'
SOURCE_NAMES = ('spec.py','model_a.py','model_b.py','frozen_spec.py','frozen_model_a.py',
                'frozen_model_b.py','frozen_scaled_model_a.py')


def policy():
    return {'kind':'fixed_sensitivity9_ninth_case_SCIP_reference_profile','version':2,
        'id':'linear_capital_sensitivity9_SCIP3600_revision2','image_id':base.IMAGE_ID,
        'producer':{'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256,'threads':16,'network':'none',
            'backend':'scip','solver_seconds_per_attempt':3600,'operational_timeout_seconds':3720,
            'relative_gap':0,'absolute_gap':0,'feasibility_tolerance':1e-9,'automatic_retries':0},
        'vendor':{'pyscipopt':'6.0.0','numpy':'1.26.4'},'projects':360,'complete_business_rows':941,
        'fixed_case':'B110_C110','maximum_new_native_searches':2,'max_parallel_new_cases':1,
        'prior_incumbent_or_warm_hint':False,'objective_scaled':False,
        'row_representation':'exact duplicate/zero-tautology omission; positive P02 threshold scaling',
        'strict_native_primal_objective_dual_and_all_original_integer_rows':True,
        'runner_excludes_complete_winner':True,'minimum_gap_pence':1,'cardinality_admission':False,
        'maximum_historical_searches':19,'admitted_proofs_required':18,
        'reference_is_not_source_or_quality_or_difficulty':True}


def profile_reference():
    backend.require(base._canonical(json.loads(PROFILE.read_bytes())) == base._canonical(policy()),
                    'The independent ninth-case SCIP resource/proof profile changed')
    return base.reference(PROFILE)


def source_files():
    folder = Path(base.__file__).parent; old = folder.parent/'linear_capital_portfolio'
    return {'spec.py':folder/'spec.py','model_a.py':Path(backend.__file__), 'model_b.py':folder/'model_b.py',
        'frozen_scaled_model_a.py':folder/'model_a.py', **{'frozen_'+n:old/n for n in ('spec.py','model_a.py','model_b.py')}}


def _complete_scaled_dimension(model):
    backend.require(len(model['project_ids']) == 360 and len(model['rows']) == 941,
                    'Only the complete fixed N360/941 matrix is admitted')
    return model_b.validate_model(model)


def adapted_ast():
    backend.require(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() == BASE_SHA,
                    'Frozen N360 producer lifecycle changed')
    tree = base.adapted_ast(); hits = Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Assign(self, node):
            names = [getattr(t,'id',None) for t in node.targets]
            if names == ['ROOT']: node.value=ast.Name('_SENSITIVITY_ROOT',ast.Load()); hits['root']+=1
            elif names == ['PREPARATION_KIND']: node.value=ast.Constant('prepared_private_sensitivity9_SCIP3600_revision2_solver'); hits['prepared']+=1
            elif names == ['TERMINAL_KIND']: node.value=ast.Constant('private_sensitivity9_SCIP3600_revision2_solver_execution'); hits['terminal']+=1
            elif names == ['CODE_FILES']: node.value=ast.parse(repr(SOURCE_NAMES),mode='eval').body; hits['sources']+=1
            elif names == ['BACKENDS']: node.value=ast.parse("{'scip':('model_a','solve_scip','native_model.cip')}",mode='eval').body; hits['backend']+=1
            elif names == ['RUNNER']:
                worker = ast.parse(node.value.value); count=0
                for item in ast.walk(worker):
                    if isinstance(item,ast.Subscript) and isinstance(item.value,ast.Dict) and [getattr(k,'value',None) for k in item.value.keys] == ['scip','cp_sat']:
                        item.value=ast.parse("{'scip':('model_a','solve_scip','native_model.cip')}",mode='eval').body; count+=1
                backend.require(count==1,'Frozen native backend dispatch changed')
                node.value=ast.Constant(ast.unparse(worker)); hits['worker']+=1
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            node=self.generic_visit(node)
            if node.name=='check_result':
                node.body.insert(-1,ast.parse('backend.strict_evidence(result,model)').body[0]); hits['strict']+=1
            return node
        def visit_Compare(self,node):
            if ast.unparse(node)=="solver.get('feasibility_tolerance_changed') is False":
                hits['tolerance_guard']+=1
                return ast.parse("solver.get('declared_feasibility_tolerance')==1e-9 and solver.get('applied_feasibility_tolerance')==1e-9 and solver.get('feasibility_tolerance_changed')==(solver['default_feasibility_tolerance']!=1e-9)",mode='eval').body
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys=[getattr(k,'value',None) for k in node.keys]
            if keys==['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
                for key in ('parallel/maxnthreads','lp/threads'): node.values[keys.index(key)]=ast.Constant(16)
                node.keys.append(ast.Constant('numerics/feastol'));node.values.append(ast.Constant(1e-9));hits['settings']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value)is str and 'sf-scaled-producer16-integer-' in node.value:
                node.value=node.value.replace('sf-scaled-producer16-integer-','sf-sensitivity9-SCIP3600-r2-');hits['owned']+=1
            return node
    tree=Adapt().visit(tree)
    backend.require(hits==Counter(dict(root=1,prepared=1,terminal=1,sources=1,backend=1,worker=1,strict=1,tolerance_guard=1,settings=1,owned=2)),
                    'Exact private SCIP runtime sites changed: '+str(hits))
    return ast.fix_missing_locations(tree)


_namespace={'__name__':__name__+'._frozen','__package__':__package__,'__file__':__file__,
    '_SENSITIVITY_ROOT':ROOT,'backend':backend,'_complete_scaled_dimension':_complete_scaled_dimension,
    '_producer_source_files':source_files,'profile_reference':profile_reference}
exec(compile(adapted_ast(),__file__,'exec'),_namespace)
for _name,_value in _namespace.items():
    if not _name.startswith('__'): globals()[_name]=_value
