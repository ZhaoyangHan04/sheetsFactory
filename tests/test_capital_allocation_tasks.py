"""Public-only toy recovery and complete normal-node admission; no LO/search18/model."""
import ast
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.task_adapters import capital_allocation as adapter
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new
from sheets_factory.workbook.capital_allocation import public_recovery as recovery
from sheets_factory.workbook.capital_allocation.excel import emit_capital_allocation_workbook
from sheets_factory.workbook.capital_allocation.ledger import simulate
from sheets_factory.workbook.capital_allocation.spec import PROJECT_IDS, SCENARIO_IDS, YEARS, SCALE, RAW_ANCESTORS
from sheets_factory.workbook.capital_allocation.validate import expected_cells

ROOT = Path(__file__).resolve().parents[1]


def specification():
    annual = lambda number: {str(year): number for year in YEARS}
    projects = []
    for index, identity in enumerate(PROJECT_IDS):
        projects.append({'id': identity, 'commission_year': 2024, 'sale_year': 2029,
            'acquisition_cost_pence': 120 + 25 * index, 'depreciation_years': 3,
            'annual_revenue_pence': {str(y): (150 if index == 0 else 40) if 2024 < y <= 2029 else 0 for y in YEARS},
            'annual_opex_pence': {str(y): 20 if 2024 < y <= 2029 else 0 for y in YEARS},
            'sale_proceeds_pence': 90})
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
        'opening_cash_pence': 300, 'minimum_cash_pence': 10, 'lp_commitment_pence': 600,
        'facility_limit_pence': 500, 'advance_rate_p12': SCALE * 3 // 4,
        'tax_rate_p12': SCALE // 4, 'tax_loss_carry_years': 2,
        'discount_factors_p12': {str(y): SCALE - 25_000_000_000 * (y - 2023) for y in YEARS},
        'projects': projects, 'scenarios': [{'id': identity,
            'revenue_factors_p12': annual(SCALE if index != 1 else SCALE * 7 // 10),
            'opex_factors_p12': annual(SCALE if index != 2 else SCALE * 13 // 10),
            'nav_factors_p12': annual(SCALE), 'sale_factors_p12': annual(SCALE),
            'bank_rates_p12': annual(SCALE // 10), 'haircuts_p12': annual(0)}
            for index, identity in enumerate(SCENARIO_IDS)],
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(RAW_ANCESTORS)}}


@pytest.fixture(scope='module')
def financial_fixture(tmp_path_factory):
    directory = tmp_path_factory.mktemp('capital-task-public-toy')
    spec = specification()
    book = openpyxl.Workbook(); book.remove(book.active)
    binding = emit_capital_allocation_workbook(book, spec, dict.fromkeys(PROJECT_IDS, 1))
    baseline = directory / 'source.xlsx'; book.save(baseline); book.close()
    binding_ref = write_new(directory / 'bindings.json', binding)
    manifest = write_new(directory / 'source_manifest.json', {'fixture_only': True})
    proof = {'workbook': reference(baseline), 'bindings': binding_ref, 'source_manifest': manifest}
    return directory, spec, baseline, binding, proof


def install_admission(monkeypatch, proof):
    def validate(record):
        assert record == proof['source_manifest']
        return deepcopy(proof)
    stub = SimpleNamespace(__file__=__file__, validate_source=validate)
    monkeypatch.setattr(adapter, 'source_admission', lambda: stub)


def make_context(directory, baseline, proof):
    return TaskContext(run_id='toy', task_id='fm-toy', mode='financial_modeling', source=baseline,
        directory=directory, config={adapter.SETTING: adapter.setting()}, audit=SimpleNamespace(emit=lambda *a, **k: None),
        llm=SimpleNamespace(), engine=SimpleNamespace(), data={'baseline': baseline,
            'finance_evidence': {'financial_seed_verified': True, 'financial_modeling_eligible': True,
                'source_manifest': proof['source_manifest'], 'audited_source_binding': deepcopy(proof)}})


def mask_copy(baseline, destination, binding):
    book = openpyxl.load_workbook(baseline)
    for item in binding['financial_bindings'] + binding['decision_bindings']:
        book[item['sheet']][item['cell']] = None
    book.save(destination); book.close()


def replace_zip_cell(path, sheet, coordinate, transform):
    with ZipFile(path) as archive:
        records = {item.filename: (item, archive.read(item)) for item in archive.infolist()}
        name = adapter._paths(archive)[sheet]
    root = ET.fromstring(records[name][1])
    cell = next(cell for cell in root.findall('.//m:sheetData/m:row/m:c', adapter.NS) if cell.get('r') == coordinate)
    transform(cell)
    records[name] = records[name][0], ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for item, raw in records.values(): archive.writestr(item, raw)


def test_plan_masks_all_financial_fields_and_all_shared_choices_not_support(financial_fixture, monkeypatch):
    _, _, baseline, binding, proof = financial_fixture
    install_admission(monkeypatch, proof)
    plan = adapter.propose_capital_allocation_task(baseline, proof['source_manifest'])
    actual = {(item['sheet'], item['cell']) for item in plan['edits']}
    expected = {(item['sheet'], item['cell']) for item in binding['financial_bindings'] + binding['decision_bindings']}
    assert len(actual) == len(plan['edits']) == 19049 and actual == expected
    assert not actual & {(item['sheet'], item['cell']) for item in binding['arithmetic_bindings']}
    assert 'mask_ranges' not in plan and all(item['after'] is None for item in plan['edits'])
    assert plan['family_adapter']['helper_values_are_protected'] is False
    assert plan['family_adapter']['full_workbook_D_required'] is True
    assert plan['family_adapter']['plan_dependent_support_count'] > 0
    assert 'maximises the worst' in plan['public_instruction']
    assert adapter.CLAUSES['financial_modeling'] in plan['public_instruction']
    assert not re.search(r'best.?plan|optimal.?npv|objective_pence|P0[1-9].*=[01]', plan['public_instruction'], re.I)


@pytest.mark.parametrize('change', ['missing_decision', 'reordered_decisions', 'protected_support', 'masked_support', 'duplicate_target', 'no_gold_plan'])
def test_binding_changes_cannot_shrink_or_protect_scope(financial_fixture, change):
    binding = deepcopy(financial_fixture[3])
    if change == 'missing_decision': binding['decision_bindings'].pop()
    if change == 'reordered_decisions': binding['decision_bindings'].reverse()
    if change == 'protected_support': binding['arithmetic_bindings'][0]['value_protected'] = True
    if change == 'masked_support': binding['arithmetic_bindings'][0]['target_eligible'] = True
    if change == 'duplicate_target': binding['financial_bindings'].append(binding['financial_bindings'][0])
    if change == 'no_gold_plan': binding['gold_plan_supplied'] = False
    with pytest.raises(ValueError): adapter._targets(binding)


@pytest.mark.parametrize('change', ['debugging', 'unverified', 'ineligible', 'proof_mismatch', 'baseline_mismatch', 'setting_mismatch'])
def test_plan_context_fails_closed(financial_fixture, monkeypatch, tmp_path, change):
    _, _, baseline, _, proof = financial_fixture
    install_admission(monkeypatch, proof)
    ctx = make_context(tmp_path, baseline, proof)
    if change == 'debugging': ctx.mode = 'debugging'
    if change == 'unverified': ctx.data['finance_evidence']['financial_seed_verified'] = False
    if change == 'ineligible': ctx.data['finance_evidence']['financial_modeling_eligible'] = False
    if change == 'proof_mismatch': ctx.data['finance_evidence']['audited_source_binding']['extra'] = 1
    if change == 'baseline_mismatch':
        altered = tmp_path / 'changed.xlsx'; altered.write_bytes(b'changed'); ctx.data['baseline'] = altered
    if change == 'setting_mismatch': ctx.config[adapter.SETTING]['helper_values_are_protected'] = True
    with pytest.raises(ValueError): adapter.CapitalAllocationPlanNode().execute(ctx)


def test_normal_raw_draft_has_no_gold_support_caches(financial_fixture, tmp_path):
    _, _, baseline, binding, _ = financial_fixture
    draft = tmp_path / 'draft.xlsx'; mask_copy(baseline, draft, binding)
    receipt = adapter.audit_input_helper_caches(baseline, draft, binding)
    assert receipt['passed'] and receipt['masked_financial_and_decision_count'] == 19049
    assert receipt['plan_dependent_caches_cleared_count'] == sum(x['plan_dependent'] for x in binding['arithmetic_bindings'])
    assert receipt['helper_values_protected'] is False and receipt['helpers_physically_masked'] is False
    helper = next(x for x in binding['arithmetic_bindings'] if x['plan_dependent'])
    def cache(cell):
        value = cell.find('m:v', adapter.NS)
        if value is None: value = ET.SubElement(cell, '{' + adapter.NS['m'] + '}v')
        value.text = '123456789'
    replace_zip_cell(draft, helper['sheet'], helper['cell'], cache)
    with pytest.raises(ValueError, match='gold cached'): adapter.audit_input_helper_caches(baseline, draft, binding)


@pytest.mark.parametrize('change', ['public_input', 'helper_formula', 'missing_mask'])
def test_raw_draft_rejects_definition_or_input_changes(financial_fixture, tmp_path, change):
    _, _, baseline, binding, _ = financial_fixture
    draft = tmp_path / 'draft.xlsx'; mask_copy(baseline, draft, binding)
    book = openpyxl.load_workbook(draft)
    if change == 'public_input': book['Capital Inputs']['B3'] = 'changed'
    if change == 'helper_formula':
        item = binding['arithmetic_bindings'][0]; book[item['sheet']][item['cell']] = '=99'
    if change == 'missing_mask':
        item = binding['decision_bindings'][0]; book[item['sheet']][item['cell']] = '=1'
    book.save(draft); book.close()
    with pytest.raises(ValueError): adapter.audit_input_helper_caches(baseline, draft, binding)


def test_registry_retains_normal_quality_and_explicit_new_recovery():
    registry = yaml.safe_load((ROOT / 'config/task_adapters/capital_allocation_nodes.yaml').read_text())['nodes']
    assert set(registry) == {'normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck',
        'independent_recovery', 'trajectory', 'diagnose', 'repair', 'export'}
    for node in ('instruction', 'precheck'):
        assert registry[node].startswith('sheets_factory.nodes.construction:')
    for node in ('trajectory', 'diagnose', 'repair', 'export'):
        assert registry[node].startswith('sheets_factory.nodes.quality:')
    assert registry['independent_recovery'].endswith('public_recovery:CapitalAllocationRecoveryNode')


def test_construct_delegates_normal_recalculation_and_keeps_helper_changes_in_complete_D(tmp_path, monkeypatch):
    """A small mocked engine contract is not an actual source or LO receipt."""
    book = openpyxl.Workbook(); book.active.title = 'Financial'; book.create_sheet('Investment Plan')
    book.create_sheet('Exact Arithmetic'); book['Financial']['A1'] = 'Provided primitive'
    financial = []
    for index in range(1, 7):
        book['Financial'].cell(index, 2, '=1')
        financial.append({'sheet': 'Financial', 'cell': 'B' + str(index), 'target_eligible': True})
    decisions = []
    for index, identity in enumerate(PROJECT_IDS, 3):
        book['Investment Plan'].cell(index, 1, identity); book['Investment Plan'].cell(index, 2, '=1')
        decisions.append({'sheet': 'Investment Plan', 'cell': 'B' + str(index),
            'project_id': identity, 'target_eligible': True})
    book['Exact Arithmetic']['B1'] = "='Investment Plan'!B3*2"
    support = [{'sheet': 'Exact Arithmetic', 'cell': 'B1', 'target_eligible': False,
        'value_protected': False, 'plan_dependent': True}]
    binding = {'financial_bindings': financial, 'decision_bindings': decisions,
        'arithmetic_bindings': support, 'gold_plan_supplied': True}
    baseline = tmp_path / 'source.xlsx'; book.save(baseline); book.close()
    def cache(cell):
        cell.find('m:v', adapter.NS).text = '2'
    replace_zip_cell(baseline, 'Exact Arithmetic', 'B1', cache)
    manifest = write_new(tmp_path / 'source_manifest.json', {'fixture_only': True})
    proof = {'workbook': reference(baseline), 'bindings': write_new(tmp_path / 'bindings.json', binding),
        'source_manifest': manifest}
    install_admission(monkeypatch, proof)
    ctx = make_context(tmp_path / 'task', baseline, proof)
    ctx.data['plan'] = adapter.propose_capital_allocation_task(baseline, manifest)
    called = []
    def normal_construct(self, context):
        called.append(context)
        draft = context.revision_dir / 'private/mutated_unrecalculated.xlsx'; draft.parent.mkdir(parents=True)
        mask_copy(baseline, draft, binding)
        delta = adapter.compare_workbooks(draft, baseline, baseline)
        return {'input': draft, 'goal': baseline, 'delta': delta}
    monkeypatch.setattr(adapter.ConstructNode, 'execute', normal_construct)
    result = adapter.CapitalAllocationConstructNode().execute(ctx)
    assert called == [ctx] and result['delta']['expected_changes'] == ['Exact Arithmetic!B1']
    assert result['capital_allocation_input_scope']['changed_helper_count'] == 1
    assert result['capital_allocation_input_scope']['complete_required_D_count'] == 1
    assert result['capital_allocation_input_scope']['no_helper_values_excluded_from_required_D'] is True
    ctx.data['plan']['edits'].pop()
    with pytest.raises(ValueError, match='scope changed'): adapter.CapitalAllocationConstructNode().execute(ctx)
    assert called == [ctx]


def test_public_recovery_toy_search_reconstructs_every_financial_posting(financial_fixture, tmp_path):
    _, spec, baseline, binding, _ = financial_fixture
    public = tmp_path / 'input.xlsx'; mask_copy(baseline, public, binding)
    output = tmp_path / 'output.xlsx'
    report = recovery.recover_public(public, output, active_project_ids=['P01', 'P02', 'P03'])
    assert report['enumeration']['toy_only'] is True and report['enumeration']['plan_count'] == 8
    assert report['enumeration']['full_enumeration'] is False
    assert report['private_reference_or_search_certificate_read'] is False
    book = openpyxl.load_workbook(output, keep_links=False)
    plan = {identity: book['Investment Plan'].cell(index + 3, 2).value for index, identity in enumerate(PROJECT_IDS)}
    assert any(plan.values()) and not all(plan.values())
    decimal = simulate(spec, plan)
    expected = expected_cells(spec, plan, decimal, binding)
    for item in binding['financial_bindings'] + binding['decision_bindings']:
        key = "'" + item['sheet'].replace("'", "''") + "'!$" + re.sub(r'([A-Z]+)([0-9]+)', r'\1$\2', item['cell'])
        assert book[item['sheet']][item['cell']].value == expected[key], (item['sheet'], item['cell'])
    for item in binding['arithmetic_bindings']:
        assert book[item['sheet']][item['cell']].value == item['formula']
    book.close()
    assert report['financial_and_decision_cells_reconstructed'] == 19049
    assert report['actual_LO_replay_still_required'] is True


@pytest.mark.parametrize('change', ['labelled_integer', 'labelled_bool', 'public_rule', 'contract_duplicate', 'incomplete_project_rows', 'wrong_calendar'])
def test_public_recovery_contract_is_sufficient_exact_and_not_silently_repaired(financial_fixture, tmp_path, change):
    _, _, baseline, binding, _ = financial_fixture
    public = tmp_path / 'input.xlsx'; mask_copy(baseline, public, binding)
    book = openpyxl.load_workbook(public)
    if change.startswith('labelled_'):
        row = next(row for row in range(3, book['Capital Inputs'].max_row + 1)
            if book['Capital Inputs'].cell(row, 1).value == 'opening_cash_pence')
        book['Capital Inputs'].cell(row, 2, True if change == 'labelled_bool' else 301)
    if change == 'public_rule': book['Capital Rules']['A4'] = 'Use different choices by scenario.'
    if change == 'contract_duplicate':
        sheet = book['Capital Contract']; text = ''.join(sheet.cell(row, 2).value for row in range(2, sheet.max_row + 1))
        text = text.replace('{', '{"schema_version":1,', 1)
        for row in range(2, sheet.max_row + 1): sheet.cell(row, 1).value = sheet.cell(row, 2).value = None
        sheet['A2'] = 'JSON part 1'; sheet['B2'] = text[:30000]
        for index, start in enumerate(range(30000, len(text), 30000), 3):
            sheet.cell(index, 1, 'JSON part ' + str(index - 1)); sheet.cell(index, 2, text[start:start + 30000])
    if change == 'incomplete_project_rows': book['S01 Projects']['A4'] = 'P99'
    if change == 'wrong_calendar': book['S01 Annual']['C2'] = 'FY2025'
    book.save(public); book.close()
    with pytest.raises(ValueError): recovery.recover_public(public, tmp_path / 'output.xlsx', active_project_ids=['P01'])
    assert not (tmp_path / 'output.xlsx').exists()


def test_public_search_rejects_tied_optima_and_no_reference_artifact_is_an_argument():
    spec = specification()
    for project in spec['projects']:
        project['annual_revenue_pence'] = {str(y): 0 for y in YEARS}
        project['annual_opex_pence'] = {str(y): 0 for y in YEARS}
        project['sale_proceeds_pence'] = project['acquisition_cost_pence']
    spec['tax_rate_p12'] = 0; spec['discount_factors_p12'] = {str(y): SCALE for y in YEARS}
    with pytest.raises(ValueError, match='unique best'): recovery._choose_plan(spec, ['P01', 'P02'])
    assert 'certificate' not in recovery.recover_public.__code__.co_varnames


def test_standalone_bundle_contains_public_integer_calculation_only_and_full_search_default():
    program = recovery.compile_public_capital_recovery()
    assert program == recovery.compile_public_capital_recovery()
    parsed = ast.parse(program)
    payload = next(node.args[0].value for node in ast.walk(parsed) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == 'b64decode')
    with ZipFile(io.BytesIO(base64.b64decode(payload))) as archive:
        assert len(archive.namelist()) == 6
        modules = {name: archive.read(name).decode() for name in archive.namelist()}
    integer = modules['sheets_factory/workbook/capital_allocation/verify.py']
    public = modules['sheets_factory/workbook/capital_allocation/public_runtime.py']
    assert '_Interpreter' in integer and '_round_ratio' in integer
    for token in ('verify_search', 'plans_csv', 'ledger', 'search.cpp', '/data/', 'validate_certificate'):
        assert token not in integer + public
    assert 'read_public_spec' in public and '1 << len(active)' in public
    calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == 'recover_public']
    assert len(calls) == 1 and not calls[0].keywords
    assert not re.search(r'best_mask\s*=\s*\d|winner\s*=\s*\d', public)


def test_bundled_public_program_imports_without_repository_and_replays_toy_only(financial_fixture, tmp_path):
    _, _, baseline, binding, _ = financial_fixture
    public = tmp_path / 'input.xlsx'; mask_copy(baseline, public, binding)
    parsed = ast.parse(recovery.compile_public_capital_recovery())
    payload = next(node.args[0].value for node in ast.walk(parsed) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == 'b64decode')
    bundle = tmp_path / 'pure_public_bundle'; bundle.mkdir()
    with ZipFile(io.BytesIO(base64.b64decode(payload))) as archive: archive.extractall(bundle)
    runner = tmp_path / 'toy_entry.py'
    runner.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(bundle)) + ')\n'
        'from sheets_factory.workbook.capital_allocation.public_runtime import recover_public\n'
        'recover_public(Path("input.xlsx"),Path("output.xlsx"),Path("report.json"),active_project_ids=["P01","P02"])\n')
    process = subprocess.run([sys.executable, '-I', str(runner)], cwd=tmp_path,
        capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['enumeration']['toy_only'] is True and report['enumeration']['plan_count'] == 4
    assert report['financial_and_decision_cells_reconstructed'] == 19049


@pytest.mark.parametrize('settings', [{}, {'compiler_backend': 'project_journal', 'replay_timeout_seconds': 1800},
    {'compiler_backend': 'capital_allocation_integer', 'replay_timeout_seconds': 120},
    {'compiler_backend': 'capital_allocation_integer', 'replay_timeout_seconds': True}])
def test_recovery_requires_explicit_backend_and_frozen_operational_budget(tmp_path, settings):
    ctx = SimpleNamespace(config={'reference_evidence_policy': 'independent_public_recovery', 'recovery': settings})
    with pytest.raises(ValueError): recovery.CapitalAllocationRecoveryNode().execute(ctx)


def test_recovery_timeout_preserves_failed_immutable_attempt_without_model_or_passing_claim(tmp_path, monkeypatch):
    from sheets_factory.nodes import quality
    source = tmp_path / 'public.xlsx'; source.write_bytes(b'public-only-fixture')
    ctx = TaskContext(run_id='toy', task_id='fm-toy', mode='financial_modeling', source=source,
        directory=tmp_path / 'task', config={'reference_evidence_policy': 'independent_public_recovery',
            'recovery': {'compiler_backend': 'capital_allocation_integer', 'replay_timeout_seconds': 1800},
            'engine': {'image': 'frozen-image'}},
        audit=SimpleNamespace(emit=lambda *a, **k: None), llm=SimpleNamespace(), engine=SimpleNamespace(),
        data={'input': source, 'instruction': 'Complete the public financial model.', 'revision_hash': 'exact-revision',
            'finance_evidence': {'financial_seed_verified': True}})
    monkeypatch.setattr(quality, '_reusable_recovery', lambda ctx: None)
    def timeout(command, **kwargs):
        assert kwargs['timeout'] == 1800
        assert '--network' in command and 'none' in command
        assert list(Path(command[command.index('--volume') + 1].split(':/workspace:rw')[0]).iterdir())
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(subprocess, 'run', timeout)
    result = recovery.CapitalAllocationRecoveryNode().execute(ctx)['recovery']
    assert result['verified'] is False and result['status'] == 'unverified'
    assert result['error_type'] == 'TimeoutExpired' and result['usage_calls'] == []
    record = Path(result['attempt_record_path']); raw = record.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result['attempt_record_sha256']
    assert record.stat().st_mode & 0o222 == 0
    assert not quality._valid_recovery_witness(ctx, result)
    again = recovery.CapitalAllocationRecoveryNode().execute(ctx)['recovery']
    assert again['attempt_id'] != result['attempt_id'] and record.read_bytes() == raw
