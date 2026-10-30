"""Prospective FM completion of financial calculations and explicit state fields.

Selection uses public field identities. It does not change source definitions or
certify quality, recovery, controls, uniqueness, or difficulty.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import openpyxl
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils import get_column_letter

from ..core.node import BaseNode, TaskRejected
from ..workbook.composite_finance import tasks as monetary
from ..workbook.derived_gold.task_templates import _formula_rectangles
from .public_input_priority import RULE
from .public_workbook_scope import (
    CLAUSES, ScopePlanNode, canonical, checked_bytes, read, reference, require,
)

POLICY = 'composite_full_state_fm'
VERSION = 1
LEASE_FIELDS = tuple(sorted(monetary._LEASE_STATE))
COVENANT_FIELDS = ('test_due', 'test_passed', 'lock_open', 'passes_open', 'passes_close', 'lock_close')
PARTNER_FIELDS = ('hurdle_xnpv', 'carry_rate', 'next_carry_rate', 'flip_earned',
                  'flip_effective_year', 'lp_sign_changes', 'lp_xirr_eligible', 'lp_last_nonzero_sign')
POLICY_SPEC = {
    'kind': 'composite_full_state_fm_policy', 'version': VERSION,
    'selection': 'existing_financial_targets_union_explicit_contractual_states',
    'lease_fields': list(LEASE_FIELDS), 'covenant_fields': list(COVENANT_FIELDS),
    'partner_fields': list(PARTNER_FIELDS),
    'operating_cash_fields': ['optional_allocation_allowed'],
    'operating_valuation_fields': ['annual_discount_rate', 'monthly_discount_rate'],
    'lease_count': 4, 'lease_months': 240, 'operating_months': 36, 'partner_years': 20,
    'additional_state_cells': 13854,
    'provided': ['dates', 'calendars', 'period_identifiers', 'ramp_factors',
                 'source_anchors', 'scenario_displays', 'empty_unqualified_XIRR_results'],
    'public_scope_clause': CLAUSES['financial_modeling'],
}

# These are encoding and observation-stage definitions, not computed answers.
STATE_RULES = (
    'All state flags use numeric 1 for true and numeric 0 for false.',
    'Lease event_flag is 1 only in a month with a stated event.',
    'Lease event_kind_code uses 0 for no event, 1 for index, 2 for modification, 3 for partial_termination and 4 for termination.',
    'Lease event_index_ratio, event_new_rate and event_new_end display 0 when their event input is absent.',
    'Lease event_retention_fraction displays 1 when its event input is absent.',
    'Lease event_rate_changed is 1 when a new rate is supplied, including a supplied zero rate.',
    'Lease annual_discount_rate records the current contractual rate after the event. An absent new rate retains the previous rate.',
    'Lease lease_current_end_month starts at the contractual end month. A supplied new end replaces it.',
    'A full termination sets lease_current_end_month to the event month minus one.',
    'Lease active_flag observes state after the event. It requires positive retained exposure and a month within the current lease term.',
    'Lease measurement_flag is 1 only for an active commencement month or active event month.',
    'Lease index factor, retained exposure and discount-rate states follow the existing contract precision rules.',
    'Operating test_passed is 0 in a month without a covenant test. Non-test months retain the lock and cure counter.',
    'Operating lock_open and passes_open precede the current test. lock_close and passes_close follow that test.',
    'The Operating cure counter stops at 2. The initial lock and counter are 0.',
    'Operating optional_allocation_allowed depends only on the stated allocation-start month. The distribution lock does not change this flag.',
    'Partner carry_rate applies during the current year. next_carry_rate records the closing decision for the following year.',
    'Partner flip_earned is 1 only in the year when the permanent flip is first earned.',
    'Partner flip_effective_year is 0 before a flip is earned. It then retains the first year with the higher carry.',
    'Partner lp_sign_changes counts changes between successive nonzero LP cash-flow signs, including the opening contribution.',
    'Partner lp_last_nonzero_sign is -1 or 1. A zero cash flow retains the preceding nonzero sign.',
    'Partner lp_xirr_eligible is 1 only after both signs occur with exactly one negative-to-positive sign change.',
    'Partner hurdle_xnpv uses the existing unrounded, dated hurdle test. Unqualified empty lp_xirr results remain provided.',
)

INSTRUCTION = (
    'Complete the missing financial calculations and contractual-state calculations in this integrated financing model. '
    'Use the provided public business briefs and contractual inputs. Complete the connected lease measurements, '
    'regulatory capital and tax recovery, same-year contingent rents, operating investment, parent funding, '
    'partnership distributions and consolidated statements. Complete the missing lease event and contract states, '
    'operating allocation and covenant states, discount-rate displays and partnership qualification states. '
    'Apply the state conventions below. Dates, calendars, period identifiers, ramp factors, source anchors and '
    'scenario displays remain provided. Preserve provided calculations, inputs, labels, currencies and ownership interests. '
    'The published regulatory workbook supplies background for the separately stated hypothetical programme. '
    'Save the completed workbook to the required output path.\n\n'
) + CLAUSES['financial_modeling']


def load_policy(record):
    value = read(record)
    require(type(value.get('version')) is int and canonical(value) == canonical(POLICY_SPEC),
            'Full-state FM policy differs from its frozen version')
    return value


def mask_cells(plan):
    """Expand only the declared rectangles, with explicit overlap rejection."""
    result = set()
    for item in plan['mask_ranges']:
        left, top, right, bottom = range_boundaries(item['range'])
        for row in range(top, bottom + 1):
            for column in range(left, right + 1):
                key = (item['sheet'], get_column_letter(column) + str(row))
                require(key not in result, 'Full-state FM mask rectangles overlap')
                result.add(key)
    return result


def state_cells(book, cached):
    """Select the predeclared state rows and fail closed on unsupported caches."""
    require(monetary._financial_scope(book)['version'] == 'composite_financial_only_v4',
            'Full-state FM requires explicit contingent and partner contracts')
    leases = monetary._lease_sheets(book)
    require(len(leases) == POLICY_SPEC['lease_count'], 'Unsupported lease count for full-state FM')
    selected = {}

    def add(sheet, field, columns):
        row = monetary._row(book[sheet], monetary._label(field))
        for column in columns:
            cell = book[sheet].cell(row, column)
            cache = cached[sheet][cell.coordinate]
            require(cell.data_type == 'f' and isinstance(cell.value, str),
                    'A selected state must be an existing scalar formula: ' + sheet + '!' + cell.coordinate)
            require(type(cache.value) in (int, float) and math.isfinite(cache.value)
                    and cache.data_type != 'e' and not monetary._is_date_formula(cell, cache),
                    'A selected state requires a finite numeric cache: ' + sheet + '!' + cell.coordinate)
            key = (sheet, cell.coordinate)
            require(key not in selected, 'Duplicate full-state FM state target')
            selected[key] = field

    for name in leases:
        for field in LEASE_FIELDS:
            add(name, field, range(3, POLICY_SPEC['lease_months'] + 3))
    for field in COVENANT_FIELDS:
        add('Operating Covenants', field, range(3, POLICY_SPEC['operating_months'] + 3))
    add('Operating Cash Flow', 'optional_allocation_allowed', range(3, POLICY_SPEC['operating_months'] + 3))
    for field in POLICY_SPEC['operating_valuation_fields']:
        add('Operating Equity Value', field, [2])
    for field in PARTNER_FIELDS:
        add('Partner Waterfall', field, range(3, POLICY_SPEC['partner_years'] + 3))
    require(len(selected) == POLICY_SPEC['additional_state_cells'], 'Full-state FM state coverage differs')
    return selected


def propose_task(baseline, mode='financial_modeling'):
    """Produce a new declarative FM plan, without writing a workbook or calling LO."""
    if mode != 'financial_modeling':
        raise TaskRejected('Full-state FM provider requires financial_modeling mode')
    original = monetary.propose_task(Path(baseline), mode)
    previous = mask_cells(original)
    book = openpyxl.load_workbook(baseline, keep_links=False)
    cached = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    try:
        states = state_cells(book, cached)
        require(not (previous & states.keys()), 'Financial target policy already includes a declared state field')
        union = previous | states.keys()
        result = deepcopy(original)
        ranges = []
        for name in book.sheetnames:
            coordinates = {(book[name][address].row, book[name][address].column)
                           for sheet, address in union if sheet == name}
            if coordinates:
                for item in _formula_rectangles(name, coordinates):
                    item.update(reason='Complete the connected financial model and its stated contractual states.',
                        business_rule='Use the provided public module contracts and explicit state conventions.')
                    ranges.append(item)
        result['mask_ranges'] = ranges
        require(mask_cells(result) == union, 'Full-state FM rectangle coverage differs from the exact target union')
        result['title'] = 'Complete the integrated financial model and contractual states'
        result['public_instruction'] = INSTRUCTION
        result['public_rules'] = list(dict.fromkeys([*original['public_rules'], RULE, *STATE_RULES]))
        result['reference_evidence'] = [text for text in original['reference_evidence']
            if not text.startswith('Financial-only reconstruction scope:')]
        result['reference_evidence'].append(
            'Financial and explicit contractual-state completion. Dates, calendars, identifiers, ramp factors, '
            'source anchors, scenario displays and empty unqualified XIRR results remain provided.')
        result['full_state_fm_selection'] = {
            'version': VERSION, 'original_financial_target_count': len(previous),
            'additional_state_target_count': len(states), 'target_count': len(union),
            'original_financial_targets_sha256': canonical(sorted(previous)),
            'additional_state_targets_sha256': canonical(sorted(states)),
            'all_targets_sha256': canonical(sorted(union)),
            'original_financial_targets_preserved_exactly': True,
            'quality_or_difficulty_certified': False,
        }
        return result
    finally:
        book.close()
        cached.close()


def audit_target_coverage(baseline, plan, finance_evidence):
    """Bind targets to the original five cell audits and original batch receipts."""
    require(finance_evidence.get('financial_seed_verified') is True, 'Full-state FM requires a verified financial source')
    proof = finance_evidence.get('audited_source_binding')
    require(isinstance(proof, dict), 'Full-state FM requires complete source audit references')
    source = reference(baseline)
    require(source['sha256'] == proof.get('workbook', {}).get('sha256'), 'Full-state FM baseline differs from the audited source')
    checked_bytes({**reference(proof['workbook']['path']), 'sha256': proof['workbook']['sha256']})
    manifest = json.loads(Path(proof['source_manifest']['path']).read_bytes())
    # Verify declared hashes, rather than replacing them with current file hashes.
    for name in ('source_manifest', 'provided_context_audit', 'public_scenarios', 'financial_audit_summary', 'stability'):
        record = proof[name]
        checked_bytes({**reference(record['path']), 'sha256': record['sha256']})
    require(manifest.get('status') == 'independently_verified_composed_financial_seed'
            and manifest.get('derived_workbook_sha256') == source['sha256'], 'Full-state FM source manifest differs')
    batch_record = finance_evidence.get('source_batch_manifest')
    batch = read({**reference(batch_record['path']), 'sha256': batch_record['sha256']})
    require(batch.get('status') == 'independently_verified_composed_financial_seed_batch'
            and batch.get('mode') == 'build' and batch.get('recipe_unchanged') is True,
            'Full-state FM requires the original verified build batch')
    attempts = [a for a in batch.get('attempts', []) if a.get('stage') == 'build' and a.get('status') == 'verified'
                and a.get('verification', {}).get('workbook', {}).get('sha256') == source['sha256']]
    require(len(attempts) == 1, 'Full-state FM source has no unique original verified build attempt')
    verification = attempts[0]['verification']
    verification_sha = hashlib.sha256(json.dumps(verification, sort_keys=True).encode()).hexdigest()
    require(verification_sha == proof.get('original_build_verification_sha256'),
            'Original full-state FM build verification binding changed')

    def verify_refs(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                checked_bytes(value)
            for item in value.values():
                verify_refs(item)
        elif isinstance(value, list):
            for item in value:
                verify_refs(item)
    verify_refs(verification)
    checked_bytes(attempts[0]['source_manifest'])
    require(attempts[0]['source_manifest']['sha256'] == proof['source_manifest']['sha256']
            and attempts[0]['source_manifest']['path'] == proof['source_manifest']['path'],
            'Original build source manifest differs')
    modules = {'lease', 'programme', 'operating', 'holding', 'contingent'}
    require(set(proof['independent_financial_audits']) == set(verification['component_audits']) == modules,
            'Full-state FM requires exactly the five original financial audits')
    coverage = {}
    audit_refs = {}
    for module in sorted(modules):
        record = proof['independent_financial_audits'][module]
        original = verification['component_audits'][module]
        require(record['path'] == original['path'] and record['sha256'] == original['sha256'],
                'Full-state FM audit differs from the original build receipt')
        audit = read(original)
        require(audit.get('passed') is True and audit.get('workbook', {}).get('sha256') == source['sha256'],
                'Full-state FM financial audit failed or belongs to another workbook')
        require(len(audit['cell_checks']) == record['checked_cells'] == audit['checked_cells'],
                'Full-state FM financial audit coverage count changed')
        audit_refs[module] = original
        for index, item in enumerate(audit['cell_checks']):
            require(item.get('passed', item.get('matched')) is True, 'Full-state FM contains a failed cell audit')
            sheet, address = item['address'].rsplit('!', 1)
            if module == 'operating':
                sheet = 'Operating ' + sheet
            key = (sheet, address)
            require(key not in coverage, 'Full-state FM cell has ambiguous independent audit ownership')
            coverage[key] = {'module': module, 'cell_check_index': index}
    targets = mask_cells(plan)
    require(targets <= coverage.keys(), 'Full-state FM includes a target without an original independent cell audit')
    return {'kind': 'full_state_FM_original_audit_target_coverage', 'source': source,
        'source_manifest': deepcopy(proof['source_manifest']), 'source_batch_manifest': deepcopy(batch_record),
        'original_build_verification_sha256': verification_sha, 'audits': audit_refs,
        'target_count': len(targets), 'all_targets_independently_audited': True,
        'cell_proofs': [{'sheet': sheet, 'cell': address, **coverage[(sheet, address)]}
                        for sheet, address in sorted(targets)],
        'LO_calls': 0, 'model_calls': 0, 'quality_or_difficulty_certified': False}


class FullStateFMPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        setting = ctx.config.get(POLICY)
        if setting is None:
            return ScopePlanNode().execute(ctx)
        require(isinstance(setting, dict) and type(setting.get('version')) is int
                and setting['version'] == VERSION and set(setting) == {'version', 'policy'},
                'Unsupported full-state FM opt-in')
        load_policy(setting['policy'])
        require(ctx.mode == 'financial_modeling' and ctx.data.get('variant', 0) == 0,
                'Full-state FM requires a new financial_modeling source identity')
        construction = ctx.config.get('construction', {})
        require(construction.get('authoring_backend') == 'composite_template'
                and construction.get('planning_scope') == 'per_mode', 'Full-state FM requires explicit per-mode composite planning')
        require(reference(ctx.source)['sha256'] == reference(ctx.data['baseline'])['sha256']
                == ctx.data.get('source_id'), 'Full-state FM must preserve the exact audited baseline')
        plan = propose_task(ctx.data['baseline'], ctx.mode)
        evidence = ctx.data.get('finance_evidence', {})
        proof = audit_target_coverage(ctx.data['baseline'], plan, evidence)
        proof['policy'] = deepcopy(setting['policy'])
        proof['plan_sha256'] = canonical(plan)
        ctx.save('composite_full_state_fm_application.json', proof)
        return {'plan': plan, 'source_assessment': {'financial_evidence': deepcopy(evidence),
            'authoring_backend': POLICY, 'known_risks': [], 'full_state_policy': deepcopy(setting['policy']),
            'quality_or_difficulty_certified': False}}
