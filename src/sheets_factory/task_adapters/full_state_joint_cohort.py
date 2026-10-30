"""Explicit mode dispatch for a prospective full-state FM and joint DBG cohort.

This module does not admit sources, expand quotas, import old task statuses,
launch models, or certify controls, quality, or difficulty. A future entry must
freeze each source's existing financial and mutation-provider admission.
"""
from __future__ import annotations

from copy import deepcopy

from ..core.node import BaseNode
from ..nodes import construction, joint_controls, scc_activity
from ..pipelines import factory, scc_activity_admission as v2, semantic_graph_admission as v3
from . import composite_full_state_fm as fm
from . import public_workbook_scope as scope

SETTING = 'full_state_joint_cohort'
VERSION = 1
METHOD = 'explicit_full_state_FM_and_admitted_joint_DBG_mode_dispatch_v1'
BACKENDS = ('full_graph_v2', 'semantic_graph_v3')


def setting(*, debug_backend):
    scope.require(debug_backend in BACKENDS, 'Select one explicit frozen joint debugging backend')
    dependencies = {
        'full_state_FM': fm.__file__, 'public_scope': scope.__file__,
        'normal_construction': construction.__file__, 'normal_factory': factory.__file__,
        'joint_controls': joint_controls.__file__, 'joint_construct': scc_activity.__file__,
        'full_graph_v2_admission': v2.__file__, 'semantic_graph_v3_admission': v3.__file__,
    }
    return {'version': VERSION, 'method': METHOD, 'debug_backend': debug_backend,
        'implementation': scope.reference(__file__),
        'dependencies': {name: scope.reference(path) for name, path in dependencies.items()}}


def validate_setting(config):
    value = config.get(SETTING)
    scope.require(isinstance(value, dict) and type(value.get('version')) is int
            and value['version'] == VERSION and value.get('debug_backend') in BACKENDS,
            'The mixed cohort requires an explicit versioned mode-dispatch setting')
    expected = setting(debug_backend=value['debug_backend'])
    scope.require(scope.canonical(value) == scope.canonical(expected),
            'The mixed cohort backend, implementation, or frozen dependency changed')
    return value['debug_backend']


def route(ctx):
    backend = validate_setting(ctx.config)
    scope.require(ctx.mode in ('financial_modeling', 'debugging'), 'Unsupported mixed cohort task mode')
    scope.require(ctx.config.get('construction', {}).get('authoring_backend') == 'composite_template'
            and ctx.config['construction'].get('planning_scope') == 'per_mode',
            'The mixed cohort requires explicit per-mode composite construction')
    evidence = ctx.data.get('finance_evidence', {})
    if ctx.mode == 'financial_modeling':
        full_state = ctx.config.get(fm.POLICY)
        scope.require(isinstance(full_state, dict) and type(full_state.get('version')) is int
                and full_state['version'] == fm.VERSION and set(full_state) == {'version', 'policy'},
                'FM mode requires the full-state completion opt-in')
        fm.load_policy(full_state['policy'])
        scope.require(not evidence.get('task_adapter') and not evidence.get('mutation_provider'),
                'FM mode cannot silently use a debugging mutation admission')
        return 'full_state_fm'
    # A mode flag alone cannot turn an ordinary financial source into a DBG
    # source. The selected frozen provider performs its full admission later.
    if backend == 'full_graph_v2':
        scope.require((evidence.get('task_adapter') or {}).get('id') == v2.ADAPTER,
                'V2 debugging requires the explicitly admitted full-graph adapter')
        joint = ctx.config.get(v2.JOINT_SETTING)
        scope.require(isinstance(joint, dict) and joint.get('enabled') is True
                and joint.get('contract') == v2.JOINT_METHOD,
                'V2 debugging requires the explicit full-workbook joint repair contract')
    else:
        scope.require((evidence.get('mutation_provider') or {}).get('id') == v3.PROVIDER_ID
                and isinstance(ctx.config.get(v3.SETTING), dict),
                'V3 debugging requires its separate admitted semantic mutation provider')
    joint_controls.validate_setting(ctx.config.get(joint_controls.SETTING))
    return backend


def receipt(ctx, node, selected, result, **extra):
    ctx.save('full_state_joint_' + node + '_dispatch.json', {
        'kind': 'prospective_mixed_cohort_mode_dispatch', 'version': VERSION,
        'mode': ctx.mode, 'selected_backend': selected,
        'setting_sha256': scope.canonical(ctx.config[SETTING]),
        'source_id': ctx.data.get('source_id'), 'node': node,
        'source_financial_admission_replaced': False,
        'task_or_repair_budgets_changed': False, 'quality_or_difficulty_certified': False,
        **extra})
    return result


class FullStateJointPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        selected = route(ctx)
        if selected == 'full_state_fm':
            result = fm.FullStateFMPlanNode().execute(ctx)
        elif selected == 'semantic_graph_v3':
            result = v3.SemanticGraphPlanNode().execute(ctx)
        else:
            result = scope.ScopeFullGraphPlanNode().execute(ctx)
            plan = result['plan']
            if 'mask_ranges' in plan:
                scope.require(type(plan['mask_ranges']) is list and not plan['mask_ranges']
                        and plan.get('family_adapter', {}).get('id') == v2.ADAPTER,
                        'An admitted DBG plan cannot declare FM mask ranges')
                normalized = deepcopy(plan)
                normalized.pop('mask_ranges')
                # Exactly the frozen V2 compatibility operation, before the
                # unmodified Factory target-claim path. No edit is filtered.
                result = {**result, 'plan': normalized}
                scope.require(scope.CLAUSES[ctx.mode] in normalized['public_instruction']
                        and fm.RULE in normalized['public_rules'], 'The admitted plan omits its explicit public scope or input priority')
                return receipt(ctx, 'plan', selected, result,
                    removed_empty_FM_only_range_field=True,
                    before_plan_sha256=scope.canonical(plan),
                    after_plan_sha256=scope.canonical(normalized),
                    edits_sha256=scope.canonical(normalized['edits']))
        scope.require('mask_ranges' not in result['plan'] or selected == 'full_state_fm',
                'A DBG provider returned an FM-only mask field')
        scope.require(scope.CLAUSES[ctx.mode] in result['plan']['public_instruction']
                and fm.RULE in result['plan']['public_rules'], 'The admitted plan omits its explicit public scope or input priority')
        return receipt(ctx, 'plan', selected, result, removed_empty_FM_only_range_field=False)


class FullStateJointConstructNode(BaseNode):
    node_id = 'construct'

    def execute(self, ctx):
        selected = route(ctx)
        if selected == 'full_state_fm':
            result = construction.ConstructNode().execute(ctx)
        elif selected == 'full_graph_v2':
            result = scc_activity.SCCConstructNode().execute(ctx)
        else:
            result = v3.SemanticGraphConstructNode().execute(ctx)
        return receipt(ctx, 'construct', selected, result)


class FullStateJointControlsNode(BaseNode):
    node_id = 'precheck'

    def execute(self, ctx):
        selected = route(ctx)
        result = (construction.ControlsNode().execute(ctx) if selected == 'full_state_fm'
                  else joint_controls.JointObservableControlsNode().execute(ctx))
        return receipt(ctx, 'precheck', selected, result)
