"""Evidence and once-only research boundaries; no model/container/service calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('official_review_test_module', ROOT / 'scripts/run_official_failure_diagnosis.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'REGISTRY', tmp_path / 'permanent_registry')
    def save(name, value): return m.write(tmp_path / name, value)
    def file(name, data=b'original workbook bytes'):
        p = tmp_path / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return m.reference(p)
    inv = {'cases': []}; census = {'rows': []}; ledger = {'rows': []}; scan = {
        'kind': 'incremental_offline_spreadsheet_failure_analysis_scan', 'version': 1, 'reports': []}
    regions = {'kind': 'complete_official_comparison_region_census_batch', 'version': 1, 'cases': []}
    evaluator = file('official.py', b'# original evaluator, never imported\n')
    inv['official_evaluator'] = evaluator
    originals = []
    # ready, immutable deep reuse, missing census, raw pass, infrastructure, pending.
    for i in range(6):
        key = f'Financial_Model/01_0{i+1}'; task = f'external-sb2-fm-01-0{i+1}'
        case = {'case_key': key, 'task_id': task, 'category': 'Financial_Model',
                'official_record': {'instruction': f'Original business request {i}.\nKeep layout.', 'answer_position': "'Business'!A1:C9"},
                'input': file(f'{i}/input.xlsx'), 'goal': file(f'{i}/gold.xlsx', b'original gold bytes')}
        inv['cases'].append(case)
        if i == 5:
            census['rows'].append({'case_key': key, 'terminal': None}); ledger['rows'].append({'case_key': key})
            regions['cases'].append({'case_key': key, 'case_terminal': None, 'status': 'pending', 'report': None, 'summary': None})
            continue
        output = file(f'{i}/native-output.xlsx', b'unchanged submitted bytes')
        alias = file(f'{i}/official-output-copy.xlsx', b'unchanged submitted bytes')
        trajectory = save(f'{i}/trajectory.json', {'steps': [{'id': 's1', 'decision': 'Use provided policy'}]})
        result = save(f'{i}/result.json', {'raw': 0})
        score = {'accuracy': 1 if i == 3 else 0, 'regression_accuracy': 1, 'modification_accuracy': 0.5}
        terminal = {'case_key': key, 'task_id': task, 'disposition': 'new_first_attempt',
            'official_raw_accuracy': score['accuracy'], 'protocol_effective_accuracy': score['accuracy'],
            'protocol_state': 'complete', 'official_primary': {'result': score, 'input': case['input'],
                'reference': case['goal'], 'output': alias, 'evaluator': evaluator}}
        original = case['official_record']['instruction'].encode(); appendix = b'\nSave to /app/output.xlsx.\n'
        rendered = file(f'{i}/export/instruction.md', original + appendix)
        terminal['instruction_transport'] = save(f'{i}/instruction_transport.json', {
            'original_instruction_sha256': m.hashlib.sha256(original).hexdigest(), 'rendered_instruction_sha256': rendered['sha256'],
            'appended_bytes_utf8': appendix.decode(), 'original_prefix_byte_identical': True, 'business_or_target_hint_added': False})
        if i == 4:
            terminal = {'case_key': key, 'task_id': task, 'disposition': 'infrastructure_or_driver_hold',
                        'retained_records': {'redacted_error': save(f'{i}/redacted_error.json', {'error': 'redacted transport error'})}}
        tref = save(f'{i}/terminal.json', terminal); originals.append(tref)
        census['rows'].append({'case_key': key, 'terminal': tref, 'official_raw': terminal.get('official_raw_accuracy')})
        manual = {'case_key': key, 'original_terminal': tref, 'deep_review_completed': i == 1}
        if i == 1: manual['receipt'] = save(f'{i}/old_manual.json', {'findings': 'confounded; not a financial failure'})
        ledger['rows'].append(manual)
        evidence = {'source': case['input'], 'reference': case['goal'], 'output': output, 'trajectory': trajectory,
                    'result': result, 'case_terminal': tref, 'official_evaluator': evaluator}
        report = save(f'{i}/offline_report.json', {'case_id': key, 'evidence': evidence,
            'public_instruction': case['official_record']['instruction'], 'automatic_cause_attribution': False})
        receipt = save(f'{i}/offline_receipt.json', {'report': report})
        scan['reports'].append({'case_id': key, 'task_id': task, 'evidence_stage': 'official_case_terminal', 'receipt': receipt})
        region = {'kind': 'complete_official_comparison_region_case_census', 'version': 1,
            'case_key': key, 'evidence': evidence, 'original_official_score': score,
            'official_score_consistency': True, 'summary': {'region_position_count': 27, 'miss_count': 2},
            'all_misses': [{'sheet': 'Business', 'cell': 'B2'}, {'sheet': 'Business', 'cell': 'B3'}], 'holds': []}
        region_ref = save(f'{i}/region_census.json', region)
        regions['cases'].append({'case_key': key, 'case_terminal': tref,
            'status': 'hold' if i == 2 else 'complete', 'report': region_ref, 'summary': region['summary']})
    invref = save('inventory.json', inv); census['inventory'] = scan['inventory'] = regions['inventory'] = invref
    regions['case_order'] = [c['case_key'] for c in inv['cases']]
    cref = save('execution_census.json', census); ledger['census'] = cref
    refs = [invref, cref, save('manual_ledger.json', ledger), save('offline_scan.json', scan), save('region_index.json', regions)]
    return {'root': tmp_path, 'refs': refs, 'inv': inv, 'census': census, 'ledger': ledger,
            'scan': scan, 'regions': regions, 'originals': originals, 'save': save}


def prepared(fixture, name='snapshot'):
    out = fixture['root'] / name
    m.prepare(*fixture['refs'], out, _toy=True)
    return out, m.validate_prepared(out)


def review(row, **changes):
    value = {'case_key': row['case_key'], 'context_id': row['context_id'], 'case_summary': 'Observed omissions; cause not established.',
        'all_misses_accounted_for': True, 'causes': [{'cause_id': row['case_key'] + ':C01', 'certainty': 'unknown',
        'classification': 'unknown', 'statement': 'Two observed official mismatches', 'miss_count': 2,
        'evidence': [{'artifact': 'region_census.json', 'pointer': '/all_misses', 'cell': 'Business!B2',
            'trace_step': 'steps/0', 'public_rule': 'Original instruction', 'observed': 'missing', 'expected': 'provided', 'arithmetic': ''}],
        'limits': 'No independent financial proof'}], 'transfers': [], 'unknowns': ['Business cause not proved']}
    value.update(changes); return value


def test_prepare_complete_coverage_and_manual_reuse_is_service_free(fixture, monkeypatch):
    import dirhash  # Package version discovery may read Git metadata on its first import.
    def forbidden(*a, **k): raise AssertionError('No model/service during prepare')
    monkeypatch.setattr(subprocess, 'Popen', forbidden); monkeypatch.setattr(m.CodexCLI, 'complete', forbidden)
    before = {r['path']: m.reference(r['path']) for r in fixture['originals']}
    out, frozen = prepared(fixture)
    assert [r['status'] for r in frozen['cases']] == ['ready', 'reused_manual_review', 'evidence_hold',
        'not_a_failure', 'ready_infrastructure', 'pending_original_attempt']
    assert len(frozen['case_order']) == 6 and frozen['actual_model_calls'] == 0
    assert frozen['cases'][1]['manual_review'] == fixture['ledger']['rows'][1]['receipt']
    assert not m.REGISTRY.exists() and not (out / 'cases').exists()
    assert all(m.reference(p) == r for p, r in before.items())


def test_production_rejects_incomplete_inventory(fixture):
    with pytest.raises(ValueError, match='200-case'):
        m.prepare(*fixture['refs'], fixture['root'] / 'not200')


def test_retained_original_attempt_uses_bound_score_without_rescore(fixture):
    case = fixture['inv']['cases'][0]; terminal = m.read(fixture['census']['rows'][0]['terminal'])
    original = fixture['root'] / 'retained_original_instruction.md'; original.write_text(case['official_record']['instruction'])
    case['existing_attempt'] = {'original_instruction': m.reference(original),
        'rendered_instruction': m.reference(fixture['root'] / '0/export/instruction.md')}
    terminal.pop('official_raw_accuracy'); terminal['disposition'] = 'reused_original_completed_attempt'
    primary = terminal['official_primary']; primary['same_submitted_alias'] = primary.pop('output'); primary.pop('evaluator')
    terminal['original_postscore'] = fixture['save']('retained_score.json', {
        'kind': 'fixed_external_pair_original_official_postscore', 'status': 'completed',
        'pinned_evaluator': fixture['inv']['official_evaluator'], 'results': [{'task_id': case['task_id'],
            'official_scores': {'original_official': primary}}]})
    new_terminal = fixture['save']('retained_terminal.json', terminal)
    census = deepcopy(fixture['census']); census['rows'][0]['terminal'] = new_terminal
    census_ref = fixture['save']('retained_census.json', census)
    ledger = deepcopy(fixture['ledger']); ledger['census'] = census_ref; ledger['rows'][0]['original_terminal'] = new_terminal
    scan = deepcopy(fixture['scan']); receipt = m.read(scan['reports'][0]['receipt']); report = m.read(receipt['report'])
    report['evidence']['case_terminal'] = new_terminal
    scan['reports'][0].update(evidence_stage='retained_original_case_terminal',
        receipt=fixture['save']('retained_offline_receipt.json', {'report': fixture['save']('retained_offline.json', report)}))
    regions = deepcopy(fixture['regions']); region = m.read(regions['cases'][0]['report'])
    region['evidence']['case_terminal'] = new_terminal
    regions['cases'][0].update(case_terminal=new_terminal, report=fixture['save']('retained_region.json', region))
    inventory_ref = fixture['save']('retained_inventory.json', fixture['inv'])
    census['inventory'] = scan['inventory'] = regions['inventory'] = inventory_ref
    census_ref = fixture['save']('retained_census_final.json', census); ledger['census'] = census_ref
    refs = [inventory_ref, census_ref, fixture['save']('retained_ledger.json', ledger),
        fixture['save']('retained_scan.json', scan), fixture['save']('retained_regions.json', regions)]
    out = fixture['root'] / 'retained_snapshot'; m.prepare(*refs, out, _toy=True)
    row = m.read(out / 'preparation.json')['cases'][0]
    assert row['status'] == 'ready' and row['original_raw_score'] == 0
    assert row['summary']['original_protocol_state'] == 'complete'
    assert row['artifacts']['original_postscore.json'] == terminal['original_postscore']


@pytest.mark.parametrize('name', ['input.xlsx', 'gold.xlsx', 'output.xlsx', 'trajectory.json', 'region_census.json', 'offline_report.json'])
def test_every_bound_evidence_mutation_is_rejected(fixture, name):
    out, frozen = prepared(fixture); path = Path(frozen['cases'][0]['artifacts'][name]['path'])
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='Changed or missing'): m.validate_prepared(out)


def test_alias_paths_may_differ_but_original_submission_bytes_must_match(fixture):
    _, frozen = prepared(fixture)
    assert frozen['cases'][0]['status'] == 'ready'
    region_ref = fixture['regions']['cases'][0]['report']; region = m.read(region_ref)
    region['evidence']['output'] = fixture['inv']['cases'][0]['input']
    new = fixture['save']('wrong_region.json', region)
    changed = deepcopy(fixture['regions']); changed['cases'][0]['report'] = new
    refs = list(fixture['refs']); refs[-1] = fixture['save']('wrong_index.json', changed)
    m.prepare(*refs, fixture['root'] / 'mismatch', _toy=True)
    row = m.read(fixture['root'] / 'mismatch/preparation.json')['cases'][0]
    assert row['status'] == 'evidence_hold' and 'mismatch' in row['holds'][0]


def test_missing_case_cannot_silently_filter_failure_list(fixture):
    regions = deepcopy(fixture['regions']); regions['cases'].pop()
    refs = list(fixture['refs']); refs[-1] = fixture['save']('filtered.json', regions)
    with pytest.raises(ValueError, match='Retain every'): m.prepare(*refs, fixture['root'] / 'filtered', _toy=True)


def test_stage_exact_bytes_and_original_instruction_no_source_edits(fixture):
    _, frozen = prepared(fixture); row = frozen['cases'][0]
    work = m.stage(row, fixture['root'] / 'staging')
    for name, ref in row['artifacts'].items():
        assert Path(ref['path']).read_bytes() == (work / name).read_bytes()
        assert (work / name).stat().st_mode & 0o222 == 0
    assert m.read(work / 'public_instruction.json')['instruction'] == fixture['inv']['cases'][0]['official_record']['instruction']
    assert not any(p.name.startswith('.secrets') for p in work.iterdir())


def test_symlink_evidence_rejected(fixture):
    p = fixture['root'] / 'link'; p.symlink_to(fixture['refs'][0]['path'])
    with pytest.raises(ValueError, match='non-symlink'): m.reference(p)


def test_full_region_count_and_cause_evidence_guards(fixture):
    _, frozen = prepared(fixture); row = frozen['cases'][0]; good = review(row)
    assert m.validate_review(row, good) == good
    bad = deepcopy(good); bad['causes'][0]['miss_count'] = 1
    with pytest.raises(ValueError, match='whole mismatch'): m.validate_review(row, bad)
    bad = deepcopy(good); bad['causes'][0].update(certainty='confirmed', classification='financial_error')
    with pytest.raises(ValueError, match='grounded arithmetic'): m.validate_review(row, bad)
    bad['causes'][0]['evidence'][0]['arithmetic'] = '1+1=2'
    assert m.validate_review(row, bad) == bad
    bad['causes'][0]['evidence'][0]['artifact'] = '/host/.secrets/api_key'
    with pytest.raises(ValueError, match='mounted bound evidence'): m.validate_review(row, bad)


def test_infrastructure_null_never_coerced_into_business_zero(fixture):
    _, frozen = prepared(fixture); row = frozen['cases'][4]
    assert row['original_raw_score'] is None
    value = review(row); value['causes'][0].update(classification='infrastructure', miss_count=0)
    value['all_misses_accounted_for'] = False
    value['causes'][0]['evidence'] = []
    assert m.validate_review(row, value) == value
    value['causes'][0]['classification'] = 'financial_error'
    with pytest.raises(ValueError, match='Infrastructure-null'): m.validate_review(row, value)


@pytest.mark.parametrize('change', [None, 'wrong_error', 'wrong_source', 'nonzero_metric', 'extra_hold', 'financial_claim'])
def test_exact_original_loading_error_only_readiness(fixture, change):
    case = fixture['inv']['cases'][0]; source = fixture['root'] / 'malformed_original.xlsx'
    metadata = b'<root><dc:creator>Author</dc:creator></root>'
    with zipfile.ZipFile(source, 'w') as archive: archive.writestr('docProps/core.xml', metadata)
    try: ET.fromstring(metadata)
    except ET.ParseError as error: message = str(error)
    source_ref = m.reference(source)
    terminal_ref = fixture['census']['rows'][0]['terminal']; terminal = m.read(terminal_ref)
    terminal['official_primary']['input'] = source_ref
    score = terminal['official_primary']['result']; score.update(accuracy=0, regression_accuracy=0,
            modification_accuracy=0, error_message=message)
    census = m.read(fixture['regions']['cases'][0]['report'])
    census.update(status='hold', original_official_score=deepcopy(score), official_score_consistency=None,
        summary={'region_position_count': None, 'miss_count': None}, all_misses=[], holds=[{
            'reason': 'offline_comparison_exception', 'exception': 'ParseError', 'message': message}])
    census['evidence']['source'] = source_ref
    new_case = deepcopy(case); new_case['input'] = source_ref
    if change == 'wrong_error': census['holds'][0]['message'] = 'another parser error'
    if change == 'wrong_source':
        with zipfile.ZipFile(source, 'w') as archive: archive.writestr('docProps/core.xml', b'<root/>')
        fresh = m.reference(source); new_case['input'] = terminal['official_primary']['input'] = census['evidence']['source'] = fresh
    if change == 'nonzero_metric': score['modification_accuracy'] = 1; census['original_official_score'] = deepcopy(score)
    if change == 'extra_hold': census['holds'].append({'reason': 'unrelated_failure'})
    census_ref = fixture['save']('error_census.json', census)
    region = {'status': 'hold', 'case_terminal': terminal_ref, 'report': census_ref}
    if change not in (None, 'financial_claim'):
        with pytest.raises(ValueError): m._evaluator_error(new_case, terminal_ref, terminal, region, fixture['inv']['official_evaluator'])
    else:
        artifacts, summary = m._evaluator_error(new_case, terminal_ref, terminal, region, fixture['inv']['official_evaluator'])
        assert artifacts['region_census.json'] == census_ref and summary['miss_count'] is None
        row = {'case_key': case['case_key'], 'context_id': 'error-context', 'status': 'ready_evaluator_error',
            'summary': {'coverage': summary}, 'artifacts': artifacts}
        value = review(row); value['all_misses_accounted_for'] = False
        value['causes'][0].update(classification='infrastructure', miss_count=0)
        if change == 'financial_claim':
            value['causes'][0]['classification'] = 'financial_error'
            with pytest.raises(ValueError, match='Infrastructure-null'): m.validate_review(row, value)
        else: assert m.validate_review(row, value) == value


def test_actual_infra_trial_binds_typed_verifier_cause_and_complete_model_output(fixture):
    from dirhash import dirhash
    case = fixture['inv']['cases'][4]; terminal_ref = fixture['census']['rows'][4]['terminal']
    folder = Path(terminal_ref['path']).parent; task = folder / 'evaluation/snapshot/SpreadsheetEval' / case['task_id']
    for relative, content in [('environment/input.xlsx', Path(case['input']['path']).read_bytes()),
            ('tests/reference.xlsx', Path(case['goal']['path']).read_bytes()), ('instruction.md', b'Original brief')]:
        path = task / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    trial = folder / 'evaluation/harbor_jobs/frontier-pass1' / (case['task_id'] + '__fixed')
    result = {'task_name': 'sheetsfactory/' + case['task_id'], 'trial_name': trial.name,
        'task_id': {'path': str(task)}, 'task_checksum': dirhash(task, 'sha256'),
        'config': {'trial_name': trial.name, 'task': {'path': str(task)}}}
    m.write(trial / 'result.json', result)
    diag = {'reward': 0, 'reason': 'verification_error', 'error_type': 'RuntimeError',
        'error': 'Iterative workbook did not reach full-sheet stability within 64 calculation passes',
        'recalculation_calls': [{'source': '/tests/original_input.xlsx', 'completed': True},
                               {'source': '/tests/reference.xlsx', 'completed': False}]}
    m.write(trial / 'verifier/diagnostics.json', diag)
    m.write(trial / 'agent/trajectory.json', {'steps': [{'step': 1, 'role': 'agent'}]})
    output = trial / 'artifacts/app/output.xlsx'; output.parent.mkdir(parents=True); output.write_bytes(b'actual completed output')
    _, frozen = prepared(fixture); row = frozen['cases'][4]
    assert row['status'] == 'ready_infrastructure' and row['original_raw_score'] is None
    assert m.read(row['artifacts']['verifier_diagnostics.json']) == diag
    assert row['artifacts']['output.xlsx'] == m.reference(output)
    assert row['artifacts']['trajectory.json']['bytes'] > 0
    # A second trial is retained as a hold, never selected based on outcome.
    m.write(trial.parent / 'second-trial/result.json', result)
    _, later = prepared(fixture, 'ambiguous_trials')
    assert later['cases'][4]['status'] == 'evidence_hold'
    assert 'Multiple actual trials' in later['cases'][4]['holds'][0]


def test_max_three_transfers_and_case_binding(fixture):
    _, frozen = prepared(fixture); row = frozen['cases'][0]; value = review(row)
    value['context_id'] = 'wrong'
    with pytest.raises(Exception): m.validate_review(row, value)
    value = review(row); value['transfers'] = [{'cause_id': row['case_key'] + ':C01', 'dimension': 'units',
        'amplification': 'independent synthetic presentations', 'unvalidated_limits': 'Not measured'}] * 4
    with pytest.raises(Exception): m.validate_review(row, value)


def test_command_fixed_readonly_container_no_host_repo_no_retries(fixture):
    client = m.ResearchCodex(ROOT, fixture['root'], None, {'model': m.MODEL, 'reasoning_effort': 'high', 'provider': 'factory'})
    work = fixture['root'] / 'evidence'
    cmd = client._build_command(work, 'http://127.0.0.1/v1', True, 'toy-review', model=m.MODEL, reasoning='high')
    assert '--read-only' in cmd and '--sandbox' in cmd and cmd[cmd.index('--sandbox')+1] == 'read-only'
    assert str(work) + ':/workspace:ro' in cmd and str(ROOT) + ':/workspace:rw' not in cmd
    assert '--dangerously-bypass-approvals-and-sandbox' not in cmd
    assert 'model_providers.factory.request_max_retries=0' in cmd
    assert 'model_providers.factory.stream_max_retries=0' in cmd
    assert 'web_search="disabled"' in cmd


def test_actual_internal_review_once_and_parse_failure_is_unknown(fixture, monkeypatch):
    out, frozen = prepared(fixture); row = frozen['cases'][0]; folder = out / 'cases' / row['task_id']; folder.mkdir(parents=True)
    reservation = m.write(m.REGISTRY / (m.reservation_id(row) + '.json'), {'case_key': row['case_key'],
        'original_terminal': row['terminal'], 'version': m.VERSION, 'context_id': row['context_id'],
        'preparation': m.reference(out / 'preparation.json')})
    request = m.write(folder / 'request.json', {'snapshot': str(out), 'case': row, 'reservation': reservation})
    calls = []
    def fake(self, prompt, role, **kwargs):
        calls.append(kwargs); raise ValueError('invalid JSON; no model service')
    monkeypatch.setattr(m.ResearchCodex, 'complete', fake)
    result = m.read(m._internal_review(request['path']))
    assert result['status'] == 'unknown' and result['no_retry'] and len(calls) == 1
    assert calls[0]['timeout'] == 900 and calls[0]['isolated'] is True
    with pytest.raises(FileExistsError): m._internal_review(request['path'])
    assert len(calls) == 1
    # A later evidence snapshot reuses the spent diagnostic, including unknown.
    _, later = prepared(fixture, 'later_snapshot')
    assert later['cases'][0]['status'] == 'prior_review_reserved'
    assert later['cases'][0]['previous_review_terminal']['path'] == str(folder / 'terminal.json')


def test_parent_dispatch_is_subprocess_and_retains_child_failure(fixture, monkeypatch):
    out, frozen = prepared(fixture); row = frozen['cases'][0]; seen = []
    class Process:
        pid = 123; returncode = 1
        def wait(self): return 1
    def fake(args, **kwargs): seen.append((args, kwargs)); return Process()
    monkeypatch.setattr(subprocess, 'Popen', fake)
    audit = m.AuditStore(fixture['root'] / 'parent_audit', {'id': 'toy'})
    ref = m._launch(out, row, {'path': 'unused mock'}, audit)
    assert seen[0][0][1:3] == ['-B', str(ROOT / 'scripts/run_official_failure_diagnosis.py')]
    assert '--internal-review' in seen[0][0] and seen[0][1]['start_new_session']
    assert m.read(ref)['status'] == 'unknown'
    audit.db.close()


def test_failure_receipt_keeps_actionable_cause_and_redacts_secrets(fixture, monkeypatch):
    monkeypatch.setenv('PRIVATE_TEST_API_KEY', 'private-test-credential-123456')
    ref = m._failure(fixture['root'] / 'failure', ValueError('Bad count: private-test-credential-123456 bearer secretvalue'))
    text = Path(ref['path']).read_text()
    assert 'Bad count' in text and '[REDACTED]' in text
    assert 'private-test-credential-123456' not in text and 'secretvalue' not in text


def test_mock_execute_reserves_every_ready_before_launch_and_rejects_rerun(fixture, monkeypatch):
    out, frozen = prepared(fixture)
    class Server:
        def __init__(self, *a, **k): pass
        def start(self): return 'http://127.0.0.1:12345/'
        def stop(self): pass
    launched = []
    def launch(output, row, reservation, audit):
        assert len(list(m.REGISTRY.glob('*.json'))) == 2
        assert audit.run['dashboard_url']
        launched.append(row['case_key'])
        return m.write(output / 'cases' / row['task_id'] / 'terminal.json', {'status': 'unknown', 'case_key': row['case_key'],
            'context_id': row['context_id']})
    monkeypatch.setattr(m, 'DashboardServer', Server); monkeypatch.setattr(m, '_launch', launch)
    terminal = m.read(m.execute_prepared(out))
    assert len(launched) == 2 and len(terminal['cases']) == 6
    assert terminal['actual_diagnostic_calls'] == 0 and not terminal['qualification_or_difficulty_granted']
    with pytest.raises(ValueError, match='already been spent'): m.execute_prepared(out)


def test_prompt_and_cli_require_explicit_separate_run(fixture):
    prompt = m.PROMPT.read_text()
    assert 'not automatically a financial' in prompt and 'ALL official mismatch' in prompt
    assert 'at most three' in prompt and 'gold is evidence' in prompt
    result = subprocess.run([m.sys.executable, str(ROOT / 'scripts/run_official_failure_diagnosis.py'),
        '--inventory', fixture['refs'][0]['path'], '--run'], capture_output=True, text=True)
    assert result.returncode != 0 and 'separate explicit step' in result.stderr
