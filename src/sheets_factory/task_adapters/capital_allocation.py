"""Normal financial-model construction for an audited common investment plan."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl

from ..core.node import BaseNode, TaskRejected
from ..nodes.construction import ConstructNode
from ..task_adapters.public_input_priority import canonical
from ..task_adapters.public_workbook_scope import CLAUSES, checked_bytes, reference, require
from ..task_adapters.lease_family import NS, _paths
from ..workbook import compare_workbooks

SETTING = 'capital_allocation_task'
ADAPTER_ID = 'capital_allocation_fm_v1'
PUBLIC_INSTRUCTION = (
    'Select one common investment plan for the three scenarios that maximises the worst '
    'scenario LP net present value, and complete the missing financial model. Use the '
    'supplied policies in Capital Rules and the public primitives in Capital Contract '
    'and Capital Inputs. Enter each shared project choice as 0 or 1. Preserve the supplied '
    'inputs and arithmetic support formulas; allow their results to recalculate. '
    + CLAUSES['financial_modeling']
)


def source_admission():
    return importlib.import_module('sheets_factory.pipelines.capital_allocation_admission')


def setting():
    from ..nodes import construction
    admission = source_admission()
    return {'enabled': True, 'version': 1, 'adapter': ADAPTER_ID,
        'implementation': reference(__file__), 'ordinary_construction': reference(construction.__file__),
        'source_admission': reference(admission.__file__),
        'mask_scope': 'all_financial_bindings_and_shared_eighteen_decisions',
        'helper_values_are_protected': False}


def validate_setting(value):
    require(isinstance(value, dict) and value == setting(),
            'The explicit capital-allocation task adapter or implementation changed')
    return value


def _read(record):
    return json.loads(checked_bytes(record))


def _targets(binding):
    financial, decisions, support = (binding.get(key) for key in
        ('financial_bindings', 'decision_bindings', 'arithmetic_bindings'))
    require(isinstance(financial, list) and len(financial) >= 6
            and isinstance(decisions, list) and len(decisions) == 18
            and isinstance(support, list) and binding.get('gold_plan_supplied') is True,
            'The audited complete financial and eighteen-decision bindings are required')
    require(all(item.get('target_eligible') is True for item in financial + decisions)
            and all(item.get('target_eligible') is False and item.get('value_protected') is False
                    for item in support),
            'Arithmetic support eligibility cannot become a mask or a protected value')
    from ..workbook.capital_allocation.spec import PROJECT_IDS
    require([item.get('project_id') for item in decisions] == list(PROJECT_IDS),
            'The full ordered common investment decision set is required')
    selected = [(item['sheet'], item['cell']) for item in financial + decisions]
    helpers = {(item['sheet'], item['cell']) for item in support}
    require(len(set(selected)) == len(selected) and len(helpers) == len(support)
            and not set(selected) & helpers, 'Financial targets and arithmetic support overlap or repeat')
    return financial + decisions, support


def propose_capital_allocation_task(baseline, source_manifest):
    """Compile exactly the declared financial targets; no planner model runs."""
    proof = source_admission().validate_source(source_manifest)
    return _propose_from_checked_proof(baseline, proof)


def _propose_from_checked_proof(baseline, proof):
    """Reuse the source proof checked by this node; never cache it across nodes."""
    require(reference(baseline)['sha256'] == proof['workbook']['sha256'],
            'The task baseline differs from the admitted actual source workbook')
    binding = _read(proof['bindings'])
    targets, support = _targets(binding)
    book = openpyxl.load_workbook(baseline, keep_links=False)
    edits = []
    try:
        for item in targets:
            cell = book[item['sheet']][item['cell']]
            require(cell.data_type == 'f' and isinstance(cell.value, str) and cell.value.startswith('='),
                    'Every financial target must be an existing supported source formula')
            edits.append({'sheet': item['sheet'], 'cell': item['cell'], 'before': cell.value,
                'after': None, 'reason': 'Complete the common investment plan and connected financial forecast.',
                'business_rule': 'Apply the complete public Capital Rules and Capital Contract.'})
        for item in support:
            cell = book[item['sheet']][item['cell']]
            require(cell.data_type == 'f' and isinstance(cell.value, str),
                    'A declared arithmetic support formula is absent')
    finally:
        book.close()
    return {'public_instruction': PUBLIC_INSTRUCTION,
        'public_rules': ['The same eighteen choices govern all three scenarios.',
            'Use the complete workbook contract; dependent support values are recalculated and checked.'],
        'reference_evidence': [{'kind': 'complete_independent_capital_allocation_source_admission',
            'source_manifest': proof['source_manifest'], 'audited_source_binding': proof}],
        'edits': edits, 'scenario_inputs': [],
        'family_adapter': {'id': ADAPTER_ID, 'source_manifest': proof['source_manifest'],
            'source_sha256': proof['workbook']['sha256'], 'bindings': proof['bindings'],
            'financial_target_count': len(binding['financial_bindings']), 'decision_target_count': 18,
            'physical_target_count': len(edits), 'provided_arithmetic_count': len(support),
            'plan_dependent_support_count': sum(item.get('plan_dependent') is True for item in support),
            'helper_values_are_protected': False, 'full_workbook_D_required': True}}


def _context(ctx):
    validate_setting(ctx.config.get(SETTING))
    require(ctx.mode == 'financial_modeling', 'This adapter supports financial modelling only')
    evidence = ctx.data.get('finance_evidence', {})
    require(evidence.get('financial_seed_verified') is True
            and evidence.get('financial_modeling_eligible') is True,
            'Capital-allocation tasks require a verified financial source')
    proof = source_admission().validate_source(evidence['source_manifest'])
    require(evidence.get('audited_source_binding') == proof
            and reference(ctx.source)['sha256'] == proof['workbook']['sha256']
            and reference(ctx.data['baseline'])['sha256'] == proof['workbook']['sha256'],
            'The source, normalized baseline or complete financial proof changed')
    return proof


def _physical(edits):
    return [{key: item[key] for key in ('sheet', 'cell', 'before', 'after')} for item in edits]


def audit_input_helper_caches(goal, draft, bindings):
    """Check the actual normal draft, rather than trusting an eligibility flag."""
    targets, support = _targets(bindings)
    selected = {(item['sheet'], item['cell']) for item in targets}
    originals = openpyxl.load_workbook(goal, keep_links=False)
    raw = openpyxl.load_workbook(draft, keep_links=False)
    try:
        require(originals.sheetnames == raw.sheetnames, 'Task construction changed source structure')
        for sheet in originals:
            other = raw[sheet.title]
            coordinates = set(sheet._cells) | set(other._cells)
            for row, column in coordinates:
                before, after = sheet.cell(row, column), other.cell(row, column)
                if (sheet.title, before.coordinate) in selected:
                    require(after.value is None, 'A declared financial or decision target was not physically masked')
                else:
                    require(before.data_type == after.data_type and before.value == after.value,
                            'An unselected definition or public primitive was changed')
        with ZipFile(draft) as archive:
            paths = _paths(archive)
            documents = {}
            cleared = []
            for item in support:
                if item.get('plan_dependent') is not True:
                    continue
                sheet = item['sheet']
                if sheet not in documents:
                    documents[sheet] = {cell.get('r'): cell for cell in
                        ET.fromstring(archive.read(paths[sheet])).findall('.//m:sheetData/m:row/m:c', NS)}
                cell = documents[sheet].get(item['cell'])
                require(cell is not None and cell.find('m:f', NS) is not None,
                        'Plan-dependent arithmetic must retain its supplied formula')
                cached = cell.find('m:v', NS)
                require((cached is None or not (cached.text or '').strip()) and cell.find('m:is', NS) is None,
                        'A plan-dependent arithmetic cell retained a gold cached value')
                cleared.append(sheet + '!' + item['cell'])
    finally:
        originals.close(); raw.close()
    return {'passed': True, 'goal': reference(goal), 'actual_normal_draft': reference(draft),
        'masked_financial_and_decision_count': len(targets),
        'provided_helper_formula_count': len(support), 'plan_dependent_caches_cleared_count': len(cleared),
        'cleared_support_coordinates_sha256': canonical(cleared),
        'unselected_definitions_and_public_primitives_unchanged': True,
        'helpers_physically_masked': False, 'helper_values_protected': False,
        'actual_input_recalculation_and_complete_D_still_required': True}


class CapitalAllocationPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        proof = _context(ctx)
        plan = _propose_from_checked_proof(ctx.data['baseline'], proof)
        ctx.save('capital_allocation_plan_binding.json', {
            'source_manifest': proof['source_manifest'], 'source': proof['workbook'],
            'physical_edits_sha256': canonical(_physical(plan['edits'])),
            'physical_target_count': len(plan['edits']), 'quality_or_difficulty_certified': False})
        return {'plan': plan, 'source_assessment': {'financial_evidence': ctx.data['finance_evidence'],
            'authoring_backend': ADAPTER_ID, 'full_quality_and_difficulty_pending': True}}


class CapitalAllocationConstructNode(ConstructNode):
    node_id = 'construct'

    def execute(self, ctx):
        proof = _context(ctx)
        expected = _propose_from_checked_proof(ctx.data['baseline'], proof)
        plan = ctx.data['plan']
        require(plan.get('family_adapter') == expected['family_adapter']
                and not plan.get('scenario_inputs') and 'mask_ranges' not in plan
                and _physical(plan.get('edits', [])) == _physical(expected['edits']),
                'The complete financial/decision target scope changed or was reduced')
        result = super().execute(ctx)
        bindings = _read(proof['bindings'])
        receipt = audit_input_helper_caches(result['goal'],
            ctx.revision_dir / 'private/mutated_unrecalculated.xlsx', bindings)
        complete = compare_workbooks(result['input'], result['goal'], result['goal'])
        require(complete == result['delta'], 'Required D was not computed over the complete workbook')
        helper_cells = {item['sheet'] + '!' + item['cell'] for item in bindings['arithmetic_bindings']}
        receipt.update(input=reference(result['input']), goal=reference(result['goal']),
            normal_construct_implementation=setting()['ordinary_construction'],
            actual_recalculation_delegated_to_ordinary_construct=True,
            complete_required_D_count=complete['expected_change_count'],
            changed_helper_count=len(helper_cells & set(complete['expected_changes'])),
            no_helper_values_excluded_from_required_D=True,
            five_controls_recovery_12QA_Harbor_and_difficulty_pending=True)
        ctx.save('capital_allocation_actual_input_scope.json', receipt)
        return {**result, 'capital_allocation_input_scope': receipt}
