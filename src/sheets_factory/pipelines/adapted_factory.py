"""Explicit source adapters inside the ordinary Factory quality pipeline.

The source proof distinguishes a fresh lease audit from transferred audits.
This module does not certify task activity, quality, recovery, or difficulty.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import openpyxl

from ..core.node import BaseNode
from ..nodes.construction import PlanNode
from .factory import FactoryPipeline

ADAPTER = 'lease_monetary_complete_v1'
SOURCE_KIND = 'derived_active_schedule_presentation'
VALIDATION = 'fresh_independent_lease_plus_transitive_exact_other_modules'
TRANSITIVE = 'transitive_independent_financial_audit_through_full_exact_typed_equivalence'
IMAGE = 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
MODULES = {'lease', 'programme', 'operating', 'holding'}
HISTORICAL_CODE_ROOT = Path(__file__).resolve().parents[1]


class HistoricalRecipeUnavailable(ValueError):
    def __init__(self, record):
        self.reference = deepcopy(record)
        super().__init__('Exact historical ancestor source snapshot unavailable: ' + str(record))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def checked(record, bindings=None):
    require(isinstance(record, dict) and isinstance(record.get('path'), str)
            and isinstance(record.get('sha256'), str), 'A complete artifact reference is required')
    path = Path(record['path']).resolve()
    require(path.is_file() and sha(path) == record['sha256'], 'Changed or missing adapter artifact: ' + str(path))
    if bindings is not None:
        require(str(path) not in bindings or bindings[str(path)] == record['sha256'], 'Conflicting artifact identity')
        bindings[str(path)] = record['sha256']
    return path


def read(record, bindings=None):
    return json.loads(checked(record, bindings).read_text())


def same_reference(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and left.get('sha256') == right.get('sha256') and checked(left) == checked(right))


def collect_references(value, bindings, visited=None, *, historical_recipe_snapshots=None, _historical=False):
    """Rehash the explicit evidence graph, including referenced JSON documents."""
    visited = set() if visited is None else visited
    snapshots = historical_recipe_snapshots or {}
    if isinstance(value, dict):
        if 'portfolio_manifest' in value and 'portfolio_manifest_sha256' in value:
            portfolio_ref = {'path': value['portfolio_manifest'], 'sha256': value['portfolio_manifest_sha256']}
            portfolio_path = checked(portfolio_ref, bindings)
            portfolio = json.loads(portfolio_path.read_text())
            require(portfolio.get('derived_workbook_sha256') == value.get('portfolio_workbook_sha256'),
                    'Portfolio ancestry workbook identity differs')
            checked({'path': portfolio['local_path'], 'sha256': portfolio['derived_workbook_sha256']}, bindings)
            if portfolio_path not in visited:
                visited.add(portfolio_path)
                collect_references(portfolio, bindings, visited, historical_recipe_snapshots=snapshots)
        if 'path' in value and 'sha256' in value:
            path = Path(value['path']).resolve()
            historical_code = (_historical and path.suffix == '.py' and path.is_relative_to(HISTORICAL_CODE_ROOT))
            if historical_code and (not path.is_file() or sha(path) != value['sha256']):
                replacement = snapshots.get(str(path))
                if replacement is None:
                    raise HistoricalRecipeUnavailable(value)
                require(replacement.get('sha256') == value['sha256'], 'Historical ancestor source snapshot SHA differs')
                checked(replacement, bindings)
            else:
                checked(value, bindings)
            if path.suffix.lower() == '.json' and path not in visited:
                visited.add(path)
                collect_references(json.loads(path.read_text()), bindings, visited,
                    historical_recipe_snapshots=snapshots, _historical=_historical)
        for key, child in value.items():
            collect_references(child, bindings, visited, historical_recipe_snapshots=snapshots,
                               _historical=_historical or key in {'recipe', 'recipe_proofs'})
    elif isinstance(value, list):
        for child in value:
            collect_references(child, bindings, visited, historical_recipe_snapshots=snapshots, _historical=_historical)


def _clean_audit(audit, workbook, label):
    require(audit.get('passed') is True and type(audit.get('checked_cells')) is int
            and audit['checked_cells'] > 0, 'Incomplete financial audit: ' + label)
    require(audit.get('workbook', {}).get('sha256') == workbook['sha256']
            and checked(audit['workbook']) == checked(workbook), 'Financial audit workbook differs: ' + label)
    require(not any(audit.get(k) for k in ('mismatches', 'control_mismatches', 'uncovered',
            'uncovered_formulas', 'native_errors', 'invalid_formula_values')), 'Financial audit has findings: ' + label)


def validate_presentation_seed(entry, bindings=None):
    """Validate new bytes and their complete, honestly transferred source proof."""
    bindings = {} if bindings is None else bindings
    require(entry.get('source_kind') == SOURCE_KIND and entry.get('modes') == ['debugging']
            and entry.get('variant', 0) == 0, 'Presentation sources are explicit new debugging identities only')
    manifest_ref = entry.get('source_manifest')
    source = read(manifest_ref, bindings)
    require(source.get('status') == 'actually_verified_active_schedule_source'
            and source.get('financial_audit_passed') is True
            and source.get('financial_validation_method') == VALIDATION, 'Unverified presentation source')
    workbook = reference(entry['local_path'])
    require(workbook['sha256'] == entry.get('sha256') == source.get('derived_workbook_sha256')
            and Path(source['local_path']).resolve() == Path(workbook['path']), 'Presentation source SHA/path differs')
    require(source.get('runtime', {}).get('image') == IMAGE
            and source['runtime'].get('image_id') == IMAGE_ID, 'Presentation source runtime differs')
    require(len(source.get('selected', [])) == 1
            and source['selected'][0].get('sha256') == workbook['sha256']
            and source['selected'][0].get('source_kind') == SOURCE_KIND
            and source['selected'][0].get('modes') == ['debugging']
            and Path(source['selected'][0]['local_path']).resolve() == checked(workbook), 'Presentation source selection differs')
    ancestor_snapshots = entry.get('finance_evidence', {}).get('ancestor_recipe_snapshots', {})
    collect_references(source, bindings, historical_recipe_snapshots=ancestor_snapshots)
    checked(workbook, bindings)
    # Historical source-build code may have moved on. Require exact frozen
    # source text when current files no longer equal that historical recipe.
    require(isinstance(source.get('recipe'), dict)
            and {'lease_family.py', 'presentation_source.py'} <= {Path(p).name for p in source['recipe']},
            'Presentation source build recipe coverage is incomplete')
    snapshots = entry.get('finance_evidence', {}).get('source_recipe_snapshots', {})
    for path, expected in source.get('recipe', {}).items():
        candidate = Path(path)
        if candidate.is_file() and sha(candidate) == expected:
            checked({'path': path, 'sha256': expected}, bindings)
        else:
            record = snapshots.get(path)
            require(isinstance(record, dict) and record.get('sha256') == expected,
                    'Historical source recipe needs its exact frozen source snapshot: ' + path)
            checked(record, bindings)
    evidence = source['selected'][0].get('finance_evidence', {})
    require(evidence.get('validation_method') == VALIDATION
            and evidence.get('financial_seed_verified') is True, 'Missing presentation financial evidence')
    lineage = read(source['lineage'], bindings)
    require(source['lineage']['sha256'] == evidence.get('transitive_coverage', {}).get('sha256')
            and lineage.get('method') == 'exact_value_preserving_active_schedule_presentation'
            and lineage.get('old_audits_relabelled_as_new_source') is False
            and checked(lineage['new_source']) == checked(workbook), 'Invalid transitive source lineage')
    original = read(lineage['original_manifest'], bindings)
    original_book = lineage['original_source']
    require(original.get('financial_audit_passed') is True
            and original.get('derived_workbook_sha256') == original_book['sha256']
            and Path(original['local_path']).resolve() == checked(original_book)
            and checked(original_book) != checked(workbook), 'Original and presentation sources lack distinct provenance')
    require(isinstance(source.get('source_ancestors'), list) and len(source['source_ancestors']) == 2
            and source['source_ancestors'] == original.get('source_ancestors')
            and source.get('source_original_ancestors') == 2, 'Presentation source ancestry differs')
    for path, expected in lineage['original_evidence_sha256'].items():
        checked({'path': path, 'sha256': expected}, bindings)
    provided = read(original['provided_context_audit'], bindings)
    require(provided.get('passed') is True and not provided.get('mismatches') and not provided.get('missing_sheets')
            and provided.get('completed', {}).get('sha256') == original_book['sha256'], 'Original provided-data proof is incomplete')
    equality = read(lineage['full_exact_equivalence'], bindings)
    require(equality.get('passed') is True and equality.get('sheet_names_equal') is True
            and not equality.get('mismatches') and equality.get('checked_existing_value_cells', 0) > 0
            and equality.get('comparison') == 'Exact typed numeric Decimal(str(cache)) values; no grading/cent normalization.',
            'Full exact typed equivalence did not pass')
    presentation = read(lineage['presentation'], bindings)
    conversions = presentation.get('conversions')
    require(isinstance(conversions, list) and conversions
            and presentation.get('converted_formula_count') == len(conversions), 'Presentation zero coverage is incomplete')
    require(presentation.get('source', {}).get('sha256') == original_book['sha256']
            and equality.get('public_note_only_metadata_exception') == presentation.get('public_note'), 'Presentation evidence differs')
    book = openpyxl.load_workbook(workbook['path'], keep_links=False)
    try:
        coordinates = set()
        for conversion in conversions:
            key = (conversion['sheet'], conversion['cell'])
            require(key not in coordinates, 'Duplicate presented zero coordinate')
            coordinates.add(key)
            cell = book[key[0]][key[1]]
            require(type(conversion.get('original_cached_value')) in (int, float)
                    and conversion['original_cached_value'] == 0
                    and isinstance(conversion.get('original_formula'), str) and conversion['original_formula'].startswith('=')
                    and type(conversion.get('provided_value')) in (int, float) and conversion['provided_value'] == 0
                    and type(cell.value) in (int, float) and cell.value == 0
                    and math.isfinite(cell.value) and not cell.is_date and cell.data_type not in {'f', 'b', 'd', 'e'},
                    'Presented constants must be literal numeric zeros, with no Boolean/date/formula substitution')
    finally:
        book.close()
    stable = read(source['stability'], bindings)
    require(stable.get('stable') is True and stable.get('actual_recalculations') == 2
            and stable.get('goal', {}).get('sha256') == workbook['sha256']
            and set(stable.get('checks', {})) == {'goal_to_first', 'first_to_second'}
            and all(c.get('passed') is True and not c.get('mismatches') for c in stable['checks'].values()),
            'Two exact actual presentation stability passes are required')
    audits = evidence.get('independent_financial_audits', {})
    require(set(audits) == set(source.get('financial_audits', {})) == MODULES
            and audits == lineage.get('transitive_component_audits'), 'Financial component coverage differs')
    summary = read(source['financial_audit'], bindings)
    for name, record in audits.items():
        audit = read(record, bindings)
        _clean_audit(audit, workbook, name)
        require(summary.get(name) == source['financial_audits'][name]
                and summary[name].get('passed') is True
                and summary[name].get('checked_cells') == audit['checked_cells'], 'Financial summary differs')
        if name == 'lease':
            require(audit.get('fresh_independent_journal_execution') is True
                    and audit.get('method') == 'independent_decimal_future_cashflows_vs_actual_excel_caches',
                    'Lease requires a fresh independent audit')
            zeros = read(audit['provided_zero_projection'], bindings)
            require(zeros.get('all_zero_bindings_independently_recomputed') is True
                    and zeros.get('zero_count') == audit.get('provided_zero_count') == len(conversions),
                    'Fresh lease zero binding proof is incomplete')
        else:
            require(audit.get('method') == TRANSITIVE and audit.get('new_independent_journal_execution_claimed') is False
                    and audit.get('financial_policies_and_primitives_unchanged') is True
                    and audit.get('original_source', {}).get('sha256') == original_book['sha256']
                    and audit.get('exact_value_equivalence') == lineage['full_exact_equivalence'], 'Invalid transferred audit: ' + name)
            old = read(audit['original_independent_audit'], bindings)
            _clean_audit(old, original_book, 'original ' + name)
            require(old['checked_cells'] == audit['checked_cells'], 'Transferred audit coverage differs')
            allowlist = read(audit['formula_allowlist'], bindings)
            require(allowlist.get('passed') is True and allowlist.get('all_remaining_formula_definitions_unchanged') is True
                    and not allowlist.get('unexpected_formula_changes')
                    and allowlist.get('removed_zero_formula_count') == allowlist.get('actual_formula_definition_changes') == len(conversions),
                    'Formula definition allowlist did not pass')
    adapter = entry.get('task_adapter', {})
    nested_adapter = entry.get('finance_evidence', {}).get('task_adapter')
    require(nested_adapter is None or nested_adapter == adapter, 'Nested and explicit task adapter bindings differ')
    require(adapter.get('id') == ADAPTER and adapter.get('policy') == source.get('presentation_policy')
            and adapter.get('policy_sha256') == canonical(adapter['policy'])
            and adapter.get('source_manifest') == manifest_ref
            and adapter['policy'].get('adapter') == ADAPTER
            and adapter['policy'].get('source_presentation') == 'exact_source_audited_numeric_zero_formulas_only'
            and adapter['policy'].get('root_impact_validation') == 'shadow_roots', 'Task adapter policy/source binding differs')
    from ..task_adapters import lease_family
    require(checked(adapter.get('implementation'), bindings) == Path(lease_family.__file__).resolve(), 'Task adapter implementation differs')
    return {'workbook': workbook, 'source_manifest': deepcopy(manifest_ref), 'validation_method': VALIDATION,
            'transitive_coverage': deepcopy(source['lineage']), 'public_scenarios': deepcopy(source['public_scenarios']),
            'source_stability': deepcopy(source['stability']), 'independent_financial_audits': deepcopy(audits),
            'ancestor_recipe_snapshots': deepcopy(ancestor_snapshots),
            'historical_source_recipe': deepcopy(source.get('recipe', {})), 'task_adapter': deepcopy(adapter)}


def validate_activity_probe(entry, probe_reference, bindings=None):
    """Require a passing actual source/policy/implementation/exact-edits proof.

    This is a construction admission condition. Normal quality nodes and all
    their evidence still execute independently in the eventual Factory run.
    """
    from ..nodes.construction import validate_shadow_root_certificate
    from ..task_adapters.lease_family import propose_debugging_task
    bindings = {} if bindings is None else bindings
    probe = read(probe_reference, bindings)
    adapter = entry['task_adapter']
    require(probe.get('passed') is True and probe.get('shadow_passed') is True
            and probe.get('actual_shadow_LO_executions') == 2
            and probe.get('qualified') is False, 'A passing actual construction probe is required')
    require(same_reference(probe.get('source_manifest'), entry['source_manifest'])
            and probe.get('baseline', {}).get('sha256') == entry['sha256']
            and probe.get('goal', {}).get('sha256') == entry['sha256']
            and probe.get('policy') == adapter['policy']
            and probe.get('policy_canonical_sha256') == adapter['policy_sha256']
            and same_reference(probe.get('adapter_implementation'), adapter['implementation']), 'Activity probe binding differs')
    collect_references(probe, bindings,
        historical_recipe_snapshots=entry.get('finance_evidence', {}).get('ancestor_recipe_snapshots', {}))
    plan = read(probe['actual_plan'], bindings)
    proposed = propose_debugging_task(Path(entry['local_path']), deepcopy(adapter['policy']))
    require(canonical(plan.get('edits')) == canonical(proposed.get('edits'))
            and probe.get('root_count') == len(proposed['edits']), 'Activity probe exact edit assertions differ')
    certificate = read(probe['shadow_certificate'], bindings)
    validate_shadow_root_certificate(certificate, checked(probe['goal']),
                                    checked(probe['public_input']), plan['edits'])
    expected_controls = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
    actual_controls = read(probe['local_control_receipt'], bindings)
    require(probe.get('local_controls') == expected_controls
            and {name: actual_controls.get(name, {}).get('reward') for name in expected_controls} == expected_controls,
            'The actual five local controls did not pass')
    instruction = checked(probe['public_instruction'], bindings)
    input_file = checked(probe['public_input'], bindings)
    require(hashlib.sha256(input_file.read_bytes() + instruction.read_bytes()).hexdigest() == probe.get('revision_hash'),
            'Activity probe public revision hash differs')
    delta = read(probe['expected_delta'], bindings)
    require(probe.get('expected_change_count', 0) > 0
            and delta.get('expected_change_count') == probe['expected_change_count'], 'Probe full changed set differs')
    source = read(entry['source_manifest'])
    snapshots = read(probe['source_build_recipe_snapshot'], bindings)
    for path, expected in source.get('recipe', {}).items():
        require(path in snapshots and snapshots[path].get('sha256') == expected, 'Probe source-build recipe snapshot differs')
        checked(snapshots[path], bindings)
    return {'activity_probe': deepcopy(probe_reference), 'baseline_sha256': entry['sha256'],
            'policy_sha256': adapter['policy_sha256'], 'edits_sha256': canonical(plan['edits']),
            'actual_shadow_LO_executions': 2, 'quality_recovery_difficulty_certified': False}


class DispatchPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        adapter = ctx.data.get('finance_evidence', {}).get('task_adapter')
        if ctx.mode != 'debugging' or adapter is None:
            return PlanNode().execute(ctx)
        require(adapter.get('id') == ADAPTER, 'Unsupported explicit task adapter')
        require(ctx.data.get('variant', 0) == 0, 'Adapted plans require a new source identity')
        from ..task_adapters import lease_family
        checked(adapter['implementation'])
        require(checked(adapter['implementation']) == Path(lease_family.__file__).resolve()
                and canonical(adapter['policy']) == adapter['policy_sha256'], 'Changed adapter implementation/policy')
        source = read(adapter['source_manifest'])
        require(sha(ctx.data['baseline']) == source['derived_workbook_sha256'], 'Adapted plan baseline differs from audited presentation')
        binding = {'baseline_sha256': sha(ctx.data['baseline']), 'policy_sha256': adapter['policy_sha256'],
                   'implementation_sha256': adapter['implementation']['sha256']}
        path = Path(ctx.data['source_cache']) / ('adapted_task_plan_' + canonical(binding) + '.json')
        if path.exists():
            cached = json.loads(path.read_text())
            require(cached.get('binding') == binding and cached.get('plan_sha256') == canonical(cached['plan']), 'Changed adapted plan cache')
            plan = cached['plan']
        else:
            plan = lease_family.propose_debugging_task(Path(ctx.data['baseline']), deepcopy(adapter['policy']))
            with path.open('x') as stream:
                json.dump({'binding': binding, 'plan_sha256': canonical(plan), 'plan': plan}, stream, ensure_ascii=False, indent=2)
        require(plan.get('family_adapter', {}).get('id') == ADAPTER, 'Adapter returned an unexpected plan')
        ctx.audit.emit('planning.adapter', task_id=ctx.task_id, mode=ctx.mode, adapter=ADAPTER,
                       baseline_sha256=binding['baseline_sha256'], plan_sha256=canonical(plan),
                       policy_sha256=adapter['policy_sha256'], llm_calls=0, activity_certified=False)
        return {'plan': deepcopy(plan), 'source_assessment': {'financial_evidence': ctx.data['finance_evidence'],
                'authoring_backend': ADAPTER, 'activity_quality_difficulty_pending': True}}


class AdaptedSourceFactory(FactoryPipeline):
    def __init__(self, *args, legacy_validator=None, **kwargs):
        self.legacy_validator = legacy_validator
        super().__init__(*args, **kwargs)

    def load_node(self, node_id):
        return DispatchPlanNode() if node_id == 'plan' else super().load_node(node_id)

    def load_seeds(self):
        seeds = super().load_seeds()
        for seed in seeds:
            if seed.get('source_kind') == SOURCE_KIND:
                proof = validate_presentation_seed(seed)
                require(seed.get('finance_evidence', {}).get('audited_source_binding') == proof, 'Changed admitted presentation binding')
                require(seed['finance_evidence'].get('task_adapter') == seed['task_adapter'], 'Missing explicit admitted adapter context')
            else:
                require(seed.get('task_adapter') is None and seed.get('finance_evidence', {}).get('task_adapter') is None,
                        'An adapter requires its validated presentation source kind')
                require(self.legacy_validator is not None, 'Legacy financial source validator is required')
                proof = self.legacy_validator(seed)
                require(seed.get('finance_evidence', {}).get('audited_source_binding') == proof, 'Changed admitted legacy source binding')
            seed['survey'] = {**seed.get('survey', {}), 'normalized_path': proof['workbook']['path'],
                              'source_sha256': seed['sha256'], 'status': 'ok', 'error_count': 0}
        return seeds

    def run_phase(self, context, phase):
        result = super().run_phase(context, phase)
        if context.data.get('baseline'):
            require(sha(context.data['baseline']) == context.data['source_id'], 'Normalized baseline differs from audited source bytes')
        return result
