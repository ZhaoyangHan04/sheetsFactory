"""One-source capital-allocation admission for the ordinary quality pipeline."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ..task_adapters.public_workbook_scope import checked_bytes, read, reference, require
from ..task_adapters.lease_family import compare_exact_typed
from ..workbook.capital_allocation.ledger import simulate
from ..workbook.capital_allocation.spec import RAW_ANCESTORS, load_spec
from ..workbook.capital_allocation.search import validate_certificate
from ..workbook.capital_allocation.validate import audit_capital_allocation_workbook
from .factory import FactoryPipeline

SOURCE_KIND = 'independently_audited_hypothetical_capital_allocation_source'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
METHOD = 'complete_independent_integer_search_and_Decimal_journal_actual_formula_audit_v1'


def collect_references(value, artifacts=None):
    artifacts = {} if artifacts is None else artifacts
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            checked_bytes(value)
            path = value['path']
            require(path not in artifacts or artifacts[path] == value['sha256'], 'Conflicting capital source artifact identities')
            artifacts[path] = value['sha256']
        for child in value.values(): collect_references(child, artifacts)
    elif isinstance(value, list):
        for child in value: collect_references(child, artifacts)
    return artifacts


def validate_source(source_manifest):
    """Recompute a complete source admission without a search, LO or a model."""
    if isinstance(source_manifest, (str, Path)): source_manifest = reference(source_manifest)
    source = read(source_manifest); collect_references(source)
    require(source.get('kind') == 'independently_verified_hypothetical_capital_allocation_source'
            and type(source.get('version')) is int and source['version'] == 1
            and source.get('status') == 'source_verified_not_task_or_difficulty_qualified'
            and source.get('financial_audit_passed') is True
            and source.get('actual_LO_recalculations') == 3 and type(source['actual_LO_recalculations']) is int
            and source.get('model_calls') == 0 and type(source['model_calls']) is int
            and source.get('quality_or_difficulty_certified') is False
            and source.get('qualified') is False and type(source.get('task_count')) is int and source['task_count'] == 0,
            'An actual independently audited capital-allocation source is required')
    workbook = source['workbook']; checked_bytes(workbook)
    require(source.get('derived_workbook_sha256') == workbook['sha256']
            and Path(source['local_path']).absolute() == Path(workbook['path']), 'The source workbook identity changed')
    require(source.get('hypothetical_forecasts_and_policy') is True and source.get('source_ancestor_unique_count') == 2
            and set(source['raw_ancestors']) == set(RAW_ANCESTORS)
            and all(source['raw_ancestors'][name]['sha256'] == digest for name, digest in RAW_ANCESTORS.items()),
            'Both original raw ancestors and the synthetic forecast declaration are required')
    spec = load_spec(read(source['public_specification']))
    proof = validate_certificate(source['search_certificate'], spec)
    require(source['validated_search_proof'] and read(source['validated_search_proof']) == proof
            and source['independent_complete_enumeration'] == proof['verification'],
            'The source does not bind the exact complete two-implementation optimisation proof')
    ledger = simulate(spec, proof['best_plan'])
    require(ledger == read(source['independent_ledger']) and ledger.get('feasible') is True
            and ledger['objective_pence'] == proof['objective_pence'], 'The posted source journal differs from public primitives or the unique optimum')
    binding = read(source['bindings'])
    require(binding.get('gold_plan_supplied') is True and binding.get('optimisation_performed') is False
            and binding.get('arithmetic_support_values_are_protected') is False
            and binding.get('plan_dependent_caches_must_be_cleared_before_task_input') is True
            and binding.get('task_input_requires_actual_recalculation_and_audit') is True
            and binding.get('complete_required_D_includes_changed_arithmetic_helpers') is True,
            'The source must preserve the full plan-dependent helper and input-recalculation contract')
    for path, digest in source['source_recipe_sha256'].items():
        require(reference(path)['sha256'] == digest, 'A capital source financial implementation changed')
    runtime = source['runtime']
    require(runtime.get('image_id') == IMAGE_ID and runtime.get('network') == 'none'
            and runtime.get('backend') == 'libreoffice_uno_docker', 'The source actual runtime differs')
    calls = source['engine_calls']; reports = source['financial_audits']
    require(len(calls) == len(reports) == 3 and [call.get('index') for call in calls] == [1, 2, 3]
            and all(type(call.get('index')) is int and call.get('completed') is True
                    and call.get('image_id') == IMAGE_ID and call.get('network') == 'none' for call in calls),
            'Normalization and both further actual stability executions are required')
    require(calls[0]['output'] == workbook and calls[1]['input'] == calls[0]['output']
            and calls[2]['input'] == calls[1]['output'], 'The actual source recalculation chain differs')
    for call, report_ref in zip(calls, reports):
        started, terminal = read(call['started_receipt']), read(call['terminal_receipt'])
        require(started.get('completed') is False and started.get('input') == call['input']
                and started.get('index') == call['index']
                and terminal == {key: value for key, value in call.items() if key != 'terminal_receipt'},
                'Actual started and terminal calculation receipts are inconsistent')
        report = read(report_ref)
        require(report.get('workbook') == call['output'] and report.get('passed') is True
                and report.get('all_formula_cells_independently_covered') is True
                and report.get('formula_count') == report.get('checked_cells') == binding['formula_count']
                and not report.get('mismatches') and not report.get('control_mismatches')
                and report.get('all_scenarios_feasible') is True and report.get('all_journals_balance') is True,
                'The source lacks complete actual independent formula checks')
    expected = {'workbook': workbook, **audit_capital_allocation_workbook(workbook['path'], spec, proof['best_plan'], ledger, binding)}
    require(expected.get('passed') is True and expected == read(reports[0]), 'The original actual source financial audit cannot be reproduced')
    stable = {'first_against_goal': compare_exact_typed(workbook['path'], calls[1]['output']['path']),
              'second_against_goal': compare_exact_typed(workbook['path'], calls[2]['output']['path'])}
    stable['stable'] = all(row['passed'] for row in stable.values())
    require(stable['stable'] is True and stable == read(source['stability']), 'The complete actual source is not stable in both further passes')
    preparation = read(source['source_preparation'])
    require(preparation.get('raw_ancestors') == source['raw_ancestors']
            and preparation.get('recipe_sha256') == source['source_recipe_sha256']
            and read(preparation['public_specification']) == spec,
            'The source differs from its zero-call public-input preparation')
    result = {'validation_method': METHOD, 'workbook': deepcopy(workbook), 'source_manifest': deepcopy(source_manifest),
        'public_specification': deepcopy(source['public_specification']), 'bindings': deepcopy(source['bindings']),
        'independent_ledger': deepcopy(source['independent_ledger']),
        'complete_enumeration': deepcopy(source['search_certificate']),
        'independent_complete_enumeration': deepcopy(source['independent_complete_enumeration']),
        'financial_audits': deepcopy(reports), 'stability': deepcopy(source['stability']),
        'runtime': deepcopy(runtime), 'source_recipe_sha256': deepcopy(source['source_recipe_sha256']),
        'quality_or_difficulty_certified': False}
    collect_references(result)
    return result


class CapitalAllocationFactory(FactoryPipeline):
    """Run one admitted first-source FM through normal scheduling and budgets."""

    def __init__(self, *args, admitted_proof=None, **kwargs):
        require(isinstance(admitted_proof, dict) and admitted_proof.get('validation_method') == METHOD,
                'The entry must supply its complete checked source admission')
        self.admitted_proof = deepcopy(admitted_proof)
        collect_references(self.admitted_proof)
        super().__init__(*args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        require(self.targets == {'financial_modeling': 1, 'debugging': 0} and len(seeds) == 1,
                'Only the first capital-allocation FM development source is admitted')
        seed = seeds[0]; actual = reference(seed['local_path'])
        evidence = seed.get('finance_evidence', {})
        require(seed.get('source_kind') == SOURCE_KIND and seed.get('modes') == ['financial_modeling']
                and type(seed.get('variant', 0)) is int and seed.get('variant', 0) == 0
                and actual == self.admitted_proof['workbook'] and seed.get('sha256') == actual['sha256']
                and evidence.get('audited_source_binding') == self.admitted_proof
                and evidence.get('source_manifest') == self.admitted_proof['source_manifest'],
                'The exact original independently admitted financial workbook is required')
        collect_references(self.admitted_proof)
        seed['survey'] = {**seed.get('survey', {}), 'normalized_path': actual['path'], 'status': 'ok', 'error_count': 0}
        return seeds

    def run_phase(self, context, phase):
        result = super().run_phase(context, phase)
        identity = self.admitted_proof['workbook']['sha256']
        require(reference(context.source) == self.admitted_proof['workbook'], 'The capital source changed after admission')
        if context.data.get('baseline'):
            require(reference(context.data['baseline'])['sha256'] == context.data.get('source_id') == identity,
                    'Normalization changed the exact audited capital source')
        return result
