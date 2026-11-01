from contextlib import contextmanager
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=spec_from_file_location('ring_publisher',ROOT/'scripts/publish_ringfenced_business_revision.py')
m=module_from_spec(spec);spec.loader.exec_module(m)
FILES=frozenset({'instruction.md','task.toml','export_manifest.json','environment/Dockerfile',
 'environment/input.xlsx','environment/recalculate','environment/resource_runner.py','environment/runtime_profile.json',
 'solution/solve.sh','solution/reference.xlsx','tests/Dockerfile','tests/original_input.xlsx','tests/reference.xlsx',
 'tests/verify.py','tests/test.sh','tests/runtime_profile.json','tests/streaming_core.py'})


@contextmanager
def monitor(*args):
 yield SimpleNamespace(task=lambda *a,**k:None,export=lambda:None,update_run=lambda **k:None)


def fixture(tmp_path,monkeypatch):
 root=tmp_path/'repo';root.mkdir();monkeypatch.setattr(m,'ROOT',root)
 monkeypatch.setattr(m,'recipes',lambda:{'immutable':'recipe'})
 monkeypatch.setattr(m,'controls',lambda:{'FILES':FILES})
 monkeypatch.setattr(m,'inspect_resource_export',lambda path:{'task_id':Path(path).name,'exact':True})
 def task(parent,name,mode,variant):
  folder=parent/name
  for file in FILES:
   path=folder/file;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name+'|'+file)
  return {'task_id':name,'mode':mode,'variant_id':variant,'revision':0,'revision_hash':('a' if mode=='financial_modeling' else 'b')*64,
   'harbor_export_binding':m.inspect_resource_export(folder),'payload_files':{f:m.ref(folder/f)['sha256'] for f in FILES},'task_directory':str(folder)}
 old=[]
 for mode,prefix in [('financial_modeling','oldFM'),('debugging','oldDBG')]:
  for i in range(10):old.append(task(root/'SpreadsheetEval',prefix+str(i),mode,'F'+str(i)))
 oldmanifest=m.write(root/'SpreadsheetEval/dataset_manifest.json',{'task_count':20,'counts_by_mode':m.MODES,
  'selected_task_ids':[t['task_id'] for t in old],'tasks':old})
 retained=[]
 for mode in m.MODES:
  for t in [t for t in old if t['mode']==mode][:5]:
   retained.append({**t,'original_release_result':{'task_checksum':m.dirhash(root/'SpreadsheetEval'/t['task_id'],'sha256')}})
 history=m.write(root/'history.json',{'task_count':10,'original_results_preserved':True,'original_material_bytes_verified':True,
  'materials_recalculated_or_rescored':False,'original_root_dataset_manifest':oldmanifest,'tasks':retained})
 new=[]
 for i in range(1,6):
  for mode,suffix in [('financial_modeling','FM'),('debugging','DBG')]:
   new.append(task(root/'outputs/new_tasks','R2-'+str(i).zfill(2)+'-'+suffix,mode,'R2-'+str(i).zfill(2)+'-'+suffix))
 f={'kind':'prepared_test','tasks':new,'batches':[],'retained_results':history,'export_files':{t['task_id']:{name:m.ref(Path(t['task_directory'])/name) for name in FILES} for t in new}}
 prepared=m.write(root/'outputs/confirmation/prepared.json',f)
 monkeypatch.setattr(m,'prepared_immutable',lambda record:f)
 monkeypatch.setattr(m,'entry',lambda:SimpleNamespace(KIND='prepared_test',p=SimpleNamespace(_N={'monitor':monitor})))
 return root,prepared,f,oldmanifest


def test_stage_keeps_original_root_and_all_historical_bytes_then_install_keeps_exact_twenty(tmp_path,monkeypatch):
 root,prepared,f,original=fixture(tmp_path,monkeypatch)
 staged=m.stage(prepared,root/'outputs/release',root=root)
 value=m.read(staged)
 assert m.ref(root/'SpreadsheetEval/dataset_manifest.json')==original
 assert m.inventory_key(m.inventory(root/'outputs/release/previous_SpreadsheetEval'))==m.inventory_key(value['previous_inventory'])
 frozen=m.ref(root/'outputs/release/SpreadsheetEval/dataset_manifest.json')
 installed=m.install(staged,root=root);actual=m.read(installed)
 assert actual['qualified'] is False and actual['raw_scores_modified'] is False
 assert m.ref(root/'SpreadsheetEval/dataset_manifest.json')['sha256']==frozen['sha256']
 manifest=m.read(root/'SpreadsheetEval/dataset_manifest.json')
 assert manifest['task_count']==20 and manifest['counts_by_mode']==m.MODES
 assert len(set(manifest['selected_task_ids']))==20
 assert len(list((root/'outputs/release/previous_SpreadsheetEval').iterdir()))==21
 assert len(list((root/'outputs/release/displaced_original_SpreadsheetEval').iterdir()))==21
 assert m.read(root/'outputs/release/previous_SpreadsheetEval/dataset_manifest.json')['tasks'][0]['task_id'].startswith('old')
 with pytest.raises(ValueError):m.install(staged,root=root)


def test_atomic_install_failure_restores_the_exact_original_and_preserves_failure(tmp_path,monkeypatch):
 root,prepared,f,original=fixture(tmp_path,monkeypatch);staged=m.stage(prepared,root/'outputs/release',root=root)
 replace=m.os.replace
 def fail(source,destination):
  if Path(source)==root/'outputs/release/SpreadsheetEval':raise OSError('injected move failure')
  return replace(source,destination)
 monkeypatch.setattr(m.os,'replace',fail)
 with pytest.raises(OSError,match='injected'):m.install(staged,root=root)
 assert m.ref(root/'SpreadsheetEval/dataset_manifest.json')==original
 failure=m.read(root/'outputs/release/install_failure.json')
 assert failure['original_root_restored'] is True and failure['qualified'] is False
 assert not (root/'outputs/release/installed.json').exists()


@pytest.mark.parametrize('mutation',['original_payload','staged_payload','backup_payload','extra_file','symlink'])
def test_install_refuses_any_changed_bytes_or_ownership_before_mutation(tmp_path,monkeypatch,mutation):
 root,prepared,f,original=fixture(tmp_path,monkeypatch);staged=m.stage(prepared,root/'outputs/release',root=root)
 base={'original_payload':root/'SpreadsheetEval','staged_payload':root/'outputs/release/SpreadsheetEval',
  'backup_payload':root/'outputs/release/previous_SpreadsheetEval'}.get(mutation,root/'outputs/release/SpreadsheetEval')
 name=m.read(base/'dataset_manifest.json')['tasks'][0]['task_id']
 if mutation=='extra_file':(base/name/'not_allowed.txt').write_text('extra')
 elif mutation=='symlink':(base/name/'instruction.md').unlink();(base/name/'instruction.md').symlink_to(root/'history.json')
 else:(base/name/'instruction.md').write_text('tampered')
 with pytest.raises(ValueError):m.install(staged,root=root)
 assert not (root/'outputs/release/displaced_original_SpreadsheetEval').exists()


def test_stage_refuses_prior_confirmation_results_and_wrong_retained_bytes(tmp_path,monkeypatch):
 root,prepared,f,original=fixture(tmp_path,monkeypatch)
 m.write(root/'outputs/confirmation/terminal.json',{'has_result':True})
 with pytest.raises(ValueError,match='before confirmation results'):m.stage(prepared,root/'outputs/release',root=root)
 assert m.ref(root/'SpreadsheetEval/dataset_manifest.json')==original


def row(raw=0,budget=False):
 return {'task_id':'t','resources':{'passed':True,'complete':True},'score':{'effective_reward':0 if budget else raw,
  'state':'known_tool_budget_failure' if budget else 'complete'},'actual_attempt':{'status':'scored','raw_verifier_reward':raw,
  'failure_kind':'cumulative_tool_budget_exhausted' if budget else None,'tool_time':{'passed':not budget,
   'budget_seconds':1800,'strict_less_than':True,'model_response_time_included':False,'parallel_executions':'sum',
   'cumulative_tool_seconds':1801 if budget else 100}}}


@pytest.mark.parametrize('raw',[0,1])
def test_known_verified_tool_budget_failure_is_zero_even_when_economics_is_correct(raw):
 value=row(raw,budget=True)
 assert m.effective(value)==(0,'known_tool_budget_failure',raw)
 assert m.conservative(value)==(0,'verified_tool_budget_failure')
 assert value['actual_attempt']['raw_verifier_reward']==raw


def test_complete_raw_one_is_success_and_never_requires_a_failure_label():
 assert m.conservative(row(1))==(1,'complete_primary_success')


@pytest.mark.parametrize('mutation',['clock_unknown','resources_unknown','infra','raw_missing','wrong_effective'])
def test_unknown_or_rewritten_results_hold_instead_of_becoming_zero(mutation):
 value=row()
 if mutation=='clock_unknown':value['actual_attempt']['tool_time']['passed']=None
 if mutation=='resources_unknown':value['resources']['complete']=False
 if mutation=='infra':value['actual_attempt']['failure_kind']='infrastructure'
 if mutation=='raw_missing':value['actual_attempt']['raw_verifier_reward']=None
 if mutation=='wrong_effective':value['score']['effective_reward']=1
 with pytest.raises(ValueError):m.effective(value)


def analysis(tmp_path,classification,changes,differences):
 result=m.write(tmp_path/'result.json',{'real':'result'})
 diagnostic=m.write(tmp_path/'verifier/diagnostics.json',{'reward':0,'wrong_values':changes,'extra_changes':[],'missing_changes':[]})
 value=row();value['actual_attempt'].update(result_file=result['path'],result_sha256=result['sha256'])
 proof=m.write(tmp_path/'proof.json',{'native_witness':True})
 a=m.write(tmp_path/'analysis.json',{'kind':'native_confirmation_nonboundary_analysis_v1','task_id':'t',
  'result_sha256':result['sha256'],'diagnostics':diagnostic,'complete':True,'classification':classification,
  'evidence':[result,diagnostic,proof],'differences':differences})
 return value,a


def test_boolean_and_numeric_boundaries_count_as_conservative_success_without_changing_raw(tmp_path):
 d={'coordinate':'Group reporting!B6','expected_type':'boolean','expected':True,'actual_type':'number','actual':1}
 value,a=analysis(tmp_path,'pure_reporting_boolean_only',['Group reporting!B6'],[d])
 assert m.conservative(value,a)==(1,'pure_reporting_boolean_only')
 assert value['actual_attempt']['raw_verifier_reward']==0 and value['score']['effective_reward']==0


def test_complete_small_numeric_boundary_counts_as_success(tmp_path):
 d={'coordinate':'Model!A1','expected_type':'number','expected':'1.11','actual_type':'number','actual':'1.10'}
 value,a=analysis(tmp_path,'pure_numeric_rounding_only',['Model!A1'],[d])
 assert m.conservative(value,a)[0]==1


@pytest.mark.parametrize('mutation',['wrong_cell','more_wrong','two_cent','boolean_is_not_number','business_without_witness'])
def test_boundary_labels_alone_cannot_admit_unexamined_business_failures(tmp_path,mutation):
 points=['Model!A1'];d={'coordinate':'Model!A1','expected_type':'number','expected':'1.11','actual_type':'number','actual':'1.10'};kind='pure_numeric_rounding_only'
 if mutation=='wrong_cell':d['coordinate']='Other!A1'
 if mutation=='more_wrong':points.append('Model!A2')
 if mutation=='two_cent':d['actual']='1.09'
 if mutation=='boolean_is_not_number':d['actual']=True
 if mutation=='business_without_witness':kind='material_business_value_failure'
 value,a=analysis(tmp_path,kind,points,[d])
 with pytest.raises(ValueError):m.conservative(value,a)


def test_genuine_nonboundary_numeric_failure_is_distinct_from_pure_boundary(tmp_path):
 d={'coordinate':'M01 - Portfolio!C5','expected_type':'number','expected':10000,'actual_type':'number','actual':9000}
 value,a=analysis(tmp_path,'material_business_value_failure',[d['coordinate']],[d])
 assert m.conservative(value,a)==(0,'material_business_value_failure')


def twenty_rows(new_primary=0,new_cautious=0):
 result=[]
 for i in range(20):result.append({'task_id':str(i),'mode':'financial_modeling' if i%2==0 else 'debugging',
  'primary_reward':int(i>=10 and i<10+new_primary),'conservative_reward':int(i>=10 and i<10+new_cautious),
  'scope':'retained_historical' if i<10 else 'new_confirmation'})
 return result


def test_combined_and_new_wave_thresholds_are_reported_separately():
 result=m.gate_rows(twenty_rows(4,4));assert result['passed'] and result['primary_overall_pass_at_1']==0.2
 assert not result['new_wave_own_point_two_gate_passed'] and result['new_wave_primary_pass_at_1']==0.4
 assert not m.gate_rows(twenty_rows(0,5))['passed']
 assert not m.gate_rows(twenty_rows(5,5))['passed']
 assert m.GATE['twenty_fresh_attempts_claimed'] is False


def test_missing_raw_zero_analysis_holds_and_usage_never_guesses_price():
 with pytest.raises(ValueError,match='HOLD'):m.conservative(row())
 value=m.usage([{'agent_result':{'n_input_tokens':100,'n_output_tokens':20,'n_cache_tokens':80}},{}])
 assert value['reported_total_tokens']==120 and value['cached_input_tokens']==80 and value['unknown_usage_calls']==1
 assert value['provider_paid_USD'] is None


@pytest.mark.parametrize('budget,seconds',[(True,1799),(False,1800)])
def test_exact_strict_tool_boundary_requires_valid_mathematical_bound(budget,seconds):
 value=row(1,budget);value['actual_attempt']['tool_time']['cumulative_tool_seconds']=seconds
 with pytest.raises(ValueError,match='HOLD'):m.effective(value)


def test_verified_interval_over_budget_remains_valid_zero_without_exact_duration():
 value=row(1,True);clock=value['actual_attempt']['tool_time'];clock['cumulative_tool_seconds']=None
 clock['cumulative_lower_bound_seconds']='1800.00001';clock['cumulative_upper_bound_seconds']='1801.4'
 assert m.conservative(value)==(0,'verified_tool_budget_failure')


def test_finalizer_joins_historical_ten_and_fresh_ten_without_editing_manifest_or_scores(tmp_path,monkeypatch):
 root,prepared,f,oldmanifest=fixture(tmp_path,monkeypatch)
 history=m.read(f['retained_results']);old_results=[]
 for i,t in enumerate(history['tasks']):
  actual=m.write(root/f'old_result_{i}.json',{'trial':i});diagnostic=m.write(root/f'old_diag_{i}.json',{'wrong_fields':{'reported_associate_line':800}})
  t['original_release_result'].update(task_id=t['task_id'],mode=t['mode'],variant_id=t['variant_id'],reward=0,
   raw_verifier_reward=0,state='complete',result_sha256=actual['sha256'])
  t['original_failure_analysis']={'boundary_only':False,'resources_passed':True,'tool_time_passed':True,
   'actual_result':actual,'diagnostics':diagnostic}
  old_results.append(t['original_release_result'])
 history['previous_release']=m.write(root/'previous_release.json',{'tasks':old_results})
 f['retained_results']=m.write(root/'history_final.json',history)
 f['materials']={t['task_id']:{'sha256':str(i)*64} for i,t in enumerate(f['tasks'])}
 prepared=m.write(root/'outputs/final_confirmation/prepared.json',f)
 staged=m.stage(prepared,root/'outputs/release',root=root);installed=m.install(staged,root=root)
 selected=[t['task_id'] for t in f['tasks']]
 evaluation=m.write(root/'evaluation.json',{'model':'gpt-6.1-sol','reasoning_effort':'xhigh'})
 selection=m.write(root/'selection.json',{'model':'gpt-6.1-sol','reasoning_effort':'xhigh','phase':'confirmation',
  'n_attempts':1,'tool_time_policy_version':6})
 resource=m.write(root/'resources.json',{'passed':True,'complete':True})
 results=[]
 for i,t in enumerate(f['tasks']):
  actual=m.write(root/f'new_result_{i}.json',{'new_trial':i});r=row(1,True)
  r.update(task_id=t['task_id'],mode=t['mode'],variant_id=t['variant_id'],material_identity=f['materials'][t['task_id']])
  r['actual_attempt'].update(harbor_export_binding=t['harbor_export_binding'],task_checksum=m.dirhash(root/'SpreadsheetEval'/t['task_id'],'sha256'),
   result_file=actual['path'],result_sha256=actual['sha256'],agent_result={'n_input_tokens':100,'n_output_tokens':10,'n_cache_tokens':80})
  results.append(r)
 terminal=m.write(root/'confirmation.json',{'kind':'test_confirmation','phase':'confirmation','outer_retries':0,
  'prepared':prepared,'selection':selection,'evaluation':evaluation,'resources':resource,'results':results})
 monkeypatch.setattr(m,'entry',lambda:SimpleNamespace(TERMINAL_KIND='test_confirmation'))
 monkeypatch.setattr(m.observer,'validate_observation_receipt',lambda *a: m.read(resource))
 usage={'input_tokens':400,'output_tokens':40,'total_tokens':440,'cached_input_tokens':300,'llm_calls':4,'unknown_usage_calls':0}
 monkeypatch.setattr(m,'validate_quality',lambda *a:{'usage':usage})
 monkeypatch.setattr(m,'engineering',lambda *a:[{'task_id':t['task_id']} for t in f['tasks']])
 monkeypatch.setattr(m,'validate_controls',lambda *a:{'passed':True})
 baseline_calls=[]
 for i in range(14):baseline_calls.append({'actual_result':m.write(root/f'prototype{i}.json',{'prototype':i}),'total_tokens':10})
 baseline=m.write(root/'baseline.json',{'kind':'actual_business_revision_prototype_usage_baseline','call_count':14,
  'calls':baseline_calls,'total_tokens':140,'input_tokens':126,'output_tokens':14,'unknown_usage_calls':0})
 monkeypatch.setattr(m,'BASELINE',Path(baseline['path']));monkeypatch.setattr(m,'BASELINE_SHA',baseline['sha256'])
 review=m.write(root/'review.json',{'real_review_ref':True});controls=m.write(root/'controls.json',{'real_control_ref':True})
 before=m.ref(root/'SpreadsheetEval/dataset_manifest.json')
 report=m.read(m.finalize(installed,terminal,review,controls,root/'qualified.json'))
 assert report['qualified'] and report['task_count']==20
 assert report['historical_retained_count']==report['fresh_new_confirmation_count']==10
 assert not report['twenty_fresh_attempts_claimed'] and not report['retained_scores_modified']
 assert report['gate_result']['primary_successes']==report['gate_result']['conservative_nonboundary_successes']==0
 assert all(r['original_raw_reward']==1 for r in report['tasks'] if r['scope']=='new_confirmation')
 assert report['consumption']['known_reported_total_tokens']==140+1100+440
 assert report['consumption']['model_calls']==28
 assert m.ref(root/'SpreadsheetEval/dataset_manifest.json')==before
