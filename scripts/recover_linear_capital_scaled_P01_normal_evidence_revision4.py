#!/usr/bin/env python3
"""Recover fixed P01 controls with their complete resource export binding."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'scripts/recover_linear_capital_scaled_P01_normal_evidence_revision3.py'
FROZEN_SHA = '8663ef48f0f2df78f8959d2f9ef9a81c3b9c905b13d4081d6825e2d66678c1d3'
BASE_KEYS = frozenset(('task_id', 'task_name', 'revision', 'revision_hash', 'export_manifest_sha256'))
KIND = 'prepared_fixed_P01_normal_append_only_evidence_recovery_revision4'
LINEAGE_PATHS = (
    'outputs/research/P01_normal_append_only_recovery_revision3_20261101T004825Z/prepared/prospective.json',
    'outputs/research/P01_normal_append_only_recovery_revision3_20261101T004825Z/prepared/failure.json',
    'outputs/research/P01_normal_append_only_recovery_revision3_20261101T004825Z/export_binding_small_scalar_diagnosis.json',
)


def load_original():
    spec = importlib.util.spec_from_file_location('_P01_evidence_revision4_frozen_parent', FROZEN)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    value.require(value.reference(FROZEN)['sha256'] == FROZEN_SHA, 'The frozen complete revision3 recovery changed')
    return value


OLD = load_original()
require, reference = OLD.require, OLD.reference


def _resource_bound_exports(staged, quarantine, expected, access):
    """Compare all enriched fields, then join the original five-field identity."""
    require(set(expected) == BASE_KEYS, 'The retained historical export requires exactly five identity fields')
    left = OLD.inspect_resource_export(staged)
    right = OLD.inspect_resource_export(quarantine)
    require(set(left) == set(right) == BASE_KEYS | {'required_controls', 'resource_runtime'}
            and left == right, 'The complete staged and quarantined resource bindings differ')
    require({key: left[key] for key in BASE_KEYS} == expected
            and left['required_controls'] == ['oracle', 'nop'], 'The retained historical export identity differs')
    # inspect_resource_export already validates every packaged file, runtime
    # profile, image, recipe and resource setting. Keep its full result as proof.
    checks = getattr(access, 'resource_export_binding_checks', [])
    checks.append({'task_id': expected['task_id'], 'historical_identity': deepcopy(expected),
                   'complete_resource_binding': deepcopy(left), 'all_enriched_fields_compared': True})
    access.resource_export_binding_checks = checks
    return True


def export_ast():
    tree = ast.parse((ROOT / 'scripts/recover_linear_capital_scaled_P01_normal_evidence.py').read_bytes())
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == '_export')
    wanted = ast.dump(ast.parse('inspect_resource_export(staged) == inspect_resource_export(quarantine) == expected').body[0].value,
                      include_attributes=False)
    changes = []

    class Adapt(ast.NodeTransformer):
        def visit_Compare(self, node):
            if ast.dump(node, include_attributes=False) == wanted:
                changes.append(1)
                return ast.copy_location(ast.parse('_resource_bound_exports(staged, quarantine, expected, access)').body[0].value, node)
            return self.generic_visit(node)

    function = Adapt().visit(function)
    require(changes == [1], 'The exact historical export comparison changed')
    return ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))


def install_export_reader():
    OLD._N['_resource_bound_exports'] = _resource_bound_exports
    exec(compile(export_ast(), str(Path(__file__)), 'exec'), OLD._N)


def recipes():
    result = OLD.recipes()
    for path in (Path(__file__), FROZEN, *(ROOT / path for path in LINEAGE_PATHS)):
        result[str(path)] = reference(path)
    return result


def prepare(output):
    out = OLD._output(output)
    require(not out.exists(), 'Preserve every previous recovery preparation')
    proposal = OLD._proposal()
    access = OLD.Access()
    access.checked(OLD.PROPOSAL, 'original_proposal')
    for row in proposal['anchors'].values():
        access.checked(row, 'unchanged_original_anchor')
    access.checked(proposal['actual_resource_diagnostic'], 'retained_resource_diagnostic')
    frozen = {'kind': KIND, 'version': 4, 'original_run': str(OLD.RUN), 'proposal': OLD.PROPOSAL,
              'task_ids': list(OLD.TASKS), 'batch_id': OLD.BATCH, 'anchors': deepcopy(proposal['anchors']),
              'resource_diagnostic': deepcopy(proposal['actual_resource_diagnostic']), 'recipe': recipes(),
              'prepared_at': datetime.now(timezone.utc).isoformat(),
              'permitted_new_calls': {'model': 0, 'LO': 0, 'Harbor': 0, 'Docker': 0},
              'original_status_or_export_mutation_permitted': False, 'qualified': False, 'formal_release': False}
    OLD._bind_sidecar_metadata(frozen, access)
    access.guard()
    out.mkdir(parents=True)
    return OLD.write(out / 'prospective.json', frozen)


def validate_prepared(output):
    out = OLD._output(output)
    frozen = json.loads((out / 'prospective.json').read_text())
    proposal = OLD._proposal()
    require(frozen['kind'] == KIND and frozen['version'] == 4 and frozen['original_run'] == str(OLD.RUN)
            and frozen['proposal'] == OLD.PROPOSAL and frozen['task_ids'] == list(OLD.TASKS)
            and frozen['batch_id'] == OLD.BATCH and frozen['anchors'] == proposal['anchors']
            and frozen['resource_diagnostic'] == proposal['actual_resource_diagnostic']
            and frozen['recipe'] == recipes()
            and frozen['permitted_new_calls'] == {'model': 0, 'LO': 0, 'Harbor': 0, 'Docker': 0}
            and frozen['original_status_or_export_mutation_permitted'] is frozen['qualified'] is frozen['formal_release'] is False,
            'The fixed original evidence recovery contract changed')
    access = OLD.Access()
    for row in (OLD.PROPOSAL, *frozen['recipe'].values(), *frozen['anchors'].values(), frozen['resource_diagnostic']):
        access.checked(row, 'frozen_recovery_dependency')
    OLD._validate_sidecar_metadata(frozen, access)
    return frozen, access


def certify(output):
    out = OLD._output(output)
    frozen, access = validate_prepared(out)
    require(not (out / 'started.json').exists(), 'Preserve the first certificate validation and any failure')
    OLD.write(out / 'started.json', {'kind': KIND, 'prospective': reference(out / 'prospective.json')})
    try:
        install_export_reader()
        result = OLD._recover(frozen, access)
        checks = getattr(access, 'resource_export_binding_checks', [])
        require(len(checks) == 2 and {row['task_id'] for row in checks} == set(OLD.TASKS),
                'Both original tasks require complete resource export equality')
        result.update(kind='fixed_P01_normal_append_only_evidence_recovery_certificate_revision4', version=4,
                      prospective=reference(out / 'prospective.json'), resource_export_binding_checks=deepcopy(checks))
        access.guard()
        return OLD.write(out / 'certificate.json', result)
    except BaseException as error:
        OLD.write(out / 'failure.json', {'kind': KIND, 'error_type': type(error).__name__, 'error': str(error),
                                       'read_only_access_inventory': access.inventory(),
                                       'new_calls': frozen['permitted_new_calls'], 'qualified': False})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    args = parser.parse_args(argv)
    require((args.output is None) != (args.prepared is None), 'Choose a fresh preparation or its frozen certificate check')
    target = args.output if args.output is not None else args.prepared
    with OLD.strict_entry().admission_monitor(target, 'P01_evidence_revision4') as state:
        result = prepare(target) if args.output is not None else certify(target)
        state['passed'] = True
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
