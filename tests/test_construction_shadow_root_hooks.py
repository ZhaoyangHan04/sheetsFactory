"""Construction routing tests use explicit certificates, never pretend LO runs."""
from copy import deepcopy
import hashlib
import json
import sys
import types

import pytest

from sheets_factory.core.node import TaskRejected
from sheets_factory.nodes import construction as module
from test_construction_template_and_root_proof_hooks import construction_fixture


@pytest.fixture
def shadow_fixture(construction_fixture, monkeypatch):
    context, observed = construction_fixture
    context.config['construction']['root_impact_validation'] = 'shadow_roots'
    observed['alter_certificate'] = lambda certificate: None
    fake = types.ModuleType('sheets_factory.checkers.shadow_roots')

    def prove(**kwargs):
        observed['certificate_calls'].append(kwargs)
        edits = kwargs['edits']
        impacts = []
        for index, edit in enumerate(edits):
            root = edit['sheet'] + '!' + edit['cell']
            lower = {'expected_change_count': 1, 'expected_changes': [root],
                'counts_are_lower_bounds': True, 'actual_individual_LO_execution': False,
                'actual_context_shadow_LO_execution': True,
                'proof_method': 'actual_scalar_shadow_value_and_complete_union_DAG'}
            impacts.append({**lower, 'root_index': index,
                'evidence': {'root_index': index, 'root': root, 'individual_active': True,
                    'combined_marginal_active': True},
                'combined_marginal': {**lower, 'edits_reversed': True, 'base': 'full_combined_mutation'}})
        certificate = {'passed': True, 'blocking': False, 'state': 'proven',
            'proof_method': 'two_actual_scalar_shadow_contexts_under_complete_union_DAG',
            'actual_LO_started_count': 2, 'actual_LO_execution_count': 2,
            'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False,
            'goal_sha256': module.digest(kwargs['goal']),
            'combined_input_sha256': module.digest(kwargs['combined_input']),
            'edits_sha256': hashlib.sha256(json.dumps(edits, sort_keys=True, ensure_ascii=False,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
            'union_graph': {'state': 'proven', 'acyclic': True, 'all_reference_branches_included': True,
                'all_before_after_formulas_included': True, 'frontier_omitted': False,
                'all_ancestor_functions_pure_and_position_independent': True},
            'contexts': [{'kind': kind, 'all_business_definitions_unchanged': True,
                'all_business_exact_typed_values_unchanged': True, 'shadow_count': len(edits)}
                for kind in ('individual', 'combined_marginal')], 'root_impacts': impacts}
        observed['alter_certificate'](certificate)
        return deepcopy(certificate)

    fake.prove_shadow_root_impacts = prove
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    return context, observed


def test_shadow_proof_routes_limits_and_records_only_two_context_executions(shadow_fixture):
    context, observed = shadow_fixture
    result = module.ConstructNode().execute(context)
    assert observed['calculations'] == 1  # Combined book only; the proof is explicitly mocked.
    assert len(observed['certificate_calls']) == 1
    called = observed['certificate_calls'][0]
    assert called['goal'] == result['goal'] and called['combined_input'] == result['input']
    assert called['max_dependency_cells'] == 500000
    assert called['per_formula_reference_cells'] == 50000
    assert called['directory'].parent.name == 'shadow_root_impact_probes'
    assert (context.revision_dir / 'private/shadow_roots_certificate.json').is_file()
    evidence = result['construction_validation']['root_impact_validation']
    assert evidence['actual_shadow_LO_execution_count'] == 2
    assert evidence['individual_LO_executions'] is False
    assert evidence['marginal_LO_executions'] is False
    assert evidence['counts_are_lower_bounds'] is True
    assert evidence['complete_per_root_changed_sets_claimed'] is False
    assert len(result['root_impacts']) == 6


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(state='rejected', passed=False, blocking=True, reason='Unsupported range'),
    lambda c: c.update(actual_LO_execution_count=1),
    lambda c: c.update(goal_sha256='0' * 64),
    lambda c: c.update(edits_sha256='0' * 64),
    lambda c: c['root_impacts'].pop(),
    lambda c: c['root_impacts'][0]['combined_marginal'].update(base='original'),
    lambda c: c['root_impacts'][0]['evidence'].update(combined_marginal_active=False),
    lambda c: c['root_impacts'][0].update(actual_individual_LO_execution=True),
    lambda c: c['contexts'][0].update(all_business_exact_typed_values_unchanged=False),
    lambda c: c['contexts'][0].update(shadow_count=1),
    lambda c: c['union_graph'].update(frontier_omitted=True),
    lambda c: c['union_graph'].update(all_ancestor_functions_pure_and_position_independent=False),
])
def test_incomplete_shadow_proofs_are_saved_and_never_fall_back(shadow_fixture, mutation):
    context, observed = shadow_fixture
    observed['alter_certificate'] = mutation
    with pytest.raises(TaskRejected, match='shadow root-impact proof rejected'):
        module.ConstructNode().execute(context)
    assert observed['calculations'] == 1
    assert (context.revision_dir / 'private/shadow_roots_certificate.json').is_file()
    assert not observed['profile_kwargs']


def test_shadow_engine_error_is_not_misclassified_as_an_inactive_root(shadow_fixture):
    context, observed = shadow_fixture
    observed['alter_certificate'] = lambda c: c.update(state='execution_error', passed=False,
        blocking=True, reason='Explicit fixture worker failure')
    with pytest.raises(RuntimeError, match='Shadow root-impact recalculation failed'):
        module.ConstructNode().execute(context)
    assert observed['calculations'] == 1
