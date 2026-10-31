"""Real tiny seventeen-file exports; no Docker, model, Harbor run or LO."""
import difflib
import hashlib
import json
from pathlib import Path
import tomllib

import openpyxl
import pytest

from sheets_factory.evaluation import resource_harbor as base
from sheets_factory.evaluation import thread_capped_harbor_export as capped
from sheets_factory.workbook.resource_engine import DEFAULT_PROFILE

PROFILE = DEFAULT_PROFILE.with_name('entity_group_large_v2.yaml')


@pytest.fixture
def task(tmp_path):
    path=tmp_path/'task';(path/'public').mkdir(parents=True);(path/'private').mkdir()
    for relative,value in [('public/input.xlsx',10),('private/goal.xlsx',20)]:
        book=openpyxl.Workbook();book.active.title='Model';book.active['A1']='GBP pence';book.active['B2']=value
        book.create_sheet('Rates')['A1']=0.05;book.save(path/relative);book.close()
    (path/'public/instruction.md').write_bytes(b'Repair the financial model. Preserve inputs; save /app/output.xlsx.\n')
    return path


@pytest.fixture
def exported(task,tmp_path):
    audit=tmp_path/'private_audit.json'
    export=capped.export_resource_harbor(task,tmp_path/'export',
        {'task_id':'cap-toy','mode':'debugging','revision':0,'revision_hash':'a'*64},runtime_profile=PROFILE,audit_path=audit)
    return export,audit


def rebind_mutation(export,audit):
    """Rehash the altered output to reach the semantic two-line audit gate."""
    manifest=json.loads((export/'export_manifest.json').read_text())
    for relative in manifest['files']:manifest['files'][relative]=capped._reference(export/relative)['sha256']
    (export/'export_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    evidence=json.loads(audit.read_text());evidence['transformed_manifest']=capped._reference(export/'export_manifest.json')
    for relative,change in evidence['dockerfile_changes'].items():
        change['after']=capped._reference(export/relative)
        before=Path(change['before']['path']).read_text();after=(export/relative).read_text()
        change['unified_diff']=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),
            fromfile=relative+'.before',tofile=relative+'.after'))
    audit.write_text(json.dumps(evidence,indent=2)+'\n')


def test_exact_two_env_lines_external_original_audit_and_unchanged_resources_and_instruction(exported,task):
    export,audit=exported
    binding=capped.inspect_resource_export(export,audit_path=audit)
    assert binding==base.inspect_resource_export(export)  # Existing frontier binding stays exact.
    evidence=json.loads(audit.read_text());original=json.loads(Path(evidence['original_manifest']['path']).read_text())
    current=json.loads((export/'export_manifest.json').read_text())
    assert original['metadata']==current['metadata'] and current['metadata'][capped.CAP_FIELD]==capped.CAP_VALUE
    assert len(evidence['original_inventory'])==len(list(p for p in export.rglob('*') if p.is_file()))==17
    assert len(evidence['unchanged_payload_files'])==14 and not audit.is_relative_to(export)
    assert set(k for k,v in original['files'].items() if current['files'][k]!=v)==set(capped.DOCKERFILES)
    for relative in capped.DOCKERFILES:
        change=evidence['dockerfile_changes'][relative]
        before=Path(change['before']['path']).read_bytes();after=(export/relative).read_bytes()
        assert after==capped._capped(before) and after.splitlines()[1]==b'ENV MAX_CONCURRENCY=2'
        assert after.count(b'MAX_CONCURRENCY')==1
    for relative in evidence['unchanged_payload_files']:
        assert capped._inventory(export)[relative]==evidence['original_inventory'][relative]
    assert (export/'instruction.md').read_bytes()==(task/'public/instruction.md').read_bytes()
    assert (export/'environment/input.xlsx').read_bytes()==(task/'public/input.xlsx').read_bytes()
    assert (export/'tests/reference.xlsx').read_bytes()==(task/'private/goal.xlsx').read_bytes()
    config=tomllib.loads((export/'task.toml').read_text())
    assert config['environment']['cpus']==config['verifier']['environment']['cpus']==2
    assert config['environment']['memory_mb']==config['verifier']['environment']['memory_mb']==32768
    assert config['agent']['timeout_sec']==14400 and config['verifier']['timeout_sec']==2400
    assert binding['resource_runtime']['execution_budget']['tool_budget_seconds']==1800
    assert evidence['actual_container_resources_verified'] is evidence['quality_or_difficulty_certified'] is False


@pytest.mark.parametrize('role',capped.DOCKERFILES)
@pytest.mark.parametrize('fault',['missing','duplicate','wrong','numeric','misplaced','other_environment'])
def test_matching_metadata_and_rehashed_files_never_replace_actual_exact_env_gate(exported,role,fault):
    export,audit=exported;path=export/role;raw=path.read_bytes()
    replacement={'missing':b'', 'duplicate':capped.ENV_LINE*2, 'wrong':b'ENV MAX_CONCURRENCY=3\n',
        'numeric':b'ENV MAX_CONCURRENCY=2.0\n','misplaced':b'',
        'other_environment':capped.ENV_LINE+b'ENV OPENBLAS_NUM_THREADS=2\n'}[fault]
    raw=raw.replace(capped.ENV_LINE,replacement)
    if fault=='misplaced':raw+=capped.ENV_LINE
    path.write_bytes(raw);rebind_mutation(export,audit)
    base.inspect_resource_export(export)
    with pytest.raises(ValueError,match='single ENV line'):
        capped.inspect_resource_export(export,audit_path=audit)


@pytest.mark.parametrize('value',[None,2,True,'MAX_CONCURRENCY=3'])
def test_cap_marker_is_only_exact_string_not_a_substitute_for_env(exported,value):
    export,audit=exported;manifest=json.loads((export/'export_manifest.json').read_text())
    manifest['metadata'][capped.CAP_FIELD]=value
    (export/'export_manifest.json').write_text(json.dumps(manifest));rebind_mutation(export,audit)
    with pytest.raises(ValueError,match='Cap metadata'):
        capped.inspect_resource_export(export,audit_path=audit)


def test_unrelated_payload_change_is_rejected_even_when_old_manifest_hashes_match(exported):
    export,audit=exported;(export/'environment/recalculate').write_text('# altered implementation\n')
    rebind_mutation(export,audit);base.inspect_resource_export(export)
    with pytest.raises(ValueError,match='outside the two Dockerfiles'):
        capped.inspect_resource_export(export,audit_path=audit)


def test_external_audit_hash_binding_cannot_be_changed_after_preparation(exported):
    export,audit=exported;ref=capped._reference(audit)
    audit.write_text(audit.read_text()+' ')
    with pytest.raises(ValueError,match='reference changed'):
        capped.inspect_resource_export(export,audit_path=ref)


def test_export_cannot_put_an_eighteenth_audit_file_inside_public_export(task,tmp_path):
    destination=tmp_path/'export'
    with pytest.raises(ValueError,match='outside the seventeen'):
        capped.export_resource_harbor(task,destination,runtime_profile=PROFILE,audit_path=destination/'audit.json')
    assert not destination.exists()


def test_an_existing_audit_or_conflicting_metadata_never_gets_overwritten(task,tmp_path):
    audit=tmp_path/'audit.json';audit.write_bytes(b'previous failure')
    with pytest.raises(ValueError,match='Preserve previous'):
        capped.export_resource_harbor(task,tmp_path/'export',runtime_profile=PROFILE,audit_path=audit)
    assert audit.read_bytes()==b'previous failure'
    with pytest.raises(ValueError,match='exact fixed string'):
        capped.export_resource_harbor(task,tmp_path/'other',{capped.CAP_FIELD:2},runtime_profile=PROFILE,audit_path=tmp_path/'new.json')


def test_base_exporter_and_packaged_verifier_implementation_are_unchanged():
    assert hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()==capped.BASE_SHA256
    assert capped.verify_local_base_image is base.verify_local_base_image
