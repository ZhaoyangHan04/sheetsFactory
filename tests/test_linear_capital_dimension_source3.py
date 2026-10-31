"""Pure preparation boundaries and mocked three-pass source lifecycle."""
from copy import deepcopy
import importlib.util,json,re,socket,subprocess
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.workbook import linear_capital_dimension_probe as probe
from test_linear_capital_portfolio_ledger import fixture as hand_toy
from test_linear_capital_optimization_runtime import services

ROOT=Path(__file__).resolve().parents[1]
definition=importlib.util.spec_from_file_location('_dimension_source3_test_entry',ROOT/'scripts/build_linear_capital_dimension_source.py')
entry=importlib.util.module_from_spec(definition);definition.loader.exec_module(entry)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('No actual service/native process is permitted in source3 tests')
 monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
 monkeypatch.setattr(socket,'create_connection',forbidden)


@pytest.fixture(params=[720,1080])
def proof(request,tmp_path,monkeypatch):
 n=request.param;e=entry.source(n);public=probe.bundle(n).catalog.build_spec()
 original=e.write(tmp_path/'input_contract.json',public);ancestor=e.write(tmp_path/'reference_raw_contract.json',public)
 plan={pid:int(i==0)for i,pid in enumerate(public['project_ids'])}
 value={'kind':f'linear_capital_n{n}_SCIP3600_best_runner_reference','version':3,'passed':True,'specification':ancestor,
  'specification_sha256':e.spec.canonical_sha256(public),'winner_plan':plan,'unique_best':True,'gap_pence':1,
  'winner_objective_pence':101,'runner_objective_pence':100,'selected_project_count':1,
  'selection_density_not_required':True,'solver_status_is_not_formal_certificate':True}
 artifact=e.write(tmp_path/'unit_mock_reference.json',value);seen=[]
 def validate(record):seen.append(record);return value
 monkeypatch.setattr(entry.references,'experiment',lambda size:SimpleNamespace(KIND=f'linear_capital_n{size}_SCIP3600_best_runner_reference',validate_completed=validate))
 monkeypatch.setattr(e,'_output',lambda path,**kwargs:Path(path))
 def forbidden(*args,**kwargs):pytest.fail('Pure preparation must not emit or calculate')
 monkeypatch.setattr(e.excel,'emit_workbook',forbidden);monkeypatch.setattr(e,'ResourceLibreOfficeEngine',forbidden)
 return n,e,public,original,artifact,value,seen


def test_genuine_provider_is_called_and_complete_fixed_contract_preparation_emits_nothing(proof,tmp_path):
 n,e,public,original,artifact,value,seen=proof;out=tmp_path/'source'
 result=e.read(e.prepare(original['path'],artifact['path'],out))
 assert seen==[artifact] and result['kind']==f'prepared_linear_capital_n{n}_native_source3'
 assert result['source_workbook_materialized'] is False and result['LO_calls']==result['optimizer_calls']==result['additional_financial_forwards']==0
 assert not list(out.rglob('*.xlsx')) and result['winner_plan']==value['winner_plan']
 frozen,actual,_=e.validate_prepared(out);assert frozen==result and actual==public
 assert e.SOURCE_KIND==f'independently_verified_linear_capital_n{n}_native_source3'
 assert not hasattr(e,'NO_SOURCE_ADMISSION')


@pytest.mark.parametrize('damage',['pending','FEASIBLE','missing_runner','old_kind','wrong_dimension','changed_raw','profile_caps'])
def test_partial_or_rebound_proofs_reject_before_any_allocation_or_services(proof,tmp_path,monkeypatch,damage):
 n,e,public,original,artifact,value,seen=proof;input_path=Path(original['path']);profile=e.DEFAULT_PROFILE
 if damage in ('pending','FEASIBLE'):value['passed']=False
 elif damage=='missing_runner':
  def reject(record):raise ValueError('Genuine full-winner-excluded runner not OPTIMAL')
  monkeypatch.setattr(entry.references,'experiment',lambda size:SimpleNamespace(KIND=value['kind'],validate_completed=reject))
 elif damage=='old_kind':value['kind']='linear_capital_scaled_producer16_best_runner_dual_financial_reference'
 elif damage=='wrong_dimension':public['kind']=probe.bundle(1080 if n==720 else 720).spec.SPEC_KIND;input_path.write_text(json.dumps(public))
 elif damage=='changed_raw':public['projects'][0]['bank_rate_bp']+=1;input_path.write_text(json.dumps(public))
 elif damage=='profile_caps':
  policy=entry.support.load_runtime_profile(profile);policy['limits']['source_physical_formulas']+=1
  profile=tmp_path/'changed_profile.yaml';profile.write_text(entry.support.yaml.safe_dump(policy))
 if damage in ('pending','FEASIBLE','old_kind'):Path(artifact['path']).write_text(json.dumps(value))
 out=tmp_path/'rejected'
 with pytest.raises(ValueError):e.prepare(input_path,artifact['path'],out,profile=profile)
 assert not out.exists()


def test_cache_clearance_preserves_every_formula_literal_style_and_other_zip_member(tmp_path):
 e=entry.source(720);raw=tmp_path/'seeded_unit.xlsx';seeded=tmp_path/'unit_seeded_zip.xlsx';cold=tmp_path/'cold.xlsx'
 book=openpyxl.Workbook();s=book.active;s['A1']='=1+2';s['A2']='="text"';s['A3']='=TRUE()';s['B1']='Provided text';s['B2']=37
 s['B2'].number_format='#,##0.00';s['B2'].font=openpyxl.styles.Font(color='FF0000');book.save(raw);book.close()
 with ZipFile(raw)as source,ZipFile(seeded,'x')as output:
  for info in source.infolist():
   data=source.read(info.filename)
   if info.filename=='xl/worksheets/sheet1.xml':
    data,count=re.subn(rb'<v\s*(?:/>|>\s*</v>)',b'<v>123</v>',data);assert count==3
   output.writestr(info,data)
 with pytest.raises(ValueError,match='cache must be absent'):entry.cache_census(seeded)
 record=e.clear_all_formula_caches(seeded,cold)
 assert record['all_formula_caches_cleared']==3 and record['remaining_formula_cache_elements']==0
 assert record['financial_formula_or_literal_edits']==0 and record['native_calculation_claimed'] is False
 with ZipFile(seeded)as left,ZipFile(cold)as right:
  assert left.namelist()==right.namelist()
  for name in left.namelist():
   a,b=left.read(name),right.read(name)
   if name.startswith('xl/worksheets/'):
    a=re.sub(rb'<v>123</v>',b'',a)
   assert a==b
 assert entry.cache_census(cold)==3


def fill_caches(source,destination,values):
 """Test-only synthetic cached output; never native/source evidence."""
 names={'ContractNotes':1}  # Worksheet order is resolved from the emitted package.
 book=openpyxl.load_workbook(source,read_only=True,data_only=False)
 try:names={f'xl/worksheets/sheet{i+1}.xml':title for i,title in enumerate(book.sheetnames)}
 finally:book.close()
 with ZipFile(source)as original,ZipFile(destination,'x')as output:
  for info in original.infolist():
   data=original.read(info.filename)
   if info.filename in names:
    tree=ET.fromstring(data)
    for cell in tree.findall('.//{*}c'):
     if cell.find('{*}f')is None:continue
     old=cell.find('{*}v')
     if old is not None:cell.remove(old)
     value=values[names[info.filename],cell.attrib['r']]
     if value is not None:
      v=ET.SubElement(cell,'{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v');v.text=str(value)
    data=ET.tostring(tree)
   output.writestr(info,data)


@pytest.mark.parametrize('n',[720,1080])
@pytest.mark.parametrize('fault',[None,'first_audit','second_audit','cleanup_unknown'])
def test_mocked_source3_runs_three_chained_full_audits_two_stabilities_once(n,fault,tmp_path,monkeypatch):
 e=entry.source(n);public=hand_toy();public.update(kind=probe.bundle(n).spec.SPEC_KIND,version=3)
 b=probe.bundle(n);winner={'P001':1};runner={'P001':0};a,c=b.A.simulate_universe(public),b.B.simulate_universe(public)
 validation=b.comparison.compare_plans(public,a,c,[{'id':'winner','plan':winner},{'id':'runner','plan':runner}],require_feasible=True)
 assert validation['passed'] is True
 out=tmp_path/'explicit_mock_source_lifecycle';out.mkdir();spec=e.write(out/'specification.json',public)
 refs={side:e.write(out/('universe_'+side+'.json'),value)for side,value in [('A',a),('B',c)]}
 dummy=e.write(out/'unit_mock_only.json',{'mock_boundary':True})
 proof={'universe_A':refs['A'],'universe_B':refs['B'],'reference_validation':e.write(out/'plan_comparison.json',validation),
  'winner_plan':winner,'winner_objective_pence':validation['plans'][0]['A']['objective_pence'],'financial_crosscheck':dummy}
 frozen={'private_specification':spec,'independent_reference':dummy,'winner_plan':winner,'winner_objective_pence':proof['winner_objective_pence'],
  'runtime_profile':e.reference(e.DEFAULT_PROFILE),'runtime_profile_value':entry.support.load_runtime_profile(e.DEFAULT_PROFILE),'recipe':e.recipes()}
 e.write(out/'preparation.json',{'explicit_mock':True})
 monkeypatch.setattr(e,'validate_prepared',lambda path:(frozen,public,proof));monkeypatch.setattr(e,'_output',lambda p,**kwargs:Path(p))
 state=services(monkeypatch)
 import sheets_factory.core.audit as audit
 import sheets_factory.dashboard as dashboard
 import sheets_factory.resume as resume
 monkeypatch.setattr(e,'AuditStore',audit.AuditStore);monkeypatch.setattr(e,'DashboardServer',dashboard.DashboardServer);monkeypatch.setattr(e,'ProducerLease',resume.ProducerLease)
 seen=[];history=[]
 class FakeEngine:
  def __init__(self,*args,**kwargs):pass
  def ensure_image(self):return e.IMAGE_ID
  def recalculate(self,source,destination):
   seen.append((e.reference(source),destination))
   binding=bindings[0];av,bv=e.expected_results(proof);values=e.expected_values(public,av,bv,binding,winner)['values']
   if fault==('first_audit'if len(seen)==1 else 'second_audit'if len(seen)==2 else 'never'):
    values=deepcopy(values);values['Portfolio','B3']+=1
   fill_caches(source,destination,values)
   history.append(e.write(out/f'fake_runtime_{len(seen)}.json',{'unit_mock_resource_only':True}))
   return destination
  def metadata(self):return {'actual_resource_receipts':history}
 bindings=[];original_emit=e.excel.emit_workbook
 def emit(*args,**kwargs):
  result=original_emit(*args,**kwargs);bindings.append(result);return result
 monkeypatch.setattr(e.excel,'emit_workbook',emit);monkeypatch.setattr(e,'ResourceLibreOfficeEngine',FakeEngine)
 def checked(call,record,frozen):
  index=history.index(record)+1
  return {'container_id':f'{index:064x}','terminal':record,'unit_mock_resource_only':True}
 monkeypatch.setattr(e,'validate_actual_call',checked);commands=[]
 def command(args,**kwargs):
  commands.append(args)
  if args[:2]==['docker','version']:return subprocess.CompletedProcess(args,0,'unit mock daemon\n','')
  assert args[:2]==['docker','inspect'] and len(args[2])==64
  return subprocess.CompletedProcess(args,1,'','daemon unavailable'if fault=='cleanup_unknown'else 'Error: No such object: '+args[2])
 monkeypatch.setattr(entry.subprocess,'run',command)
 if fault is None:
  manifest=e.read(e.execute_prepared(out));assert len(seen)==3 and len(commands)==6
  assert seen[0][0]==e.read(manifest['cache_clearance'])['output'] and entry.cache_census(Path(seen[0][0]['path']))==bindings[0]['formula_count']
  assert all(e.read(r)['passed']for r in manifest['financial_audits'])
  assert len(e.read(manifest['stability'])['comparisons'])==2 and manifest['LO_calls']==3 and manifest['qualified'] is False
  checked_manifest=e.validate_source(e.reference(out/'source_manifest.json'));assert checked_manifest==manifest
  assert len(commands)==6  # Cold validation must not inspect Docker again.
  cleanup=e.read(manifest['actual_engine_calls'][0]['owned_cleanup']);cleanup['owned'][0]['stderr']='daemon unavailable'
  path=Path(manifest['actual_engine_calls'][0]['owned_cleanup']['path']);path.write_text(json.dumps(cleanup))
  with pytest.raises(ValueError):e.validate_source(e.reference(out/'source_manifest.json'))
 else:
  with pytest.raises(RuntimeError,match='preserve'):e.execute_prepared(out)
  assert len(seen)==(2 if fault=='second_audit'else 1) and not(out/'source_manifest.json').exists()
  terminal=e.read(next((out/'private/attempts').glob('*/terminal.json')));assert terminal['status']=='failed'
 assert state['released'] and state['closed'] and state['stopped']
 before=len(seen)
 with pytest.raises(ValueError,match='retry'):e.execute_prepared(out)
 assert len(seen)==before


def test_cli_rejects_replacement_or_invalid_arguments_before_loading_source(monkeypatch):
 monkeypatch.setattr(entry,'source',lambda n:pytest.fail('Invalid CLI reached source factory'))
 for argv in (['prepare','--projects','360'],['run','--projects','720','--prepared','p','--port','65536'],
  ['validate','--projects','720','--prepared','p','--reference','changed']):
  with pytest.raises(SystemExit):entry.main(argv)


def test_pinned_reference_and_compatibility_guards_stay_active_when_factory_is_warm(tmp_path,monkeypatch):
 entry.source(720);bad=tmp_path/'changed_ancestor.py';bad.write_text('# not a reviewed ancestor')
 monkeypatch.setitem(entry.PINS,bad,'0'*64)
 with pytest.raises(ValueError,match='Frozen dimension source ancestor'):entry.source(720)
