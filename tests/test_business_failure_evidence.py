"""Economic-error witnesses require complete recalculated evidence, not OJ zero alone."""
from copy import deepcopy
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.evaluation import business_failure_evidence as m


@pytest.fixture
def bundle(tmp_path):
    def put(name, data):
        p = tmp_path/name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data)); return m.reference(p)
    def make(goal=100, output=90, *, field='net_income', scale=1,
             baseline=0, output_type=None, extra=None):
        provenance = {'kind': 'three_complete_native_recalculated_value_maps', 'version': 1, 'roles': {}}
        maps = {}
        for role, value in [('input', baseline), ('reference', goal), ('output', output)]:
            path = tmp_path/role/'native.xlsx'; path.parent.mkdir(parents=True, exist_ok=True)
            book = openpyxl.Workbook(); book.active.title = 'Report'; book.active['A1'] = 'Hypothetical business'
            book.active['B2'] = value
            if role == 'output' and output_type == 'error': book.active['B2'].data_type = 'e'
            if extra:
                for cell, values in extra.items(): book.active[cell] = values[role]
            book.save(path); book.close()
            origin = path.with_name('original.xlsx'); origin.write_bytes(path.read_bytes())
            values = m.extract_native_maps(path); maps[role] = values
            original, recalculated = m.reference(origin), m.reference(path)
            receipt = {'TEST_ONLY_mock_native_boundary': True, 'kind': 'resource_bound_libreoffice_call',
                'role': 'source', 'status': 'completed', 'source': original, 'output': recalculated,
                'started_at': '2026-11-01T06:00:00+00:00', 'finished_at': '2026-11-01T06:00:01+00:00',
                'container_id': 'a'*64, 'actual_resources_verified': True, 'thread_cap_verified': True,
                'actual_resources': {'cpus_nanoseconds': 2_000_000_000, 'memory_bytes': 32*1024**3, 'pids_limit': 256},
                'thread_cap_before': {'container_id': 'a'*64, 'values': ['MAX_CONCURRENCY=2']},
                'thread_cap_after': {'container_id': 'a'*64, 'values': ['MAX_CONCURRENCY=2'], 'exit_code_observed': '0'}}
            for key, name in [('implementation', 'resource_engine.py'), ('upstream_engine', 'engine.py'),
                              ('thread_cap_adapter', 'thread_capped_resource_engine.py')]:
                receipt[key] = m.reference(m.ROOT/'src/sheets_factory/workbook'/name)
            provenance['roles'][role] = {'map_scope': 'complete_sparse_workbook',
                'original_workbook': original, 'recalculated_workbook': recalculated,
                'typed_map': put(role+'/typed.json', values['typed']),
                'raw_numeric_map': put(role+'/raw.json', values['raw_numeric']),
                'native_receipt': put(role+'/receipt.json', receipt)}
        bindings = {'E001/2027Q1/'+field: {'sheet': 'Report', 'cell': 'B2', 'role': 'report'}}
        scales = {'E001': scale}
        provenance['bindings'] = put('bindings.json', bindings)
        provenance['entity_money_scales'] = put('entity-money-scales.json', scales)
        return {'maps': maps, 'bindings': bindings, 'entity_money_scales': scales, 'provenance': provenance, 'put': put}
    return make


def run(b, reward=0, **kwargs):
    return m.analyze(b['maps']['input']['typed'], b['maps']['reference']['typed'], b['maps']['output']['typed'],
        bindings=b['bindings'], entity_money_scales=b['entity_money_scales'], provenance=b['provenance'],
        original_reward=reward, raw_reference=b['maps']['reference']['raw_numeric'],
        raw_output=b['maps']['output']['raw_numeric'], **kwargs)


@pytest.mark.parametrize('field,category', [('net_income','recognition'), ('current_tax','tax'),
    ('closing_cash','noncash_cashbridge'), ('closing_investment','investment'),
    ('dividend','distribution'), ('closing_retained_earnings','rollforward')])
def test_one_material_core_error_is_sufficient_without_a_cell_count_minimum(bundle, field, category):
    b = bundle(field=field); result = run(b)
    assert result['state'] == 'diagnosed' and result['business_failure_evidence'] is True
    assert result['business_qualified'] is True and result['original_reward'] == 0
    assert result['primary_reward_modified'] is False and result['new_LO_model_Harbor_calls'] == 0
    witness, = result['economic_witnesses']
    assert witness['category'] == category and witness['point'] == 'Report!B2'
    assert witness['expected_gbp'] == '100' and witness['actual_gbp'] == '90'
    assert witness['absolute_difference_gbp'] == '10' and witness['relative_difference'] == '0.1'


@pytest.mark.parametrize('scale,expected', [(1,'100'), (1000,'100000'), (1000000,'100000000'),
    ('GBP','100'), ('GBP000','100000'), ('mGBP','100000000')])
def test_entity_money_representation_converts_to_true_GBP(bundle, scale, expected):
    result = run(bundle(scale=scale)); assert result['business_failure_evidence'] is True
    assert result['economic_witnesses'][0]['expected_gbp'] == expected


@pytest.mark.parametrize('field', ['reported_associate_line', 'reported_current_tax', 'yoy_percent',
    'qoq_percent', 'net_margin_percent', 'ratio', 'cagr', 'index'])
def test_display_and_growth_or_ratio_only_failures_are_not_financial_witnesses(bundle, field):
    result = run(bundle(field=field))
    assert result['state'] == 'diagnosed' and result['business_failure_evidence'] is False
    assert not result['economic_witnesses'] and len(result['excluded_differences']) == 1


def test_half_cent_mGBP_primary_mismatch_is_excluded_by_unrounded_economic_difference(bundle):
    result = run(bundle(goal=.045, output=.0449999999999999, scale=1000000))
    assert result['primary_wrong_count'] == 1
    assert result['business_failure_evidence'] is False
    assert result['excluded_differences'][0]['reason'] == 'economic_difference_at_or_below_tolerance'


@pytest.mark.parametrize('expected,actual,witness', [(0,.01,False), (0,.02,True),
    (1_000_000_000,1_000_000_000.05,False), (1_000_000_000,1_000_000_000.2,True)])
def test_absolute_and_relative_tolerances_are_strict_and_not_a_hidden_epsilon(bundle, expected, actual, witness):
    result = run(bundle(goal=expected, output=actual))
    assert result['business_failure_evidence'] is witness


def test_raw_difference_without_primary_wrong_value_is_not_counted(bundle):
    result = run(bundle(goal=100.001, output=100.004))
    assert result['primary_wrong_count'] == 0 and result['business_failure_evidence'] is False


@pytest.mark.parametrize('value,kind', [('wrong text','quality_issues'), (True,'quality_issues'),
    (None,'coverage_issues'), ('#DIV/0!','quality_issues')])
def test_types_errors_and_missing_values_are_quality_or_coverage_findings(bundle, value, kind):
    result = run(bundle(output=value, output_type='error' if value == '#DIV/0!' else None))
    assert result['state'] == 'diagnosed' and result['business_failure_evidence'] is False
    assert result[kind] and not result['economic_witnesses']


def test_strong_model_success_is_accepted_as_success_not_relabelled_business_failure(bundle):
    result = run(bundle(output=100), reward=1)
    assert result['state'] == 'diagnosed' and result['business_failure_evidence'] is False
    assert result['business_qualified'] is False and result['original_reward'] == 1


def test_success_with_conflicting_recalculation_reports_quality_conflict_not_a_business_zero(bundle):
    result = run(bundle(output=90), reward=1)
    assert result['business_failure_evidence'] is False and result['original_reward'] == 1
    assert any(i['reason'] == 'original_success_conflicts_with_recalculated_core_values' for i in result['quality_issues'])


@pytest.mark.parametrize('fault', ['no_provenance', 'no_raw_maps', 'source_cache_only', 'failed_native',
    'wrong_engine', 'changed_output', 'partial_map', 'fake_map', 'unknown_scale', 'wrong_cap'])
def test_incomplete_or_unrecalculated_evidence_is_unknown_never_an_invented_zero(bundle, fault):
    b = bundle()
    role = b['provenance']['roles']['output']
    if fault == 'no_provenance': b['provenance'] = {}
    elif fault == 'no_raw_maps':
        result = m.analyze({}, {}, {}, bindings={}, entity_money_scales={},
            provenance=b['provenance'], original_reward=0)
        assert result['state'] == 'unknown' and result['business_failure_evidence'] is None
        return
    elif fault == 'source_cache_only': role['map_scope'] = 'unrecalculated_source_cache'
    elif fault in ('failed_native','wrong_engine','wrong_cap'):
        receipt = m._read(role['native_receipt'])
        if fault == 'failed_native': receipt['status'] = 'failed'
        elif fault == 'wrong_engine': receipt['implementation']['sha256'] = 'unsupported'
        else: receipt['thread_cap_after']['values'] = ['MAX_CONCURRENCY=8']
        role['native_receipt'] = b['put']('changed-native.json', receipt)
    elif fault == 'changed_output': Path(role['recalculated_workbook']['path']).write_bytes(b'changed')
    elif fault == 'partial_map':
        b['maps']['output']['typed'].pop('Report!A1')
        role['typed_map'] = b['put']('partial-typed.json', b['maps']['output']['typed'])
    elif fault == 'fake_map': b['maps']['output']['typed']['Report!B2'] = ['number','1.00']
    else: b['entity_money_scales']['E001'] = 500
    result = run(b)
    assert result['state'] == 'unknown' and result['business_failure_evidence'] is None
    assert result['business_qualified'] is None and result['original_reward'] == 0


def test_given_core_fact_change_is_a_quality_issue_not_financial_reasoning_failure(bundle):
    b = bundle(); next(iter(b['bindings'].values()))['role'] = 'provided_fact'
    b['provenance']['bindings'] = b['put']('given-bindings.json', b['bindings'])
    result = run(b)
    assert result['business_failure_evidence'] is False
    assert result['quality_issues'][0]['reason'] == 'changed_given_fact'


@pytest.mark.parametrize('which', ['bindings', 'entity_money_scales'])
def test_changed_semantic_position_or_money_scale_cannot_create_false_economic_evidence(bundle, which):
    b = bundle()
    if which == 'bindings': next(iter(b['bindings'].values()))['field'] = 'current_tax'
    else: b[which]['E001'] = 1000000
    result = run(b)
    assert result['state'] == 'unknown' and result['business_failure_evidence'] is None


def test_default_switch_is_enabled_but_explicit_disable_does_no_evidence_inspection():
    result = m.analyze({}, {}, {}, bindings={}, entity_money_scales={}, provenance={}, original_reward=0, enabled=False)
    assert result['state'] == 'disabled' and result['business_failure_evidence'] is None
    assert result['primary_reward_modified'] is False


def test_absent_provenance_object_is_unknown_instead_of_a_failure_score():
    result = m.analyze({}, {}, {}, bindings={}, entity_money_scales={}, provenance=None, original_reward=0)
    assert result['state'] == 'unknown' and result['business_failure_evidence'] is None


def test_workbook_mutation_during_extraction_cannot_leave_a_valid_native_proof(bundle, monkeypatch):
    b = bundle(); extractor = m.extract_native_maps
    output = b['provenance']['roles']['output']['recalculated_workbook']['path']
    def mutate(path):
        values = extractor(path)
        if str(path) == output: Path(path).write_bytes(b'changed after complete extraction')
        return values
    monkeypatch.setattr(m, 'extract_native_maps', mutate)
    result = run(b)
    assert result['state'] == 'unknown' and result['business_failure_evidence'] is None
