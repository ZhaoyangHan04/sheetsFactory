"""Prospective public workbook scope, composed with input-priority routing."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ..core.node import BaseNode, TaskRejected
from .public_input_priority import PriorityPlanNode, PriorityRepairNode

POLICY = 'public_workbook_scope'
VERSION = 1
COMMON_SCOPE = (
    "Keep exactly the input workbook's worksheet names and order; do not add, remove or rename worksheets. "
    "Edit only existing model cells needed for the requested completion or repair. "
)
PRESERVATION = 'Preserve provided inputs and unrelated formulas; allow dependent formula results to recalculate.'
CLAUSES = {
    'financial_modeling': COMMON_SCOPE + (
        'Do not add helper cells or populate otherwise blank cells. The only exception is completing the missing '
        'financial formulas identified by this task, without expanding the stated targets. '
    ) + PRESERVATION,
    'debugging': COMMON_SCOPE + (
        'Do not add helper cells or populate originally blank cells with new values or formulas. '
    ) + PRESERVATION,
}
PLAN_NODE = 'sheets_factory.task_adapters.public_workbook_scope:ScopePlanNode'
FULL_GRAPH_PLAN_NODE = 'sheets_factory.task_adapters.public_workbook_scope:ScopeFullGraphPlanNode'
REPAIR_NODE = 'sheets_factory.task_adapters.public_workbook_scope:ScopeRepairNode'


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Scope artifact must be a regular non-symlink file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def checked_bytes(record):
    require(isinstance(record, dict) and isinstance(record.get('path'), str), 'Missing scope artifact reference')
    path = Path(record['path'])
    require(path.is_absolute() and path == path.resolve() and path.is_file(), 'Unsafe scope artifact path')
    raw = path.read_bytes()
    require(type(record.get('bytes')) is int and record['bytes'] == len(raw)
            and hashlib.sha256(raw).hexdigest() == record.get('sha256'), 'Scope artifact bytes or SHA changed')
    return raw


def read(record):
    value = json.loads(checked_bytes(record).decode('utf-8'))
    require(isinstance(value, dict), 'Scope artifact must contain a JSON object')
    return value


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def registry_nodes(base):
    """Keep Construct and every quality node exactly as selected by the caller."""
    require(isinstance(base, dict) and {'plan', 'repair'} <= set(base), 'Incomplete base node registry')
    permitted_plan = {'sheets_factory.nodes.construction:PlanNode': PLAN_NODE,
        'sheets_factory.task_adapters.public_input_priority:PriorityPlanNode': PLAN_NODE,
        'sheets_factory.pipelines.scc_activity_admission:FullGraphSCCPlanNode': FULL_GRAPH_PLAN_NODE,
        PLAN_NODE: PLAN_NODE, FULL_GRAPH_PLAN_NODE: FULL_GRAPH_PLAN_NODE}
    permitted_repair = {'sheets_factory.nodes.quality:RepairNode',
        'sheets_factory.task_adapters.public_input_priority:PriorityRepairNode', REPAIR_NODE}
    require(base['plan'] in permitted_plan and base['repair'] in permitted_repair,
            'Unknown plan/repair wrapper cannot be silently replaced')
    result = deepcopy(base)
    result.update(plan=permitted_plan[base['plan']], repair=REPAIR_NODE)
    return result


def append_scope(plan, mode):
    require(mode in CLAUSES, 'Unsupported public workbook scope mode')
    require(isinstance(plan.get('public_instruction'), str) and plan['public_instruction'].strip(),
            'Scope requires an existing public instruction')
    result = deepcopy(plan)
    if CLAUSES[mode] not in result['public_instruction']:
        result['public_instruction'] = result['public_instruction'].rstrip() + '\n\n' + CLAUSES[mode]
    return result


def binding(ctx):
    setting = ctx.config.get(POLICY)
    if setting is None:
        return None, None
    require(isinstance(setting, dict) and type(setting.get('version')) is int
            and setting['version'] == VERSION, 'Unsupported public workbook scope policy')
    manifest = read(setting.get('manifest'))
    require(manifest.get('kind') == 'public_workbook_scope_binding'
            and type(manifest.get('version')) is int and manifest['version'] == VERSION
            and manifest.get('clauses') == CLAUSES,
            'Public scope binding policy or clauses differ')
    actual = reference(ctx.source)
    source_id = ctx.data.get('source_id', actual['sha256'])
    require(source_id == actual['sha256'], 'Public scope source identity changed')
    source = manifest.get('sources', {}).get(source_id)
    require(isinstance(source, dict) and source.get('source') == actual,
            'Public scope source is not explicitly bound')
    checked_bytes(source['source'])
    require(manifest.get('quality_or_difficulty_certified') is False,
            'A public scope binding cannot certify quality or difficulty')
    return manifest, source


def validate_authorization(ctx, manifest, source):
    auth = manifest.get('tasks', {}).get(ctx.task_id)
    if auth is None:
        return None
    require(type(auth.get('revision')) is int and ctx.revision == auth['revision']
            and auth.get('source_sha256') == source['source']['sha256'], 'Stale scope repair task or source')
    for name in ('plan', 'baseline', 'goal', 'input', 'instruction', 'diagnosis', 'program_review'):
        checked_bytes(auth[name])
    require(canonical(ctx.data['plan']) == canonical(read(auth['plan'])), 'Scope repair plan changed')
    require(auth['baseline']['sha256'] == auth['goal']['sha256'] == source['source']['sha256'],
            'Scope repair cannot change the immutable source or numeric reference')
    require(hashlib.sha256(checked_bytes(auth['input']) + checked_bytes(auth['instruction'])).hexdigest()
            == auth.get('revision_hash'), 'Scope repair public revision changed')
    old = read(auth['diagnosis'])
    require(old.get('task_revision_hash') == auth['revision_hash'], 'Original scope diagnosis belongs to another revision')
    review = read(auth['program_review'])
    require(review.get('task_id') == ctx.task_id and review.get('revision') == ctx.revision
            and review.get('revision_hash') == auth['revision_hash'], 'Scope review header differs')
    issues = review.get('issues', [])
    require(isinstance(issues, list) and issues, 'Scope review has no confirmed issue')
    for issue in issues:
        require(issue.get('task_id') == ctx.task_id and issue.get('revision') == ctx.revision
                and issue.get('revision_hash') == auth['revision_hash']
                and issue.get('problem_id') == 'Q03' and issue.get('route_id') == 'R03'
                and issue.get('certainty') == 'confirmed' and issue.get('evidence'),
                'Scope review is not an exact confirmed Q03/R03 issue')
        for evidence in issue['evidence']:
            checked_bytes(evidence)
    require(len(set(auth['authorized_issue_ids'])) == len(auth['authorized_issue_ids'])
            and set(auth['authorized_issue_ids']) == {issue['issue_id'] for issue in issues},
            'Scope authorization differs from the reviewed issues')
    return auth


class ScopePlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        manifest, source = binding(ctx)  # Reject bad opt-ins before planning.
        result = PriorityPlanNode().execute(ctx)
        if manifest is None:
            return result
        plan = append_scope(result['plan'], ctx.mode)
        ctx.save('public_workbook_scope_application.json', {'version': VERSION,
            'source': source['source'], 'clause': CLAUSES[ctx.mode],
            'changed_plan_fields': ['public_instruction'],
            'before_plan_sha256': canonical(result['plan']), 'after_plan_sha256': canonical(plan),
            'quality_or_difficulty_certified': False})
        return {**result, 'plan': plan}


class ScopeFullGraphPlanNode(BaseNode):
    """An explicit future registry can preserve the frozen joint-plan provider."""
    node_id = 'plan'

    def execute(self, ctx):
        manifest, source = binding(ctx)
        # Import only on this explicit route; legacy/FM never use the adapter.
        from ..pipelines.scc_activity_admission import FullGraphSCCPlanNode
        result = FullGraphSCCPlanNode().execute(ctx)
        if manifest is None:
            return result
        require(ctx.mode == 'debugging', 'Full-graph scope wrapper requires debugging mode')
        plan = append_scope(result['plan'], ctx.mode)
        ctx.save('public_workbook_scope_application.json', {'version': VERSION,
            'source': source['source'], 'clause': CLAUSES[ctx.mode],
            'wrapped_plan_provider': 'FullGraphSCCPlanNode',
            'changed_plan_fields': ['public_instruction'],
            'before_plan_sha256': canonical(result['plan']), 'after_plan_sha256': canonical(plan),
            'quality_or_difficulty_certified': False})
        return {**result, 'plan': plan}


class ScopeRepairNode(BaseNode):
    node_id = 'repair'

    def execute(self, ctx):
        manifest, source = binding(ctx)
        if manifest is None or ctx.task_id not in manifest.get('tasks', {}):
            return PriorityRepairNode().execute(ctx)
        routes = ctx.data.get('repair_routes', [])
        declared = manifest['tasks'][ctx.task_id].get('authorized_issue_ids', [])
        if not routes or any(route.get('issue_id') not in declared or route.get('problem_id') != 'Q03'
                             for route in routes):
            return PriorityRepairNode().execute(ctx)
        auth = validate_authorization(ctx, manifest, source)
        require(all(route.get('route_class') == 'repair' and route.get('route_id') == 'R03' for route in routes)
                and {route['issue_id'] for route in routes} == set(auth['authorized_issue_ids']),
                'Scope repair route differs from its exact authorization')
        issues = {issue['issue_id']: issue for issue in ctx.data.get('diagnosis', {}).get('issues', [])}
        require(all(issues.get(route['issue_id'], {}).get('problem_id') == 'Q03'
                    and issues[route['issue_id']].get('certainty') == 'confirmed' for route in routes),
                'Scope repair requires the reviewed issue in the current diagnosis')
        proposed = append_scope(ctx.data['plan'], ctx.mode)
        if proposed == ctx.data['plan']:
            raise TaskRejected('Public workbook scope is already explicit; no repair progress')
        ctx.save('public_workbook_scope_repair.json', {'version': VERSION,
            'source': source['source'], 'assigned_issue_ids': list(auth['authorized_issue_ids']),
            'clause': CLAUSES[ctx.mode], 'changed_plan_fields': ['public_instruction'],
            'before_plan_sha256': canonical(ctx.data['plan']), 'after_plan_sha256': canonical(proposed),
            'old_diagnostics_cleared': False, 'numeric_reference_unchanged': True,
            'requires_full_new_revision_quality': True, 'reuse_old_harbor_controls': False,
            'new_five_local_controls_public_recovery_all12_diagnostics_and_actual_harbor_required': True,
            'quality_or_difficulty_certified': False})
        return {'next_plan': proposed}
