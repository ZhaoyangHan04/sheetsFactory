"""Exact descriptor ownership, unchanged parsing cache and real metadata closure."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
POOL=ROOT/'outputs/research/ringfenced_pair_zero_service_preparation_20261101T010044Z/pool/prospective.json'


def module():
    spec=importlib.util.spec_from_file_location('_pair_session_host_descriptor_test',ROOT/'scripts/run_ringfenced_pair_session_revision2.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.fixture
def bound(tmp_path):
    m=module();host=tmp_path/'solver.log';host.write_bytes(b'exact retained native log')
    parent=m.c.write(tmp_path/'solver_result.json',{'immutable':'parent descriptor'})
    record=m.c.reference(host);local={**record,'path':'/app/solver.log'}
    row={'container_descriptor':local,'host':record,'allowed_parent_JSONs':[parent],
        'native_preparation':parent,'native_terminal':parent,'native_validation':parent}
    token=m._CONTEXT.set([row])
    try:artifacts=m._Artifacts()
    finally:m._CONTEXT.reset(token)
    return m,artifacts,parent,local,host,row


def test_exact_parent_descriptor_is_recorded_and_host_hash_stat_guarded(bound):
    m,a,parent,local,host,row=bound
    a._parents.append(parent)
    try:a.add(local,expand=True)
    finally:a._parents.pop()
    assert str(host) in a.records and local['path'] not in a.records
    assert a.container_descriptor_bindings==[{**row,'actual_parent_JSON':parent}]
    assert a.records[parent['path']][0]==parent
    a.guard();host.write_bytes(b'changed retained native log')
    with pytest.raises(ValueError,match='artifact changed'):a.guard()


@pytest.mark.parametrize('problem',['unknown_name','traversal','SHA','bytes','missing_parent','other_parent','wrong_parent_SHA'])
def test_missing_wrong_or_unowned_container_descriptor_fails_closed(bound,tmp_path,problem):
    m,a,parent,local,_,_=bound;local=deepcopy(local);owner=parent
    if problem=='unknown_name':local['path']='/app/unknown.log'
    elif problem=='traversal':local['path']='/app/../solver.log'
    elif problem=='SHA':local['sha256']='0'*64
    elif problem=='bytes':local['bytes']+=1
    elif problem=='missing_parent':owner=None
    elif problem=='other_parent':owner=m.c.write(tmp_path/'other.json',{})
    else:owner={**parent,'sha256':'0'*64}
    if owner:a._parents.append(owner)
    with pytest.raises(ValueError,match='unbound or unknown'):a.add(local,expand=True)


def test_parent_mutation_and_unmapped_host_dependencies_are_not_skipped(bound,tmp_path):
    m,a,parent,local,_,_=bound;Path(parent['path']).write_text('changed parent')
    a._parents.append(parent)
    with pytest.raises(ValueError):a.add(local)
    missing={'path':str(tmp_path/'missing-host.txt'),'sha256':'0'*64,'bytes':0}
    with pytest.raises(ValueError):a.add(missing)


def test_constructor_requires_selected_immutable_job_context():
    m=module()
    with pytest.raises(ValueError,match='Selected immutable'):m._Artifacts()


@pytest.mark.parametrize('problem',['unknown_backend','wrong_version','bad_mount','CID','wrong_host_SHA','wrong_container_path'])
def test_selected_real_native_descriptor_validation_rejects_mutations(monkeypatch,problem):
    if not POOL.is_file():pytest.skip('Retained selected native metadata unavailable')
    m=module();context=m.c.read(POOL)['contexts'][0];reference=m.c.read(context['reference'])
    descriptor=m.c.read(reference['solver_validations']['best']);prep=descriptor['preparation'];old=m.c.read
    def read(row):
        value=deepcopy(old(row))
        if row==prep:
            if problem=='unknown_backend':value['request']['backend']='other'
            elif problem=='wrong_version':value['version']=1
        elif row==descriptor['host_before']:
            if problem=='bad_mount':value['Mounts'][0]['Source']='/other/job_bundle'
            elif problem=='CID':value['Id']='0'*64
        elif row==descriptor['solver_result']:
            if problem=='wrong_host_SHA':value['log_reference']['sha256']='0'*64
            elif problem=='wrong_container_path':value['log_reference']['path']='/app/../solver.log'
        # Maintain inline-result equality so SHA/path guards themselves decide.
        elif row==reference['solver_validations']['best'] and problem in ('wrong_host_SHA','wrong_container_path'):
            field=value['solver']['log_reference'];field['sha256' if problem=='wrong_host_SHA' else 'path']='0'*64 if problem=='wrong_host_SHA' else '/app/../solver.log'
        return value
    monkeypatch.setattr(m.c,'read',read)
    with pytest.raises(ValueError):m._job_aliases(reference,'best')


def test_real_selected_metadata_closure_maps_only_fixed_three_CP_artifacts_and_no_cold_replay(tmp_path,monkeypatch):
    if not POOL.is_file():pytest.skip('Retained selected native metadata unavailable')
    m=module();prospective=m.c.reference(POOL);frozen=m.c.read(prospective)
    monkeypatch.setattr(m._N['stream'],'preflight_all',lambda *a,**k:pytest.fail('No full-ten parser replay'))
    monkeypatch.setattr(m._N['proof'],'_compose',lambda *a,**k:pytest.fail('No genuine cold provider replay'))
    aliases=m.selected_metadata(prospective,'R2-01')
    assert len(aliases)==12 and {Path(r['container_descriptor']['path']).name for r in aliases}==set(m.NAMES.values())
    token=m._CONTEXT.set(aliases)
    try:a=m._Artifacts()
    finally:m._CONTEXT.reset(token)
    a.bind(frozen['contexts'])
    for context in m.c.pair_contexts(frozen['contexts'],'R2-01'):
        a.bind([context['reference'],context['source_manifest']],expand=True)
    a.guard()
    assert len(a.records)>7000 and a.container_descriptor_bindings
    assert all(r['actual_parent_JSON'] in r['allowed_parent_JSONs'] for r in a.container_descriptor_bindings)
    assert not any(path.startswith('/app/') for path in a.records)
    # This is the exact prior cache identity function; no full worksheet parser,
    # composition hydration, source validator, Docker or model is called above.
    identity=m._N['_parse_identity'](prospective,frozen)
    assert identity['producer_entry']['sha256']==m._N['PILOT_SHA']
    assert identity['geometry_profile']['sha256']==m._N['PROFILE_SHA']
    assert m._N['__file__']==str(m.FROZEN) and m.c.reference(m.FROZEN)['sha256']==m.FROZEN_SHA
    m.c.write(tmp_path/'actual_selected_metadata_closure.json',{'passed':True,'prospective':prospective,
        'guarded_records':len(a.records),'authenticated_native_descriptors':len(aliases),
        'encountered_container_parent_bindings':len(a.container_descriptor_bindings),
        'actual_cold_calls':0,'full_ten_worksheet_parse_calls':0,'native_calls':0})


def test_new_source_recipe_binds_both_implementations_without_altering_parser_identity():
    from types import SimpleNamespace
    m=module();pilot=SimpleNamespace(_N={'recipes':lambda:{}},recipes=lambda:{})
    copied=m._source(SimpleNamespace(checked_certificate=lambda r:r),pilot)
    recipe=copied['recipes']()
    assert recipe[str(m.FROZEN)]['sha256']==m.FROZEN_SHA
    assert recipe[str(Path(m.__file__).resolve())]==m.c.reference(m.__file__)
    assert copied is not pilot._N and pilot._N['recipes']()=={}


def test_private_lifecycle_has_no_shared_admission_registry_or_original_global_edits():
    m=module();other=module()
    assert m._N['_LIVE'] is not other._N['_LIVE'] and m._N['_SEAL'] is not other._N['_SEAL']
    assert m._N['_Artifacts'] is m._Artifacts and m._N['_mint'] is m._mint
    assert m._N['execute_prepared'].__globals__ is m._N
    assert m._N['_Admission'].guard.__globals__ is m._N
