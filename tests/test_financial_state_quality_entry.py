"""Financial development admission and actual producer startup, without model/LO calls."""
import builtins
from copy import deepcopy
import dis
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
from types import CodeType
from urllib.parse import urlparse

import pytest
import yaml

from sheets_factory.reporting import read_run
from sheets_factory.resume import PROTECTED_BUDGETS

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('financial_state_quality_entry', ROOT / 'scripts/run_financial_state_quality.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return entry.reference(path)


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    base = tmp_path / 'original'; base.mkdir()
    config = yaml.safe_load((ROOT / 'config/pipelines/composite_quality20.yaml').read_text())
    config.update(project_root=str(ROOT), run_dir=str(base))
    config['run'].update(continuation_id='old', resume_existing_task_ids=['old'], external_repair_manifest='old')
    sources = []
    for index in range(10):
        book = base / ('source-' + str(index) + '.xlsx'); book.write_bytes(str(index).encode())
        proof = {'workbook': entry.cohort.ref(book)}
        sources.append({'sha256': entry.sha(book), 'local_path': str(book), 'profile_id': 'C' + str(index),
                        'finance_evidence': {'audited_source_binding': proof}, 'modes': ['financial_modeling']})
    seed_ref = write_json(base / 'seed_manifest.json', {'selected': sources})
    batch_ref = write_json(base / 'batch.json', {'selected': sources, 'model_scores_consulted': False})
    for key in ('public_input_priority', 'public_workbook_scope'):
        ref = write_json(base / (key + '.json'), {'kind': key, 'sources': {e['sha256']: {} for e in sources},
                                               'tasks': {'fm-old': {'revision': 1}}, 'quality_or_difficulty_certified': False})
        config[key] = {'version': 1, 'manifest': ref}
    (base / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    recipe = base / 'unchanged.py'; recipe.write_text('# original\n')
    write_json(base / 'preflight_manifest.json', {
        'kind': 'prepared_normal_quality_cohort', 'mode': 'financial_modeling', 'source_count': 10,
        'prepared_seed_manifest': seed_ref, 'source_batch_manifest': batch_ref,
        'source_artifacts_sha256': {}, 'recipe_sha256': {str(recipe): entry.sha(recipe)}})
    observed = []
    def validate(seed):
        observed.append(seed['sha256'])
        return deepcopy(seed['finance_evidence']['audited_source_binding'])
    monkeypatch.setattr(entry.cohort, 'validate_seed', validate)
    return base, tmp_path / 'development', sources, observed


def test_preparation_preserves_all_ten_and_runs_only_the_first_source_without_old_authorizations(admitted):
    base, output, sources, observed = admitted
    before = (base / 'resolved_config.yaml').read_bytes()
    result = entry.prepare(output, base)
    frozen = entry.validate_prepared(output)
    assert result == entry.reference(output / 'preflight_manifest.json')
    assert observed == [e['sha256'] for e in sources] + [sources[0]['sha256']]
    selection = entry.read(output / 'predeclared_source_selection.json')
    assert selection['ordered_source_sha256'] == [e['sha256'] for e in sources]
    assert selection['delivery_targets'] == {'financial_modeling': 10, 'debugging': 10}
    config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
    old = yaml.safe_load(before)
    assert config['run']['targets'] == {'financial_modeling': 1, 'debugging': 0}
    assert all(config['run'].get(k) == old['run'].get(k) for k in PROTECTED_BUDGETS)
    assert 'continuation_id' not in config['run'] and 'external_repair_manifest' not in config['run']
    assert config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
    assert config['harbor']['execute_controls'] is True
    for key in ('public_input_priority', 'public_workbook_scope'):
        assert entry.read(entry.checked(config[key]['manifest']))['tasks'] == {}
        assert entry.read(entry.checked(old[key]['manifest']))['tasks'] == {'fm-old': {'revision': 1}}
    assert frozen['actual_model_calls'] == frozen['actual_LO_calls'] == 0 and frozen['qualified'] is False
    assert (base / 'resolved_config.yaml').read_bytes() == before
    assert not (output / 'run.sqlite').exists()


def test_changed_original_recipe_is_rejected_before_preparation(admitted):
    base, output, sources, observed = admitted
    (base / 'unchanged.py').write_text('changed')
    with pytest.raises(ValueError, match='artifact changed'):
        entry.prepare(output, base)
    assert not output.exists() and observed == []


def test_original_selection_cannot_be_reordered(admitted):
    base, output, sources, observed = admitted
    original = entry.read(base / 'preflight_manifest.json')
    original['prepared_seed_manifest'] = write_json(base / 'seed_manifest.json', {'selected': list(reversed(sources))})
    write_json(base / 'preflight_manifest.json', original)
    with pytest.raises(ValueError, match='source order'):
        entry.prepare(output, base)
    assert not output.exists() and observed == []


def test_tampering_with_prepared_public_authorization_or_source_is_rejected(admitted):
    base, output, sources, observed = admitted
    entry.prepare(output, base)
    (output / 'public_workbook_scope_binding.json').write_text('{}')
    with pytest.raises(ValueError, match='Changed or missing audited artifact'):
        entry.validate_prepared(output)


def test_preparation_is_not_overwritten(admitted):
    base, output, sources, observed = admitted
    output.mkdir()
    with pytest.raises(ValueError, match='fresh directory'):
        entry.prepare(output, base)


def test_cli_validates_once_and_never_executes_implicitly(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: calls.append('validate'))
    def execute(path, **kwargs):
        entry.validate_prepared(path); calls.append('execute'); return 0
    monkeypatch.setattr(entry, 'execute_prepared', execute)
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    assert calls == ['validate']
    calls.clear()
    assert entry.main(['--prepared', str(tmp_path), '--run']) == 0
    assert calls == ['validate', 'execute']


def test_all_entry_global_names_are_bound():
    def names(code):
        result = {i.argval for i in dis.get_instructions(code) if i.opname == 'LOAD_GLOBAL'}
        for constant in code.co_consts:
            if isinstance(constant, CodeType): result.update(names(constant))
        return result
    for function in (entry.prepare, entry.validate_prepared, entry.execute_prepared, entry.main):
        assert names(function.__code__) - set(function.__globals__) - set(vars(builtins)) == set()


def test_actual_startup_instantiates_audited_factory_starts_dashboard_and_releases_everything(admitted, monkeypatch):
    base, output, sources, observed = admitted
    entry.prepare(output, base)
    calls, addresses = [], []
    class LocalModel:
        def __init__(self, *args): pass
        def _credentials(self): calls.append('stub_credentials')
    class LocalEngine:
        def __init__(self, *args): pass
        def metadata(self): return {'image_id': entry.cohort.IMAGE_ID}
    monkeypatch.setattr(entry.cohort, 'CohortCodex', LocalModel)
    monkeypatch.setattr(entry.cohort, 'LibreOfficeEngine', LocalEngine)
    def run(self):
        calls.append('actual_factory_initialized')
        assert isinstance(self, entry.cohort.AuditedSourceFactory)
        assert (output / 'run.sqlite').is_file()
        assert entry.read(output / 'producer.lock')['status'] == 'active'
        assert os.environ['TMPDIR'] == str(output / 'temporary')
        assert self.audit.run['producer_pid'] == os.getpid()
        parsed = urlparse(self.audit.run['dashboard_url'])
        addresses.append((parsed.hostname, parsed.port))
        with socket.create_connection(addresses[-1], timeout=1): pass
        return False
    monkeypatch.setattr(entry.cohort.AuditedSourceFactory, 'run', run)
    before_env, before_cache = os.environ.get('TMPDIR'), tempfile.tempdir
    assert entry.execute_prepared(output) == 2
    assert calls == ['stub_credentials', 'actual_factory_initialized']
    state = read_run(output)['run']
    assert state['exit_code'] == 2 and state['producer_active'] is False
    assert entry.read(output / 'producer.lock')['status'] == 'released'
    assert os.environ.get('TMPDIR') == before_env and tempfile.tempdir == before_cache
    with pytest.raises(OSError): socket.create_connection(addresses[-1], timeout=.1)


def test_real_factory_load_preserves_independently_audited_normalized_path(admitted):
    base, output, sources, observed = admitted
    entry.prepare(output, base)
    config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
    # Exercise the actual audited override after the ordinary manifest loader.
    from sheets_factory.pipelines.factory import FactoryPipeline
    original_loader = FactoryPipeline.load_seeds
    try:
        FactoryPipeline.load_seeds = lambda self: deepcopy(sources[:1])
        factory = object.__new__(entry.cohort.AuditedSourceFactory)
        loaded = factory.load_seeds()
    finally:
        FactoryPipeline.load_seeds = original_loader
    assert loaded[0]['survey']['normalized_path'] == sources[0]['local_path']
    assert loaded[0]['survey']['source_sha256'] == sources[0]['sha256']
