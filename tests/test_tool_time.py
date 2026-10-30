"""Native timing receipts: arithmetic fixtures plus preserved real metadata."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import hashlib,json
from pathlib import Path
import pytest
from sheets_factory.evaluation.tool_time import account_tool_time,account_trial_tool_time

EPOCH=datetime(2026,10,30,tzinfo=timezone.utc)
BASE=1793318400000

def stamp(value):return (EPOCH+timedelta(seconds=float(D(str(value))))).isoformat()
def call(identity,start,end,*,name='exec',arguments=None,code='',output=''):
    payload={'type':'custom_tool_call','call_id':identity,'name':name,'input':code}
    if arguments is not None:payload['arguments']=json.dumps(arguments)
    return [{'type':'response_item','timestamp':stamp(start),'payload':payload},
            {'type':'response_item','timestamp':stamp(end),'payload':{'type':'custom_tool_call_output','call_id':identity,'output':output}}]
def item(identity,start,end,*,process='1',command='x',status='completed',kind='CommandExecution',duration=None):
    duration=D(str(end))-D(str(start)) if duration is None else D(str(duration))
    ns=int(duration*1_000_000_000)
    return {'type':'event_msg','timestamp':stamp(end),'payload':{'type':'item_completed',
        'started_at_ms':BASE+int(D(str(start))*1000),'completed_at_ms':BASE+int(D(str(end))*1000),
        'item':{'id':identity,'type':kind,'process_id':process,'command':['/bin/bash','-lc',command],
                'status':status,'duration':{'secs':ns//1_000_000_000,'nanos':ns%1_000_000_000}}}}
def receipt(tmp_path,records,name='session.jsonl',**kw):
    path=tmp_path/name;path.write_text(''.join(json.dumps(record)+'\n' for record in records))
    return account_tool_time([path],**kw)
def expect(result,seconds):
    assert result['state']=='verified',result['problems']
    assert D(str(result['cumulative_tool_seconds']))==D(str(seconds))

@pytest.mark.parametrize('seconds,passed',[('1799.999',True),('1800',False),('1800.001',False)])
def test_strict_tool_time_threshold(tmp_path,seconds,passed):
    result=receipt(tmp_path,call('c',0,seconds)+[item('i',0,seconds)])
    expect(result,seconds);assert result['passed'] is passed
    assert result['threshold_reached'] is (not passed)


def test_parallel_children_add_and_wrapper_counts_only_uncovered_wall_time(tmp_path):
    result=receipt(tmp_path,call('c',0,12)+[item('a',1,11,process='1'),item('b',1,11,process='2')])
    expect(result,22);assert result['wrappers'][0]['uncovered_seconds']==2


def test_parallel_distinct_wrappers_resolve_command_ownership(tmp_path):
    records=call('a',0,10,name='exec_command',arguments={'cmd':'alpha'})
    records+=call('b',0,10,name='exec_command',arguments={'cmd':'beta'})
    records += [item('a1',0,10,command='alpha'),item('b1',0,10,command='beta',process='2')]
    expect(receipt(tmp_path,records),20)


def test_model_response_gap_is_excluded_and_failed_execution_is_charged(tmp_path):
    records=call('a',0,3)+[item('a1',0,3,status='failed')]
    records += [{'type':'event_msg','timestamp':stamp(5000),'payload':{'type':'item_completed','item':{'type':'Reasoning','id':'reason'}}}]
    records += call('b',10000,10004)+[item('b1',10000,10004,process='2')]
    expect(receipt(tmp_path,records),7)


def test_process_spanning_two_polls_is_charged_once_and_only_real_overheads_remain(tmp_path):
    records=call('start',0,2,name='exec_command',arguments={'cmd':'slow'})
    records += call('poll1',40,50,name='write_stdin',arguments={'session_id':7})
    records += call('poll2',90,103,name='write_stdin',arguments={'session_id':7})
    records += [item('native',1,101,process='7',command='slow')]
    result=receipt(tmp_path,records)
    expect(result,103)
    assert [x['uncovered_seconds'] for x in result['wrappers']]==[1,0,2]


def test_code_mode_poll_links_same_process_but_independent_overlapping_tool_still_counts(tmp_path):
    records=call('start',0,1,name='exec_command',arguments={'cmd':'slow'})
    records += call('poll',30,40,code='const r = await tools.write_stdin({"session_id": 7, chars: ""}); text(r);')
    records += call('other',30,40,name='clock__curr_time',arguments={})
    records += [item('native',0,100,process='7',command='slow')]
    expect(receipt(tmp_path,records),110)


def test_wait_for_known_code_cell_does_not_recharge_its_primitive(tmp_path):
    records=call('launch',0,1,output='Script running with cell ID cell_17')
    records += call('poll',50,60,name='wait',arguments={'cell_id':'cell_17'})
    records += [item('native',0,100)]
    expect(receipt(tmp_path,records),100)


@pytest.mark.parametrize('name,args,code',[
    ('write_stdin',{'session_id':'missing'},''),('wait',{'cell_id':'missing'},''),
    ('exec',None,'await tools.write_stdin({session_id: load("id")});'),
])
def test_unresolved_poll_evidence_is_unknown_never_a_scored_failure(tmp_path,name,args,code):
    result=receipt(tmp_path,call('p',0,1,name=name,arguments=args,code=code))
    assert result['state']=='unknown' and result['passed'] is None


def test_exact_duplicate_events_are_deduplicated_and_conflicts_fail_closed(tmp_path):
    records=call('c',0,5)+[item('i',0,5)]
    result=receipt(tmp_path,records+deepcopy(records));expect(result,5)
    assert result['duplicate_event_count']==3
    conflict=deepcopy(records[0]);conflict['payload']['name']='different'
    result=receipt(tmp_path,records+[conflict],name='conflict.jsonl')
    assert result['state']=='unknown' and result['passed'] is None


def test_pending_process_updates_need_one_consistent_final_record(tmp_path):
    pending=item('i',0,1,status='in_progress');pending['payload']['completed_at_ms']=None
    records=call('c',0,10)+[pending,item('i',0,10)]
    expect(receipt(tmp_path,records),10)
    result=receipt(tmp_path,call('c',0,1)+[pending],name='pending.jsonl')
    assert result['state']=='unknown'
    result=receipt(tmp_path,records+[item('i',0,11)],name='conflicting_final.jsonl')
    assert result['state']=='unknown'


@pytest.mark.parametrize('mutation',['missing_output','missing_end','bad_duration','orphan','truncated'])
def test_incomplete_or_corrupt_timing_cannot_become_a_budget_failure(tmp_path,mutation):
    records=call('c',0,5)+[item('i',0,5)]
    if mutation=='missing_output':records.pop(1)
    elif mutation=='missing_end':records[-1]['payload'].pop('completed_at_ms')
    elif mutation=='bad_duration':records[-1]['payload']['item']['duration']['secs']=10
    elif mutation=='orphan':records[-1]=item('i',6,7)
    path=tmp_path/'bad.jsonl';path.write_text(''.join(json.dumps(x)+'\n' for x in records)+('{"payload":' if mutation=='truncated' else ''))
    result=account_tool_time([path]);assert result['state']=='unknown' and result['passed'] is None


def test_missing_session_files_are_unknown(tmp_path):
    assert account_tool_time([])['state']=='unknown'
    assert account_tool_time([tmp_path/'missing'])['state']=='unknown'


def trial(tmp_path):
    folder=tmp_path/'trial';(folder/'agent/sessions').mkdir(parents=True)
    records=call('c',1,3)+[item('i',1,3)]
    session=folder/'agent/sessions/native.jsonl';session.write_text(''.join(json.dumps(x)+'\n' for x in records))
    (folder/'agent/codex.txt').write_text(json.dumps({'type':'item.completed','item':{'type':'command_execution','id':'item_0'}})+'\n')
    result=folder/'result.json';result.write_text(json.dumps({'agent_execution':{'started_at':stamp(0),'finished_at':stamp(10)}}))
    return folder,result


def test_trial_binds_result_and_stream_hashes_and_actual_execution_window(tmp_path):
    folder,path=trial(tmp_path);result=account_trial_tool_time(path);expect(result,2)
    assert result['result_file']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['stream_coverage']['matched']
    d=json.loads(path.read_text());d['agent_execution']['finished_at']=stamp(2);path.write_text(json.dumps(d))
    result=account_trial_tool_time(path);assert result['state']=='unknown'
    assert 'outside actual agent execution' in ' '.join(result['problems'])


def test_trial_rejects_missing_result_missing_window_or_truncated_stream(tmp_path):
    assert account_trial_tool_time(tmp_path/'missing.json')['state']=='unknown'
    folder,path=trial(tmp_path);path.write_text('{}');assert account_trial_tool_time(path)['state']=='unknown'
    path.write_text(json.dumps({'agent_execution':{'started_at':stamp(0),'finished_at':stamp(10)}}))
    with (folder/'agent/codex.txt').open('a') as f:f.write('{"type":"item.completed",')
    assert account_trial_tool_time(path)['state']=='unknown'


def test_trial_rejects_native_stream_coverage_loss(tmp_path):
    folder,path=trial(tmp_path)
    with (folder/'agent/codex.txt').open('a') as f:f.write(json.dumps({'type':'item.completed','item':{'type':'file_change','id':'item_1'}})+'\n')
    assert account_trial_tool_time(path)['state']=='unknown'


def test_real_native_synchronous_failed_command_metadata_preserves_microsecond_duration(tmp_path):
    # These timestamps, process/item identifiers and duration are preserved from
    # an actual native CLI execution. Command/output contents are omitted.
    records=[{'type':'response_item','timestamp':'2026-10-30T10:18:41.470Z','payload':{'type':'custom_tool_call','call_id':'call_86751c01a0004df8b16a767d69e5db0f','name':'exec','input':''}},
      {'type':'event_msg','timestamp':'2026-10-30T10:18:41.534Z','payload':{'type':'item_completed','started_at_ms':1793355521534,'completed_at_ms':1793355521534,'item':{'type':'CommandExecution','id':'exec-3c820745-6ca1-430c-8599-e093c1f7d64f','process_id':'68028','status':'failed','duration':{'secs':0,'nanos':5214}}}},
      {'type':'response_item','timestamp':'2026-10-30T10:18:41.853Z','payload':{'type':'custom_tool_call_output','call_id':'call_86751c01a0004df8b16a767d69e5db0f','output':[]}}]
    result=receipt(tmp_path,records);expect(result,'.383')
    assert result['tools'][0]['execution_seconds']==.000005214
    assert result['wrappers'][0]['uncovered_seconds']==.382994786


def test_same_wrapper_launch_and_dynamic_local_process_poll_use_owned_native_timing(tmp_path):
    code='const r = await tools.exec_command({cmd: "slow"}); await tools.write_stdin({session_id:r.session_id});'
    records=call('local',0,12,code=code)+[item('process',1,11,process='17',command='slow')]
    result=receipt(tmp_path,records)
    expect(result,12)
    assert result['wrappers'][0]['uncovered_seconds']==2


def test_dynamic_poll_cannot_claim_an_unrelated_process_or_ambiguous_local_launches(tmp_path):
    records=call('local',0,12,code='const r = await tools.exec_command({cmd: "slow"}); await tools.write_stdin({session_id:other.session_id});')
    records+=[item('process',1,11,command='slow')]
    assert receipt(tmp_path,records)['state']=='unknown'
    code='const r = await tools.exec_command({cmd: "slow"}); const s = await tools.exec_command({cmd: "second"}); await tools.write_stdin({session_id:r.session_id});'
    records=call('local',0,12,code=code)+[item('process',1,11,command='slow'),item('process2',2,10,process='2',command='second')]
    assert receipt(tmp_path,records,name='ambiguous.jsonl')['state']=='unknown'


def test_empty_native_evidence_is_unknown_but_a_real_model_only_session_costs_zero(tmp_path):
    path=tmp_path/'empty.jsonl';path.write_text('')
    assert account_tool_time([path])['state']=='unknown'
    records=[{'type':'event_msg','timestamp':stamp(1),'payload':{'type':'item_completed','item':{'type':'Reasoning','id':'reason'}}}]
    expect(receipt(tmp_path,records,name='model_only.jsonl'),0)
