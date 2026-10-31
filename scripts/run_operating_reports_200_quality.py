#!/usr/bin/env python3
"""Prepare fixed200 FM normal review; a later --prepared --run starts services."""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import FunctionType
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.pipelines import operating_reports_200_quality as pipeline
from sheets_factory.task_adapters import operating_reports_200_quality as nodes
from sheets_factory.task_adapters import reference_receipt_diagnosis as receipt
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease

UPSTREAM = ROOT/'scripts/run_heterogeneous_native_quality.py'
UPSTREAM_SHA = 'e16991e7950e6cc3a9948d59507b768cb2c6fe90d7c098e32a644596cc7d3de4'
DEFAULT_CONFIG = ROOT/'config/pipelines/operating_reports_200_quality_v1.yaml'
KIND = 'prepared_fixed200_financial_modeling_reference_quality'
reference, require = pipeline.reference, pipeline.require
require(reference(UPSTREAM)['sha256'] == UPSTREAM_SHA, 'The frozen generic normal lifecycle changed')
_definition = importlib.util.spec_from_file_location('_fixed200_normal_lifecycle', UPSTREAM)
_base = importlib.util.module_from_spec(_definition); _definition.loader.exec_module(_base)
_namespace = {**vars(_base), '__file__': __file__, '__name__': __name__+'._normal_lifecycle',
    'pipeline': pipeline, 'KIND': KIND, 'DEFAULT_CONFIG': DEFAULT_CONFIG, '_SESSIONS': {}}
for _name, _value in vars(_base).items():
    if isinstance(_value, FunctionType) and _value.__globals__ is vars(_base):
        _new = FunctionType(_value.__code__, _namespace, _value.__name__, _value.__defaults__, _value.__closure__)
        _new.__kwdefaults__ = deepcopy(_value.__kwdefaults__)
        if _new.__kwdefaults__ and 'config_path' in _new.__kwdefaults__: _new.__kwdefaults__['config_path'] = DEFAULT_CONFIG
        _namespace[_name] = _new


def _prepare_ast():
    tree = ast.parse(UPSTREAM.read_bytes())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare')
    function.name = '_prepare_many'; counts = {}
    changes = {'766 audited task outputs': '93510 independent fixed200 business fields',
        'local:scoped-native-business-views': 'local:fixed200-financial-modeling-view'}
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in changes:
                old = node.value; node.value = changes[old]; counts[old] = counts.get(old, 0)+1
            return node
        def visit_Dict(self, node):
            node = self.generic_visit(node)
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'debugging_eligible':
                    require(isinstance(value, ast.Constant) and value.value is True, 'The exact seed eligibility seam changed')
                    value.value = False; counts['debugging_eligible'] = counts.get('debugging_eligible', 0)+1
            return node
    function = Adapt().visit(function)
    require(counts == {**{key: 1 for key in changes}, 'debugging_eligible': 1}, 'The exact generic preparation metadata seams changed')
    return ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))


exec(compile(_prepare_ast(), str(UPSTREAM), 'exec'), _namespace)
_validate = _namespace['validate_prepared']


def recipes(config, admissions):
    rows = _base.runtime.recipes(config, [])
    paths = [Path(__file__), UPSTREAM, DEFAULT_CONFIG, pipeline.REGISTRY, Path(pipeline.__file__),
        Path(nodes.__file__), Path(pipeline.base.__file__), Path(nodes.base.__file__),
        Path(receipt.__file__), *receipt.DEPENDENCIES]
    for path in paths:
        record = reference(path); rows[record['path']] = record['sha256']
    for value in admissions: rows.update(value.recipe)
    return rows


def prepare(validation_terminal, output, *, mode='financial_modeling', config_path=DEFAULT_CONFIG):
    require(mode == 'financial_modeling', 'Only the observed fixed FM candidate enters this quality run')
    return _namespace['_prepare_many']([validation_terminal], output, config_path=config_path)


def validate_prepared(output):
    frozen, config, admissions = _validate(output)
    require(frozen['kind'] == KIND and frozen['count'] == 1
        and frozen['targets'] == {'financial_modeling': 1, 'debugging': 0}
        and frozen['reference_evidence_policy'] == 'reference_review'
        and frozen['independent_public_solver_attempted'] is frozen['existing_development_score_transferred'] is False,
        'No other family, debugging candidate, public-solving witness or previous score may enter')
    require(len(admissions) == 1 and pipeline.admission(admissions[0])['first_development_material_identity'] == pipeline.FIRST_MATERIAL,
        'The exact spent first-v6 FM task identity changed')
    return frozen, config, admissions


_namespace.update(recipes=recipes, validate_prepared=validate_prepared)
execute_prepared = _namespace['execute_prepared']
validate_normal_resources = _namespace['validate_normal_resources']


@contextmanager
def admission_monitor(output, operation):
    """A separate audit/panel exists before any slow cold-admission work."""
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs'), 'Use a real private normal-quality directory')
    folder = output.parent/(output.name+'_'+operation+'_monitor_'+uuid4().hex[:12])
    folder.mkdir(parents=True); lease = ProducerLease(folder).acquire()
    audit = server = pulse = None; stop = threading.Event(); tick = time.monotonic()
    state = {'passed': False, 'inner_exit_code': None}; failure = None; errors = []
    try:
        audit = AuditStore(folder, {'id': folder.name, 'name': 'Fixed200 FM normal quality · admission and execution',
            'status': 'running', 'target_count': 1, 'qualified': False, 'producer_pid': os.getpid(), 'producer_active': True,
            'operation': operation, 'inner_output': str(output), 'active_stage': 'cold_source_and_task_admission'})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        _base.write(folder/'started.json', {'pid': os.getpid(), 'at': datetime.now(timezone.utc).isoformat(),
            'dashboard_url': url, 'operation': operation, 'inner_output': str(output), 'code': reference(__file__)})
        audit.update_run(dashboard_url=url); audit.export()
        print(json.dumps({'admission_dashboard_url': url, 'pid': os.getpid(), 'monitor_directory': str(folder)}), flush=True)
        def heartbeat():
            while not stop.wait(15):
                try: audit.update_run(elapsed_seconds=time.monotonic()-tick); audit.export()
                except Exception as error: errors.append({'type': type(error).__name__})
        pulse = threading.Thread(target=heartbeat, daemon=True); pulse.start()
        yield state
    except BaseException as error:
        failure = {'type': type(error).__name__}; raise
    finally:
        stop.set()
        if pulse: pulse.join(timeout=1)
        if audit:
            try:
                audit.update_run(status='passed' if state['passed'] and failure is None else 'failed', producer_active=False,
                    elapsed_seconds=time.monotonic()-tick, inner_exit_code=state['inner_exit_code']); audit.export()
            except Exception as error: errors.append({'type': type(error).__name__})
        for closer in ([server.stop] if server else [])+([audit.db.close] if audit else [])+[lease.release]:
            try: closer()
            except Exception as error: errors.append({'type': type(error).__name__})
        _base.write(folder/'terminal.json', {'kind': 'fixed200_normal_admission_outer_monitor', 'version': 1,
            'operation': operation, 'inner_output': str(output), 'operation_completed': failure is None,
            'inner_passed': state['passed'], 'inner_exit_code': state['inner_exit_code'], 'failure': failure,
            'monitor_errors': errors, 'elapsed_seconds': time.monotonic()-tick,
            'inner_actual_service_counts_are_authoritative': True, 'monitor_does_not_launch_native_models_or_LO': True,
            'qualified': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-terminal', type=Path); parser.add_argument('--mode', choices=['financial_modeling'], default='financial_modeling')
    parser.add_argument('--output', type=Path); parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true'); parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    require(0 <= args.port <= 65535, 'Use a valid local dashboard port')
    if args.prepared:
        require(args.validation_terminal is None and args.output is None, 'Use the exact existing normal preparation')
        with admission_monitor(args.prepared, 'run' if args.run else 'validate') as state:
            if args.run:
                code = execute_prepared(args.prepared, port=args.port)
                state.update(passed=code == 0, inner_exit_code=code); return code
            result = validate_prepared(args.prepared)[0]; state['passed'] = True
    else:
        require(not args.run and args.validation_terminal is not None and args.output is not None,
            'Prepare and review before a separate --prepared --run')
        with admission_monitor(args.output, 'prepare') as state:
            result = prepare(args.validation_terminal, args.output, mode=args.mode); state['passed'] = True
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
