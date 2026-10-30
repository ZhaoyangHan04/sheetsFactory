"""Large diagnostic evidence transport without native CLI or model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from sheets_factory.core.node import TaskContext
from sheets_factory.llm.schemas import diagnosis_output_schema
from sheets_factory.nodes import quality


ROOT = Path(__file__).resolve().parents[1]
MARKER = '\nEVIDENCE FILE RECEIPT:\n'
SUFFIX = '\nReturn assessments as an object'


class Audit:
    def emit(self, *args, **kwargs):
        pass
    def task(self, *args, **kwargs):
        pass


class FileReviewer:
    """Validate caller/file/schema plumbing, not actual spreadsheet quality."""
    model = 'gpt-6-sol'

    def __init__(self):
        self.calls = []

    def complete(self, prompt, **options):
        workspace = Path(options['workspace'])
        raw = (workspace / 'evidence.json').read_bytes()
        payload = json.loads(raw)
        call = {'prompt': prompt, 'options': options, 'raw': raw, 'payload': payload}
        self.calls.append(call)
        assert options['output_schema'] == diagnosis_output_schema(payload['assigned_check_ids'])
        return {'assessments': {check: {'state': 'clear', 'reason': 'Offline evidence-transport fixture',
                    'evidence': ['Declared fixture observations; no model or calculation claimed']}
                for check in payload['assigned_check_ids']}, 'issues': [], 'evidence_requests': []}


def context(tmp_path, *, large=False):
    source = tmp_path / 'input.xlsx'
    source.write_bytes(b'file transport fixture; not a calculated workbook')
    backend = FileReviewer()
    ctx = TaskContext('fixture-run', 'fm-transport', 'financial_modeling', source, tmp_path / 'task',
        {'project_root': str(ROOT), 'agents': {'timeout_seconds': 15},
         'diagnosis': {'difficulty_deferred': False}}, Audit(), backend, None)
    labels = [f'Forecast!B{i}' for i in range(1, 3056)] if large else ['Forecast!B1']
    edits = [{'sheet': 'Forecast', 'cell': f'B{i}', 'before': f'=Inputs!B1*{i}', 'after': None}
             for i in range(1, 2305 if large else 2)]
    profile = {'sheet_count': 0, 'nonempty_sheet_count': 0, 'formula_count': 0,
               'errors': [], 'external_references': [], 'sheets': []}
    ctx.data.update(input=source, goal=source, instruction='Restore the declared business model.',
        public_profile=profile, profile=profile,
        plan={'public_rules': ['Use public period/input conventions.'], 'edits': edits,
              'private_sentinel': 'PRIVATE_PAYLOAD_MUST_STAY_IN_PRIVATE_FILE'},
        construction_validation={'all_fields_preserved': {'unicode': '完整财务证据'}},
        delta={'expected_changes': labels, 'expected_change_count': len(labels)},
        root_impacts=[{'index': i, 'expected_changes': [labels[i % len(labels)]]} for i in range(len(edits))],
        recovery={'verified': True, 'program': 'retained recovery witness\n' * (60000 if large else 1)},
        revision_hash='fixture-revision', traces=[{'events': []}],
        controls={'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0},
        engine_report={'normalization_ok': True, 'recalculation_ok': True, 'stable': True})
    return ctx, backend


def receipt(call):
    return json.loads(call['prompt'].split(MARKER, 1)[1].split(SUFFIX, 1)[0])


def test_above_one_MiB_private_payload_is_complete_file_and_small_prompt(tmp_path):
    ctx, backend = context(tmp_path, large=True)
    report = quality.DiagnoseNode().execute(ctx)['diagnosis']
    private = next(c for c in backend.calls if not c['options']['isolated'])
    assert len(private['raw']) > 1048576
    assert len(private['prompt']) < 65536
    binding = receipt(private)
    assert binding == {'file': 'evidence.json', 'sha256': hashlib.sha256(private['raw']).hexdigest(),
                       'bytes': len(private['raw']), 'assigned_check_ids': ['Q04', 'Q06', 'Q09']}
    payload = private['payload']
    assert len(payload['private']['plan']['edits']) == 2304
    assert len(payload['private']['expected_delta']['expected_changes']) == 3055
    assert payload['private']['independent_recovery'] == ctx.data['recovery']
    assert payload['private']['construction'] == ctx.data['construction_validation']
    assert payload['private']['root_impacts'] == ctx.data['root_impacts']
    assert private['raw'] == json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
    assert 'PRIVATE_PAYLOAD_MUST_STAY_IN_PRIVATE_FILE' not in private['prompt']
    assert 'COMPLETE expected_delta' in private['prompt'] and 'Do not cat or print' in private['prompt']
    assert not report['execution_failures']


def test_public_and_private_workspaces_paths_permissions_and_schemas_stay_separate(tmp_path):
    ctx, backend = context(tmp_path)
    quality.DiagnoseNode().execute(ctx)
    public, private = backend.calls
    assert public['options']['isolated'] is True and private['options']['isolated'] is False
    assert public['options']['role'] == 'public_diagnostician'
    assert private['options']['role'] == 'reference_diagnostician'
    assert 'Read /workspace/evidence.json for all assigned' in public['prompt']
    assert MARKER not in public['prompt']
    assert 'Read /workspace/evidence.json for all assigned' not in private['prompt']
    assert 'Open the relative file evidence.json' in private['prompt']
    assert str(tmp_path) not in private['prompt']
    assert public['options']['workspace'] != private['options']['workspace']
    assert 'private' not in public['payload'] and 'PRIVATE_PAYLOAD_MUST_STAY_IN_PRIVATE_FILE' not in public['raw'].decode()
    assert 'private' in private['payload']
    assert all((c['options']['workspace'] / 'input.xlsx').exists() for c in backend.calls)
    assert (private['options']['workspace'] / '../private').resolve() == ctx.revision_dir / 'private'
    assert all(c['options']['timeout'] == 15 for c in backend.calls)


def test_file_transport_context_and_full_payload_remain_bound_to_diagnostic_cache(tmp_path, monkeypatch):
    ctx, backend = context(tmp_path)
    node = quality.DiagnoseNode()
    first = node.execute(ctx)['diagnosis']
    assert len(backend.calls) == 2
    cached = node.execute(ctx)['diagnosis']
    assert len(backend.calls) == 2 and all(batch['cache_hit'] for batch in cached['llm_batches'])
    original = quality.PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS
    monkeypatch.setattr(quality, 'PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS', original + 'Transport fixture version change.\n')
    changed = node.execute(ctx)['diagnosis']
    assert len(backend.calls) == 4 and not any(batch['cache_hit'] for batch in changed['llm_batches'])
    assert first['task_revision_hash'] == changed['task_revision_hash']
    # Changing only private evidence reuses public review and invalidates private.
    ctx.data['recovery'] = deepcopy(ctx.data['recovery'])
    ctx.data['recovery']['program'] += '\nnew retained private witness line'
    node.execute(ctx)
    assert len(backend.calls) == 5 and backend.calls[-1]['options']['isolated'] is False
