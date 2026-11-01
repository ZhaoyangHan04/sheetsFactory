"""Fixed200 normal review with a scoped immutable development witness.

The genuine task/source closure remains a current causal dependency. The spent
development snapshot is documentary provenance; only its consumed FM material
is interpreted here. Its unrelated historical selections are not providers.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import FunctionType, ModuleType
import weakref

from ..pipelines import operating_reports_200_quality as old_pipeline
from . import operating_reports_200_quality as old_nodes

ROOT = old_pipeline.ROOT
reference, require = old_pipeline.reference, old_pipeline.require
ANCESTORS = {
    str(Path(old_pipeline.__file__)): '6480b00232e7c70d8e9b2e66977fcb3fb21292c329864f3cdc65d4a4e82a09c8',
    str(Path(old_nodes.__file__)): 'd4e37353164ed1647ccd9564297a48bf1bebb86edd374ff964e9a50f7e5b4d44',
}
for _path, _sha in ANCESTORS.items():
    require(reference(_path)['sha256'] == _sha, 'The frozen fixed200 normal ancestor changed')
REGISTRY = ROOT/'config/task_adapters/operating_reports_200_quality_revision2_nodes.yaml'
FAILURE_DIAGNOSIS = {
    'path': str(ROOT/'outputs/research/operating_reports_200_normal_historical_closure_failure_readonly_20261031T235508Z/receipt.json'),
    'sha256': 'e0e434f7dca8d17a56f0f30592ebb6b8fb1478bae50f327523f1126da02c03b2', 'bytes': 3749,
}
CONSUMED_DEVELOPMENT_KEYS = ('input', 'goal', 'original_instruction', 'rendered_instruction')


def _bind_development_witness(value, actual_ref, dev_ref, development):
    """Guard the exact snapshot and interpreted leaves, without traversing history."""
    value.references.check(dev_ref)
    leaves = {key: deepcopy(development[key]) for key in CONSUMED_DEVELOPMENT_KEYS}
    for record in leaves.values():
        value.references.check(record)
    value.development_dependency_scope = {
        'protocol': 'immutable_snapshot_and_consumed_financial_modeling_leaves_v2',
        'genuine_current_task_source_root': deepcopy(actual_ref),
        'genuine_current_task_source_discovery_unchanged': True,
        'historical_snapshot': deepcopy(dev_ref), 'consumed_mode': 'financial_modeling',
        'consumed_leaf_refs': leaves,
        'material_task_version': deepcopy(development['material_task_version']),
        'unconsumed_history_role': 'immutable_documentary_provenance_not_current_provider_code',
    }


def setting():
    return {**old_pipeline.setting(), 'version': 2,
        'pipeline': reference(__file__), 'nodes': reference(__file__), 'registry': reference(REGISTRY),
        'dependency_protocol': 'immutable_snapshot_and_consumed_financial_modeling_leaves_v2',
        'frozen_implementation_ancestors': {path: reference(path) for path in ANCESTORS}}


def _clone(function, namespace):
    copied = FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
    copied.__kwdefaults__ = deepcopy(function.__kwdefaults__)
    return copied


# Only this one AST call changes. The complete genuine engineering validation,
# current source discovery, large interpreted objects, and material gates stay.
pipeline = ModuleType(__name__+'._pipeline')
_pipe_ns = pipeline.__dict__
_pipe_ns.update({**vars(old_pipeline), '__file__': __file__, '__name__': __name__+'._pipeline',
    'REGISTRY': REGISTRY, '_LIVE': weakref.WeakSet(), 'setting': setting,
    '_bind_development_witness': _bind_development_witness})
_tree = ast.parse(Path(old_pipeline.__file__).read_bytes())
_class = next(node for node in _tree.body if isinstance(node, ast.ClassDef) and node.name == 'OperatingReportsAdmission')
_replacements = []
class _ScopeWitness(ast.NodeTransformer):
    def visit_Expr(self, node):
        if ast.dump(node.value, include_attributes=False) == ast.dump(ast.parse('self.references.discover(dev_ref)').body[0].value, include_attributes=False):
            _replacements.append('development_discovery')
            return ast.copy_location(ast.parse('_bind_development_witness(self, actual_ref, dev_ref, development)').body[0], node)
        return self.generic_visit(node)
_class = _ScopeWitness().visit(_class)
require(_replacements == ['development_discovery'], 'The exact historical witness discovery seam changed')
exec(compile(ast.fix_missing_locations(ast.Module(body=[_class], type_ignores=[])), str(Path(old_pipeline.__file__)), 'exec'), _pipe_ns)
OperatingReportsAdmission = _pipe_ns['OperatingReportsAdmission']
_original_init = OperatingReportsAdmission.__init__


def _initialize(self, validation_terminal):
    _original_init(self, validation_terminal)
    for path in (*ANCESTORS, str(Path(__file__)), str(REGISTRY)):
        record = reference(path); self.references.check(record); self.recipe[path] = record['sha256']
    self.references.check(FAILURE_DIAGNOSIS)
    scope = deepcopy(self.development_dependency_scope)
    scope['current_guarded_artifacts'] = [deepcopy(self.references.files[path]) for path in sorted(self.references.files)]
    scope['current_recipe_sha256'] = deepcopy(self.recipe)
    self.evidence['dependency_scope'] = scope
    self.evidence['retained_failed_normal_preparation'] = deepcopy(FAILURE_DIAGNOSIS)
    self.proof.update(kind='opaque_fixed200_financial_modeling_reference_admission_revision2', version=2,
        dependency_scope=scope, retained_failed_normal_preparation=deepcopy(FAILURE_DIAGNOSIS))
    self.identity = deepcopy(self.proof)
    self.evidence_sha = hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest()
    self.guard()


OperatingReportsAdmission.__init__ = _initialize
_pipe_ns['NativeScopeAdmission'] = OperatingReportsAdmission
for _name in ('boundary', 'admission', 'validate_seed', 'validate_configuration'):
    _pipe_ns[_name] = _clone(getattr(old_pipeline, _name), _pipe_ns)
_pipe_ns['_configuration'] = _clone(old_pipeline._configuration, _pipe_ns)


class NativeQualityFactory(old_pipeline.NativeQualityFactory):
    """The same factory bytecode with the revision2 live admission namespace."""


for _method in ('__init__', 'load_seeds', 'run_phase', '_claim_targets'):
    setattr(NativeQualityFactory, _method, _clone(getattr(old_pipeline.NativeQualityFactory, _method), _pipe_ns))
_pipe_ns['NativeQualityFactory'] = NativeQualityFactory
pipeline.__dict__['_namespace'] = _pipe_ns

_node_ns = {**old_nodes._namespace, **vars(old_nodes), 'pipeline': pipeline,
    'REGISTRY': REGISTRY, 'setting': setting, 'admission': _pipe_ns['admission']}
for _name in ('context', 'canonical_plan', 'independent_evidence', '_export'):
    _node_ns[_name] = _clone(getattr(old_nodes, _name), _node_ns)
    globals()[_name] = _node_ns[_name]
for _name in ('NormalizeNode', 'ProfileNode', 'PlanNode', 'ConstructNode', 'InstructionNode',
              'ControlsNode', 'DiagnoseNode', 'RepairNode', 'ExportNode'):
    _old = getattr(old_nodes, _name)
    _new = type(_name, (_old,), {'__module__': __name__, 'execute': _clone(_old.execute, _node_ns)})
    globals()[_name] = _new

base, receipt = old_nodes.base, old_nodes.receipt
REWARDS, TaskRejected = old_nodes.REWARDS, old_nodes.TaskRejected
validate_reference_export = old_nodes.validate_reference_export
