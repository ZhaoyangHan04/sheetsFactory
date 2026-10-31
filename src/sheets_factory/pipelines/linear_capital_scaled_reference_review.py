"""N360 ordinary quality using supported reference review, not public solving.

The existing source admission remains authoritative. The complete original view
protocol runs in a new opaque namespace with its one required upstream recipe
binding. Normal configuration and factory settings are isolated as well. Frozen
original modules are never mutated.
"""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path
from types import FunctionType
import weakref

from . import linear_capital_scaled_quality as source
from .factory import FactoryPipeline

UPSTREAM_SHA256 = '805598136866e52763ac168c18df7491cada54f329c6814aa47ea66643dee27d'
SETTING = 'linear_capital_scaled_reference_review'
PROFILE = source.ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
ROOT, References, reference, require = source.ROOT, source.References, source.reference, source.require
LinearSourceAdmission = source.LinearSourceAdmission
require_source_admission = source.require_source_admission
DEFAULT_PROVIDERS, NORMAL_SOURCE_KIND, REWARDS = source.DEFAULT_PROVIDERS, source.NORMAL_SOURCE_KIND, source.REWARDS
REQUIRED_VIEW_UPSTREAM = {'path':str(ROOT/'scripts/validate_linear_capital_task_view.py'),
    'sha256':'24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974',
    'bytes':25755}
_ACTIVE_REFERENCE_VIEWS = weakref.WeakSet()


def current_view_recipe(helper):
    """The actual N360 validator binds its one frozen upstream implementation."""
    require(reference(REQUIRED_VIEW_UPSTREAM['path']) == REQUIRED_VIEW_UPSTREAM,
        'The exact required upstream actual-view protocol changed')
    original = source._current_view_recipe(helper)
    require(REQUIRED_VIEW_UPSTREAM['path'] not in original,
        'The original view recipe acquired an unreviewed upstream-binding change')
    return {**original, REQUIRED_VIEW_UPSTREAM['path']:REQUIRED_VIEW_UPSTREAM['sha256']}


def require_view_admission(value):
    require(type(value) is ReferenceViewAdmission and value in _ACTIVE_REFERENCE_VIEWS,
        'A live reference-review view admission is required; JSON or another opaque type is not evidence')
    return value.guard()


class ReferenceViewAdmission:
    """Complete original validation in an isolated, strictly typed namespace.

    Only the known extra upstream recipe binding differs. Actual kind/version,
    source, raw inputs, seven/eleven calls, complete D, controls, financial and
    typed-value checks remain the original protocol bytecode.
    """
    def __init__(self, *args, **kwargs):
        _view_namespace['_original_view_init'](self, *args, **kwargs)
        self.proof.update(kind='admitted_complete_native_linear_capital_scaled_reference_review_view',
            upstream_actual_view_protocol=REQUIRED_VIEW_UPSTREAM.copy(),
            prior_normal_quality_inherited=False, prior_public_solver_success_inherited=False)


LinearViewAdmission = ReferenceViewAdmission
_view_namespace = dict(vars(source))
_view_namespace.update(__name__=__name__+'._complete_view_protocol',
    LinearViewAdmission=ReferenceViewAdmission, _ACTIVE_VIEWS=_ACTIVE_REFERENCE_VIEWS,
    _current_view_recipe=current_view_recipe, require_view_admission=require_view_admission)
for _name in ('__init__', 'guard', '_recheck_values'):
    _original = getattr(source.LinearViewAdmission, _name)
    require(_original.__closure__ is None, 'The original complete-view protocol acquired an unhandled closure')
    _copy = FunctionType(_original.__code__, _view_namespace, _name,
        _original.__defaults__, _original.__closure__)
    _copy.__kwdefaults__ = _original.__kwdefaults__
    if _name == '__init__':
        _view_namespace['_original_view_init'] = _copy
    else:
        setattr(ReferenceViewAdmission, _name, _copy)
validate_seed = FunctionType(source.validate_seed.__code__, _view_namespace, 'validate_seed',
    source.validate_seed.__defaults__, source.validate_seed.__closure__)


def adapted_ast():
    require(hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest() == UPSTREAM_SHA256,
        'The frozen N360 opaque admission implementation changed')
    tree = source.adapted_ast()
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        and n.name in {'validate_configuration', 'LinearCapitalQualityFactory'}]
    require(len(tree.body) == 2, 'The exact original configuration/factory pair changed')
    counts = {}
    def mark(key): counts[key] = counts.get(key, 0) + 1
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 2 and node.module == 'task_adapters':
                require([(n.name, n.asname) for n in node.names] == [('linear_capital_scaled', 'adapter')],
                    'The original configuration adapter import changed')
                node.names = [ast.alias(name='linear_capital_scaled_reference_review', asname='adapter')]
                mark('adapter')
            return node
        def visit_Constant(self, node):
            if node.value == 'independent_public_recovery':
                node.value = 'reference_review'; mark('policy')
            elif node.value == 'linear_capital_scaled':
                node.value = SETTING; mark('setting')
            elif node.value == 'The normal family requires isolated public-only reconstruction':
                node.value = 'The N360 route requires supported Q01–Q04 reference review'; mark('message')
            return node
        def visit_Assign(self, node):
            if [ast.unparse(n) for n in node.targets] == ['recovery_config']:
                require(ast.unparse(node.value) == "config['recovery']", 'The recovery guard changed')
                mark('remove_config'); return None
            return self.generic_visit(node)
        def visit_Expr(self, node):
            text = ast.unparse(node)
            if text.startswith('require(recovery_config.get('):
                mark('remove_solver_guard'); return None
            if text.startswith('adapter.recovery.validate_offline_configuration('):
                mark('remove_offline'); return None
            if text.startswith('adapter.recovery.validate_public_runtime('):
                mark('remove_runtime'); return None
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    expected = {'adapter':1, 'policy':1, 'setting':2, 'message':1,
        'remove_config':1, 'remove_solver_guard':1, 'remove_offline':1, 'remove_runtime':1}
    require(counts == expected, 'The bounded reference-review factory adaptation changed: '+str(counts))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), str(source.UPSTREAM), 'exec'), globals())
_configuration_guard = validate_configuration


def validate_configuration(config):
    profile = _configuration_guard(config)
    require(config.get('recovery') == {'compiler_backend':'reference_review',
        'public_solver_required':False, 'public_solver_attempted':False},
        'This route must not require or claim an exact public-solving witness')
    require(config['agents']['model'] == 'gpt-6-sol'
        and config['agents']['reasoning_effort'] == 'high', 'Retain the ordinary normal quality model')
    require(profile['image']['id'] == 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043',
        'Retain the pinned normal task image')
    return profile
