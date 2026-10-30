"""Offline admission and normal-routing checks; no model, Docker, or LO calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.nodes.construction import NormalizeNode, PlanNode, construction_contract

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('composite_quality_cohort',ROOT/'scripts/run_composite_quality_cohort.py')
cohort=importlib.util.module_from_spec(spec);spec.loader.exec_module(cohort)

def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

def fake_source(folder,index):
 folder.mkdir(parents=True)
 book=folder/'composite.xlsx';book.write_bytes(('audited source '+str(index)).encode())
 identity=cohort.sha(book);summary={name:{'passed':True,'checked_cells':10,'mismatch_count':0} for name in ('lease','programme','operating','holding')}
 for name in summary:dump(folder/'private'/(name+'_financial_audit.json'),{'workbook':cohort.ref(book),'passed':True,'checked_cells':10,'mismatches':[]})
 provided=folder/'private/provided.json';dump(provided,{'passed':True,'completed':cohort.ref(book),'mismatches':[],'missing_sheets':[]})
 scenarios=folder/'public_scenarios.json';dump(scenarios,{'lease':{'primitive':index}})
 stable=folder/'private/stability.json';dump(stable,{'stable':True,'first_against_goal':{'reward':1},'second_against_goal':{'reward':1}})
 financial=folder/'private/financial.json';dump(financial,summary)
 manifest=folder/'seed_manifest.json';dump(manifest,{'local_path':str(book),'derived_workbook_sha256':identity,
  'financial_audit_passed':True,'financial_audits':summary,'financial_audit':cohort.ref(financial),
  'provided_context_audit':cohort.ref(provided),'public_scenarios':cohort.ref(scenarios),'stability':cohort.ref(stable),
  'runtime':{'image':cohort.IMAGE,'image_id':cohort.IMAGE_ID}})
 return {'profile_id':'C'+str(index).zfill(2),'sha256':identity,'local_path':str(book),'source_manifest':cohort.ref(manifest),'finance_evidence':{'financial_seed_verified':True}}


def make_batch(path,entries):
 selection=path.with_name(path.stem+'-selection.json');dump(selection,{'profiles':[e['profile_id'] for e in entries],'model_results_consulted':False})
 plan=path.with_name(path.stem+'-plan.json');dump(plan,{'kind':'offline-plan'})
 scenario=path.with_name(path.stem+'-scenario.json');dump(scenario,{'kind':'offline-scenario'})
 attempts=[]
 for e in entries:
  m=Path(e['source_manifest']['path']);a={n:cohort.ref(m.parent/'private'/(n+'_financial_audit.json')) for n in ('lease','programme','operating','holding')}
  attempts.append({'id':e['profile_id'],'stage':'build','status':'verified','source_manifest':e['source_manifest'],
   'verification':{'workbook':cohort.ref(e['local_path']),'four_audits':a}})
 dump(path,{'selected':entries,'verified_derived_workbook_count':len(entries),'target_derived_workbook_count':len(entries),
  'source_ancestor_unique_count':2,'mode':'build','recipe_unchanged':True,'status':'independently_verified_composed_financial_seed_batch',
  'model_scores_consulted':False,'source_selection':cohort.ref(selection),'plan':cohort.ref(plan),'scenario_config':cohort.ref(scenario),'attempts':attempts})

@pytest.fixture
def batch(tmp_path):
 entries=[fake_source(tmp_path/'sources'/str(i),i) for i in range(10)]
 path=tmp_path/'batch.json';make_batch(path,entries)
 return path

@pytest.mark.parametrize('mode',cohort.MODES)
def test_prepare_binds_complete_audits_and_fixed_quota_without_models(batch,tmp_path,mode,monkeypatch):
 monkeypatch.setattr(cohort.CodexCLI,'__init__',lambda *a,**k:pytest.fail('Preparation must not initialize models'))
 output=tmp_path/'prepared';receipt=cohort.prepare_cohort(batch,output,mode=mode)
 config=yaml.safe_load((output/'resolved_config.yaml').read_text());selected=cohort.read(output/'seed_manifest.json')['selected']
 assert receipt['actual_model_calls']==0 and receipt['qualified'] is False
 assert config['run']['targets']=={'financial_modeling':10,'debugging':10}
 assert config['run']['max_sources']==20 and config['run']['max_candidates_per_seed']==1
 assert all(e['modes']==[mode] and e['variant']==0 for e in selected)
 for e in selected:
  evidence=e['finance_evidence'];assert len(evidence['independent_financial_audits'])==4
  assert all(Path(r['path']).is_file() and cohort.sha(r['path'])==r['sha256'] for r in evidence['independent_financial_audits'].values())
  assert 'cell_checks' not in evidence # Full audit files remain hash-bound artifacts, not copied summaries.
 assert config['recovery']['compiler_backend']=='composite_journal'
 assert config['diagnosis']['selection']=={'include':'all','exclude':[]}
 assert config['diagnosis']['execution']['reference_evidence_transport']=='audited_summary'
 contract=construction_contract(mode,config)
 assert contract['modes']['financial_modeling']['edit_count']['max']==100000
 assert contract['modes']['debugging']['edit_count']['max']==5000
 assert contract['root_impact_validation']=='shadow_roots'
 assert contract['source_requirements']['max_profile_cells']==500000
 assert config['agents']['trajectory_timeout_seconds']==600

@pytest.mark.parametrize('defect',['source_sha','arbitrary_path','audit_source','provided_source','failed_audit','missing_provided','duplicate','not_verified'])
def test_admission_rejects_incomplete_or_different_audited_source(batch,tmp_path,defect):
 data=cohort.read(batch);entry=data['selected'][0];manifest=Path(entry['source_manifest']['path']);source=cohort.read(manifest)
 if defect=='source_sha':Path(entry['local_path']).write_bytes(b'changed')
 elif defect=='arbitrary_path':entry['local_path']=data['selected'][1]['local_path']
 elif defect=='duplicate':data['selected'][1]=deepcopy(entry)
 elif defect=='not_verified':data['verified_derived_workbook_count']=9
 elif defect=='audit_source':
  p=manifest.parent/'private/lease_financial_audit.json';a=cohort.read(p);a['workbook']['sha256']='0'*64;dump(p,a)
 elif defect=='failed_audit':
  p=manifest.parent/'private/lease_financial_audit.json';a=cohort.read(p);a['passed']=False;dump(p,a)
 elif defect=='provided_source':
  p=Path(source['provided_context_audit']['path']);a=cohort.read(p);a['completed']['sha256']='0'*64;dump(p,a);source['provided_context_audit']=cohort.ref(p)
 else:source.pop('provided_context_audit')
 dump(manifest,source);entry['source_manifest']=cohort.ref(manifest);dump(batch,data)
 with pytest.raises((ValueError,KeyError)):cohort.prepare_cohort(batch,tmp_path/'prepared')
 assert not (tmp_path/'prepared').exists()


def test_adapter_restores_only_validated_source_and_normalize_copies_exact_bytes(batch,tmp_path,monkeypatch):
 output=tmp_path/'prepared';cohort.prepare_cohort(batch,output)
 config=yaml.safe_load((output/'resolved_config.yaml').read_text());audit=AuditStore(output,{'id':'offline','status':'running'})
 class Engine:
  def normalize(self,*args):pytest.fail('An audited source must not be normalized into different bytes')
  def check_stable(self,*args):return {'stable':True}
  def metadata(self):return {'image_id':cohort.IMAGE_ID}
 pipeline=cohort.AuditedSourceFactory(config,audit,None,Engine());seeds=pipeline.load_seeds()
 assert pipeline.targets=={'financial_modeling':10,'debugging':10}
 assert all(s['survey']['normalized_path']==s['local_path'] for s in seeds)
 context=pipeline._context(seeds[0],'financial_modeling')
 NormalizeNode().run(context)
 assert cohort.sha(context.data['baseline'])==seeds[0]['sha256']
 assert context.data['finance_evidence']['independent_financial_audits']
 from sheets_factory.workbook.composite_finance import tasks
 monkeypatch.setattr(tasks,'propose_task',lambda *_args:{'mask_ranges':[{'sheet':'Fixture','range':'C1:C6'}]})
 PlanNode().run(context)
 assert context.data['source_assessment']['financial_evidence']==context.data['finance_evidence']
 assert context.data['source_assessment']['financial_evidence']['source_manifest']['sha256']
 # Zero quotas are supported by the existing controller, though the cohort
 # deliberately keeps the final 10+10 quota fixed for continuation.
 pipeline.targets={'financial_modeling':10,'debugging':0}
 assert pipeline.reserve('debugging','dbg-impossible') is False


def test_private_role_override_preserves_other_caller_timeouts(tmp_path,monkeypatch):
 seen=[]
 monkeypatch.setattr(cohort.CodexCLI,'complete',lambda self,*a,**k:seen.append(k) or {})
 instance=object.__new__(cohort.CohortCodex)
 instance.complete('p',role='reference_diagnostician',timeout=1200)
 instance.complete('p',role='public_diagnostician',timeout=1200)
 assert [x['timeout'] for x in seen]==[2400,1200]


def test_prepared_default_does_not_execute_models(batch,tmp_path,monkeypatch):
 output=tmp_path/'prepared'
 monkeypatch.setattr(cohort,'execute_prepared',lambda *a,**k:pytest.fail('Only --run may start models'))
 assert cohort.main(['--source-manifest',str(batch),'--output',str(output)])==0
 assert cohort.main(['--prepared',str(output)])==0
 with pytest.raises(ValueError,match='never overwritten'):cohort.prepare_cohort(batch,output)


def test_existing_resume_appends_dbg_only_without_resetting_fm_or_repair_budgets(batch,tmp_path):
 from sheets_factory.resume import prepare_resume, candidate_task_id
 first=tmp_path/'fm-run';cohort.prepare_cohort(batch,first)
 fm=cohort.read(first/'seed_manifest.json')['selected'];first_id=candidate_task_id(fm[0],'financial_modeling')
 audit=AuditStore(first,{'id':'fixture','status':'shortfall','producer_active':False})
 audit.task(first_id,mode='financial_modeling',source_id=fm[0]['sha256'],status='qualified',targets=[['Fixture','C1']])
 audit.export()
 other_entries=[fake_source(tmp_path/'dbg-sources'/str(i),i+20) for i in range(10)]
 other=tmp_path/'dbg-batch.json';make_batch(other,other_entries)
 second=tmp_path/'dbg-prepared';cohort.prepare_cohort(other,second,mode='debugging')
 old=yaml.safe_load((first/'resolved_config.yaml').read_text())
 session=prepare_resume(first,extra_manifest=second/'seed_manifest.json',current_code_revision='offline-fixture',producer_probe=lambda *_:[])
 try:
  config=session.config
  assert config['run']['targets']=={'financial_modeling':10,'debugging':10}
  for key in ('max_steps','max_evidence_rounds_per_revision','infrastructure_retries_per_stage','max_additional_trials_per_revision'):
   assert config['run'][key]==old['run'][key]
  pipeline=cohort.AuditedSourceFactory(config,session.audit,None,object())
  seeds=pipeline.load_seeds()
  assert len(seeds)==20 and sum(s['modes']==['debugging'] for s in seeds)==10
  jobs=pipeline._eligible_source_jobs(seeds)
  assert all(candidate_task_id(s,m)!=first_id for s in jobs for m in s['modes'])
  assert next(t for t in session.audit.snapshot()['tasks'] if t['id']==first_id)['status']=='qualified'
 finally:session.close()


@pytest.mark.parametrize('defect',['status','mode','recipe','count','order','duplicate_build','unchanged_summary_changed_audit'])
def test_original_build_order_and_all_stored_hashes_are_required(batch,tmp_path,defect):
 data=cohort.read(batch)
 if defect=='status':data['status']='preflight_only'
 elif defect=='mode':data['mode']='preflight'
 elif defect=='recipe':data['recipe_unchanged']=False
 elif defect=='count':data['verified_derived_workbook_count']=11
 elif defect=='order':data['selected'].reverse()
 elif defect=='duplicate_build':data['attempts'].append(deepcopy(data['attempts'][0]))
 else:
  p=Path(data['selected'][0]['source_manifest']['path']).parent/'private/lease_financial_audit.json'
  audit=cohort.read(p);audit['cell_checks']=[{'expected':1,'actual':1}];dump(p,audit)
 dump(batch,data)
 with pytest.raises(ValueError):cohort.prepare_cohort(batch,tmp_path/'prepared')
 assert not (tmp_path/'prepared').exists()


def test_prepared_run_with_existing_direct_audit_database_cannot_reinitialize(batch,tmp_path,monkeypatch):
 output=tmp_path/'prepared';cohort.prepare_cohort(batch,output)
 audit=AuditStore(output,{'id':'closed','status':'shortfall','producer_active':False});audit.export()
 before=cohort.sha(output/'run.sqlite')
 monkeypatch.setattr(cohort.CohortCodex,'__init__',lambda *a,**k:pytest.fail('Refuse restart before model initialization'))
 with pytest.raises(ValueError,match='explicit resume'):cohort.execute_prepared(output)
 assert cohort.sha(output/'run.sqlite')==before
