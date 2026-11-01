"""Shared goals must not collapse distinct debugging tasks into one Harbor name."""
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
import pytest

from sheets_factory.evaluation import material_release_layout as layout
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export


def workbook(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.active.title = 'Summary'
    book.active['A1'] = value
    book.active['B1'] = 'Annual revenue'
    for name in ('History', 'Forecast', 'Budget', 'Assumptions'):
        book.create_sheet(name)['A1'] = 'Supplied business context'
    book.save(path)
    book.close()


def exported(tmp_path, name, source_value, *, repacked=False):
    task = tmp_path / ('source_' + name)
    workbook(task / 'public/input.xlsx', source_value)
    workbook(task / 'private/goal.xlsx', 10)
    (task / 'public/instruction.md').write_text('Repair the revenue report. Save /app/output.xlsx.\n')
    if repacked:
        for path in (task / 'public/input.xlsx', task / 'private/goal.xlsx'):
            with ZipFile(path) as archive:
                members = [(item.filename, archive.read(item.filename)) for item in archive.infolist()]
            with ZipFile(path, 'w', compression=ZIP_DEFLATED, compresslevel=1) as archive:
                for filename, raw in reversed(members):
                    archive.writestr(filename, raw)
    export = tmp_path / ('export_' + name)
    export_resource_harbor(task, export, {'task_id': 'shared-goal-id', 'revision': 0,
                                        'revision_hash': 'r0', 'mode': 'debugging'})
    evidence = tmp_path / (name + '_evidence.json')
    evidence.write_text(json.dumps({'fixture': 'not_a_quality_certificate'}))
    return export, {'task_directory': str(export), 'mode': 'debugging', 'quality_evidence': layout.reference(evidence)}


def test_distinct_inputs_with_one_goal_keep_distinct_names_and_all_business_bytes(tmp_path):
    first, a = exported(tmp_path, 'a', 1)
    second, b = exported(tmp_path, 'b', 2)
    assert inspect_resource_export(first)['task_name'] == inspect_resource_export(second)['task_name']
    before = {str(p): p.read_bytes() for source in (first, second) for p in source.rglob('*') if p.is_file()}
    result = layout.stage_pool([a, b], tmp_path / 'pool')
    manifest = json.loads(Path(result['path']).read_text())
    assert manifest['by_mode'] == {'financial_modeling': 0, 'debugging': 2}
    assert len({row['task_id'] for row in manifest['tasks']}) == 2
    assert not manifest['confirmation_cohort_frozen'] and not manifest['formal_release_qualified']
    assert not manifest['quality_certified_by_this_operation'] and not manifest['old_scores_transferred']
    for row in manifest['tasks']:
        source, destination = Path(row['original_directory']), Path(row['task_directory'])
        assert inspect_resource_export(destination)['task_id'] == row['task_id'] == destination.name
        assert row['changed_files'] == ['export_manifest.json', 'task.toml']
        for name in row['inventory']:
            if name not in row['changed_files']:
                assert (source / name).read_bytes() == (destination / name).read_bytes()
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())


def test_repacking_or_renaming_cannot_create_another_logical_task(tmp_path):
    first, a = exported(tmp_path, 'a', 1)
    second, b = exported(tmp_path, 'b', 1, repacked=True)
    assert layout.reference(first / 'environment/input.xlsx')['sha256'] != layout.reference(second / 'environment/input.xlsx')['sha256']
    assert layout.identity(first, 'debugging') == layout.identity(second, 'debugging')
    with pytest.raises(ValueError, match='repeats logical material'):
        layout.stage_pool([a, b], tmp_path / 'duplicate_pool')
    assert not (tmp_path / 'duplicate_pool').exists()


@pytest.mark.parametrize('fault', ['reference', 'file', 'symlink', 'mode'])
def test_invalid_source_or_changed_evidence_cannot_enter_the_pool(tmp_path, fault):
    source, row = exported(tmp_path, 'a', 1)
    if fault == 'reference':
        Path(row['quality_evidence']['path']).write_text('changed')
    elif fault == 'file':
        (source / 'tests/reference.xlsx').write_bytes(b'changed')
    elif fault == 'symlink':
        original = source / 'instruction.md'
        data = original.read_bytes(); original.unlink()
        target = tmp_path / 'outside_instruction.md'; target.write_bytes(data)
        original.symlink_to(target)
    else:
        row['mode'] = 'unsupported'
    with pytest.raises((ValueError, OSError)):
        layout.stage_pool([row], tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


def test_a_wrong_destination_name_or_existing_pool_cannot_reset_identity(tmp_path):
    source, row = exported(tmp_path, 'a', 1)
    with pytest.raises(ValueError, match='logical material identity'):
        layout.repackage(source, tmp_path / 'arbitrary-new-name', 'debugging')
    destination = tmp_path / 'pool'
    layout.stage_pool([row], destination)
    with pytest.raises(ValueError, match='fresh real output'):
        layout.stage_pool([row], destination)
