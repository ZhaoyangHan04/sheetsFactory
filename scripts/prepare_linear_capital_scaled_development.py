#!/usr/bin/env python3
"""Freeze one N360 native development attempt with prospective stream resilience.

The first attempt retains all history and uses the frozen SUM tool-time policy.
Preparation starts no calculation or model. The explicit run command starts one
development attempt; its outer infrastructure retry allowance is zero.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).with_name('prepare_linear_capital_development.py')
UPSTREAM_SHA256 = '5bafc37a217545fe96d79a97c834c1439b6b1b859f38efeaa95223e941d51ba4'
VERSION = 2


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    if UPSTREAM != UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen complete first-development implementation changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM)); counts = {}
    def changed(key): counts[key] = counts.get(key, 0)+1
    strings = {
        'prequality_linear_capital_native_development': 'prequality_linear_capital_scaled_native_development',
        'linear_capital_task_view_actual_validation': 'linear_capital_scaled_task_view_actual_validation',
        'scripts/validate_linear_capital_task_view.py': 'scripts/validate_linear_capital_scaled_task_view.py',
        'linear_capital_portfolio': 'linear_capital_scaled',
        '-linear-': '-linear-scaled-',
    }
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'sheets_factory.evaluation.clock_resource_frontier':
                node.module = 'sheets_factory.evaluation.native_transport_frontier'; changed('transport_import')
            return node
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in strings:
                before = node.value; node.value = strings[before]; changed(before)
            return node
        def visit_FunctionDef(self, node):
            node = self.generic_visit(node)
            if node.name == 'checked_material':
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Compare) and _ast.unparse(item) == "actual['version'] == 1":
                        item.comparators[0] = _ast.Constant(VERSION); changed('actual_version')
            elif node.name == '_prepare':
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Dict) and any(isinstance(k, _ast.Constant) and k.value == 'family' for k in item.keys):
                        for key, value in zip(item.keys, item.values):
                            if isinstance(key, _ast.Constant) and key.value == 'schema_version':
                                value.value = VERSION; changed('manifest_version')
                        for key, expression in [('native_transport_profile', 'transport_profile()'),
                            ('source_provider', "'scaled360'"), ('phase', "'development'")]:
                            item.keys.append(_ast.Constant(key)); item.values.append(_ast.parse(expression, mode='eval').body)
                        changed('prospective_profile')
            elif node.name == 'validate_prepared':
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Compare) and _ast.unparse(item) == "frozen.get('schema_version') == 1":
                        item.comparators[0] = _ast.Constant(VERSION); changed('manifest_version_gate')
            elif node.name in ('_run_once', 'prepare'):
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Dict) and any(isinstance(key, _ast.Constant) and key.value == 'kind' for key in item.keys):
                        item.keys.extend([_ast.Constant('version'), _ast.Constant('native_transport_profile')])
                        item.values.extend([_ast.Constant(VERSION), _ast.parse('transport_profile()', mode='eval').body]); changed('attempt_envelope')
                if node.name == '_run_once':
                    for item in node.body:
                        if isinstance(item, _ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], _ast.Name) and item.targets[0].id == 'started':
                            if not (isinstance(item.value, _ast.Call) and isinstance(item.value.func, _ast.Name) and item.value.func.id == 'write' and len(item.value.args) == 2):
                                raise ValueError('The first-attempt reservation boundary changed')
                            item.value = _ast.Call(func=_ast.Name(id='_reserve_first_attempt', ctx=_ast.Load()),
                                args=[_ast.Name(id=name, ctx=_ast.Load()) for name in ('prepared', 'frozen', 'destination')]+[item.value.args[1]], keywords=[])
                            changed('material_reservation')
                    for item in _ast.walk(node):
                        if isinstance(item, _ast.keyword) and item.arg == 'prior_selections':
                            if _ast.unparse(item.value) != "[r['path'] for r in frozen['prior_model_selection_inventory']]":
                                raise ValueError('The complete prior-selection dispatch boundary changed')
                            item.value = _ast.parse("[r['path'] for r in read(started)['prior_model_selection_inventory']]", mode='eval').body
                            changed('launch_history_dispatch')
            return node
    tree.body = [node for node in tree.body if not (isinstance(node, _ast.If)
        and _ast.dump(node.test) == _ast.dump(_ast.parse("__name__ == '__main__'", mode='eval').body))]
    tree = Adapt().visit(tree)
    expected = {key: 1 for key in strings}; expected['-linear-'] = 2
    expected.update(transport_import=2, actual_version=1, manifest_version=1,
        prospective_profile=1, manifest_version_gate=1, attempt_envelope=4, material_reservation=1,
        launch_history_dispatch=1)
    if counts != expected:
        raise ValueError('The exact N360 first-development substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
from sheets_factory.evaluation.native_transport_frontier import transport_profile, PROFILE_PATH
_base_recipes = recipes
_base_checked_material = checked_material
_base_validate_prepared = validate_prepared


def recipes():
    adapted_ast()
    from sheets_factory.evaluation import native_transport_frontier
    native_transport_frontier.adapted_ast()
    files = (UPSTREAM, Path(native_transport_frontier.__file__), PROFILE_PATH)
    return {**_base_recipes(), **{str(path.resolve()): reference(path)['sha256'] for path in files}}


def checked_material(source_manifest, view_manifest, validation_manifest):
    result = _base_checked_material(source_manifest, view_manifest, validation_manifest)
    source, view, actual = result[3], result[4], result[6]
    require(source.get('kind') == 'independently_verified_linear_capital_scaled_native_source'
        and type(source.get('version')) is int and source['version'] == 1
        and view.get('kind') == 'materialized_unverified_linear_capital_scaled_task_view'
        and type(view.get('version')) is int and view['version'] == 1
        and actual.get('source_provider') == 'scaled360',
        'The fixed N360 source, material namespace or provider differs')
    return result


def validate_prepared(output):
    frozen = _base_validate_prepared(output)
    require(frozen.get('native_transport_profile') == transport_profile()
        and frozen.get('source_provider') == 'scaled360' and frozen.get('phase') == 'development',
        'The prospective transport profile or fixed development provider changed')
    current_history = selection_history(frozen['material_task_version'])
    require(all(record in current_history for record in frozen['selection_history_inventory']),
        'A frozen model-selection history artifact is missing or changed')
    require(frozen.get('history_roots') == [str(path.resolve()) for path in HISTORY_ROOTS],
        'The complete declared model-selection history roots changed')
    return frozen


def _reserve_first_attempt(prepared, frozen, destination, started_value):
    """Spend one durable material attempt before reaching the model boundary.

One shared reservation also covers two separately prepared snapshots of the
same material. A failed or interrupted launch retains the reservation forever.
"""
    require(bool(HISTORY_ROOTS), 'At least one complete declared history root is required')
    root = Path(HISTORY_ROOTS[0]).absolute()
    require(root == root.resolve(), 'The material reservation root must be a real path')
    root.mkdir(parents=True, exist_ok=True)
    directory = root/'.scaled_development_reservations'
    require(directory == directory.resolve(), 'The material reservation directory must be a real path')
    directory.mkdir(exist_ok=True)
    lock_path = directory/'launch.lock'
    import os
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('A scaled material first-attempt reservation is already in progress') from error
        # Cold checks are repeated inside the shared critical section. The
        # per-snapshot lock is already held by run_development.
        require(validate_prepared(prepared) == frozen, 'The prepared material changed before reservation')
        identity = frozen['material_task_version']
        current_history = selection_history(identity)
        require(all(record in current_history for record in frozen['selection_history_inventory']),
            'A frozen model-selection history artifact is missing or changed')
        partition = history_partition(current_history)
        launch_value = {**started_value, 'selection_history_inventory': current_history,
            'prior_model_selection_inventory': partition['model_selections'],
            'nonmodel_preparation_inventory': partition['nonmodel_preparations']}
        reservation_path = directory/(identity['sha256']+'.json')
        require(not reservation_path.exists() and not reservation_path.is_symlink(),
            'This material already has a reserved first attempt; no retry, rename or second snapshot is authorized')
        reservation = write(reservation_path, {'kind': KIND+'_material_first_attempt_reservation',
            'version': VERSION, 'material_task_version': identity,
            'prepared_snapshot': reference(prepared/'probe_manifest.json'),
            'evaluation_output': str(destination), 'started_value': launch_value,
            'selection_history_inventory': current_history,
            'prior_model_selection_inventory': partition['model_selections'],
            'nonmodel_preparation_inventory': partition['nonmodel_preparations'],
            'native_transport_profile': transport_profile(), 'phase': 'development',
            'effective_infrastructure_retries': 0, 'qualified': False})
        # Exclusive creates retain both records even if a later launch fails.
        return write(prepared/'development_started.json', {**launch_value, 'material_reservation': reservation})


if __name__ == '__main__': raise SystemExit(main())
