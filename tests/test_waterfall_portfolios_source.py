from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import shutil
from xml.etree import ElementTree as X
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import schema


ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    path=ROOT/'scripts/build_waterfall_portfolios_source.py'
    loader=importlib.util.spec_from_file_location('_test_waterfall_source',path)
    value=importlib.util.module_from_spec(loader);loader.loader.exec_module(value)
    return value


def store(module,path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');return module.reference(path)


def raw_toy():
    f={'id':'F001','number':1,'type':'income_credit','layout':'annual_columns','fund_ledger_sign':'signed_cash_uses',
        'lp1_share_bp':3500,'preferred_rate_bp':600,'compound_unpaid_preference':False,'base_gp_carry_bp':1000,
        'promote_gp_bp':[2000,3000,4000],'lp_distribution_multiple_threshold_bp':[12500,17500],
        'call_month':1,'commitment_pence':1000,**{k:0 for k in schema.OPENING_FIELDS},'scenarios':[]}
    f.update(opening_investment_book_cost_pence=101,opening_unreturned_capital_pence=101,
             opening_cumulative_lp_paid_in_pence=101)
    f['scenarios']=[{'id':'BASE','periods':[{'year':2025,'call_date':'2025-01-01',
        **{k:0 for k in schema.PERIOD_MONEY_FIELDS},'realization_receipts_pence':101}]}]
    return {'kind':schema.SPEC_KIND,'version':1,'dimension_mode':'toy','contract':{
        'path':str(schema.CONTRACT_PATH),'sha256':schema.CONTRACT_SHA256,'bytes':15174},
        'contract_sha256':schema.CONTRACT_SHA256,'seed':1,'years':[2025],'historical_years':[2025],
        'scenario_ids':['BASE'],'funds':[f]}


@pytest.fixture
def data(module,tmp_path):
    raw=raw_toy();schema.validate_spec(raw);key='F001/BASE/2025'
    row={k:0 for k in schema.ROW_FIELDS}
    for k in ('realization_receipts','cash_before_distribution','available_cash','opening_unreturned_capital',
              'cumulative_lp_paid_in','capital_entitlement','capital_paid','lp_total_distribution',
              'fund_total_distribution','cumulative_lp_distributions'):row[k]=101
    row.update(lp1_distribution=35,lp2_distribution=66,lp1_net_cashflow=35,lp2_net_cashflow=66,
        lp_distribution_multiple={'numerator':101,'denominator':101},capital_and_pref_shortfall=False)
    result={'kind':schema.RESULT_KIND,'version':1,'implementation':'A','specification_sha256':schema.canonical_sha256(raw),
        'row_order':[key],'rows':{key:row},'aggregate_order':['BASE/2025'],
        'aggregates':{'BASE/2025':{f:row[f] for f in schema.AGGREGATE_FIELDS}},'proof':{'fixture':True}}
    other=deepcopy(result);other['implementation']='B'
    a=store(module,tmp_path/'A.json',result);b=store(module,tmp_path/'B.json',other)
    comparison={'kind':'complete_stored_independent_waterfall_A_B_comparison','passed':True,'differences':[],
        'same_raw_no_resampling':True,'new_financial_forward_calls_by_comparator':0,'A':a,'B':b,
        'specification':store(module,tmp_path/'raw.json',raw),'row_count':1,'aggregate_count':1,
        'integer_pence_fields_compared':56,'integer_aggregate_pence_fields_compared':20,
        'LP_ratio_pairs_compared':1,'boolean_fields_compared':1}
    financial={};index=1
    def add(field,projection,**extra):
        nonlocal index
        point=f'Ledger!A{index}';index+=1
        financial[point]={'sheet':'Ledger','cell':point.split('!')[1],'formula':'=0','row_key':key,
            'field':field,'projection':projection,'sign':1,**extra}
    for field in schema.ROW_FIELDS:
        add(field,'pence');add(field,'GBP')
    for metric,field in module.USES.items():
        for unit in ('pence','GBP'):add(field,'presentation_sign',metric=metric,unit=unit,sign=-1)
    add('lp_distribution_multiple','ratio2dp');add('capital_and_pref_shortfall','bool')
    for field in schema.AGGREGATE_FIELDS:
        for projection in ('pence','GBP'):
            point=f'Ledger!A{index}';index+=1
            financial[point]={'sheet':'Ledger','cell':point.split('!')[1],'formula':'=0','aggregate_key':'BASE/2025',
                'field':field,'projection':projection,'sign':1}
    bindings={'financial':financial,'provided':{}}
    return SimpleNamespace(raw=raw,A=result,B=other,comparison=comparison,bindings=bindings)


def make_book(module,tmp_path,data):
    path=tmp_path/'fixture.xlsx';book=openpyxl.Workbook();book.active.title='Ledger';book.create_sheet('Facts');book.create_sheet('Read Me')
    for point,record in data.bindings['financial'].items():book[record['sheet']][record['cell']]=record['formula']
    provided=data.bindings['provided']
    for i,path_keys in enumerate(sorted(module._fact_paths(data.raw['funds'],('funds',)),key=str),1):
        value=module._path_value(data.raw,list(path_keys));cell=f'A{i}';book['Facts'][cell]=value
        provided['Facts!'+cell]={'sheet':'Facts','cell':cell,'value':value,'path':list(path_keys)}
    for i,policy in enumerate(schema.contract()['business_policies'],1):
        cell=f'A{i}';book['Read Me'][cell]=policy
        provided['Read Me!'+cell]={'sheet':'Read Me','cell':cell,'value':policy,'contextkind':'policy'}
    book.save(path);book.close();return path


def cache_book(module,source,target,expected,*,numeric_bool=False):
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(source) as a,ZipFile(target,'w',ZIP_DEFLATED) as b:
        for item in a.infolist():
            content=a.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':
                root=X.fromstring(content)
                for cell in root.iter(ns+'c'):
                    if cell.find(ns+'f') is None:continue
                    wanted=expected['Ledger!'+cell.get('r')]
                    for value in list(cell):
                        if value.tag in (ns+'v',ns+'is'):cell.remove(value)
                    v=X.SubElement(cell,ns+'v')
                    if wanted['type']=='boolean':
                        cell.set('t','n' if numeric_bool else 'b');v.text='1' if wanted['value'] else '0'
                    else:cell.set('t','n');v.text=wanted['value']
                content=X.tostring(root)
            b.writestr(item,content)


def test_frozen_ancestor_private_namespace_and_hardware_are_preserved(module):
    assert module.reference(module.ANCESTOR)['sha256']==module.ANCESTOR_SHA
    assert module.execute_prepared.__globals__ is module._N
    assert module.execute_prepared.__globals__ is not module.__dict__
    assert module._N['KIND']==module.KIND and module._N['SOURCE_KIND']==module.SOURCE_KIND
    profile,values=module.runtime(module.PROFILE)
    assert profile['path']==str(module.PROFILE)
    assert values['image']['id']=='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
    assert values['docker_resources']['source']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
    assert values['timeouts']['workbook_file_seconds']==600


def test_upstream_byte_drift_rejects_without_modifying_frozen_driver(module,tmp_path,monkeypatch):
    copied=tmp_path/'changed_ancestor.py';copied.write_bytes(module.ANCESTOR.read_bytes()+b'\n')
    monkeypatch.setattr(module,'ANCESTOR',copied)
    with pytest.raises(ValueError,match='frozen genuine source3'):module._load_ancestor()


def test_whole_stored_results_and_all_170_typed_physical_projections(module,data):
    a,b=module.compare_stored(data.raw,data.comparison)
    expected=module.project_expected(data.raw,data.bindings,a,b)
    assert len(expected)==170
    for point,e in data.bindings['financial'].items():
        if e['projection']=='presentation_sign' and e['field']=='capital_paid':
            assert expected[point]=={'type':'number','value':'-101' if e['unit']=='pence' else '-1.01'}
        elif e['projection']=='bool':assert expected[point]=={'type':'boolean','value':False}
        elif e['projection']=='ratio2dp':assert expected[point]=={'type':'number','value':'1'}


@pytest.mark.parametrize('mutation',[
    lambda r:r['row_order'].clear(),lambda r:r['rows']['F001/BASE/2025'].pop('capital_paid'),
    lambda r:r['rows']['F001/BASE/2025'].update(capital_paid=True),
    lambda r:r['rows']['F001/BASE/2025'].update(capital_paid=100),
    lambda r:r['rows']['F001/BASE/2025'].update(capital_and_pref_shortfall=0),
    lambda r:r['rows']['F001/BASE/2025'].update(lp_distribution_multiple={'numerator':1,'denominator':1}),
    lambda r:r['aggregates']['BASE/2025'].update(capital_paid=0)])
def test_stored_pass_flag_never_replaces_full_coverage_and_exact_values(module,data,tmp_path,mutation):
    mutated=deepcopy(data.B);mutation(mutated);data.comparison['B']=store(module,tmp_path/'mutatedB.json',mutated)
    with pytest.raises((ValueError,KeyError)):module.compare_stored(data.raw,data.comparison)


@pytest.mark.parametrize('mutation',[
    lambda m:m.pop(next(iter(m))),
    lambda m:next(v for v in m.values() if v['projection']=='pence').update(sign=-1),
    lambda m:next(v for v in m.values() if v['projection']=='presentation_sign').update(sign=1),
    lambda m:next(v for v in m.values() if v['projection']=='presentation_sign').update(metric='unknown'),
    lambda m:next(v for v in m.values() if v['projection']=='ratio2dp').update(projection='pence')])
def test_projection_omission_wrong_sign_unknown_alias_and_ratio_relabel_reject(module,data,mutation):
    mutation(data.bindings['financial'])
    with pytest.raises((ValueError,KeyError)):module.project_expected(data.raw,data.bindings,data.A,data.B)


def test_exact_ratio_half_up_and_non_numeric_boolean(module,data):
    for result in (data.A,data.B):
        result['rows']['F001/BASE/2025']['lp_distribution_multiple']={'numerator':201,'denominator':200}
    expected=module.project_expected(data.raw,data.bindings,data.A,data.B)
    ratio=next(p for p,r in data.bindings['financial'].items() if r['projection']=='ratio2dp')
    boolean=next(p for p,r in data.bindings['financial'].items() if r['projection']=='bool')
    assert expected[ratio]=={'type':'number','value':'1.01'}
    assert expected[boolean]=={'type':'boolean','value':False}


def test_renderer_copy_is_bound_alongside_original_raw_without_reference_substitution(module,data,tmp_path):
    original=data.comparison['specification']
    copied=store(module,tmp_path/'renderer_specification_copy.json',data.raw)
    candidate={'specification':copied,'specification_sha256':schema.canonical_sha256(data.raw)}
    public,bound=module._original_raw(candidate,data.comparison)
    assert public==data.raw and bound==original and copied!=original
    mutated=deepcopy(data.raw);mutated['funds'][0]['preferred_rate_bp']+=1
    candidate['specification']=store(module,tmp_path/'different_specification.json',mutated)
    with pytest.raises(ValueError,match='once-frozen'):module._original_raw(candidate,data.comparison)


def test_real_toy_definition_full_cache_clearance_and_typed_native_projection(module,data,tmp_path):
    source=make_book(module,tmp_path,data);definition=module.source_definition(source,data.bindings,data.raw)
    expected=module.project_expected(data.raw,data.bindings,data.A,data.B)
    assert len(definition['formulas'])==170 and definition['raw_fact_paths_checked']>20
    cold=tmp_path/'cold.xlsx';module.clear_all_formula_caches(source,cold)
    assert module._physical_empty(cold)==170
    assert module._N['audit_workbook'](cold,definition,expected,empty_caches=True)['passed'] is True
    actual=tmp_path/'native_fixture.xlsx';cache_book(module,cold,actual,expected)
    assert module._N['audit_workbook'](actual,definition,expected)['passed'] is True
    wrong=tmp_path/'wrongbool.xlsx';cache_book(module,cold,wrong,expected,numeric_bool=True)
    assert module._N['audit_workbook'](wrong,definition,expected)['passed'] is False
    with pytest.raises(ValueError,match='physical formula cache'):module._physical_empty(actual)


def test_all_raw_facts_and_policy_text_are_required(module,data,tmp_path):
    source=make_book(module,tmp_path,data)
    point=next(p for p,r in data.bindings['provided'].items() if 'path' in r)
    value=data.bindings['provided'].pop(point)
    with pytest.raises(ValueError):module.source_definition(source,data.bindings,data.raw)
    data.bindings['provided'][point]=value;value['path']=['funds',0,'commitment_pence']
    with pytest.raises(ValueError):module.source_definition(source,data.bindings,data.raw)


def test_noncircular_gate_rejects_iteration_enablement(module,data,tmp_path):
    source=make_book(module,tmp_path,data);book=openpyxl.load_workbook(source);book.calculation.iterate=True;book.save(source);book.close()
    with pytest.raises(ValueError,match='noncircular'):module.source_definition(source,data.bindings,data.raw)


def test_legacy_pass_and_fabricated_forward_pass_cannot_admit(module,tmp_path):
    old=store(module,tmp_path/'old.json',{'kind':'independently_checked_equity_income_group_iterative_source','version':1,'passed':True})
    with pytest.raises(ValueError):module.validate_source(old)
    fake=store(module,tmp_path/'fakeA.json',{'kind':'complete_single_original_waterfall_independent_A_forward','version':1,'passed':True})
    evidence={'forward_A':fake,'forward_B':fake,'comparison':fake}
    with pytest.raises((KeyError,ValueError)):module._forward_evidence(evidence,{})


def test_prepare_ui_precedes_cold_failure_and_preserves_failure_without_services(module,tmp_path,monkeypatch):
    seen=[]
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):seen.append('panel');return 'http://127.0.0.1:0/'
        def stop(self):seen.append('closed')
    monkeypatch.setitem(module._N,'DashboardServer',Server)
    original=module.read
    def read(value):seen.append('cold');return {'kind':'wrong_family','version':1}
    monkeypatch.setattr(module,'read',read)
    out=tmp_path/'source'
    with pytest.raises(ValueError):module.prepare(tmp_path/'never_read.xlsx',out,independent_comparison='unused',forward_A='unused',forward_B='unused')
    assert seen[0]=='panel' and 'cold' in seen and seen[-1]=='closed'
    assert (out/'preparation_failure.json').exists() and not (out/'preparation.json').exists()
    assert not list(out.glob('*.xlsx'))
    assert (out/'prepare_audit/run.sqlite').exists()


def test_run_ui_precedes_genuine_cold_failure_and_zero_calls_retained(module,tmp_path,monkeypatch):
    f={'kind':module.KIND,'version':1,'specification':{},'specification_sha256':'fixture','bindings':{}}
    store(module,tmp_path/'preparation.json',f);seen=[]
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):seen.append('panel');return 'http://127.0.0.1:0/'
        def stop(self):seen.append('closed')
    def cold(output):seen.append('cold');raise ValueError('mock genuine cold gate failure')
    monkeypatch.setitem(module._N,'DashboardServer',Server);monkeypatch.setitem(module._N,'validate_prepared',cold)
    with pytest.raises(RuntimeError,match='preserve'):module.execute_prepared(tmp_path)
    assert seen[:2]==['panel','cold'] and seen[-1]=='closed'
    terminal=json.loads((tmp_path/'source_manifest.json').read_text())
    assert terminal['passed'] is False and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==0
    assert terminal['new_financial_forwards']==0 and terminal['memoized_independent_ledgers'] is True
    assert terminal['qualified'] is terminal['normal_all12_QA_passed'] is False


def test_actual_lifecycle_three_calls_and_two_stabilities_mocked_with_real_audit(module,tmp_path,monkeypatch):
    cold=tmp_path/'cold.xlsx';cold.write_bytes(b'explicit pure fixture, never native')
    f={'kind':module.KIND,'version':1,'specification':{},'specification_sha256':'fixture','bindings':{},
        'cold_start':module.reference(cold),'runtime_profile':{'path':str(module.PROFILE)}}
    f['definition']=store(module,tmp_path/'def.json',{})
    f['expected']=store(module,tmp_path/'expected.json',{})
    f['independent_comparison']=store(module,tmp_path/'comparison.json',{})
    store(module,tmp_path/'preparation.json',f);seen=[];history=[];calls=[]
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):seen.append('panel');return 'http://127.0.0.1:0/'
        def stop(self):pass
    class Engine:
        def __init__(self,*args,**kwargs):pass
        def ensure_image(self):seen.append('image')
        def recalculate(self,source,target):
            calls.append((str(source),str(target)));shutil.copyfile(source,target)
            history.append('owned_fixture_'+str(len(calls)));return target
        def metadata(self):return {'actual_resource_receipts':history}
    def validate(output):seen.append('cold');return f
    def validate_call(call,record,frozen):return {'container_id':str(call['index'])*64,'terminal':{'fixture':True}}
    monkeypatch.setitem(module._N,'DashboardServer',Server);monkeypatch.setitem(module._N,'validate_prepared',validate)
    monkeypatch.setitem(module._N,'_crosscheck_prepared',lambda frozen:({},{}))
    monkeypatch.setitem(module._N,'spec',SimpleNamespace(validate=lambda x:x))
    read_original=module._N['read']
    monkeypatch.setitem(module._N,'read',lambda value:{} if value=={} else read_original(value))
    monkeypatch.setitem(module._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setitem(module._N,'validate_call',validate_call)
    monkeypatch.setitem(module._N,'audit_workbook',lambda *args,**kwargs:{'passed':True,'fixture_only':True})
    monkeypatch.setitem(module._N,'compare_typed',lambda *args,**kwargs:{'passed':True,'whole_populated_grid_compared':True,'fixture_only':True})
    monkeypatch.setitem(module._N,'owned_absence',lambda actual:{'all_owned_containers_absent':True,'daemon_reachable':True,'fixture_only':True})
    terminal_ref=module.execute_prepared(tmp_path);terminal=read_original(terminal_ref)
    assert seen.index('panel')<seen.index('cold')<seen.index('image')
    assert len(calls)==3 and calls[0][0]==str(cold)
    assert calls[1][0]==calls[0][1] and calls[2][0]==calls[1][1]
    assert terminal['actual_LO_calls_completed']==terminal['actual_LO_calls_started']==3
    assert {'source1_to_source2','source2_to_source3','cleanup'}<=set(terminal['records'])
    assert terminal['source']==module.reference(tmp_path/'source3.xlsx')
    assert terminal['normal_all12_QA_passed'] is terminal['qualified'] is False
    assert (tmp_path/'audit/run.sqlite').exists()
