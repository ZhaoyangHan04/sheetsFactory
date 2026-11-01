"""Give distinct spreadsheet materials distinct Harbor names without changing data."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tomllib

from .resource_harbor import inspect_resource_export


def reference(path):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_file():
        raise ValueError('Use an existing real file without symlink parents')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def checked(record):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256', 'bytes'} or reference(record['path']) != record:
        raise ValueError('The complete retained file reference changed')
    return Path(record['path'])


def identity(directory, mode):
    if mode not in ('financial_modeling', 'debugging'):
        raise ValueError('Use a supported spreadsheet category')
    from .linear_capital_scaled_publication_v4 import material_identity
    return material_identity(directory, mode)


def inventory(directory):
    return {str(path.relative_to(directory)): reference(path) for path in sorted(Path(directory).rglob('*')) if path.is_file()}


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def repackage(source, destination, mode):
    """Change only the Harbor name and its manifest hashes, preserving material."""
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source != source.resolve() or destination != destination.resolve() or destination.exists():
        raise ValueError('Keep the source intact and use a fresh real destination')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Keep the source and destination in separate directory trees')
    original = inspect_resource_export(source)
    material = identity(source, mode)
    prefix = 'fm' if mode == 'financial_modeling' else 'dbg'
    task_id = prefix + '-' + material['sha256'][:24]
    if destination.name != task_id:
        raise ValueError('The destination name must bind the full logical material identity')
    before = inventory(source)
    if len(before) != 17:
        raise ValueError('A complete seventeen-file source export is required')
    shutil.copytree(source, destination)
    config = destination / 'task.toml'
    text = config.read_text()
    old_name = tomllib.loads(text)['task']['name']
    new_name = 'sheetsfactory/' + task_id
    pattern = r'(?m)^name\s*=\s*' + re.escape(json.dumps(old_name)) + r'\s*$'
    text, count = re.subn(pattern, 'name = ' + json.dumps(new_name), text)
    if count != 1 or tomllib.loads(text)['task']['name'] != new_name:
        raise ValueError('The original task name must occupy one unambiguous TOML field')
    config.write_text(text)
    manifest_path = destination / 'export_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['task_id'] = task_id
    if 'task_id' in manifest['metadata']:
        if manifest['metadata']['task_id'] != original['task_id']:
            raise ValueError('The source manifest contains conflicting task identities')
        manifest['metadata']['task_id'] = task_id
    manifest['files']['task.toml'] = reference(config)['sha256']
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    repackaged = inspect_resource_export(destination)
    after = inventory(destination)
    if set(before) != set(after):
        raise ValueError('Repackaging changed the complete file inventory')
    changed = sorted(name for name in before if before[name]['sha256'] != after[name]['sha256'])
    if changed != ['export_manifest.json', 'task.toml']:
        raise ValueError('Only the Harbor name and its export manifest may change')
    if identity(destination, mode) != material:
        raise ValueError('Repackaging changed workbook data, formulas or instructions')
    if inventory(source) != before:
        raise ValueError('The original source export changed during repackaging')
    return {'mode': mode, 'task_id': task_id, 'material_task_version': material,
            'original_directory': str(source), 'original_binding': original,
            'task_directory': str(destination), 'binding': repackaged,
            'original_inventory': before, 'inventory': after,
            'changed_files': changed, 'workbooks_and_instruction_byte_identical': True,
            'renaming_does_not_reset_development_or_confirmation_reservations': True}


def stage_pool(declarations, output):
    """Stage a partial private pool; this function grants no quality or release status."""
    output = Path(output).absolute()
    if output != output.resolve() or output.exists() or not isinstance(declarations, list) or not declarations:
        raise ValueError('Declare a nonempty pool and use a fresh real output directory')
    identities = []
    sources = []
    for row in declarations:
        if not isinstance(row, dict) or set(row) != {'task_directory', 'mode', 'quality_evidence'}:
            raise ValueError('Declare each original task, category and exact quality evidence reference')
        checked(row['quality_evidence'])
        source = Path(row['task_directory']).absolute()
        inspect_resource_export(source)
        material = identity(source, row['mode'])
        if material['sha256'] in identities:
            raise ValueError('The pool repeats logical material, even with a different name or ZIP package')
        identities.append(material['sha256'])
        sources.append((deepcopy(row), source, material))
    output.mkdir(parents=True)
    payload = output / 'SpreadsheetEval'
    payload.mkdir()
    rows = []
    try:
        for row, source, material in sources:
            prefix = 'fm' if row['mode'] == 'financial_modeling' else 'dbg'
            task_id = prefix + '-' + material['sha256'][:24]
            staged = repackage(source, payload / task_id, row['mode'])
            staged['quality_evidence'] = row['quality_evidence']
            rows.append(staged)
        return write(output / 'pool_manifest.json', {
            'kind': 'private_spreadsheet_material_candidate_pool', 'version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(), 'implementation': reference(__file__),
            'tasks': rows, 'count': len(rows), 'by_mode': {
                mode: sum(row['mode'] == mode for row in rows) for mode in ('financial_modeling', 'debugging')},
            'quality_evidence_interpretation': 'retained_reference_only_not_a_quality_certificate',
            'quality_certified_by_this_operation': False, 'confirmation_cohort_frozen': False,
            'confirmation_attempts': 0, 'old_scores_transferred': False,
            'formal_release_qualified': False, 'new_model_LO_solver_Harbor_calls': 0})
    except BaseException as error:
        write(output / 'failure.json', {'error_type': type(error).__name__, 'error': str(error),
                                       'completed_tasks': rows, 'formal_release_qualified': False})
        raise
