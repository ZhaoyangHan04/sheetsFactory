"""Explicit, bounded Q02 repair of capital reporting layout wording only."""
from __future__ import annotations

from copy import deepcopy
import hashlib

from ..core.node import BaseNode
from ..nodes.quality import RepairNode
from . import capital_allocation as original
from .public_workbook_scope import canonical, checked_bytes, read, reference, require

VERSION = 1
SETTING = 'capital_public_schema'
KIND = 'capital_allocation_public_output_schema_repair_policy'
REPAIR_NODE = 'sheets_factory.task_adapters.capital_public_schema:CapitalPublicSchemaRepairNode'
SUMMARY_CLAUSE = (
    'In Capital Summary, rows 3–5 represent S01–S03. Column B is feasibility (1 or 0); '
    'C is diagnostic LP NPV in integer pence under the supplied NPV policy regardless of '
    'feasibility; D equals C when B is 1 and is empty otherwise. B7 is the all-scenario '
    'feasibility flag; D7 is the minimum scenario NPV when all are feasible and is empty otherwise.'
)
PROJECT_CLAUSE = (
    'Each Projects sheet reports all eighteen unweighted candidate asset schedules, including '
    'candidates whose shared choice is 0. Apply the shared 0/1 choices when aggregating candidate '
    'schedules into Annual; do not zero unselected candidates’ individual Projects rows.'
)
CLAUSE = SUMMARY_CLAUSE + '\n\n' + PROJECT_CLAUSE


def setting(manifest):
    return {'version': VERSION, 'manifest': manifest, 'implementation': reference(__file__),
            'original_capital_adapter': reference(original.__file__)}


def registry_nodes(base):
    require(isinstance(base, dict) and base.get('plan') == 'sheets_factory.task_adapters.capital_allocation:CapitalAllocationPlanNode'
            and base.get('construct') == 'sheets_factory.task_adapters.capital_allocation:CapitalAllocationConstructNode'
            and base.get('repair') == 'sheets_factory.nodes.quality:RepairNode'
            and base.get('independent_recovery') == 'sheets_factory.workbook.capital_allocation.public_recovery:CapitalAllocationRecoveryNode',
            'Only the original capital registry can receive the explicit schema repair')
    result = deepcopy(base); result['repair'] = REPAIR_NODE
    return result


def append_schema(plan):
    require(isinstance(plan, dict) and isinstance(plan.get('public_instruction'), str), 'A complete original plan is required')
    require(SUMMARY_CLAUSE not in plan['public_instruction'] and PROJECT_CLAUSE not in plan['public_instruction'],
            'The reporting schema is already explicit or partially applied')
    result = deepcopy(plan)
    result['public_instruction'] += '\n\n' + CLAUSE
    require({k: v for k, v in plan.items() if k != 'public_instruction'}
            == {k: v for k, v in result.items() if k != 'public_instruction'},
            'Public schema clarification cannot change any business or construction field')
    return result


def source_assessment(evidence):
    """Exactly the original CapitalAllocationPlanNode's complete source facts."""
    return {'financial_evidence': deepcopy(evidence), 'authoring_backend': original.ADAPTER_ID,
            'full_quality_and_difficulty_pending': True}


def binding(ctx):
    value = ctx.config.get(SETTING)
    if value is None:
        return None
    require(isinstance(value, dict) and type(value.get('version')) is int and value['version'] == VERSION
            and value == setting(value.get('manifest')), 'The explicit schema repair implementation changed')
    manifest = read(value['manifest'])
    require(manifest.get('kind') == KIND and type(manifest.get('version')) is int and manifest['version'] == VERSION
            and manifest.get('clause') == CLAUSE and manifest.get('quality_or_difficulty_certified') is False,
            'The reviewed public schema policy changed')
    return manifest


class CapitalPublicSchemaRepairNode(BaseNode):
    node_id = 'repair'

    def execute(self, ctx):
        manifest = binding(ctx)
        if manifest is None or ctx.task_id not in manifest.get('tasks', {}):
            return RepairNode().execute(ctx)
        auth = manifest['tasks'][ctx.task_id]
        routes = ctx.data.get('repair_routes', [])
        if not routes or any(route.get('issue_id') not in auth['authorized_issue_ids']
                             or route.get('problem_id') != 'Q02' for route in routes):
            return RepairNode().execute(ctx)
        require(ctx.mode == 'financial_modeling' and type(ctx.revision) is int
                and type(auth.get('revision')) is int and ctx.revision == auth['revision']
                and {route['issue_id'] for route in routes} == set(auth['authorized_issue_ids'])
                and all(route.get('route_id') == 'R02' and route.get('route_class') == 'repair' for route in routes),
                'The exact authorized Q02/R02 repair task or route changed')
        issues = {issue['issue_id']: issue for issue in ctx.data.get('diagnosis', {}).get('issues', [])}
        require(all(issues.get(route['issue_id'], {}).get('problem_id') == 'Q02'
                    and issues[route['issue_id']].get('certainty') == 'confirmed' for route in routes),
                'Schema repair requires the actual confirmed external Q02 issue')
        source = manifest['sources'][auth['source_sha256']]
        for record in manifest['forensic_receipts']:
            checked_bytes(record)
        for key in ('plan', 'input', 'instruction', 'goal', 'baseline', 'diagnosis', 'program_review'):
            checked_bytes(auth[key])
        require(canonical(ctx.data['plan']) == canonical(read(auth['plan']))
                and reference(ctx.source)['sha256'] == source['source']['sha256'] == auth['source_sha256']
                and reference(ctx.data['baseline'])['sha256'] == auth['source_sha256']
                and auth['goal']['sha256'] == auth['source_sha256']
                and hashlib.sha256(checked_bytes(auth['input']) + checked_bytes(auth['instruction'])).hexdigest() == auth['revision_hash'],
                'The original plan, source, reference or public revision changed')
        evidence = ctx.data.get('finance_evidence')
        family = ctx.data['plan'].get('family_adapter', {})
        require(family.get('id') == original.ADAPTER_ID and family.get('physical_target_count') == 19049
                and family.get('financial_target_count') == 19031 and family.get('decision_target_count') == 18
                and len(ctx.data['plan'].get('edits', [])) == 19049,
                'The complete original financial/decision target scope changed')
        require(evidence == source['financial_evidence'], 'The complete original finance evidence was not restored')
        assessment = source_assessment(evidence)
        require(not ctx.data.get('source_assessment') or ctx.data['source_assessment'] == assessment,
                'Existing original source facts differ; schema repair cannot replace business evidence')
        proposed = append_schema(ctx.data['plan'])
        ctx.save('capital_public_schema_repair.json', {'version': VERSION, 'source': source['source'],
            'assigned_issue_ids': auth['authorized_issue_ids'], 'changed_plan_fields': ['public_instruction'],
            'before_plan_sha256': canonical(ctx.data['plan']), 'after_plan_sha256': canonical(proposed),
            'full_source_assessment_restored_from_exact_finance_evidence': True,
            'old_diagnostics_cleared': False, 'old_official_score_changed': False,
            'numeric_reference_unchanged': True, 'target_count_unchanged': 19049,
            'five_controls_public_recovery_all12_diagnostics_actual_Harbor_required': True,
            'quality_or_difficulty_certified': False})
        return {'next_plan': proposed, 'source_assessment': assessment}
