from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('ring_finalizer_v2',ROOT/'scripts/finalize_ringfenced_business_revision2.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def make_contract(tmp_path):
 b=m.base;driver=tmp_path/'bounded_driver.py';driver.write_text('# frozen bounded review driver\n')
 calls=[]
 for i in range(4):calls.append(b.write(tmp_path/f'failed_call{i}.json',{'model':'gpt-6-sol','reasoning_effort':'high','status':'failed'}))
 old=b.write(tmp_path/'failed_review.json',{'kind':m.OLD_REVIEW_KIND,'shared_semantic_passed':False,
  'failures':{str(i):{} for i in range(4)},'ordinary_review_native_calls':calls,
  'tasks':[{'task_id':mode+str(i)} for mode in b.MODES for i in range(5)],
  'usage':{'llm_calls':4,'unknown_usage_calls':4,'total_tokens':0}})
 guard=b.write(tmp_path/'packet_projection.json',{'read_only_projection':True})
 profile={'kind':m.CONTRACT_KIND,'version':1,'driver':b.ref(driver),'terminal_kind':'actual_bounded_review_v2',
  'prepared_kind':'prepared_bounded_review_v2','failed_review':old,'packet_guards':[guard]}
 return b.write(tmp_path/'contract.json',profile),profile


def test_contract_preserves_four_unknown_failures_and_never_resamples_a_valid_review(tmp_path):
 binding,profile=make_contract(tmp_path)
 assert m.contract(binding)==(binding,profile)
 old=m.read(profile['failed_review']);calls=old['ordinary_review_native_calls']
 value=m.read(calls[0]);value['status']='completed';calls[0]=m.base.write(tmp_path/'completed_call.json',value)
 profile['failed_review']=m.base.write(tmp_path/'partly_complete_review.json',old)
 changed=m.base.write(tmp_path/'changed_contract.json',profile)
 with pytest.raises(ValueError,match='valid completed'):m.contract(changed)


def review_fixture(tmp_path):
 binding,profile=make_contract(tmp_path);b=m.base
 packet=b.write(tmp_path/'prepared_packet.json',{'kind':profile['prepared_kind'],'implementation':profile['driver'],
  'cohort_entry':b.ref(b.ENTRY),'all_five_pairs_in_both_role_views':True,'model':'gpt-6-sol',
  'reasoning_effort':'high','model_calls_permitted':4,'prior_incomplete_review':profile['failed_review'],
  'incomplete_review_calls_preserved':4,'previous_valid_judgments_replaced':False,
  'workspace_inventory':{'packet':profile['packet_guards'][0]},
  'bounded_packets':{mode+'/'+role:profile['packet_guards'][0] for mode in b.MODES for role in ('public','reference')}})
 dispatch=b.write(tmp_path/'dispatch.json',{'prepared':packet})
 tasks=[];review_tasks=[]
 for mode in b.MODES:
  for i in range(5):
   name=mode+str(i);artifacts={}
   for field in ('input','instruction','goal'):artifacts[field]=b.write(tmp_path/f'{name}_{field}.json',{'case':i,'mode':mode,'field':field})
   tasks.append({'task_id':name,'mode':mode,'harbor_export_binding':{'resource_runtime':{'source_artifacts':artifacts}}})
   review_tasks.append({'task_id':name,'mode':mode,**artifacts})
 resources=[];calls=[]
 for i in range(4):
  identity=str(i)*32;name='sf-codex-'+identity[:20];image='sha256:'+'b'*64
  calls.append(b.write(tmp_path/f'call{i}.json',{'call_id':identity,'status':'completed','model':'gpt-6-sol',
   'reasoning_effort':'high','isolated':True,'started_at':'2026-11-01T08:00:00+00:00','finished_at':'2026-11-01T08:01:00+00:00'}))
  resources.append(b.write(tmp_path/f'resource{i}.json',{'container_name':name,'expected_image_id':image,
   'passed':True,'observations':[{'at':'2026-11-01T08:00:30+00:00','passed':True,'container':{
    'Id':str(i)*64,'Name':'/'+name,'Image':image,'NanoCpus':2000000000,'Memory':34359738368,'PidsLimit':256}}]}))
 mode_assessments={mode:{'assessments':{f'Q{i:02d}':{'state':'not_applicable' if i==8 else 'clear'} for i in range(1,13)},'issues':[]} for mode in b.MODES}
 review={'kind':profile['terminal_kind'],'shared_semantic_passed':True,'ordinary_review_resources_passed':True,
  'failures':{},'outer_retries':0,'all_enabled_check_ids':[f'Q{i:02d}' for i in range(1,13)],'tasks':review_tasks,
  'dispatch':dispatch,'ordinary_review_resources':resources,'ordinary_review_native_calls':calls,'modes':mode_assessments}
 return profile,{'tasks':tasks},review


def test_bounded_review_keeps_original_semantic_checks_and_exact_all_ten_materials(tmp_path):
 profile,prepared,review=review_fixture(tmp_path);before=m.base.ref(m.BASE)
 reference=m.base.write(tmp_path/'review.json',review)
 result=m.quality_validator(profile)(reference,prepared)
 assert result==review and m.base.ref(m.BASE)==before
 assert str(m.base.REVIEW).endswith('run_ringfenced_shared_quality_review.py')


@pytest.mark.parametrize('mutation',['wrong_kind','wrong_packet_kind','missing_task','changed_input','semantic_flag',
 'blocker','wrong_cpu','unknown_resource','wrong_container','observation_after_finish','extra_call'])
def test_bounded_packets_cannot_bypass_scope_semantics_or_actual_resources(tmp_path,mutation):
 profile,prepared,review=review_fixture(tmp_path)
 if mutation=='wrong_kind':review['kind']=m.OLD_REVIEW_KIND
 if mutation=='wrong_packet_kind':profile['prepared_kind']='wrong'
 if mutation=='missing_task':review['tasks'].pop()
 if mutation=='changed_input':review['tasks'][0]['input']=m.base.write(tmp_path/'different_input.json',{'changed':True})
 if mutation=='semantic_flag':review['modes']['financial_modeling']['assessments']['Q02']['state']='flagged'
 if mutation=='blocker':review['modes']['debugging']['issues'].append({'severity':'blocker'})
 if mutation in ('wrong_cpu','unknown_resource','wrong_container','observation_after_finish'):
  actual=m.read(review['ordinary_review_resources'][0])
  if mutation=='wrong_cpu':actual['observations'][0]['container']['NanoCpus']=4000000000
  if mutation=='unknown_resource':actual['passed']=False
  if mutation=='wrong_container':actual['container_name']='unrelated'
  if mutation=='observation_after_finish':actual['observations'][0]['at']='2026-11-01T08:01:01+00:00'
  review['ordinary_review_resources'][0]=m.base.write(tmp_path/'changed_resource.json',actual)
 if mutation=='extra_call':review['ordinary_review_native_calls'].append(review['ordinary_review_native_calls'][0])
 reference=m.base.write(tmp_path/'review.json',review)
 with pytest.raises(ValueError):m.quality_validator(profile)(reference,prepared)


def test_append_only_provenance_counts_unknown_failed_calls_without_changing_primary_or_manifest(tmp_path):
 binding,profile=make_contract(tmp_path)
 original={'kind':'qualified_ringfenced_business_revision_release','version':1,'dataset_manifest':{'sha256':'fixed'},
  'tasks':[{'original_raw_reward':1,'primary_reward':0,'conservative_reward':0}],
  'consumption':{'known_reported_total_tokens':123,'model_calls':28,'unknown_usage_calls':0}}
 before=deepcopy(original);result=m.augment(original,binding,profile)
 assert original==before and result['tasks']==original['tasks'] and result['dataset_manifest']==original['dataset_manifest']
 assert result['version']==2 and result['consumption']['known_reported_total_tokens']==123
 assert result['consumption']['model_calls']==32 and result['consumption']['unknown_usage_calls']==4
 assert result['consumption']['failed_original_semantic_review']['zero_known_tokens_does_not_mean_zero_consumption']
 assert result['finalizer_revision2']['staged_recipe_and_dataset_manifest_unchanged']
