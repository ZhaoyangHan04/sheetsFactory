"""Offline contract tests. Mock checker receipts certify no workbook activity."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes import construction, scc_activity as node
from sheets_factory.pipelines import scc_activity_admission as admission
from sheets_factory.task_adapters.public_input_priority import ref, canonical

ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return ref(path)


def fixture(tmp_path):
    source = tmp_path/'source.xlsx'
    book = openpyxl.Workbook();book.active.title = 'First';book.create_sheet('Second')
    book['First']['A1'] = "='Second'!A1+1";book['Second']['A1'] = '=2+2'
    book['Second']['B1'] = 0;book.save(source);book.close()
    edits = [{'sheet':'First','cell':'A1','before':"='Second'!A1+1",'after':"='Second'!A1-1"},
             {'sheet':'Second','cell':'A1','before':'=2+2','after':'=2-2'}]
    scope = {'schema_version':2,'adapter':admission.ADAPTER,'family_count':2,'formula_slots':3,
        'prospective_nonzero_roots':2,'families':[
            {'sheet':'First','cells':[{'cell':'A1','source_kind':'finite_numeric_nonzero'}]},
            {'sheet':'Second','cells':[{'cell':'A1','source_kind':'finite_numeric_nonzero'},
                                     {'cell':'B1','source_kind':'exact_numeric_zero'}]}]}
    scope_ref = dump(tmp_path/'scope.json', scope)
    implementation = tmp_path/'compiler.py';implementation.write_text('# Offline binding fixture\n')
    adapter = {'id':admission.ADAPTER,'implementation':ref(implementation),
               'policy':{'version':2,'fixture':True}}
    adapter['policy_sha256'] = canonical(adapter['policy'])
    source_manifest = dump(tmp_path/'source_manifest.json', {'offline_fixture':True})
    plan = {'edits':edits,'public_instruction':'Repair the financial definitions.',
            'public_rules':['Keep the supplied financial terms.'],'reference_evidence':['Offline fixture'],
            'family_adapter':{'id':admission.ADAPTER}}
    source_binding = {'source':ref(source),'source_manifest':source_manifest,'task_adapter':adapter,
                      'scope_inventory':scope_ref,'root_count':2,'edits_sha256':canonical(edits),
                      'financial_admission':dump(tmp_path/'financial_admission.json', {'offline_fixture':True}),
                      'public_input_priority_audit':dump(tmp_path/'timing_audit.json',{'source':ref(source),
                          'numeric_reference_proof':dump(tmp_path/'timing_proof.json',{'source_manifest':source_manifest})})}
    checker = tmp_path/'checker.py'
    checker.write_text('from .native_error_probe import exact_typed_value\n'
        'def prove_scc_island_root_impacts(**kwargs):\n    return None\n'
        'def validate_scc_island_root_certificate(*args):\n    return []\n')
    setting = {'enabled':True,'version':8,'upstream_construction':admission.upstream_binding(),
        'checker':ref(checker),'bindings':dump(tmp_path/'bindings.json',
            {'kind':'scc_activity_source_bindings','version':8,'sources':{ref(source)['sha256']:source_binding}})}
    events = []
    audit = SimpleNamespace(emit=lambda *args,**kwargs:events.append((args,kwargs)))
    ctx = TaskContext('offline','dbg-fixture','debugging',source,tmp_path/'task',
        {admission.SETTING:setting,'project_root':str(ROOT)},audit,None,None,
        data={'baseline':source,'plan':plan,'source_id':ref(source)['sha256'],
              'source_cache':tmp_path/'source_cache',
              'finance_evidence':{'task_adapter':adapter,'full_graph_financial_admission':source_binding['financial_admission']}})
    return ctx,source_binding,scope,events


def isolate_financial_gate(monkeypatch):
    """Unit fixtures cannot claim to have audited an actual financial source."""
    monkeypatch.setattr(admission,'validate_financial_admission',lambda b:{'offline_unit_fixture':True})
    def unit_timing(reference,binding):
        record=admission.read(reference)
        admission.require(admission.same_artifact(record['source'],binding['source']), 'Wrong unit timing source')
        admission.require(admission.same_artifact(admission.read(record['numeric_reference_proof'])['source_manifest'],binding['source_manifest']),
            'Wrong unit timing manifest')
        return record
    monkeypatch.setattr(admission,'validate_presented_numeric_timing',unit_timing)


def test_copied_construct_prefix_and_suffix_are_exact_upstream_AST():
    assert ref(Path(construction.__file__))['sha256']==admission.UPSTREAM_SHA256
    old_tree=ast.parse(Path(construction.__file__).read_text())
    new_tree=ast.parse(Path(node.__file__).read_text())
    old=next(n for c in old_tree.body if isinstance(c,ast.ClassDef) and c.name=='ConstructNode'
             for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='execute').body
    new=next(n for c in new_tree.body if isinstance(c,ast.ClassDef) and c.name=='SCCConstructNode'
             for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='_execute_scc').body
    def assignment(n,name):
        return isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)
    proof_start=next(i for i,n in enumerate(old) if assignment(n,'root_impacts'))
    final_start=next(i for i,n in enumerate(old) if assignment(n,'analysis'))
    simplify=lambda nodes:[ast.dump(n,include_attributes=False) for n in nodes]
    assert simplify(new[:proof_start])==simplify(old[:proof_start])
    assert simplify(new[-len(old[final_start:]):])==simplify(old[final_start:])


def test_registry_preserves_priority_and_every_mandatory_quality_node():
    selected=yaml.safe_load((ROOT/'config/task_adapters/scc_activity_nodes.yaml').read_text())['nodes']
    previous=yaml.safe_load((ROOT/'config/task_adapters/public_input_priority_nodes.yaml').read_text())['nodes']
    assert set(selected)==set(previous)
    assert {k for k in selected if selected[k]!=previous[k]}=={'construct','plan'}
    assert selected['construct']=='sheets_factory.nodes.scc_activity:SCCConstructNode'
    assert selected['plan']=='sheets_factory.pipelines.scc_activity_admission:FullGraphSCCPlanNode'
    for mode in ('financial_modeling','debugging'):
        template=yaml.safe_load((ROOT/f'src/sheets_factory/pipelines/templates/{mode}.yaml').read_text())
        assert template['phases']['revision']==['construct','instruction','precheck','independent_recovery','trajectory','diagnose']


@pytest.mark.parametrize('mode,setting',[('financial_modeling',{'enabled':True,'version':0}),('debugging',None),
                                       ('debugging',{'enabled':False})])
def test_non_opt_in_or_financial_modeling_delegates_original_construct(tmp_path,monkeypatch,mode,setting):
    ctx,*_=fixture(tmp_path);ctx.mode=mode;ctx.config={admission.SETTING:setting}
    marker={'ordinary':True};calls=[]
    monkeypatch.setattr(construction.ConstructNode,'execute',lambda self,c:calls.append(c) or marker)
    assert node.SCCConstructNode().execute(ctx) is marker and calls==[ctx]


def test_explicit_binding_loads_exact_v8_provider_with_relative_imports(tmp_path,monkeypatch):
    isolate_financial_gate(monkeypatch)
    ctx,*_=fixture(tmp_path)
    result=admission.validate_context_binding(ctx)
    assert result['provider'].exact_typed_value is not None
    assert result['allow_constant_index_ancestors'] is False


@pytest.mark.parametrize('defect',['version','upstream','source','baseline','compiler','policy','plan','scope',
    'checker','missing_source','scenario','limits','index_bool'])
def test_explicit_binding_rejects_before_any_engine_or_model(tmp_path,monkeypatch,defect):
    isolate_financial_gate(monkeypatch)
    ctx,binding,scope,_=fixture(tmp_path);setting=ctx.config[admission.SETTING]
    if defect=='version':setting['version']=True
    elif defect=='upstream':setting['upstream_construction']['sha256']='0'*64
    elif defect=='source':ctx.source.write_bytes(b'changed')
    elif defect=='baseline':
        different=tmp_path/'other.xlsx';different.write_bytes(b'different');ctx.data['baseline']=different
    elif defect=='compiler':Path(binding['task_adapter']['implementation']['path']).write_text('# changed')
    elif defect=='policy':binding['task_adapter']['policy']['changed']=True
    elif defect=='plan':ctx.data['plan']['edits'][0]['after']='=9+9'
    elif defect=='scope':
        ctx.data['plan']['edits'].pop();binding['edits_sha256']=canonical(ctx.data['plan']['edits']);binding['root_count']=1
    elif defect=='checker':Path(setting['checker']['path']).write_text('# changed')
    elif defect=='missing_source':binding=None
    elif defect=='scenario':ctx.data['plan']['scenario_inputs']=[{'sheet':'First','cell':'B1','after':1}]
    elif defect=='limits':setting['proof_limits']={'max_island_cells':True}
    else:setting['allow_constant_index_ancestors']='yes'
    setting['bindings']=dump(Path(setting['bindings']['path']),{'kind':'scc_activity_source_bindings','version':8,
        'sources':{ctx.data['source_id']:binding} if binding is not None else {}})
    with pytest.raises((ValueError,KeyError)):
        admission.validate_context_binding(ctx)


def fake_certificate(ctx, goal, combined, checker):
    impacts=[]
    for index,edit in enumerate(ctx.data['plan']['edits']):
        impacts.append({'root_index':index,'evidence':{'root_index':index,'root':edit['sheet']+'!'+edit['cell'],
            'individual_active':True,'combined_marginal_active':True}})
    return {'version':8,'proof_method':admission.METHOD,'passed':True,'blocking':False,
        'state':'proven_local_own_value_lower_bounds','actual_LO_started_count':6,'actual_LO_execution_count':6,
        'implementation_sha256':checker['sha256'],'goal_sha256':ref(goal)['sha256'],
        'combined_input_sha256':ref(combined)['sha256'],'edits_sha256':canonical(ctx.data['plan']['edits']),
        'root_count':len(impacts),'root_impacts':impacts,'counts_are_lower_bounds':True,
        'union_graph':{'constant_INDEX_extension':{'enabled':False}},
        'complete_per_root_changed_sets_claimed':False,'full_counterfactual_convergence_claimed':False,
        'counterfactual_uniqueness_claimed':False,'source_uniqueness_transferred_to_mutants':False}


@pytest.mark.parametrize('defect',['version','count_bool','count_incomplete','context','edit','omitted_root',
    'swapped_roots','inactive','overclaim','checker'])
def test_certificate_shape_gate_rejects_incomplete_or_overstated_proof(tmp_path,defect):
    ctx,*_=fixture(tmp_path);checker=ctx.config[admission.SETTING]['checker']
    cert=fake_certificate(ctx,ctx.source,ctx.source,checker)
    if defect=='version':cert['version']=6
    elif defect=='count_bool':cert['actual_LO_started_count']=True
    elif defect=='count_incomplete':cert['actual_LO_execution_count']=5
    elif defect=='context':cert['goal_sha256']='0'*64
    elif defect=='edit':cert['edits_sha256']='0'*64
    elif defect=='omitted_root':cert['root_impacts'].pop()
    elif defect=='swapped_roots':cert['root_impacts'].reverse()
    elif defect=='inactive':cert['root_impacts'][0]['evidence']['combined_marginal_active']=False
    elif defect=='overclaim':cert['counterfactual_uniqueness_claimed']=True
    else:cert['implementation_sha256']='0'*64
    provider=SimpleNamespace(validate_scc_island_root_certificate=lambda *a:cert['root_impacts'])
    with pytest.raises(ValueError):admission.validate_certificate(cert,ctx.source,ctx.source,ctx.data['plan']['edits'],
        provider=provider,checker_reference=checker)


def construction_fixture(tmp_path,monkeypatch,*,native_block=False,error_block=False,proof_state=None):
    import shutil
    isolate_financial_gate(monkeypatch)
    ctx,binding,scope,events=fixture(tmp_path);calls=[]
    checker=ctx.config[admission.SETTING]['checker']
    def prove(**kwargs):
        calls.append(('proof',kwargs))
        cert=fake_certificate(ctx,kwargs['goal'],kwargs['combined_input'],checker)
        if proof_state:cert.update(passed=False,blocking=True,state=proof_state,reason='Mock checker failure')
        return cert
    provider=SimpleNamespace(prove_scc_island_root_impacts=prove,
        validate_scc_island_root_certificate=lambda c,*a:c['root_impacts'])
    monkeypatch.setattr(admission,'load_v8_checker',lambda r:provider)
    monkeypatch.setattr(node,'validate_plan',lambda *a:{'native_error_candidates':[],'before_assertions_passed':True})
    changes=['First!A1','Second!A1','Downstream!C9']
    delta={'expected_change_count':3,'expected_changes':changes,'goal_sheets':['First','Second']}
    monkeypatch.setattr(node,'compare_workbooks',lambda *a:deepcopy(delta))
    monkeypatch.setattr(node,'evaluate_native_risk_guard',lambda d,*a,**k:calls.append(('native',d)) or
        {'state':'blocked' if native_block else 'clear','blocking':native_block,'issues':[]})
    monkeypatch.setattr(node,'probe_native_errors',lambda **k:calls.append(('native_error',k)) or
        {'state':'blocked' if error_block else 'clear','blocking':error_block,'problem_id':'Q04','candidates':[],'probes':[],'duration_ms':0})
    monkeypatch.setattr(node,'profile_workbook',lambda *a,**k:calls.append(('profile',k)) or {'fixture':True})
    def calculate(source,target):
        calls.append(('calculate',str(target)));shutil.copyfile(source,target);return target
    ctx.engine=SimpleNamespace(recalculate=calculate)
    return ctx,calls,delta


def test_opt_in_construct_keeps_complete_D_native_guards_and_final_artifacts(tmp_path,monkeypatch):
    ctx,calls,delta=construction_fixture(tmp_path,monkeypatch)
    source_before=ctx.source.read_bytes();result=node.SCCConstructNode().execute(ctx)
    assert [c[0] for c in calls]==['calculate','native','native_error','proof','profile']
    assert next(c[1] for c in calls if c[0]=='native')==delta['expected_changes']
    assert next(c[1] for c in calls if c[0]=='native_error')['required_delta']==delta['expected_changes']
    assert result['delta']==delta and ctx.source.read_bytes()==source_before
    assert result['construction_validation']['root_impact_validation']['actual_checker_LO_execution_count']==6
    assert len(result['root_impacts'])==2
    private=ctx.revision_dir/'private'
    assert all((private/name).is_file() for name in ('plan.json','edit_validation.json','expected_delta.json',
        'root_impacts.json','native_risk_guard.json','native_error_probe.json','scc_v8_roots_certificate.json'))
    assert (ctx.revision_dir/'public/profile.json').is_file()
    kwargs=next(c[1] for c in calls if c[0]=='proof')
    assert 'allow_constant_index_ancestors' not in kwargs


@pytest.mark.parametrize('guard',['native','native_error'])
def test_native_failure_cannot_reach_scc_proof(tmp_path,monkeypatch,guard):
    ctx,calls,_=construction_fixture(tmp_path,monkeypatch,native_block=guard=='native',error_block=guard=='native_error')
    with pytest.raises(TaskRejected):node.SCCConstructNode().execute(ctx)
    assert 'proof' not in [c[0] for c in calls]
    assert (ctx.revision_dir/'private/expected_delta.json').is_file()


@pytest.mark.parametrize('state,exception',[('execution_error',RuntimeError),('rejected',TaskRejected)])
def test_failed_scc_receipt_is_saved_without_falling_back_to_weaker_proof(tmp_path,monkeypatch,state,exception):
    ctx,calls,_=construction_fixture(tmp_path,monkeypatch,proof_state=state)
    with pytest.raises(exception):node.SCCConstructNode().execute(ctx)
    receipt=json.loads((ctx.revision_dir/'private/scc_v8_roots_certificate.json').read_text())
    assert receipt['state']==state and receipt['passed'] is False
    assert 'profile' not in [c[0] for c in calls]


def financial_fixture(tmp_path):
    """Schema fixture with fake execution records; never selected or certified."""
    from sheets_factory.task_adapters.lease_family import compare_exact_typed
    from sheets_factory.task_adapters.presentation_source import verify_formula_allowlist
    ctx,binding,scope,_=fixture(tmp_path)
    original=tmp_path/'original.xlsx';original.write_bytes(ctx.source.read_bytes());original_ref=ref(original)
    book=openpyxl.load_workbook(ctx.source);book['First']['D1']='Fixture presentation note';book.save(ctx.source);book.close()
    source_ref=ref(ctx.source);binding['source']=source_ref
    raw=tmp_path/'presentation_raw.xlsx';raw.write_bytes(ctx.source.read_bytes())
    first=tmp_path/'stable1.xlsx';first.write_bytes(ctx.source.read_bytes())
    second=tmp_path/'stable2.xlsx';second.write_bytes(ctx.source.read_bytes())
    scope['source']=original_ref
    # The standalone financial fixture transfers no zero formulas. Its scope
    # and receipts do not assert a usable economic task or a real engine run.
    scope['families'][1]['cells'].pop();scope['formula_slots']=2
    binding['scope_inventory']=dump(tmp_path/'scope.json',scope)
    audits={}
    for name in ('lease','programme','operating','holding','contingent'):
        audits[name]=dump(tmp_path/(name+'_audit.json'),{'workbook':original_ref,'passed':True,
            'checked_cells':1,'mismatches':[],'cell_checks':[]})
    original_manifest=dump(tmp_path/'original_manifest.json',{'local_path':str(original),
        'derived_workbook_sha256':original_ref['sha256'],'financial_audit_passed':True,
        'contingent_all_years_unique':True,'runtime':{'image_id':admission.IMAGE_ID},
        'financial_audits':{name:{'checked_cells':1} for name in audits}})
    binding['source_manifest']=dump(tmp_path/'source_manifest.json',{
        'status':'actually_verified_complete_financial_graph_presentation','local_path':str(ctx.source),
        'derived_workbook_sha256':source_ref['sha256'],'financial_audit_passed':True,
        'financial_validation_method':admission.TRANSFER_METHOD,
        'runtime':{'image_id':admission.IMAGE_ID}})
    presentation={'source':original_ref,'raw_presentation':ref(raw),'conversions':[],
        'public_note':{'sheet':'First','cell':'D1','value':'Fixture presentation note'}}
    presentation_ref=dump(tmp_path/'presentation.json',presentation)
    equality=dump(tmp_path/'equality.json',compare_exact_typed(original,ctx.source,public_note=presentation['public_note']))
    allowlist=dump(tmp_path/'allowlist.json',verify_formula_allowlist(original,ctx.source,[]))
    stable=dump(tmp_path/'stable.json',{'stable':True,'checks':{
        'goal_to_first':compare_exact_typed(ctx.source,first),'first_to_second':compare_exact_typed(first,second)}})
    transfer=dump(tmp_path/'transfer.json',{'method':admission.TRANSFER_METHOD,
        'original_source':original_ref,'presented_source':source_ref,'original_independent_audits':audits,
        'exact_typed_equivalence':equality,'formula_allowlist':allowlist,
        'new_independent_journal_execution_claimed':False,'old_audits_relabelled_as_new_source':False})
    calls=[]
    for input_file,output_file in ((raw,ctx.source),(ctx.source,first),(first,second)):
        calls.append({'input':ref(input_file),'output':ref(output_file),'completed':True,
            'image_id':admission.IMAGE_ID,'backend':'libreoffice_uno_docker','network':'none'})
    document={'kind':'actual_full_graph_presentation_financial_admission',
        'financial_validation_method':admission.TRANSFER_METHOD,'new_independent_journal_execution_claimed':False,
        'source':source_ref,'source_manifest':binding['source_manifest'],'scope_inventory':binding['scope_inventory'],
        'original_source':original_ref,'original_manifest':original_manifest,'original_independent_audits':audits,
        'presentation':presentation_ref,'exact_typed_equivalence':equality,'formula_allowlist':allowlist,
        'independent_zero_coverage':dump(tmp_path/'zero_coverage.json',[]),
        'engine_calls':calls,'actual_stability':stable,'financial_audit_transfer':transfer}
    binding['financial_admission']=dump(tmp_path/'financial_admission.json',document)
    return binding,document


def test_financial_schema_recomputes_exact_typed_equivalence_allowlist_and_stability(tmp_path):
    binding,document=financial_fixture(tmp_path)
    assert admission.validate_financial_admission(binding)==document


@pytest.mark.parametrize('defect',['offline_only','wrong_source','wrong_scope','missing_audit','changed_audit',
    'audit_findings','forged_equality','forged_allowlist','missing_call','wrong_runtime','broken_chain',
    'forged_stability','fresh_journal_claim','relabelled_audit','bool_zero'])
def test_financial_admission_cannot_use_offline_flags_or_unbound_transfer(tmp_path,defect):
    binding,document=financial_fixture(tmp_path)
    if defect=='offline_only':document['kind']='offline_preflight_only_not_a_certified_source'
    elif defect=='wrong_source':document['source']=document['original_source']
    elif defect=='wrong_scope':document['scope_inventory']=document['original_manifest']
    elif defect=='missing_audit':document['original_independent_audits'].pop('contingent')
    elif defect in ('changed_audit','audit_findings'):
        path=Path(document['original_independent_audits']['lease']['path']);data=json.loads(path.read_text())
        if defect=='changed_audit':data['workbook']=binding['source']
        else:data['mismatches']=[{'cell':'A1'}]
        document['original_independent_audits']['lease']=dump(path,data)
    elif defect in ('forged_equality','forged_allowlist'):
        key='exact_typed_equivalence' if defect=='forged_equality' else 'formula_allowlist'
        document[key]=dump(Path(document[key]['path']),{'passed':True})
    elif defect=='missing_call':document['engine_calls'].pop()
    elif defect=='wrong_runtime':document['engine_calls'][0]['image_id']='sha256:'+'0'*64
    elif defect=='broken_chain':document['engine_calls'][1]['input']=document['original_source']
    elif defect=='forged_stability':document['actual_stability']=dump(Path(document['actual_stability']['path']),{'stable':True})
    elif defect=='fresh_journal_claim':document['new_independent_journal_execution_claimed']=True
    elif defect=='relabelled_audit':
        path=Path(document['financial_audit_transfer']['path']);data=json.loads(path.read_text())
        data['old_audits_relabelled_as_new_source']=True;document['financial_audit_transfer']=dump(path,data)
    else:
        path=Path(document['presentation']['path']);data=json.loads(path.read_text())
        data['conversions']=[{'original_cached_value':False,'provided_value':0}]
        document['presentation']=dump(path,data)
    binding['financial_admission']=dump(Path(binding['financial_admission']['path']),document)
    with pytest.raises(ValueError):admission.validate_financial_admission(binding)


@pytest.mark.parametrize('mode,explicit',[('financial_modeling',True),('debugging',False)])
def test_ordinary_plan_delegates_priority_wrapper(tmp_path,monkeypatch,mode,explicit):
    ctx,*_=fixture(tmp_path);ctx.mode=mode
    if not explicit:ctx.data['finance_evidence']={}
    marker={'ordinary_priority':True};called=[]
    monkeypatch.setattr(admission.PriorityPlanNode,'execute',lambda self,c:called.append(c) or marker)
    assert admission.FullGraphSCCPlanNode().execute(ctx) is marker and called==[ctx]


def test_full_graph_adapter_without_explicit_activity_admission_never_replans(tmp_path,monkeypatch):
    ctx,*_=fixture(tmp_path);ctx.config={}
    monkeypatch.setattr(admission.PriorityPlanNode,'execute',lambda *a:pytest.fail('Must not silently replan the full source'))
    with pytest.raises(ValueError,match='explicit SCC'):admission.FullGraphSCCPlanNode().execute(ctx)


def install_compiler(ctx,binding,tmp_path,*,omit_root=False):
    plan=deepcopy(ctx.data['plan'])
    if omit_root:plan['edits'].pop()
    path=tmp_path/'compiler.py'
    path.write_text('def compile_complete_mutation(baseline, scope, policy):\n    return '+repr(plan)+'\n')
    binding['task_adapter']['implementation']=ref(path)
    ctx.config[admission.SETTING]['bindings']=dump(Path(ctx.config[admission.SETTING]['bindings']['path']),
        {'kind':'scc_activity_source_bindings','version':8,'sources':{ctx.data['source_id']:binding}})


def test_explicit_plan_compiles_all_roots_and_appends_new_source_audited_priority(tmp_path,monkeypatch):
    isolate_financial_gate(monkeypatch)
    ctx,binding,*_=fixture(tmp_path);install_compiler(ctx,binding,tmp_path)
    before=deepcopy(ctx.data['plan']);result=admission.FullGraphSCCPlanNode().execute(ctx)
    assert result['plan']['edits']==before['edits'] and ctx.data['plan']==before
    assert result['plan']['public_rules'][-1]==admission.append_rule(before)['public_rules'][-1]
    assert admission.FullGraphSCCPlanNode().execute(ctx)==result
    assert len(list(ctx.data['source_cache'].glob('scc_full_graph_plan_*.json')))==1


@pytest.mark.parametrize('defect',['old_timing_source','financial_context_missing','compiler_truncation','cache_tamper'])
def test_full_graph_compiler_cannot_borrow_old_source_audits_or_shrink_scope(tmp_path,monkeypatch,defect):
    isolate_financial_gate(monkeypatch)
    ctx,binding,*_=fixture(tmp_path);install_compiler(ctx,binding,tmp_path,omit_root=defect=='compiler_truncation')
    if defect=='old_timing_source':
        other=tmp_path/'old.xlsx';other.write_bytes(b'original source before new presentation')
        binding['public_input_priority_audit']=dump(Path(binding['public_input_priority_audit']['path']),{'source':ref(other)})
        ctx.config[admission.SETTING]['bindings']=dump(Path(ctx.config[admission.SETTING]['bindings']['path']),
            {'kind':'scc_activity_source_bindings','version':8,'sources':{ctx.data['source_id']:binding}})
    elif defect=='financial_context_missing':ctx.data['finance_evidence'].pop('full_graph_financial_admission')
    elif defect=='cache_tamper':
        admission.FullGraphSCCPlanNode().execute(ctx)
        path=next(ctx.data['source_cache'].glob('*.json'));saved=json.loads(path.read_text())
        saved['plan']['edits'].pop();dump(path,saved)
    with pytest.raises(ValueError):admission.FullGraphSCCPlanNode().execute(ctx)


def probe_fixture(tmp_path,monkeypatch):
    isolate_financial_gate(monkeypatch)
    ctx,binding,*_=fixture(tmp_path);checker=ctx.config[admission.SETTING]['checker']
    cert=fake_certificate(ctx,ctx.source,ctx.source,checker)
    provider=SimpleNamespace(validate_scc_island_root_certificate=lambda c,*a:c['root_impacts'])
    monkeypatch.setattr(admission,'load_v8_checker',lambda r:provider)
    controls={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    delta={'expected_change_count':3,'expected_changes':['First!A1','Second!A1','Downstream!C9']}
    import sheets_factory.workbook as workbook
    monkeypatch.setattr(workbook,'compare_workbooks',lambda *a:deepcopy(delta))
    instruction=tmp_path/'instruction.md';instruction.write_text('Offline probe fixture\n')
    probe={'kind':'scc_v8_full_graph_activity_probe','passed':True,'qualified':False,
        'source_manifest':binding['source_manifest'],'baseline':binding['source'],'goal':binding['source'],
        'policy':binding['task_adapter']['policy'],'policy_canonical_sha256':binding['task_adapter']['policy_sha256'],
        'adapter_implementation':binding['task_adapter']['implementation'],'scope_inventory':binding['scope_inventory'],
        'actual_plan':dump(tmp_path/'plan.json',ctx.data['plan']),'root_count':2,
        'scc_certificate':dump(tmp_path/'scc_certificate.json',cert),'allow_constant_index_ancestors':False,
        'public_input':binding['source'],'public_instruction':ref(instruction),
        'local_controls':controls,'local_control_receipt':dump(tmp_path/'controls.json',{k:{'reward':v} for k,v in controls.items()}),
        'expected_delta':dump(tmp_path/'delta.json',delta),'expected_change_count':3,
        'revision_hash':hashlib.sha256(ctx.source.read_bytes()+instruction.read_bytes()).hexdigest()}
    entry={'sha256':binding['source']['sha256'],'local_path':str(ctx.source),'modes':['debugging'],
        'source_manifest':binding['source_manifest'],'task_adapter':binding['task_adapter'],'scc_activity_binding':binding}
    return entry,probe,checker


def test_scc_probe_validates_five_actual_receipts_and_recomputes_full_D(tmp_path,monkeypatch):
    entry,probe,checker=probe_fixture(tmp_path,monkeypatch)
    result=admission.validate_scc_activity_probe(entry,dump(tmp_path/'probe.json',probe),checker_reference=checker)
    assert result['actual_checker_LO_executions']==6 and result['complete_D_recomputed_without_LO']
    assert not result['quality_recovery_difficulty_certified'] and not result['financial_source_correctness_certified']


@pytest.mark.parametrize('defect',['legacy_dag','goal','summary_only_controls','delta_truncation','revision',
    'qualified','scope','index_policy','edit_digest'])
def test_scc_probe_does_not_accept_legacy_or_incomplete_evidence(tmp_path,monkeypatch,defect):
    entry,probe,checker=probe_fixture(tmp_path,monkeypatch)
    if defect=='legacy_dag':
        cert=admission.read(probe['scc_certificate']);cert['version']=6
        probe['scc_certificate']=dump(Path(probe['scc_certificate']['path']),cert)
    elif defect=='goal':probe['goal']=probe['public_instruction']
    elif defect=='summary_only_controls':
        probe['local_control_receipt']=dump(Path(probe['local_control_receipt']['path']),{'oracle':{'reward':1}})
    elif defect=='delta_truncation':
        probe['expected_delta']=dump(Path(probe['expected_delta']['path']),{'expected_change_count':2,'expected_changes':['First!A1','Second!A1']})
    elif defect=='revision':probe['revision_hash']='0'*64
    elif defect=='qualified':probe['qualified']=True
    elif defect=='scope':probe['scope_inventory']=probe['actual_plan']
    elif defect=='index_policy':probe['allow_constant_index_ancestors']=True
    else:entry['scc_activity_binding']['edits_sha256']='0'*64
    with pytest.raises(ValueError):admission.validate_scc_activity_probe(entry,dump(tmp_path/'probe.json',probe),checker_reference=checker)


def admitted_seed_fixture(tmp_path,monkeypatch):
    entry,probe,checker=probe_fixture(tmp_path,monkeypatch)
    entry['source_kind']=admission.SOURCE_KIND
    entry['activity_probe']=dump(tmp_path/'probe.json',probe)
    setting={'enabled':True,'version':8,'upstream_construction':admission.upstream_binding(),'checker':checker,
        'bindings':dump(tmp_path/'source_bindings.json',{'kind':'scc_activity_source_bindings','version':8,
            'sources':{entry['sha256']:entry['scc_activity_binding']}})}
    proof=admission.validate_full_graph_seed(entry,setting)
    entry['finance_evidence']={'task_adapter':entry['task_adapter'],
        'full_graph_financial_admission':entry['scc_activity_binding']['financial_admission'],'audited_source_binding':proof}
    return entry,setting,proof


def test_full_factory_seed_restores_only_audited_new_source_normalized_path(tmp_path,monkeypatch):
    entry,setting,proof=admitted_seed_fixture(tmp_path,monkeypatch)
    entry['survey']={'normalized_path':'/untrusted/other.xlsx'}
    monkeypatch.setattr(admission.FactoryPipeline,'load_seeds',lambda self:[entry])
    factory=object.__new__(admission.SCCActivityFactory);factory.config={admission.SETTING:setting};factory.legacy_validator=None
    seeds=factory.load_seeds()
    assert seeds[0]['survey']['normalized_path']==proof['workbook']['path']
    assert seeds[0]['survey']['source_sha256']==entry['sha256']


@pytest.mark.parametrize('defect',['missing_probe','source_kind','wrong_adapter_context','wrong_financial_context',
    'wrong_admission','mode','variant_bool','index_bool'])
def test_factory_cannot_admit_unverified_presentation_or_adapter_on_legacy_source(tmp_path,monkeypatch,defect):
    entry,setting,proof=admitted_seed_fixture(tmp_path,monkeypatch)
    if defect=='missing_probe':entry.pop('activity_probe')
    elif defect=='source_kind':entry['source_kind']='legacy'
    elif defect=='wrong_adapter_context':entry['finance_evidence']['task_adapter']={}
    elif defect=='wrong_financial_context':entry['finance_evidence']['full_graph_financial_admission']={}
    elif defect=='wrong_admission':entry['finance_evidence']['audited_source_binding']={}
    elif defect=='mode':entry['modes']=['financial_modeling']
    elif defect=='variant_bool':entry['variant']=False
    else:setting['allow_constant_index_ancestors']=0
    monkeypatch.setattr(admission.FactoryPipeline,'load_seeds',lambda self:[entry])
    factory=object.__new__(admission.SCCActivityFactory);factory.config={admission.SETTING:setting}
    factory.legacy_validator=lambda seed:pytest.fail('Invalid adapter must not use legacy admission')
    with pytest.raises((ValueError,KeyError)):factory.load_seeds()


def test_legacy_factory_seed_keeps_original_financial_validator(tmp_path,monkeypatch):
    ctx,*_=fixture(tmp_path);proof={'workbook':ref(ctx.source),'legacy_fixture':True}
    seed={'sha256':ref(ctx.source)['sha256'],'source_kind':'legacy',
        'finance_evidence':{'audited_source_binding':proof},'survey':{'normalized_path':'/untrusted'}}
    monkeypatch.setattr(admission.FactoryPipeline,'load_seeds',lambda self:[seed])
    factory=object.__new__(admission.SCCActivityFactory);factory.config={};calls=[]
    factory.legacy_validator=lambda entry:calls.append(entry) or proof
    assert factory.load_seeds()[0]['survey']['normalized_path']==str(ctx.source.resolve()) and calls==[seed]


def test_factory_wraps_existing_phase_then_checks_exact_baseline_identity(tmp_path,monkeypatch):
    ctx,*_=fixture(tmp_path);calls=[];marker=object()
    monkeypatch.setattr(admission.FactoryPipeline,'run_phase',lambda self,c,p:calls.append((c,p)) or marker)
    factory=object.__new__(admission.SCCActivityFactory)
    assert factory.run_phase(ctx,'revision') is marker and calls==[(ctx,'revision')]
    ctx.data['source_id']='0'*64
    with pytest.raises(ValueError,match='Normalized baseline'):factory.run_phase(ctx,'revision')
