#!/usr/bin/env python3
"""Retain completed native task records after an audit keyword failure."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_factory_build_recovery', ROOT/'scripts/build_operating_reports_factory_batch.py')
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)


def recover(directory):
    directory = Path(directory).absolute()
    original = json.loads((directory/'engineered_batch.json').read_text())
    correction = json.loads((directory/'bookkeeping_correction_prospective.json').read_text())
    freeze = build.read(correction['original_plan_freeze'])
    saved = build.checked(correction['executed_code_copy'])
    if build.ref(saved)['sha256'] != freeze['implementation']['sha256']:
        raise ValueError('The saved executed builder must match the original frozen implementation')
    plans = {(row['mode'], row['plan']['variant_id']) for row in freeze['plans']}
    expected_error = "AuditStore.task() got multiple values for argument 'task_id'"
    tasks = []; recovered = []
    for path in sorted((directory/'private').glob('*/task_record.json')):
        task = json.loads(path.read_text()); key = (task['mode'], task['variant_id'])
        if key not in plans or task['plan_freeze'] != correction['original_plan_freeze']:
            raise ValueError('A task is not in the original frozen batch')
        checks = build.read(task['individual_engineering'])
        if checks['passed'] is not True or checks['native_error_count'] != 0 or not checks['given_literals_unchanged']:
            raise ValueError('Require completed individual native engineering')
        if build.inspect_resource_export(task['task_directory'], audit_path=task['worker_cap_audit']) != task['harbor_export_binding']:
            raise ValueError('The complete actual export changed')
        failure = json.loads((directory/'failures'/(task['variant_id']+'.json')).read_text())
        if failure['error_type'] != 'TypeError' or failure['error'] != expected_error:
            raise ValueError('This recovery covers only the post-export audit keyword error')
        recovered.append({'record': build.ref(path), 'original_failure': build.ref(directory/'failures'/(task['variant_id']+'.json'))})
        tasks.append(task)
    if len(tasks) != len(plans) or len({(row['mode'], row['variant_id']) for row in tasks}) != len(plans):
        raise ValueError('Require every frozen task to have completed engineering and a unique actual export')
    return build.write(directory/'engineered_batch_recovered.json', {**original,
        'tasks': tasks, 'selected_task_ids': [row['task_id'] for row in tasks], 'count': len(tasks),
        'by_mode': {mode: sum(row['mode'] == mode for row in tasks) for mode in ('financial_modeling', 'debugging')},
        'original_terminal': build.ref(directory/'engineered_batch.json'),
        'bookkeeping_correction': build.ref(directory/'bookkeeping_correction_prospective.json'),
        'recovered_record_evidence': recovered, 'failures': [], 'new_LO_or_model_calls': 0,
        'recovery_scope': 'post_export_audit_keyword_only', 'qualified': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--directory', required=True, type=Path)
    print(json.dumps(recover(parser.parse_args().directory)))
