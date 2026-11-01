"""Explicit large-family runner; the frozen sparse comparison stays unchanged.

This file is also copied into Harbor tasks. It requires only the standard
library for the agent's recalculation command. The private verifier loads its
separately packaged, SHA-bound streaming comparison implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types

CORE_SHA256 = '76c9c8ac718195fd9daa04c90a2f7f3b4dfb1f8d70e7b45acadb1386c6cdc665'
WORKBOOK_FILE_SECONDS = 600
VERIFIER_TOTAL_SECONDS = 2400
EXECUTION_BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
                    'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}


UPSTREAM_RESOURCE_RUNTIME_SHA256 = 'fd076d6327840012214ede6a1cb4191c4f6f68d3455ac1896aea535aab37ef2d'
PROFILE_CANONICAL_SHA256 = '68ef77cadb65f69e78d35c31337ebe41ac327aa2a4d82114606f4357255c7697'


def validate_profile(profile):
    """Accept only the complete approved ringfenced-pair operational contract."""
    if not isinstance(profile, dict):
        raise ValueError('Unexpected ringfenced resource profile')
    try:
        payload = json.dumps(profile, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid ringfenced resource profile values') from error
    if hashlib.sha256(payload.encode()).hexdigest() != PROFILE_CANONICAL_SHA256:
        raise ValueError('The exact ringfenced-pair resources, identity or geometry changed')
    return json.loads(payload)


def load_profile(path):
    """Validate the exact exported profile using only the standard library."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The ringfenced runtime profile must be a regular file')
    return validate_profile(json.loads(path.read_text()))


def comparison_core():
    """Use the same exact sparse-value algorithm in-repo and when exported."""
    if __package__:
        from . import streaming_verifier as core
        path = Path(core.__file__)
    else:
        path = Path(__file__).with_name('streaming_core.py')
        if not path.is_file() or path.is_symlink():
            raise ValueError('The frozen streaming comparison is missing')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != CORE_SHA256:
            raise ValueError('The frozen streaming comparison changed')
        # Avoid writing __pycache__ into the immutable exported file inventory.
        core = types.ModuleType('sheetsfactory_streaming_core')
        core.__file__ = str(path)
        exec(compile(payload, str(path), 'exec'), core.__dict__)
    if hashlib.sha256(path.read_bytes()).hexdigest() != CORE_SHA256:
        raise ValueError('The frozen streaming comparison changed')
    return core


def recalculate(source: Path, destination: Path, timeout=WORKBOOK_FILE_SECONDS):
    """Bound the unchanged UNO calculation and reap its process group on timeout."""
    if type(timeout) is not int or timeout != WORKBOOK_FILE_SECONDS:
        raise ValueError('This family requires exactly 600 seconds per workbook')
    process = subprocess.Popen(
        ['/usr/bin/python3', '/opt/uno_recalculate.py', str(source), str(destination)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode or not destination.is_file():
        raise RuntimeError('LibreOffice recalculation failed: ' + stderr[-2000:])
    return stdout


def _contract(profile):
    return {'profile_id': profile['id'],
            'workbook_file_timeout_seconds': WORKBOOK_FILE_SECONDS,
            'verifier_total_timeout_seconds': VERIFIER_TOTAL_SECONDS,
            'solver_tool_budget': profile['solver_tool_budget'],
            'execution_budget': dict(EXECUTION_BUDGET),
            'operational_guard_is_model_failure': False,
            'requested_verifier_resources': profile['docker_resources']['verifier'],
            'actual_container_resources_verified': False,
            'quality_or_difficulty_certified': False}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'recalculate':
        parser = argparse.ArgumentParser(description='Recalculate one workbook with the explicit 600-second bound')
        parser.add_argument('source', type=Path)
        parser.add_argument('destination', type=Path)
        parser.add_argument('--profile', required=True, type=Path)
        args = parser.parse_args(argv[1:])
        load_profile(args.profile)
        print(recalculate(args.source.resolve(), args.destination.resolve(), timeout=WORKBOOK_FILE_SECONDS), end='')
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('input', 'goal', 'output'):
        parser.add_argument('--' + field, required=True, type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--reward', type=Path, default=Path('/logs/verifier/reward.txt'))
    parser.add_argument('--report', type=Path, default=Path('/logs/verifier/diagnostics.json'))
    args = parser.parse_args(argv)
    calls, contract = [], None
    try:
        profile = load_profile(args.profile)
        contract = _contract(profile)
        core = comparison_core()
        if not args.output.is_file() or args.output.is_symlink():
            raise ValueError('Submitted workbook is missing or a symlink')
        with tempfile.TemporaryDirectory(prefix='sheetsfactory-resource-verify-') as temporary:
            paths = [Path(temporary) / (name + '.xlsx') for name in ('input', 'goal', 'output')]
            for source, destination in zip((args.input, args.goal, args.output), paths):
                call = {'source': str(source), 'timeout_seconds': WORKBOOK_FILE_SECONDS,
                        'completed': False}
                calls.append(call)
                started = time.monotonic()
                try:
                    recalculate(source.resolve(), destination, timeout=WORKBOOK_FILE_SECONDS)
                    call['completed'] = True
                finally:
                    call['duration_seconds'] = time.monotonic() - started
            result = core.compare_files(*paths)
    except Exception as exc:
        result = {'reward': 0, 'reason': 'verification_error',
                  'error_type': type(exc).__name__, 'error': str(exc)}
    result['resource_contract'] = contract
    result['recalculation_calls'] = calls
    args.reward.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    args.reward.write_text(str(result['reward']) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
