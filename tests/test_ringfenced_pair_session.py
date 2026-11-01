"""Tiny mocked cold proofs; opaque lifecycle/immutable artifacts, zero services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sheets_factory.core.audit import AuditStore

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    p=ROOT/'scripts/run_ringfenced_pair_session.py';s=importlib.util.spec_from_file_location('_pair_session_test',p)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def write(module,path,value):
    path.write_text(json.dumps(value));return module.c.reference(path)


@pytest.fixture
def admitted(module,tmp_path,monkeypatch):
    m=module;events=[];stub=write(m,tmp_path/'stub.json',{'fixture':'no_services'})
    contexts=[{'profile_id':p,'specification':stub,'reference':stub,'source_manifest':stub,'workbook':stub,
        'engineering_worker':stub,'engineering_pair':stub} for p in m.c.PROFILE_ORDER]
    contract=write(m,tmp_path/'contract.json',m.c.public_contract(contexts,'R2-01'))
    frozen={'contexts':contexts,'contracts':{'R2-01':contract}}
    prospective=write(m,tmp_path/'prospective.json',frozen)
    monkeypatch.setattr(m.c,'validate_prospective',lambda _:deepcopy(frozen))
    monkeypatch.setattr(m.c,'recipes',lambda:{'fixture':stub})
    def parse(ref):events.append('parse10');return {'kind':'mock_full10','inventory':ref,'fixture_only':True}
    monkeypatch.setattr(m.stream,'preflight_all',parse)
    def refcheck(_):events.append('reference');return {'fixture':True}
    def sourcecheck(_):events.append('source');return {'fixture':True}
    rp=SimpleNamespace(validate_completed=refcheck,recipes=lambda:{'fixture':stub})
    sp=SimpleNamespace(validate_source=sourcecheck,recipes=lambda:{'fixture':stub})
    monkeypatch.setattr(m.proof,'_providers',lambda:(rp,sp))
    def hydrate(context,rp,sp):
        rp.validate_completed(context['reference']);sp.validate_source(context['source_manifest'])
        index=m.c.MANDATE_ORDER.index(context['id'])+1
        def report(offset):
            return {sid:{'annual':[{'year':y,'fiscal_year':2026+y,
                **{f:index*10000+y*10+i+offset for i,f in enumerate(m.c.GROUP_FIELDS)}}
                for y in m.c.YEARS]} for sid in m.c.SCENARIOS}
        row={'id':context['id'],'profile_id':context['profile_id'],'gap_pence':index+1,
            'geometry':deepcopy(m.proof.LOCAL_GEOMETRY),
            'best':{'objective_pence':index*1000,'plan':{'P001':1,'P002':0},'report_A':report(0),'report_B':report(0)},
            'runner':{'objective_pence':index*1000-index-1,'plan':{'P001':0,'P002':1},'report_A':report(2),'report_B':report(2)}}
        for field in ('reference','source_manifest','workbook','specification','model_A','model_B','best_solver_receipt',
            'excluded_runner_solver_receipt','best_solver_validation','runner_solver_validation','whole_financial_validation'):row[field]=stub
        return row
    monkeypatch.setitem(m.proof._N,'_hydrate',hydrate)
    token=m._mint(prospective,'R2-01');d=m._LIVE[token]
    certificate={**d['certificate'],'prospective':prospective,'created_at':'toy'}
    d['certificate']=certificate;d['certificate_ref']=write(m,tmp_path/'certificate.json',certificate)
    d['artifacts'].add(d['certificate_ref'])
    return SimpleNamespace(token=token,data=d,events=events,stub=stub,prospective=prospective)


def test_one_true_parse_then_two_complete_cold_proofs_and_guarded_reuse(module,admitted):
    assert admitted.events==['parse10','reference','source','reference','source']
    for _ in range(3):assert admitted.token.checked_certificate(admitted.data['certificate_ref'])==admitted.data['certificate']
    assert admitted.events==['parse10','reference','source','reference','source']
    assert admitted.token.parsed(admitted.prospective)['fixture_only']
    with pytest.raises(ValueError):admitted.token.parsed({'passed':True})


def test_opaque_credential_is_not_json_or_constructible_or_mutable(module,admitted):
    with pytest.raises(ValueError):module._Admission(object(),{}, {},'R2-01',None)
    with pytest.raises(ValueError):module.execute_prepared({'passed':True})
    with pytest.raises(TypeError):json.dumps(admitted.token)
    with pytest.raises(AttributeError):admitted.token.state='prepared'
    with pytest.raises(AttributeError):admitted.token.certificate={'passed':True}


def test_wrong_donor_or_renamed_equivalent_certificate_is_not_admitted(module,admitted,tmp_path):
    renamed=write(module,tmp_path/'renamed.json',admitted.data['certificate'])
    with pytest.raises(ValueError,match='different, renamed'):admitted.token.checked_certificate(renamed)
    changed=deepcopy(admitted.data['certificate']);changed['local_whole_evidence'][1]['profile_id']='L360-P07'
    with pytest.raises(ValueError):admitted.token.checked_certificate(write(module,tmp_path/'wrong_donor.json',changed))


def test_any_guarded_content_replacement_or_repack_invalidates_token(module,admitted):
    path=Path(admitted.stub['path']);old=path.read_bytes();path.write_bytes(old)
    with pytest.raises(ValueError,match='artifact changed'):admitted.token.checked_certificate(admitted.data['certificate_ref'])


def test_recursive_dependency_changes_and_symlinks_fail_closed(module,tmp_path):
    child=write(module,tmp_path/'child.json',{'number':1});parent=write(module,tmp_path/'parent.json',{'child':child})
    guard=module._Artifacts();guard.add(parent,expand=True);guard.guard()
    Path(child['path']).write_text('{"number":2}')
    with pytest.raises(ValueError,match='artifact changed'):guard.guard()
    link=tmp_path/'link.json';link.symlink_to(parent['path'])
    with pytest.raises(ValueError):module._Artifacts().add({'path':str(link),'sha256':parent['sha256'],'bytes':parent['bytes']})


def test_previously_hashed_envelope_is_still_expanded_and_descendants_guarded(module,tmp_path):
    child=write(module,tmp_path/'child.json',{'number':1})
    parent=write(module,tmp_path/'parent.json',{'child':child})
    guard=module._Artifacts();guard.add(parent)
    assert str(Path(child['path'])) not in guard.records
    guard.add(parent,expand=True)
    assert str(Path(child['path'])) in guard.records
    guard.add(parent,expand=True)  # Repeated dependency walks are idempotent.
    guard.guard();Path(child['path']).write_text('{"number":2}')
    with pytest.raises(ValueError,match='artifact changed'):guard.guard()


def test_unknown_large_dependency_envelope_is_not_silently_ignored(module,tmp_path,monkeypatch):
    monkeypatch.setattr(module,'JSON_METADATA_LIMIT',32)
    known=write(module,tmp_path/'bindings.json',{'fixture_large_closed_data':'x'*50})
    module._Artifacts().add(known,expand=True)
    unknown=write(module,tmp_path/'unknown_envelope.json',{'hidden_reference':known})
    guard=module._Artifacts()
    for _ in range(2):
        with pytest.raises(ValueError,match='Unknown large metadata'):guard.add(unknown,expand=True)


def test_source_functions_are_private_bytecode_copies_with_exact_cached_gate(module,admitted):
    pilot=module._pilot();ns=module._source(admitted.token,pilot)
    for name in ('prepare','validate_prepared','execute_prepared','validate_completed','audit_workbook','engines'):
        assert ns[name].__code__ is pilot._N[name].__code__
        assert ns[name].__globals__ is ns and ns[name].__globals__ is not pilot._N
    assert ns['KIND']==module.KIND and ns['TERMINAL_KIND']==module.TERMINAL_KIND
    assert pilot._N['KIND']!=module.KIND
    assert str(Path(module.__file__).resolve()) in ns['recipes']()
    assert ns['composition'].validate_certificate(admitted.data['certificate_ref'])==admitted.data['certificate']
    assert admitted.events.count('parse10')==1 and admitted.events.count('source')==2


def test_execution_token_is_one_shot_and_never_launches_twice(module,admitted):
    calls=[];d=admitted.data
    d['state']='prepared';d['pilot']=SimpleNamespace(_observed=lambda label,out,op:op())
    d['source_namespace']={'execute_prepared':lambda out:(calls.append(out),{'fixture':'no_actual_call'})[1]}
    assert module.execute_prepared(admitted.token)=={'fixture':'no_actual_call'}
    with pytest.raises(ValueError,match='unspent'):module.execute_prepared(admitted.token)
    assert len(calls)==1 and d['state']=='spent'


def test_failed_execution_also_permanently_consumes_token(module,admitted):
    d=admitted.data;d['state']='prepared';d['pilot']=SimpleNamespace(_observed=lambda label,out,op:op())
    def fail(_):raise ValueError('actual source failure preserved')
    d['source_namespace']={'execute_prepared':fail}
    with pytest.raises(ValueError,match='source failure'):module.execute_prepared(admitted.token)
    with pytest.raises(ValueError,match='unspent'):module.execute_prepared(admitted.token)


def test_cold_validator_compares_entire_fresh_proof_before_actual_source_receipts(module,admitted,tmp_path,monkeypatch):
    certificate=deepcopy(admitted.data['certificate']);certificate['composition']['winner_objective_pence']+=1
    certref=write(module,tmp_path/'altered_certificate.json',certificate)
    prep=write(module,tmp_path/'preparation.json',{'certificate':certref})
    terminal=write(module,tmp_path/'terminal.json',{'kind':module.TERMINAL_KIND,'version':1,'preparation':prep})
    monkeypatch.setattr(module,'_source',lambda *a:pytest.fail('Invalid fresh proof must not reach the actual source validator'))
    with pytest.raises(ValueError,match='fresh cold certificate'):module.validate_completed(terminal)
    assert admitted.events.count('parse10')==2 and admitted.events.count('source')==4


def test_one_process_prepare_to_execution_has_one_parse_two_cold_proofs_and_no_serialized_token(module,admitted,tmp_path,monkeypatch):
    admitted.events.clear();monkeypatch.setattr(module,'ROOT',tmp_path)
    fake_pilot=SimpleNamespace(_observed=lambda label,out,op:op())
    monkeypatch.setattr(module,'_pilot',lambda:fake_pilot)
    def local_emit(donors,path,**kwargs):
        assert [r['id'] for r in donors]==['M01','M02']
        assert kwargs['expected_census']=={'sheets':740,'formulas':2494656,'nonempty':3547132}
        path.write_bytes(b'pure tiny fixture; not a production workbook')
        return {'output':module.c.reference(path),'donors':donors,'mock_only':True}
    monkeypatch.setattr(module.stream,'_compose',local_emit)
    def source_namespace(token,pilot):
        def prepare(cert,local,folder):
            token.checked_certificate(cert);assert module.c.read(local)['mock_only']
            folder.mkdir();return write(module,folder/'preparation.json',{'kind':module.KIND,'certificate':cert,'local':local,'fixture_only':True})
        def execute(folder):
            cert=module.c.read(folder/'preparation.json')['certificate'];token.checked_certificate(cert)
            return write(module,folder/'terminal.json',{'kind':'pure_mock_only_no_native','qualified':False})
        return {'prepare':prepare,'execute_prepared':execute,'recipes':lambda:{'fixture':admitted.stub}}
    monkeypatch.setattr(module,'_source',source_namespace)
    out=tmp_path/'outputs/session'
    token=module.prepare(admitted.prospective,out)
    assert admitted.events==['parse10','reference','source','reference','source']
    meta=module.c.read(out/'session_preparation.json')
    assert meta['process_local_token_serialized'] is False and meta['native_calls']==0 and meta['qualified'] is False
    result=module.execute_prepared(token);assert module.c.read(result)['qualified'] is False
    assert admitted.events==['parse10','reference','source','reference','source']
    with pytest.raises(ValueError):module.execute_prepared(token)


def test_json_pass_flag_does_not_replace_complete_actual_source_receipts(module,admitted,tmp_path):
    prep=write(module,tmp_path/'fake_source_preparation.json',{'certificate':admitted.data['certificate_ref']})
    terminal=write(module,tmp_path/'fake_source_terminal.json',{'kind':module.TERMINAL_KIND,'version':1,
        'passed':True,'preparation':prep})
    with pytest.raises((ValueError,KeyError)):module.validate_completed(terminal)


def test_final_source_replay_cannot_drift_an_already_admitted_artifact(module,admitted,tmp_path,monkeypatch):
    prep=write(module,tmp_path/'final_source_preparation.json',{'certificate':admitted.data['certificate_ref']})
    terminal=write(module,tmp_path/'final_source_terminal.json',{'kind':module.TERMINAL_KIND,'version':1,'preparation':prep})
    def final(_):
        Path(admitted.stub['path']).write_text('{"fixture":"changed during final source replay"}')
        return {'mock_only':'must not escape final guard'}
    monkeypatch.setattr(module,'_source',lambda *a:{'validate_completed':final})
    with pytest.raises(ValueError,match='artifact changed'):module.validate_completed(terminal)


@pytest.fixture
def witnessed_parse(module,admitted,tmp_path):
    """A tiny actual AuditStore and fabricated parse rows, explicitly fixture-only."""
    root=tmp_path/'original_parse';folder=root/'preflight';folder.mkdir(parents=True)
    frozen=module.c.read(admitted.prospective)
    report={'kind':module.stream.PREFLIGHT_KIND,'version':1,'prospective':admitted.prospective,
        'passed':True,'donors':[{'profile_id':r['profile_id'],'workbook':r['workbook'],'sheets':370,
        'physical_formulas':1247328,'all_formula_roundtrips_checked':True,'business_criterion_sites':280,
        'other_formula_elements':8,'parsed_formula_cache_bound':8192,'financial_bindings_expanded':0}
        for r in frozen['contexts']],'total_physical_formulas':12473280,
        'all_ten_donors_checked_before_hydration':True,'recipe':module.c.recipes(),'new_workbooks_services_forwards':0}
    report_ref=write(module,folder/'preflight.json',report)
    audit_dir=root/'preflight_all_ten_formula_preflight_audit'
    audit=AuditStore(audit_dir,{'status':'running','phase':'all_ten_formula_preflight','model_calls':0,'solver_calls':0})
    audit.update_run(status='passed',producer_active=False);audit.export();audit.db.close()
    log=root/'preflight.log';lines=[{'phase':'all_ten_formula_preflight','dashboard_url':'http://127.0.0.1:1/'}]
    lines.extend({'phase':'all_ten_formula_preflight','profile_id':r['profile_id'],'donors_complete':i,
        'physical_formulas_checked':i*1247328} for i,r in enumerate(frozen['contexts'],1));lines.append(report_ref)
    log.write_text('\n'.join(json.dumps(row) for row in lines)+'\n')
    cache=module.freeze_preflight_cache(report_ref,log,root/'cache.json',observed_exit_code=0)
    return SimpleNamespace(cache=cache,root=root,report=report,report_ref=report_ref,log=log,frozen=frozen,
        summary=module.c.reference(audit_dir/'summary.json'),database=module.c.reference(audit_dir/'run.sqlite'))


def test_root_pinned_complete_parse_reuse_still_runs_both_genuine_cold_providers(module,admitted,witnessed_parse):
    admitted.events.clear()
    token=module._mint(admitted.prospective,'R2-01',parse_cache=witnessed_parse.cache,
        expected_cache_sha256=witnessed_parse.cache['sha256'])
    assert admitted.events==['reference','source','reference','source']
    assert module._LIVE[token]['parse_cache']==witnessed_parse.cache
    module._require(token)
    witnessed_parse.log.write_text('changed after admission')
    with pytest.raises(ValueError,match='artifact changed'):module._require(token)


def test_a_later_sqlite_journal_invalidates_admitted_cached_execution(module,admitted,witnessed_parse):
    token=module._mint(admitted.prospective,'R2-01',parse_cache=witnessed_parse.cache,
        expected_cache_sha256=witnessed_parse.cache['sha256'])
    Path(witnessed_parse.database['path']+'-wal').write_bytes(b'new unadmitted state')
    with pytest.raises(ValueError,match='database journal'):module._require(token)


@pytest.mark.parametrize('expected',[None,'0'*64,'not-a-sha'])
def test_pure_cache_cannot_self_supply_root_pin(module,admitted,witnessed_parse,expected):
    admitted.events.clear()
    with pytest.raises(ValueError):module._mint(admitted.prospective,'R2-01',parse_cache=witnessed_parse.cache,
        expected_cache_sha256=expected)
    assert admitted.events==[]


@pytest.mark.parametrize('mutation',['inventory','code','profile','bare_pass'])
def test_even_pinned_cache_must_match_complete_current_inventory_and_code(module,admitted,witnessed_parse,tmp_path,mutation):
    value=module.c.read(witnessed_parse.cache)
    if mutation=='inventory':value['identity']['contexts'][0]['seed']=999
    elif mutation=='code':value['identity']['recipe']={}
    elif mutation=='profile':value['identity']['geometry_profile']['sha256']='0'*64
    else:value={'kind':module.PARSE_CACHE_KIND,'version':1,'passed':True,'identity':{}}
    ref=write(module,tmp_path/('wrong_'+mutation+'.json'),value);admitted.events.clear()
    with pytest.raises((ValueError,KeyError)):module._mint(admitted.prospective,'R2-01',parse_cache=ref,
        expected_cache_sha256=ref['sha256'])
    assert admitted.events==[]


@pytest.mark.parametrize('mutation',['nine_only','reordered','unproved_formula','wrong_workbook','partial_transcript','failed_exit','running_audit','database_running'])
def test_parse_cache_requires_all_ten_whole_censuses_and_natural_completed_producer(module,admitted,witnessed_parse,tmp_path,mutation):
    fixture=witnessed_parse;report=deepcopy(fixture.report);exit_code=0
    if mutation=='nine_only':report['donors'].pop()
    elif mutation=='reordered':report['donors'][0],report['donors'][1]=report['donors'][1],report['donors'][0]
    elif mutation=='unproved_formula':report['donors'][0]['all_formula_roundtrips_checked']=False
    elif mutation=='wrong_workbook':report['donors'][0]['workbook']={'path':'wrong','sha256':'0'*64,'bytes':1}
    elif mutation=='partial_transcript':fixture.log.write_text('\n'.join(fixture.log.read_text().splitlines()[:-1]))
    elif mutation=='failed_exit':exit_code=1
    elif mutation=='running_audit':
        summary=module.c.read(fixture.summary);summary['run']['status']='running'
        fixture.summary=write(module,Path(fixture.summary['path']),summary)
    elif mutation=='database_running':
        with module.sqlite3.connect(fixture.database['path']) as db:
            run=json.loads(db.execute("SELECT value FROM state WHERE key='run'").fetchone()[0]);run['status']='running'
            db.execute("UPDATE state SET value=? WHERE key='run'",(json.dumps(run),));db.commit()
        fixture.database=module.c.reference(fixture.database['path'])
    ref=write(module,Path(fixture.report_ref['path']),report)
    with pytest.raises(ValueError):module._completed_parse(ref,admitted.prospective,fixture.frozen,
        module.c.reference(fixture.log),fixture.summary,fixture.database,exit_code)
