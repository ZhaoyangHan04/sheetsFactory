from sheets_factory.checkers.unsafe_regions import inspect_unsafe_regions, parse_region


def risk(certainty='confirmed'):
    return {'risk_id': 'unit-mismatch', 'certainty': certainty,
            'unsafe_regions': [{'sheet': 'Income', 'range': 'E31:P34'}],
            'evidence': [{'cell': 'Income!B33', 'label': 'Net Profit (monthly)'},
                         {'cell': 'Income!E31', 'claim': 'Annual depreciation subtracted as monthly cost'}]}


def test_full_delta_includes_downstream_cells_outside_physical_edits():
    result = inspect_unsafe_regions(['Depreciation!D6', 'Income!E31', 'Income!F33'], [risk()],
                                   sheet_names=['Income', 'Depreciation'])
    assert result['state'] == 'flagged'
    assert result['issues'][0]['route_id'] == 'R09'
    assert result['issues'][0]['affected_cells'] == ['Income!E31', 'Income!F33']


def test_same_source_with_disjoint_delta_is_not_blanket_rejected():
    result = inspect_unsafe_regions(['Balance Sheet!F9', 'Balance Sheet!F10', 'Balance Sheet!F11'],
                                   [risk()], sheet_names=['Income', 'Balance Sheet', 'Depreciation'])
    assert result['state'] == 'clear'
    assert not result['blocking']


def test_suspected_intersection_requires_evidence_instead_of_confirmed_repair():
    result = inspect_unsafe_regions(['Income!E33'], [risk('suspected')], sheet_names=['Income'])
    assert result['state'] == 'unknown'
    assert result['issues'][0]['route_id'] == 'R12'


def test_unstructured_legacy_description_cannot_be_silently_cleared():
    result = inspect_unsafe_regions(['Income!E33'], ['Possible period mismatch in Income!E31:P34'], sheet_names=['Income'])
    assert result['state'] == 'unknown'
    assert result['evidence_requests']


def test_invalid_registry_sheet_or_missing_fact_evidence_is_unknown():
    assert inspect_unsafe_regions(['Income!E33'], [risk()], sheet_names=['Other'])['state'] == 'unknown'
    incomplete = risk()
    incomplete['evidence'] = []
    assert inspect_unsafe_regions(['Income!E33'], [incomplete], sheet_names=['Income'])['state'] == 'unknown'


def test_sheet_names_preserve_significant_spaces_and_quotes():
    supplied = {'risk_id': 'quoted', 'certainty': 'confirmed',
                'unsafe_regions': ["'Income Statement 50% '!$E$31:$P$34"], 'evidence': ['specific observed defect']}
    assert inspect_unsafe_regions(['Income Statement 50% !F33'], [supplied],
                                 sheet_names=['Income Statement 50% '])['state'] == 'flagged'
    assert parse_region("'It''s a sheet'!A1").sheet == "It's a sheet"


def test_large_bounded_region_uses_membership_without_cell_expansion():
    supplied = {'risk_id': 'large', 'certainty': 'confirmed',
                'unsafe_regions': ['Sheet!A1:XFD1048576'], 'evidence': ['fixture broad unsafe region']}
    result = inspect_unsafe_regions(['Sheet!XFD1048576', 'Sheet!XFD1048576'], [supplied], sheet_names=['Sheet'])
    assert result['full_delta_size'] == 1
    assert result['issues'][0]['affected_cells'] == ['Sheet!XFD1048576']


def test_no_registry_is_not_an_assertion_that_baseline_is_correct():
    result = inspect_unsafe_regions(['Sheet!A1'], [], sheet_names=['Sheet'])
    assert result['state'] == 'not_applicable'
    assert 'not baseline certification' in result['reason']


def write_registry(tmp_path, sources):
    import json
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps({'schema_version': 1, 'sources': sources}))
    return path


def test_registry_selection_requires_exact_full_hash_never_reference_filename(tmp_path):
    from sheets_factory.checkers.unsafe_regions import evaluate_native_risk_guard
    path = write_registry(tmp_path, [{'source_sha256': 'a' * 64, 'reference_name': 'same-name.xls', 'risks': [risk()]}])
    blocked = evaluate_native_risk_guard(['Income!E31'], 'a' * 64, project_root=tmp_path,
        registry_path=path, sheet_names=['Income'])
    other_source = evaluate_native_risk_guard(['Income!E31'], 'b' * 64, project_root=tmp_path,
        registry_path=path, sheet_names=['Income'])
    assert blocked['blocking'] and blocked['registered_risk_count'] == 1
    assert other_source['state'] == 'not_applicable' and not other_source['blocking']
    assert other_source['registered_risk_count'] == 0
    assert blocked['llm_q09_still_required'] and not blocked['baseline_business_correctness_certified']


def test_legacy_prose_and_malformed_facts_are_unknown_but_cannot_program_block(tmp_path):
    from sheets_factory.checkers.unsafe_regions import evaluate_native_risk_guard
    malformed = risk()
    malformed['unsafe_regions'] = ['Income!entire sheet']
    path = write_registry(tmp_path, [{'source_sha256': 'a' * 64, 'risks': [malformed]}])
    result = evaluate_native_risk_guard(['Income!E33'], 'a' * 64, project_root=tmp_path,
        registry_path=path, sheet_names=['Income'], legacy_risks=['Possible native issue, inspect with LLM.'])
    assert result['state'] == 'unknown' and not result['blocking']
    assert len(result['evidence_requests']) == 2
    assert result['legacy_risks'] == ['Possible native issue, inspect with LLM.']
    assert result['llm_q09_still_required']


def test_suspected_structured_intersection_is_not_a_programmatic_confirmation():
    result = inspect_unsafe_regions(['Income!E31'], [risk('suspected')], sheet_names=['Income'])
    assert result['state'] == 'unknown' and not result['blocking']


def test_malformed_registry_or_unknown_source_identity_never_becomes_clear(tmp_path):
    from sheets_factory.checkers.unsafe_regions import evaluate_native_risk_guard
    path = tmp_path / 'bad.json'
    path.write_text('{invalid')
    result = evaluate_native_risk_guard(['Income!E31'], 'a' * 64, project_root=tmp_path,
        registry_path=path, sheet_names=['Income'])
    assert result['state'] == 'unknown' and not result['blocking']
    path.write_text('{"sources": [{"source_sha256": "only-prefix"}]}')
    result = evaluate_native_risk_guard(['Income!E31'], 'a' * 64, project_root=tmp_path,
        registry_path=path, sheet_names=['Income'])
    assert result['state'] == 'unknown' and result['evidence_requests']
    result = evaluate_native_risk_guard(['Income!E31'], 'only-prefix', project_root=tmp_path,
        sheet_names=['Income'])
    assert result['state'] == 'unknown' and not result['blocking']


def test_actual_registered_facts_allow_safe_asset_module_but_block_wrong_monthly_income():
    from pathlib import Path
    from sheets_factory.checkers.unsafe_regions import evaluate_native_risk_guard
    root = Path(__file__).resolve().parents[1]
    source = 'bbcce4d0b5921ebc42fb5d2772293e35a114c784c74e184a38c3d94eb767fca6'
    sheet_names = ['Income', 'Balance Sheet', 'Cashflow', 'Depreciation', 'simple income', 'RoadMap']
    contaminated = evaluate_native_risk_guard(['Depreciation!E7', 'Income!E31', 'Income!E33'], source,
        project_root=root, sheet_names=sheet_names)
    local_assets = evaluate_native_risk_guard(['Balance Sheet!F9', 'Balance Sheet!F10', 'Balance Sheet!F11'], source,
        project_root=root, sheet_names=sheet_names)
    assert contaminated['blocking']
    assert contaminated['issues'][0]['affected_cells'] == ['Income!E31', 'Income!E33']
    assert local_assets['state'] == 'clear' and not local_assets['blocking']


def test_missing_risk_identifier_is_not_a_valid_clear_assessment():
    incomplete = risk()
    del incomplete['risk_id']
    result = inspect_unsafe_regions(['Balance Sheet!F9'], [incomplete], sheet_names=['Income', 'Balance Sheet'])
    assert result['state'] == 'unknown' and not result['blocking']
