"""Real Factory target-claim tests; no backend, model, or LO calls."""
import ast
import builtins
from copy import deepcopy
import dis
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from types import CodeType
from urllib.parse import urlparse

import pytest
import yaml

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.pipelines.full_graph_factory_compat import (
    FullGraphFactoryCompat, SETTING, setting, validate_setting)
from sheets_factory.pipelines.scc_activity_admission import ADAPTER, canonical
from sheets_factory.reporting import read_run

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('full_graph_compat_entry', ROOT / 'scripts/run_full_graph_factory_compat.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


class Audit:
    def __init__(self): self.tasks = []; self.updates = []
    def snapshot(self): return {'tasks': deepcopy(self.tasks)}
    def task(self, *args, **kwargs): self.updates.append((args, kwargs))


def context(tmp_path, *, mode='debugging', count=3):
    plan = {'mask_ranges': [], 'family_adapter': {'id': ADAPTER},
        'public_instruction': 'Keep exactly the original sheets.', 'public_rules': ['Original financial rules'],
        'edits': [{'sheet': 'Model', 'cell': 'A' + str(i+1), 'before': '=1', 'after': '=2'} for i in range(count)]}
    config = {SETTING: setting(), 'run': {'max_target_overlap': .8}}
    ctx = TaskContext('unit', 'dbg-unit', mode, tmp_path / 'source.xlsx', tmp_path / 'task', config,
                      None, None, None, data={'source_id': 'a'*64, 'plan': plan})
    pipeline = object.__new__(FullGraphFactoryCompat)
    pipeline.config = config; pipeline.lock = threading.RLock(); pipeline.audit = Audit(); pipeline.target_claims = {}
    return pipeline, ctx


@pytest.mark.parametrize('count', [3, 20895])
def test_actual_factory_claim_preserves_every_edit_overlap_fingerprint_and_public_scope(tmp_path, count):
    pipeline, ctx = context(tmp_path, count=count); before = deepcopy(ctx.data['plan'])
    original_digest = canonical(before['edits'])
    pipeline._claim_targets(ctx)
    assert 'mask_ranges' not in ctx.data['plan']
    assert ctx.data['plan'] == {k: v for k, v in before.items() if k != 'mask_ranges'}
    assert canonical(ctx.data['plan']['edits']) == original_digest
    targets = sorted((e['sheet'], e['cell']) for e in before['edits'])
    assert pipeline.audit.updates[-1][1]['targets'] == targets
    assert ctx.data['target_fingerprint'] == hashlib.sha256(json.dumps(targets).encode()).hexdigest()
    proof = json.loads((ctx.revision_dir / 'private/factory_plan_schema_compatibility.json').read_text())
    assert proof['physical_edit_count'] == count and proof['removed_value'] == []
    assert not proof['quality_or_difficulty_certified']


@pytest.mark.parametrize('value', [[{'sheet': 'Model', 'range': 'A1:A3'}], None, {}, '', False])
def test_nonempty_or_wrong_typed_range_metadata_is_rejected(tmp_path, value):
    pipeline, ctx = context(tmp_path); ctx.data['plan']['mask_ranges'] = value
    with pytest.raises(TaskRejected, match='cannot declare'):
        pipeline._claim_targets(ctx)
    assert not pipeline.audit.updates


def test_ordinary_fm_is_delegated_without_metadata_changes(tmp_path, monkeypatch):
    pipeline, ctx = context(tmp_path, mode='financial_modeling'); original = deepcopy(ctx.data['plan']); observed = []
    monkeypatch.setattr(FactoryPipeline, '_claim_targets', lambda self, value: observed.append(value) or 'normal-FM')
    assert pipeline._claim_targets(ctx) == 'normal-FM'
    assert observed == [ctx] and ctx.data['plan'] == original
    assert not (ctx.revision_dir / 'private/factory_plan_schema_compatibility.json').exists()


def test_absent_range_field_uses_the_original_claim(tmp_path):
    pipeline, ctx = context(tmp_path); del ctx.data['plan']['mask_ranges']
    pipeline._claim_targets(ctx)
    assert len(pipeline.audit.updates[-1][1]['targets']) == 3
    assert not (ctx.revision_dir / 'private/factory_plan_schema_compatibility.json').exists()


def test_unknown_adapter_cannot_borrow_full_graph_compatibility(tmp_path):
    pipeline, ctx = context(tmp_path); ctx.data['plan']['family_adapter']['id'] = 'other'
    with pytest.raises(TaskRejected, match='explicit complete'):
        pipeline._claim_targets(ctx)


def test_real_factory_duplicate_target_rejection_is_preserved(tmp_path):
    pipeline, ctx = context(tmp_path)
    targets = frozenset((e['sheet'], e['cell']) for e in ctx.data['plan']['edits'])
    pipeline.target_claims[('a'*64, 'debugging', targets)] = 'prior-task'
    pipeline.audit.tasks = [{'id': 'prior-task', 'status': 'ready'}]
    with pytest.raises(TaskRejected, match='Q08: duplicate'):
        pipeline._claim_targets(ctx)


@pytest.mark.parametrize('defect', ['missing', 'version_bool', 'code', 'upstream'])
def test_compatibility_requires_exact_explicit_code_and_upstream_binding(defect):
    config = {SETTING: setting()}
    if defect == 'missing': config.clear()
    elif defect == 'version_bool': config[SETTING]['version'] = True
    elif defect == 'code': config[SETTING]['implementation']['sha256'] = '0'*64
    else: config[SETTING]['upstream_factory']['sha256'] = '0'*64
    with pytest.raises(ValueError, match='explicit'):
        validate_setting(config)


def test_new_execution_matches_frozen_entry_except_explicit_factory_class():
    original = ast.parse((ROOT / 'scripts/run_full_graph_quality.py').read_text())
    copied = ast.parse((ROOT / 'scripts/run_full_graph_factory_compat.py').read_text())
    left = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_prepared')
    right = next(node for node in copied.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_prepared')
    class Normalize(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'FullGraphFactoryCompat': node.id = 'SCCActivityFactory'
            return node
    assert ast.dump(left, include_attributes=False) == ast.dump(Normalize().visit(right), include_attributes=False)


def test_cli_executes_only_explicitly_and_validates_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: calls.append('validate') or {})
    def execute(path, **kwargs):
        entry.validate_prepared(path); calls.append('execute'); return 0
    monkeypatch.setattr(entry, 'execute_prepared', execute)
    assert entry.main(['--prepared', str(tmp_path), '--run']) == 0
    assert calls == ['validate', 'execute']
    calls.clear()
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    assert calls == ['validate']


def test_all_execute_global_names_are_bound_and_missing_import_is_detected(monkeypatch):
    def missing(function):
        def names(code):
            result = {i.argval for i in dis.get_instructions(code) if i.opname == 'LOAD_GLOBAL'}
            for constant in code.co_consts:
                if isinstance(constant, CodeType): result.update(names(constant))
            return result
        return names(function.__code__) - set(function.__globals__) - set(vars(builtins))
    assert missing(entry.execute_prepared) == set()
    monkeypatch.delattr(entry, 'os')
    assert missing(entry.execute_prepared) == {'os'}


def test_real_execute_setup_reaches_factory_run_and_cleans_server_lease_and_temp(tmp_path, monkeypatch):
    output = tmp_path / 'prepared'; output.mkdir()
    config = yaml.safe_load((ROOT / 'config/pipelines/composite_quality20.yaml').read_text())
    config.update(project_root=str(ROOT), run_dir=str(output), host_runtime=entry.cohort.host_runtime_settings(output))
    config['run']['targets'] = {'financial_modeling': 0, 'debugging': 1}
    config['agents']['max_parallel_calls'] = 1
    config[SETTING] = setting()
    (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    frozen = {'count': 1, 'development_only': True, 'recipe_sha256': {}, 'host_runtime': config['host_runtime']}
    (output / 'preflight_manifest.json').write_text(json.dumps(frozen))
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: deepcopy(frozen))
    calls = []; addresses = []
    class LocalModel:
        def __init__(self, root, run, audit, settings): self.config = settings
        def _credentials(self): calls.append('stub_credentials_only')
    class LocalEngine:
        def __init__(self, *args): pass
        def metadata(self): calls.append('stub_engine_metadata_only'); return {'image_id': entry.cohort.IMAGE_ID}
    monkeypatch.setattr(entry.cohort, 'CohortCodex', LocalModel)
    monkeypatch.setattr(entry.cohort, 'LibreOfficeEngine', LocalEngine)
    def local_run(self):
        calls.append('actual_Factory_instance_run')
        assert isinstance(self, FullGraphFactoryCompat)
        assert (output / 'run.sqlite').is_file()
        assert json.loads((output / 'producer.lock').read_text())['status'] == 'active'
        assert self.audit.run['producer_pid'] == os.getpid()
        assert os.environ['TMPDIR'] == str(output / 'temporary')
        address = urlparse(self.audit.run['dashboard_url']); addresses.append((address.hostname, address.port))
        with socket.create_connection(addresses[-1], timeout=1): pass
        return False
    monkeypatch.setattr(FullGraphFactoryCompat, 'run', local_run)
    before_env, before_cache = os.environ.get('TMPDIR'), tempfile.tempdir
    assert entry.execute_prepared(output, port=0) == 2
    assert calls == ['stub_credentials_only', 'stub_engine_metadata_only', 'actual_Factory_instance_run']
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'
    state = read_run(output)['run']
    assert state['producer_active'] is False and state['exit_code'] == 2
    assert state['producer_pid'] == os.getpid()
    assert os.environ.get('TMPDIR') == before_env and tempfile.tempdir == before_cache
    with pytest.raises(OSError): socket.create_connection(addresses[-1], timeout=.1)
