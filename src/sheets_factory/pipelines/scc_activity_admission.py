"""Explicit SCC-v8 activity bindings, separate from financial and quality proof.

The source auditor must validate the new presentation and its financial lineage
before this activity admission is used. A six-call local own-value certificate
does not establish counterfactual uniqueness, recovery, quality, or difficulty.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
from pathlib import Path

from ..core.node import BaseNode
from ..nodes import construction
from ..task_adapters.public_input_priority import (PriorityPlanNode, append_rule, canonical, checked,
    equivalent, read, ref, require, sha, write)
from .adapted_factory import collect_references
from .factory import FactoryPipeline
from .presented_numeric_timing import audit_presented_numeric_timing, validate_presented_numeric_timing
from .joint_repair_activity import SETTING as JOINT_SETTING, METHOD as JOINT_METHOD
from .joint_repair_activity import validate_physical_edits, describe_joint_delta

SETTING = 'scc_activity'
ADAPTER = 'composite_complete_financial_graph_v2'
SOURCE_KIND = 'derived_complete_financial_graph_presentation'
METHOD = 'two_context_typed_boundary_compact_DAG_complete_cyclic_SCC_own_value_witness_v8'
UPSTREAM_SHA256 = '9e729242123f58a333b21ba29ff79c63026864ec8851c594e3573de7ead7fcdc'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
TRANSFER_METHOD = 'transitive_independent_financial_audits_through_full_exact_typed_equivalence'


def upstream_binding():
    path = Path(construction.__file__).resolve()
    require(sha(path) == UPSTREAM_SHA256, 'SCC integration upstream Construct implementation changed')
    return ref(path)


def load_v8_checker(reference):
    """Load only the exact approved file, with its relative package preserved."""
    path = checked(reference)
    name = 'sheets_factory.checkers._scc_activity_v8_' + reference['sha256']
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, 'SCC-v8 checker cannot be loaded')
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    require(sha(path) == reference['sha256'], 'SCC-v8 checker changed during import')
    require(callable(getattr(provider, 'prove_scc_island_root_impacts', None))
            and callable(getattr(provider, 'validate_scc_island_root_certificate', None)),
            'SCC-v8 checker API is incomplete')
    return provider


def validate_scope_inventory(inventory, edits):
    """Require every nonzero member of the complete declared monetary scope."""
    require(inventory.get('schema_version') == 2 and inventory.get('adapter') == ADAPTER,
            'Unsupported complete financial scope inventory')
    labels, all_labels, families = [], set(), inventory.get('families')
    require(isinstance(families, list) and type(inventory.get('family_count')) is int
            and len(families) == inventory['family_count'],
            'Incomplete financial family inventory')
    for family in families:
        require(isinstance(family.get('sheet'), str) and isinstance(family.get('cells'), list),
                'Malformed financial family inventory')
        for cell in family['cells']:
            label = family['sheet'] + '!' + cell['cell']
            require(label not in all_labels, 'Repeated cell in full financial scope')
            all_labels.add(label)
            require(cell.get('source_kind') in {'finite_numeric_nonzero', 'exact_numeric_zero'},
                    'Unsupported typed member in financial scope')
            if cell['source_kind'] == 'finite_numeric_nonzero':
                labels.append(label)
    actual = [e['sheet'] + '!' + e['cell'] for e in edits]
    require(type(inventory.get('formula_slots')) is int and len(all_labels) == inventory['formula_slots']
            and type(inventory.get('prospective_nonzero_roots')) is int
            and len(labels) == inventory['prospective_nonzero_roots']
            and len(actual) == len(set(actual)) == len(labels) and set(actual) == set(labels),
            'The plan omits or adds members of the complete nonzero financial scope')
    return labels


def same_artifact(left, right):
    return checked(left) == checked(right) and left['sha256'] == right['sha256']


def validate_financial_admission(binding):
    """Fail-closed contract for a future actually normalized full-graph source.

    No offline presentation receipt can meet this schema. These checks re-read
    the original independent audits and all actual workbooks, preserving the
    explicit transitive financial claim instead of relabelling old audits.
    """
    from ..task_adapters.lease_family import compare_exact_typed
    from ..task_adapters.presentation_source import verify_formula_allowlist
    admission = read(binding['financial_admission'])
    require(admission.get('kind') == 'actual_full_graph_presentation_financial_admission'
            and admission.get('financial_validation_method') == TRANSFER_METHOD
            and admission.get('new_independent_journal_execution_claimed') is False,
            'An actual, explicitly transitive full-graph source financial admission is required')
    require(same_artifact(admission['source'], binding['source'])
            and same_artifact(admission['source_manifest'], binding['source_manifest'])
            and same_artifact(admission['scope_inventory'], binding['scope_inventory']),
            'Full-graph financial admission binds another presented source or scope')
    original = read(admission['original_manifest'])
    require(sha(checked(admission['original_source'])) == original.get('derived_workbook_sha256')
            and Path(original['local_path']).resolve() == checked(admission['original_source'])
            and original.get('financial_audit_passed') is True
            and original.get('contingent_all_years_unique') is True
            and original.get('runtime', {}).get('image_id') == IMAGE_ID,
            'The original independently audited source identity or runtime differs')
    source = read(binding['source_manifest'])
    require(source.get('status') == 'actually_verified_complete_financial_graph_presentation'
            and source.get('financial_audit_passed') is True
            and source.get('derived_workbook_sha256') == binding['source']['sha256']
            and Path(source['local_path']).resolve() == checked(binding['source'])
            and source.get('financial_validation_method') == TRANSFER_METHOD
            and source.get('runtime', {}).get('image_id') == IMAGE_ID,
            'The normalized full-graph source manifest is not actually certified')
    require(read(binding['scope_inventory']).get('source', {}).get('sha256') == admission['original_source']['sha256'],
            'The complete financial scope belongs to another original source')
    audits = admission['original_independent_audits']
    require(set(audits) == set(original.get('financial_audits', {}))
            == {'lease','programme','operating','holding','contingent'},
            'The original independent financial audit coverage is incomplete')
    independently_checked_zeros = {}
    for name, reference in audits.items():
        audit = read(reference)
        require(same_artifact(audit['workbook'], admission['original_source'])
                and audit.get('passed') is True and type(audit.get('checked_cells')) is int
                and audit['checked_cells'] > 0
                and audit['checked_cells'] == original['financial_audits'][name]['checked_cells']
                and all(not audit.get(key) for key in ('mismatches','control_mismatches','uncovered',
                    'uncovered_formulas','native_errors','invalid_formula_values')),
                'The original independent financial audit changed or has unresolved findings: ' + name)
        for check in audit.get('cell_checks', []):
            if check.get('passed', check.get('matched')) is not True:
                continue
            expected = check.get('expected_independent', check.get('expected'))
            if isinstance(expected, bool):
                continue
            try:
                value = Decimal(str(expected))
            except (InvalidOperation, ValueError):
                continue
            if value.is_finite() and value == 0:
                address = check.get('address', '')
                if name == 'operating' and not address.startswith('Operating '):
                    address = 'Operating ' + address
                independently_checked_zeros.setdefault(address, set()).add(name)
    presentation = read(admission['presentation'])
    conversions = presentation.get('conversions')
    require(same_artifact(presentation['source'], admission['original_source']) and isinstance(conversions, list)
            and all(type(x.get('provided_value')) in (int,float) and x['provided_value'] == 0
                and type(x.get('original_cached_value')) in (int,float) and x['original_cached_value'] == 0
                for x in conversions), 'Only declared exact numeric zero conversions may transfer financial evidence')
    inventory = read(binding['scope_inventory'])
    scope_zeros = {family['sheet'] + '!' + cell['cell'] for family in inventory['families']
                   for cell in family['cells'] if cell.get('source_kind') == 'exact_numeric_zero'}
    converted = [item['sheet'] + '!' + item['cell'] for item in conversions]
    require(len(converted) == len(set(converted)) and set(converted) == scope_zeros
            and scope_zeros <= set(independently_checked_zeros),
            'Every converted zero must be in the full monetary scope and independently checked as numeric zero')
    zero_coverage = read(admission['independent_zero_coverage'])
    expected_zero_coverage = [{'address':label,'expected_independent':'0',
        'source_independent_modules':sorted(independently_checked_zeros[label])} for label in converted]
    require(zero_coverage == expected_zero_coverage, 'Independent zero coverage does not bind every declared conversion')
    original_path, source_path = checked(admission['original_source']), checked(binding['source'])
    equality = read(admission['exact_typed_equivalence'])
    allowlist = read(admission['formula_allowlist'])
    require(equality == compare_exact_typed(original_path, source_path, public_note=presentation['public_note'])
            and equality.get('passed') is True
            and allowlist == verify_formula_allowlist(original_path, source_path, conversions)
            and allowlist.get('passed') is True, 'Actual full typed equality or strict formula allowlist does not hold')
    calls = admission.get('engine_calls', [])
    require(isinstance(calls, list) and len(calls) == 3
            and all(call.get('completed') is True and call.get('image_id') == IMAGE_ID
                and call.get('backend') == 'libreoffice_uno_docker' and call.get('network') == 'none' for call in calls),
            'Full-graph source admission requires normalization and two actual stability executions')
    for call in calls:
        checked(call['input']);checked(call['output'])
    require(same_artifact(calls[0]['input'], presentation['raw_presentation'])
            and same_artifact(calls[0]['output'], binding['source'])
            and same_artifact(calls[1]['input'], calls[0]['output'])
            and same_artifact(calls[2]['input'], calls[1]['output']), 'Actual source normalization/stability execution chain differs')
    stable = read(admission['actual_stability'])
    actual_checks = {'goal_to_first':compare_exact_typed(source_path, checked(calls[1]['output'])),
                     'first_to_second':compare_exact_typed(checked(calls[1]['output']), checked(calls[2]['output']))}
    require(stable.get('checks') == actual_checks and stable.get('stable') is True
            and all(check.get('passed') is True for check in actual_checks.values()),
            'The actual normalized source is not fully exact typed stable')
    transfer = read(admission['financial_audit_transfer'])
    require(transfer.get('method') == TRANSFER_METHOD
            and same_artifact(transfer['original_source'], admission['original_source'])
            and same_artifact(transfer['presented_source'], binding['source'])
            and transfer.get('original_independent_audits') == audits
            and transfer.get('exact_typed_equivalence') == admission['exact_typed_equivalence']
            and transfer.get('formula_allowlist') == admission['formula_allowlist']
            and transfer.get('new_independent_journal_execution_claimed') is False
            and transfer.get('old_audits_relabelled_as_new_source') is False,
            'Financial audit transfer must preserve original identities and exact scope')
    return admission


def validate_source_binding(binding, *, plan=None):
    source = checked(binding['source'])
    checked(binding['source_manifest'])
    adapter = binding['task_adapter']
    require(adapter.get('id') == ADAPTER and canonical(adapter.get('policy')) == adapter.get('policy_sha256'),
            'SCC activity adapter or policy binding differs')
    checked(adapter['implementation'])
    inventory = read(binding['scope_inventory'])
    validate_financial_admission(binding)
    validate_presented_numeric_timing(binding['public_input_priority_audit'], binding)
    if plan is not None:
        validate_plan_binding(binding,inventory,plan)
    return source


def validate_plan_binding(binding,inventory,plan):
    edits = plan.get('edits', [])
    validate_scope_inventory(inventory,edits)
    require(plan.get('family_adapter', {}).get('id') == ADAPTER
            and canonical(edits) == binding.get('edits_sha256')
            and type(binding.get('root_count')) is int and len(edits) == binding['root_count'],
            'SCC activity plan or exact edit binding differs')


def validate_context_binding(ctx, *, require_plan=True):
    """Return None for legacy/FM tasks; fail closed for an explicit DBG opt-in."""
    if ctx.mode != 'debugging':
        return None
    joint = ctx.config.get(JOINT_SETTING)
    strict = ctx.config.get(SETTING)
    joint_enabled = isinstance(joint, dict) and joint.get('enabled') is True
    require(not (joint_enabled and isinstance(strict, dict) and strict.get('enabled') is True),
            'Choose one explicit joint or SCC activity contract')
    setting = joint if joint_enabled else strict
    if setting is None or isinstance(setting, dict) and setting.get('enabled') is False:
        return None
    require(isinstance(setting, dict) and setting.get('enabled') is True
            and type(setting.get('version')) is int and setting['version'] == (1 if joint_enabled else 8),
            'Activity requires an explicit versioned opt-in')
    if joint_enabled:
        require(setting.get('contract') == JOINT_METHOD, 'Unsupported joint repair contract')
    require(setting.get('upstream_construction') == upstream_binding(), 'SCC integration upstream binding differs')
    manifest = read(setting['bindings'])
    require(manifest.get('kind') == ('full_graph_joint_repair_source_bindings' if joint_enabled else 'scc_activity_source_bindings')
            and manifest.get('version') == (1 if joint_enabled else 8),
            'Unsupported SCC activity source bindings')
    identity = sha(ctx.source)
    source_binding = manifest.get('sources', {}).get(identity)
    # A mixed registry can serve an ordinary source without changing its proof.
    if source_binding is None:
        require((ctx.data.get('finance_evidence', {}).get('task_adapter') or {}).get('id') != ADAPTER,
                'Explicit full-graph adapter has no SCC source binding')
        return None
    source = validate_source_binding(source_binding, plan=ctx.data['plan'] if require_plan else None)
    require(sha(ctx.data['baseline']) == identity == source_binding['source']['sha256']
            and source.resolve() == Path(ctx.source).resolve(), 'SCC source or normalized baseline changed')
    require(ctx.data.get('finance_evidence', {}).get('task_adapter') == source_binding['task_adapter'],
            'SCC source has no exact explicit admitted adapter context')
    require(ctx.data.get('finance_evidence', {}).get('full_graph_financial_admission') == source_binding['financial_admission'],
            'SCC source financial admission was not explicitly restored by source validation')
    if require_plan:
        require(not ctx.data['plan'].get('scenario_inputs'), 'Full-graph SCC activity requires the unchanged audited financial goal')
    limits = setting.get('proof_limits', {})
    require(isinstance(limits, dict) and set(limits) <= {'max_dependency_edges', 'max_island_cells', 'max_island_sheets'}
            and all(type(value) is int and value > 0 for value in limits.values()), 'Invalid SCC proof resource limits')
    allow_index = setting.get('allow_constant_index_ancestors', False)
    require(type(allow_index) is bool, 'SCC constant-INDEX ancestor opt-in must be boolean')
    provider = None if joint_enabled else load_v8_checker(setting['checker'])
    return {'setting': setting, 'source_binding': source_binding, 'provider': provider,
            'proof_limits': deepcopy(limits), 'allow_constant_index_ancestors': allow_index,
            'activity_contract':JOINT_METHOD if joint_enabled else 'scc_island_v8'}


def validate_certificate(certificate, goal, combined_input, edits, *, provider, checker_reference):
    """Add integration identity/scope checks, then use the full v8 validator."""
    checked(checker_reference)
    require(certificate.get('version') == 8 and certificate.get('proof_method') == METHOD,
            'SCC activity requires the version-8 typed-boundary proof')
    require(certificate.get('passed') is True and certificate.get('blocking') is False
            and certificate.get('state') == 'proven_local_own_value_lower_bounds', 'SCC activity proof is incomplete')
    require(type(certificate.get('actual_LO_started_count')) is int and certificate['actual_LO_started_count'] == 6
            and type(certificate.get('actual_LO_execution_count')) is int and certificate['actual_LO_execution_count'] == 6,
            'SCC activity requires exactly six actual checker executions')
    require(certificate.get('implementation_sha256') == checker_reference['sha256']
            and certificate.get('goal_sha256') == sha(goal)
            and certificate.get('combined_input_sha256') == sha(combined_input)
            and certificate.get('edits_sha256') == canonical(edits), 'SCC activity context or checker identity differs')
    require(type(certificate.get('root_count')) is int and certificate['root_count'] == len(edits)
            and certificate.get('counts_are_lower_bounds') is True
            and all(certificate.get(k) is False for k in ('complete_per_root_changed_sets_claimed',
                'full_counterfactual_convergence_claimed', 'counterfactual_uniqueness_claimed',
                'source_uniqueness_transferred_to_mutants')), 'SCC activity lower-bound scope is incomplete or overstated')
    impacts = provider.validate_scc_island_root_certificate(certificate, goal, combined_input, edits)
    require(isinstance(impacts, list) and len(impacts) == len(edits), 'SCC activity evidence omits a root')
    expected = [e['sheet'] + '!' + e['cell'] for e in edits]
    for index, (label, impact) in enumerate(zip(expected, impacts)):
        check = impact.get('evidence', {})
        require(impact.get('root_index') == index and check.get('root_index') == index and check.get('root') == label
                and check.get('individual_active') is True and check.get('combined_marginal_active') is True,
                'SCC activity root labels, order, or two-context witnesses differ')
    checked(checker_reference)
    return impacts


def validate_index_policy(certificate, expected):
    extension = certificate.get('union_graph', {}).get('constant_INDEX_extension', {})
    require(type(extension.get('enabled')) is bool and extension['enabled'] is expected,
            'SCC constant-INDEX ancestor proof does not match the explicit configured policy')


class FullGraphSCCPlanNode(BaseNode):
    """Call the field compiler only after the new presented-source proof passes."""
    node_id = 'plan'

    def execute(self, ctx):
        if ctx.mode != 'debugging' or (ctx.data.get('finance_evidence', {}).get('task_adapter') or {}).get('id') != ADAPTER:
            return PriorityPlanNode().execute(ctx)
        binding = validate_context_binding(ctx, require_plan=False)
        require(binding is not None, 'The complete financial-graph adapter requires explicit SCC-v8 admission')
        source = binding['source_binding'];adapter = source['task_adapter']
        require(ctx.data.get('variant', 0) == 0, 'A complete financial-graph adapter requires a new source identity')
        path = checked(adapter['implementation'])
        spec = importlib.util.spec_from_file_location(
            'sheets_factory.task_adapters._bound_full_graph_' + adapter['implementation']['sha256'], path)
        require(spec is not None and spec.loader is not None, 'The exact full-graph compiler cannot be loaded')
        compiler = importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
        require(callable(getattr(compiler, 'compile_complete_mutation', None))
                and sha(path) == adapter['implementation']['sha256'], 'The full-graph compiler changed or lacks its API')
        cache_binding = {'source_sha256':source['source']['sha256'],
            'scope_inventory_sha256':source['scope_inventory']['sha256'],
            'policy_sha256':adapter['policy_sha256'],'compiler_sha256':adapter['implementation']['sha256'],
            'edits_sha256':source['edits_sha256'],'public_input_priority_audit':source['public_input_priority_audit'],
            'integration_implementation_sha256':sha(__file__),'activity_contract':binding['activity_contract']}
        cache = Path(ctx.data['source_cache']) / ('scc_full_graph_plan_' + canonical(cache_binding) + '.json')
        if cache.exists():
            saved = json.loads(cache.read_text())
            require(saved.get('binding') == cache_binding and saved.get('plan_sha256') == canonical(saved['plan']),
                    'The full-graph task plan cache changed')
            plan = saved['plan']
        else:
            plan = compiler.compile_complete_mutation(Path(ctx.data['baseline']),
                read(source['scope_inventory']), deepcopy(adapter['policy']))
            validate_plan_binding(source,read(source['scope_inventory']),plan)
            # This is a NEW-source numeric policy audit, never a silent reuse of
            # the ancestor's priority binding after its workbook SHA changed.
            plan = append_rule(plan)
            if binding['activity_contract'] == JOINT_METHOD:
                metadata = plan['family_adapter']
                metadata['compiler_planned_root_proof_route'] = metadata.get('root_proof_route')
                metadata['root_proof_route'] = JOINT_METHOD
                metadata['individual_or_marginal_activity_claimed'] = False
            evidence = plan.setdefault('reference_evidence', [])
            require(isinstance(evidence, list), 'The full-graph reference evidence must be a list')
            evidence.append({'kind':'hash_bound_presented_source_numeric_reference',
                'financial_validation_method':TRANSFER_METHOD,'financial_admission':source['financial_admission'],
                'scope_inventory':source['scope_inventory'],'numeric_timing_audit':source['public_input_priority_audit'],
                'new_independent_journal_execution_claimed':False})
            cache.parent.mkdir(parents=True, exist_ok=True)
            with cache.open('x') as stream:
                json.dump({'binding':cache_binding,'plan_sha256':canonical(plan),'plan':plan}, stream, ensure_ascii=False, indent=2)
        validate_plan_binding(source,read(source['scope_inventory']),plan)
        checked(source['source'])
        require(not plan.get('scenario_inputs'), 'The complete financial plan cannot alter audited scenario inputs')
        checked(adapter['implementation'])
        ctx.save('scc_full_graph_plan_binding.json', {'source':source['source'],
            'financial_admission':source['financial_admission'],'scope_inventory':source['scope_inventory'],
            'public_input_priority_audit':source['public_input_priority_audit'],
            'plan_sha256':canonical(plan),'edits_sha256':canonical(plan['edits']),
            'root_count':len(plan['edits']),'model_calls':0,'activity_quality_difficulty_certified':False})
        ctx.audit.emit('planning.adapter', task_id=ctx.task_id, mode=ctx.mode, adapter=ADAPTER,
            plan_sha256=canonical(plan), root_count=len(plan['edits']), llm_calls=0, activity_certified=False)
        return {'plan':deepcopy(plan),'source_assessment':{'financial_evidence':ctx.data['finance_evidence'],
            'authoring_backend':ADAPTER,'activity_quality_difficulty_pending':True}}


def validate_full_graph_seed(entry, setting):
    """A future Factory seed needs financial, full-scope and real v8 evidence."""
    require(entry.get('source_kind') == SOURCE_KIND and entry.get('modes') == ['debugging']
            and type(entry.get('variant', 0)) is int and entry.get('variant', 0) == 0,
            'Full-graph sources are explicit new debugging identities only')
    require(isinstance(setting, dict) and setting.get('enabled') is True
            and setting.get('version') == 8 and setting.get('upstream_construction') == upstream_binding(),
            'The full-graph Factory requires the explicit bound SCC-v8 configuration')
    manifest = read(setting['bindings'])
    require(manifest.get('kind') == 'scc_activity_source_bindings' and manifest.get('version') == 8
            and manifest.get('sources', {}).get(entry.get('sha256')) == entry.get('scc_activity_binding'),
            'The full-graph seed is outside its immutable SCC source bindings')
    source = entry['scc_activity_binding']
    require(entry.get('task_adapter') == source['task_adapter']
            and entry.get('source_manifest') == source['source_manifest']
            and entry.get('sha256') == source['source']['sha256']
            and Path(entry['local_path']).resolve() == checked(source['source']), 'Full-graph seed source or adapter differs')
    activity = validate_scc_activity_probe(entry, entry['activity_probe'], checker_reference=setting['checker'])
    require(type(setting.get('allow_constant_index_ancestors', False)) is bool
            and activity['allow_constant_index_ancestors'] is setting.get('allow_constant_index_ancestors', False),
            'The full-graph probe and Factory constant-INDEX policies differ')
    return {'workbook':deepcopy(source['source']),'source_manifest':deepcopy(source['source_manifest']),
        'financial_admission':deepcopy(source['financial_admission']),
        'public_input_priority_audit':deepcopy(source['public_input_priority_audit']),
        'scope_inventory':deepcopy(source['scope_inventory']),'activity':activity,
        'validation_method':TRANSFER_METHOD,'quality_recovery_difficulty_certified':False}


def validate_joint_engineering_probe(entry):
    """Read actual two-pass joint evidence; five controls remain Factory work."""
    from ..task_adapters.lease_family import compare_exact_typed
    source = entry['scc_activity_binding'];probe_ref = entry['joint_engineering_probe']
    probe = read(probe_ref);calls = read(entry['joint_engine_calls'])
    require(probe.get('status') == 'joint_engineering_probe_complete_not_task_admitted'
            and probe.get('actual_LO_recalculations') == 2 and probe.get('exact_typed_stable') is True
            and probe.get('individual_or_marginal_activity_tested') is False
            and probe.get('SCC_executions') == 0 and probe.get('qualified') is False,
            'An actual two-pass joint engineering probe is required')
    require(same_artifact(probe['baseline'], source['source'])
            and same_artifact(probe['source_manifest'], source['source_manifest'])
            and same_artifact(probe['source_financial_admission'], source['financial_admission']),
            'Joint engineering probe source financial binding differs')
    plan = read(probe['plan']);validate_source_binding(source,plan=plan)
    require(probe.get('edits_sha256') == canonical(plan['edits'])
            and probe.get('root_count') == len(plan['edits']), 'Joint engineering exact physical edits differ')
    require(isinstance(calls,list) and len(calls) == 2
            and [c.get('phase') for c in calls] == ['mutant_normalize','mutant_second_recalculation']
            and all(c.get('completed') is True and c.get('backend') == 'libreoffice_uno_docker'
                and c.get('image_id') == IMAGE_ID and c.get('network') == 'none' for c in calls),
            'Joint engineering actual execution chain is incomplete')
    for call in calls:
        checked(call['input']);checked(call['output'])
    injection = read(probe['raw_injection'])
    require(injection.get('passed') is True and injection.get('exact_formula_edit_set') is True
            and injection.get('edits_sha256') == canonical(plan['edits'])
            and same_artifact(injection['raw_mutant'],calls[0]['input'])
            and same_artifact(injection['baseline'],probe['baseline'])
            and same_artifact(injection['plan'],probe['plan']), 'Joint raw-injection report differs from the actual first LO input')
    require(same_artifact(calls[0]['output'],probe['input'])
            and same_artifact(calls[1]['input'],probe['input']) and same_artifact(calls[1]['output'],probe['second_pass']),
            'Joint engineering actual execution artifacts differ')
    baseline,input_file,second = checked(probe['baseline']),checked(probe['input']),checked(probe['second_pass'])
    validate_physical_edits(baseline,checked(calls[0]['input']),plan['edits'])
    validate_physical_edits(baseline,input_file,plan['edits'])
    validate_physical_edits(input_file,second,[])
    stability = compare_exact_typed(input_file,second)
    require(stability.get('passed') is True and read(probe['stability']) == stability,
            'Joint engineering whole input is not exact typed stable')
    delta = read(probe['full_delta'])
    summary = describe_joint_delta(baseline,input_file,plan['edits'],delta)
    require(probe.get('expected_change_count') == summary['complete_required_D_count']
            and probe.get('changed_edited_root_count') == summary['physical_edits_in_actual_D_count']
            and probe.get('unchanged_edited_root_count') == summary['unobservable_physical_edit_count']
            and probe.get('mutant_error_count') == len(summary['native_input_errors']),
            'Joint engineering physical edits, complete D, or native-error counts differ')
    return {'activity_contract':JOINT_METHOD,'engineering_probe':deepcopy(probe_ref),
        'actual_engine_calls':deepcopy(entry['joint_engine_calls']),
        'physical_formula_mutation_count':len(plan['edits']),
        'complete_required_D_count':summary['complete_required_D_count'],
        'physical_edits_in_actual_D_count':summary['physical_edits_in_actual_D_count'],
        'unobservable_physical_edit_count':summary['unobservable_physical_edit_count'],
        'native_input_error_count':len(summary['native_input_errors']),
        'individual_or_marginal_activity_claimed':False,'joint_input_global_uniqueness_claimed':False,
        'five_controls_recovery_quality_Harbor_pending':True,'quality_recovery_difficulty_certified':False}


def validate_joint_seed(entry,setting):
    require(entry.get('source_kind') == SOURCE_KIND and entry.get('modes') == ['debugging']
            and type(entry.get('variant',0)) is int and entry.get('variant',0) == 0,
            'Joint full-graph seeds are explicit new debugging identities only')
    require(isinstance(setting,dict) and setting.get('enabled') is True and setting.get('version') == 1
            and setting.get('contract') == JOINT_METHOD and setting.get('upstream_construction') == upstream_binding(),
            'An explicit joint-workbook activity configuration is required')
    manifest = read(setting['bindings']);source = entry['scc_activity_binding']
    require(manifest.get('kind') == 'full_graph_joint_repair_source_bindings' and manifest.get('version') == 1
            and manifest.get('sources',{}).get(entry.get('sha256')) == source,
            'Joint source is outside its immutable source binding')
    require(entry.get('task_adapter') == source['task_adapter']
            and entry.get('source_manifest') == source['source_manifest']
            and entry.get('sha256') == source['source']['sha256']
            and Path(entry['local_path']).resolve() == checked(source['source']), 'Joint seed source or adapter differs')
    return {'workbook':deepcopy(source['source']),'source_manifest':deepcopy(source['source_manifest']),
        'financial_admission':deepcopy(source['financial_admission']),
        'public_input_priority_audit':deepcopy(source['public_input_priority_audit']),
        'scope_inventory':deepcopy(source['scope_inventory']),'activity':validate_joint_engineering_probe(entry),
        'validation_method':TRANSFER_METHOD,'quality_recovery_difficulty_certified':False}


class SCCActivityFactory(FactoryPipeline):
    """Normal Factory phases with strict NEW-source normalization admission."""

    def __init__(self, *args, legacy_validator=None, **kwargs):
        self.legacy_validator = legacy_validator
        super().__init__(*args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        for seed in seeds:
            if seed.get('source_kind') == SOURCE_KIND:
                joint = self.config.get(JOINT_SETTING)
                proof = validate_joint_seed(seed,joint) if isinstance(joint,dict) and joint.get('enabled') is True else validate_full_graph_seed(seed,self.config.get(SETTING))
                evidence = seed.get('finance_evidence', {})
                require(evidence.get('task_adapter') == seed['task_adapter']
                        and evidence.get('full_graph_financial_admission') == seed['scc_activity_binding']['financial_admission'],
                        'The full-graph seed lacks explicit source financial and adapter context')
            else:
                require(seed.get('task_adapter') is None and seed.get('finance_evidence', {}).get('task_adapter') is None,
                        'An explicit full-graph adapter requires its new admitted presentation source kind')
                require(self.legacy_validator is not None, 'Legacy financial source validator is required')
                proof = self.legacy_validator(seed)
            require(seed.get('finance_evidence', {}).get('audited_source_binding') == proof,
                    'The admitted source proof changed')
            seed['survey'] = {**seed.get('survey', {}),'normalized_path':proof['workbook']['path'],
                'source_sha256':seed['sha256'],'status':'ok','error_count':0}
        return seeds

    def run_phase(self, context, phase):
        result = super().run_phase(context, phase)
        if context.data.get('baseline'):
            require(sha(context.data['baseline']) == context.data['source_id'],
                    'Normalized baseline differs from the admitted financial source bytes')
        return result


def validate_scc_activity_probe(entry, probe_reference, *, checker_reference, bindings=None):
    """Activity-only admission after a separate full financial source audit.

    The immutable entry carries ``scc_activity_binding`` with the full scope,
    exact plan edit digest, policy and presented source identity. This function
    cannot serve as ``validate_presentation_seed`` or certify financial lineage.
    """
    bindings = {} if bindings is None else bindings
    probe = read(probe_reference)
    source_binding = entry['scc_activity_binding']
    require(entry.get('modes') == ['debugging'] and entry.get('variant', 0) == 0
            and entry.get('task_adapter') == source_binding['task_adapter']
            and entry.get('sha256') == source_binding['source']['sha256']
            and Path(entry['local_path']).resolve() == checked(source_binding['source'])
            and entry.get('source_manifest') == source_binding['source_manifest'], 'SCC activity entry binding differs')
    collect_references(probe, bindings,
        historical_recipe_snapshots=entry.get('finance_evidence', {}).get('ancestor_recipe_snapshots', {}))
    require(probe.get('kind') == 'scc_v8_full_graph_activity_probe'
            and probe.get('passed') is True and probe.get('qualified') is False,
            'A passing SCC-v8 construction probe is required')
    adapter = source_binding['task_adapter']
    require(probe.get('source_manifest') == entry['source_manifest']
            and probe.get('baseline') == source_binding['source']
            and probe.get('goal', {}).get('sha256') == entry['sha256']
            and probe.get('policy') == adapter['policy']
            and probe.get('policy_canonical_sha256') == adapter['policy_sha256']
            and probe.get('adapter_implementation') == adapter['implementation']
            and probe.get('scope_inventory') == source_binding['scope_inventory'], 'SCC activity probe source, policy, or full scope differs')
    plan = read(probe['actual_plan'])
    validate_source_binding(source_binding, plan=plan)
    require(probe.get('root_count') == len(plan['edits']), 'SCC activity probe root count differs')
    provider = load_v8_checker(checker_reference)
    certificate = read(probe['scc_certificate'])
    validate_certificate(certificate, checked(probe['goal']), checked(probe['public_input']), plan['edits'],
                         provider=provider, checker_reference=checker_reference)
    require(type(probe.get('allow_constant_index_ancestors')) is bool,
            'SCC activity probe must declare its constant-INDEX policy')
    validate_index_policy(certificate, probe['allow_constant_index_ancestors'])
    expected_controls = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
    controls = read(probe['local_control_receipt'])
    require(probe.get('local_controls') == expected_controls
            and {name: controls.get(name, {}).get('reward') for name in expected_controls} == expected_controls,
            'SCC activity actual five local controls did not pass')
    public_input = checked(probe['public_input']);instruction = checked(probe['public_instruction'])
    require(hashlib.sha256(public_input.read_bytes() + instruction.read_bytes()).hexdigest() == probe.get('revision_hash'),
            'SCC activity public revision hash differs')
    from ..workbook import compare_workbooks
    actual_delta = compare_workbooks(public_input, checked(probe['goal']), checked(probe['goal']))
    delta = read(probe['expected_delta'])
    require(actual_delta.get('expected_change_count', 0) > 0
            and delta.get('expected_changes') == actual_delta.get('expected_changes')
            and delta.get('expected_change_count') == actual_delta['expected_change_count'] == probe.get('expected_change_count'),
            'SCC activity probe does not retain the complete actual changed-value set')
    collect_references(source_binding, bindings,
        historical_recipe_snapshots=entry.get('finance_evidence', {}).get('ancestor_recipe_snapshots', {}))
    checked(checker_reference)
    return {'activity_probe': deepcopy(probe_reference), 'checker': deepcopy(checker_reference),
            'baseline_sha256': entry['sha256'], 'edits_sha256': canonical(plan['edits']),
            'scope_inventory': deepcopy(source_binding['scope_inventory']), 'actual_checker_LO_executions': 6,
            'allow_constant_index_ancestors':probe['allow_constant_index_ancestors'],
            'complete_D_recomputed_without_LO': True, 'quality_recovery_difficulty_certified': False,
            'financial_source_correctness_certified': False}
