#!/usr/bin/env python3
"""Future paired N360 views with one genuine source admission per process.

Only --run starts the unchanged seven plus eleven actual calculations.
The opaque session is never reconstructed from a persisted pass flag.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
from types import FunctionType, SimpleNamespace
import weakref

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.pipelines import linear_capital_scaled_quality as quality

POOL = ROOT/'scripts/prepare_linear_capital_scaled_pool_view_pair.py'
VALIDATOR = ROOT/'scripts/validate_linear_capital_scaled_task_view.py'
FROZEN = {
    str(POOL): '4e5e1f897fe9285da81aef01e1efcea19ee26f83cea2cfefe8f0de1b9e904689',
    str(ROOT/'scripts/prepare_linear_capital_scaled_view_pair.py'): 'eda80d92e2172ea5d8f2119573c5f3495981f996fb4cb28c5ca3b0709dc5ca47',
    str(VALIDATOR): '64af9d3e3b7ba7cfbd460cdad47d30dd9641cdb81e74c298137232d8a3611542',
    str(ROOT/'scripts/validate_linear_capital_task_view.py'): '24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974',
    str(Path(quality.__file__)): '805598136866e52763ac168c18df7491cada54f329c6814aa47ea66643dee27d',
    str(quality.UPSTREAM): '995e50d28aec160bd4ebb0a3fcfe1356acc945c17026c8694951a74a0e9a9775',
}
PREPARED = 'prepared_linear_capital_scaled_cached_pool_view_pair'
KIND = 'linear_capital_scaled_cached_pool_view_pair_actual_validation'
POLICY_KIND = 'process_local_opaque_scaled_source_reuse'
_LIVE = weakref.WeakSet()
_SESSIONS = {}
_MODULES = {}
_COMPLETED_COLD_VALIDATIONS = 0

PAIR_FUNCTIONS = frozenset('''_base_recipes _checked_pool_source _pool_evidence
    _profile_identity adapted_ast checked_source execute_prepared guard main now
    policy prepare read recipes reference require support validate_prepared write'''.split())
VALIDATOR_FUNCTIONS = frozenset('''_base_recipes _complete_delta _control_comparison
    _provider _record_provider _require_complete_delta _require_typed_stability _view
    _workbook_binding adapted_ast execute_prepared main prepare recipes required_roles
    source_support validate_completed validate_prepared'''.split())
VALIDATOR_IMPORTS = {
    'utcnow': 'sheets_factory.core.audit',
    'compare_workbooks': 'sheets_factory.evaluation.streaming_delta',
    'compare_files': 'sheets_factory.evaluation.streaming_verifier',
    '_sparse_cells': 'sheets_factory.evaluation.streaming_verifier',
    'compare_typed_caches': 'sheets_factory.workbook.heterogeneous_contracts.validate',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def frozen_dependencies():
    for name, digest in FROZEN.items():
        require(quality.reference(name)['sha256'] == digest,
            'A frozen paired-session dependency changed: '+name)


def _module(path):
    frozen_dependencies()
    key = str(path)
    if key not in _MODULES:
        descriptor = importlib.util.spec_from_file_location('_cached_pair_frozen_'+path.stem, path)
        module = importlib.util.module_from_spec(descriptor)
        descriptor.loader.exec_module(module)
        _MODULES[key] = module
    return _MODULES[key]


def _isolate(module, expected_functions, imported_functions):
    """Copy every local function into one private dependency namespace.

    A new local function, closure, or unexpected imported function fails closed.
    No function retains the frozen module's global dictionary.
    """
    original = vars(module)
    own = {name: value for name, value in original.items()
        if isinstance(value, FunctionType) and value.__globals__ is original}
    foreign = {name: value for name, value in original.items()
        if isinstance(value, FunctionType) and value.__globals__ is not original}
    require(set(own) == expected_functions and set(foreign) == set(imported_functions),
        'Unhandled function-global isolation; the frozen callable census changed')
    require(all(value.__module__ == imported_functions[name] for name, value in foreign.items()),
        'An imported validation function changed its declared dependency')
    require(all(value.__closure__ is None for value in own.values()),
        'A frozen function acquired an unhandled closure')
    namespace = {name: ({} if name == '_MODULES' else deepcopy(value) if name != '__builtins__'
        and isinstance(value, (dict, list, set)) else value) for name, value in original.items()}
    for name, value in own.items():
        function = FunctionType(value.__code__, namespace, name, value.__defaults__, None)
        function.__kwdefaults__ = deepcopy(value.__kwdefaults__)
        function.__annotations__ = deepcopy(value.__annotations__)
        namespace[name] = function
    require(all(namespace[name].__globals__ is namespace for name in own),
        'A private validation function escaped its isolated namespace')
    return namespace


class _SourceFacade:
    def __init__(self, session, *, pair=False):
        self._session = session
        self._pair = pair

    def validate_source(self, record):
        return self._session.checked_source(record)

    def write(self, path, value):
        if self._pair and isinstance(value, dict):
            # Diagnostics must remain writable after a source guard fails.
            # This is immutable audit metadata, never an admission authority.
            value = {**value, 'source_reuse_policy': deepcopy(self._session._metadata_policy),
                'actual_source_cold_validation_count_in_process': 1,
                'source_admission_process_id': self._session.owner_pid}
        return self._session.admission.helper.write(path, value)

    def __getattr__(self, name):
        return getattr(self._session.admission.helper, name)


class PairSession:
    """One registered N360 admission, usable only by its creating process."""
    def __init__(self, source_manifest):
        global _COMPLETED_COLD_VALIDATIONS
        frozen_dependencies()
        self.owner_pid = os.getpid()
        self.source_manifest = (deepcopy(source_manifest) if isinstance(source_manifest, dict)
            else quality.reference(source_manifest))
        self.admission = quality.LinearSourceAdmission(self.source_manifest, provider_id='scaled360')
        _COMPLETED_COLD_VALIDATIONS += 1
        require(self.admission.cold_source_validation_count == 1,
            'Exactly one genuine source cold validation is required')
        _LIVE.add(self)
        source = self.checked_source(self.source_manifest)
        require(source.get('qualified') is False, 'Source admission cannot transfer task qualification')
        self._build()
        self._metadata_policy = deepcopy(self.policy())

    def guard(self):
        require(type(self) is PairSession and self in _LIVE and self.owner_pid == os.getpid(),
            'A genuine opaque paired session from this process is required')
        frozen_dependencies()
        return quality.require_source_admission(self.admission)

    def checked_source(self, record):
        require(record == self.source_manifest, 'The opaque source cache cannot admit another source')
        return self.guard()

    def policy(self):
        self.guard()
        return {'kind': POLICY_KIND, 'version': 1, 'source_manifest': deepcopy(self.source_manifest),
            'source_provider': 'scaled360', 'provider_registry': deepcopy(self.admission.providers.reference),
            'provider_module': deepcopy(self.admission.provider['module']),
            'pool_policy': quality.reference(self.pair.CONFIG),
            'pool_policy_version': 2, 'first_development_profile': 'L360-P01',
            'required_actual_LO_calls': {'financial_modeling': 7, 'debugging': 11},
            'persisted_metadata_is_not_an_admission': True}

    def _build(self):
        validator_module = _module(VALIDATOR)
        validator = _isolate(validator_module, VALIDATOR_FUNCTIONS, VALIDATOR_IMPORTS)
        validator_helper = _SourceFacade(self)
        def source_support(provider='scaled360'):
            require(provider == 'scaled360', 'The cached validator accepts only the fixed N360 provider')
            self.guard()
            return validator_helper
        validator['source_support'] = source_support
        self.validator = SimpleNamespace(**validator)

        pair_module = _module(POOL)
        pair = _isolate(pair_module, PAIR_FUNCTIONS, {})
        pair_helper = _SourceFacade(self, pair=True)
        def support(name):
            require(name in ('source', 'validator'), 'Unknown cached-pair support dependency')
            return pair_helper if name == 'source' else self.validator
        pair['support'] = support
        pair['PREPARED'], pair['KIND'] = PREPARED, KIND
        original_recipes = pair['recipes']
        def recipes():
            self.guard()
            paths = [Path(__file__), quality.DEFAULT_PROVIDERS, *map(Path, FROZEN)]
            return {**original_recipes(), **{str(path.resolve()): quality.reference(path)['sha256'] for path in paths}}
        pair['recipes'] = recipes
        original_validate = pair['validate_prepared']
        def validate_prepared(output):
            frozen, source = original_validate(output)
            require(frozen.get('source_reuse_policy') == self.policy()
                and type(frozen.get('actual_source_cold_validation_count_in_process')) is int
                and frozen['actual_source_cold_validation_count_in_process'] == 1
                and type(frozen.get('source_admission_process_id')) is int
                and frozen['source_admission_process_id'] > 0,
                'The complete process-local admission policy or cold-count metadata changed')
            return frozen, source
        pair['validate_prepared'] = validate_prepared
        self.pair = SimpleNamespace(**pair)


def _session(source_manifest, session=None):
    record = deepcopy(source_manifest) if isinstance(source_manifest, dict) else quality.reference(source_manifest)
    if session is not None:
        require(type(session) is PairSession and session in _LIVE,
            'JSON, fabricated, or cross-namespace objects cannot supply a paired admission')
        session.checked_source(record)
        return session
    quality.References().check(record)
    key = (record['path'], record['sha256'], record['bytes'])
    if key not in _SESSIONS:
        _SESSIONS[key] = PairSession(record)
    _SESSIONS[key].checked_source(record)
    return _SESSIONS[key]


def _source_helper():
    # Resolve the same frozen provider without calling the original pair's
    # support loader or mutating its module cache.
    frozen_dependencies()
    return quality.SourceProviders().load('scaled360')[1]


def _admission_failure(output, error, *, preparation, prior_completed):
    """Retain a failed cold admission without entering any actual view stage."""
    helper = _source_helper()
    output = helper._output(output, fresh=preparation)
    if preparation:
        output.mkdir(parents=True)
    name = 'source_admission_failure.json' if preparation else 'execution_preflight_failure.json'
    require(not (output/name).exists(), 'Preserve the first failed source admission')
    return helper.write(output/name, {'stage': 'genuine_cold_source_admission',
        'error_type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc(),
        'completed_source_cold_validation_count': _COMPLETED_COLD_VALIDATIONS-prior_completed,
        'source_validation_attempt_count_unknown': True,
        'producer_pid': os.getpid(), 'LO_calls': 0, 'model_calls': 0, 'solver_calls': 0,
        'Harbor_calls': 0, 'task_count': 0, 'qualified': False, 'retry_count': 0})


def prepare(source_manifest, output, *, session=None):
    # Check the fresh output contract before any potentially expensive cold work.
    _source_helper()._output(output, fresh=True)
    prior_completed = _COMPLETED_COLD_VALIDATIONS
    try:
        live = _session(source_manifest, session)
    except BaseException as error:
        _admission_failure(output, error, preparation=True, prior_completed=prior_completed)
        raise
    return live.pair.prepare(live.source_manifest, output)


def _prepared_session(output, session=None):
    path = Path(output)/'preparation.json'
    frozen = json.loads(path.read_text())
    return _session(frozen['source_manifest'], session)


def validate_prepared(output, *, session=None):
    live = _prepared_session(output, session)
    return live.pair.validate_prepared(output)


def execute_prepared(output, *, port=0, session=None):
    output = _source_helper()._output(output)
    require(not any((output/name).exists() for name in
        ('started.json', 'terminal.json', 'execution_preflight_failure.json', 'source_admission_failure.json')),
        'Preserve the first pair attempt; retries are disabled')
    prior_completed = _COMPLETED_COLD_VALIDATIONS
    try:
        live = _prepared_session(output, session)
    except BaseException as error:
        _admission_failure(output, error, preparation=False, prior_completed=prior_completed)
        raise
    return live.pair.execute_prepared(output, port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    require(0 <= args.port <= 65535, 'Use a valid local dashboard port')
    if args.prepared:
        require(args.source_manifest is None and args.output is None, 'Frozen pairs cannot receive replacement inputs')
        result = execute_prepared(args.prepared, port=args.port) if args.run else validate_prepared(args.prepared)[0]
    else:
        require(args.source_manifest is not None and args.output is not None, 'Provide an actual source and fresh output')
        result = prepare(args.source_manifest, args.output)
        if args.run:
            result = execute_prepared(args.output, port=args.port)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
