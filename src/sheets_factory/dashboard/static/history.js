// Independent read-only viewer additions. No production events or tasks change.
'use strict';
labels.ready='待 Harbor 验证';
labels.constructing='构造中';
labels.harbor_validation='Harbor 验证中';
labels.shortfall='题量不足';
labels.evidence_incomplete='计时证据不完整';
const historyStageFilter=elem('select');
historyStageFilter.id='filter-stage';
historyStageFilter.setAttribute('aria-label','阶段');
historyStageFilter.add(new Option('全部阶段',''));
$('filter-status').after(historyStageFilter);
historyStageFilter.addEventListener('change',()=>renderTable());
const historyTab=elem('button','tab','节点明细');
historyTab.dataset.tab='node_attempts';
document.querySelector('.tabs').append(historyTab);
historyTab.addEventListener('click',()=>{state.tab='node_attempts';document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===historyTab));$('search').value='';$('filter-status').value='';updateStatusFilter();renderTable();});
const historyRows=currentRows;
currentRows=function(){const stage=historyStageFilter.value;return historyRows().filter(row=>!stage||first(row.stage,row.node_id,row.node,'')===stage);};
const historyRender=render;
render=function(){
 const previous=historyStageFilter.value;
 historyStageFilter.replaceChildren(new Option('全部阶段',''));
 for(const n of rows(state.snapshot.nodes))historyStageFilter.add(new Option(nodeName(n),first(n.node_id,n.node)));
 historyStageFilter.value=previous;
 historyRender();
 const m=state.snapshot.metrics||{};
 text('candidate-sub','候选 '+fmt(m.candidates)+' · 合格 '+fmt(m.qualified)+' · 待验证 '+fmt(m.ready));
 $('calls').parentElement.querySelector('.label').textContent='LLM 调用 · 活动 '+fmt(m.active_llm_calls);
 document.querySelector('.main-grid .panel:first-child .panelhead small').textContent='完成尝试累计耗时；Token 为已知输入 + 输出，缓存已包含';
};
renderNodes=function(list){
 const parent=$('nodes');parent.replaceChildren();
 if(!list.length){parent.append(elem('div','empty','尚无阶段记录'));return;}
 for(const n of list.slice().sort((a,b)=>Number(b.status==='running')-Number(a.status==='running'))){
  const row=elem('div','node'),icon=elem('div','nodeicon '+(n.status==='running'?'live':'done'),n.status==='running'?'◌':'✓');
  const body=elem('div');body.append(elem('div','nodename',nodeName(n)));
  body.append(elem('div','nodemeta',fmt(n.count)+' 次 · 完成 '+fmt(n.completed)+' · 失败 '+fmt(n.failed_count)+' · 活动 '+fmt(n.running_count)));
  body.append(elem('div','nodemeta','已知 '+fmt(n.total_tokens)+' tokens · 输入 '+fmt(n.input_tokens)+'（缓存 '+fmt(n.cached_input_tokens)+'）· 输出 '+fmt(n.output_tokens)+(n.unknown_usage_calls?' · '+n.unknown_usage_calls+' 次用量待补':'')));
  const right=elem('div','nodeduration',duration(n.cumulative_ms));
  right.append(elem('small',null,'已完成累计'));
  if(n.running_count)right.append(elem('small',null,'运行中合计 '+duration(n.running_elapsed_ms)));
  row.append(icon,body,right);parent.append(row);
 }
};
const historyTime=renderTime;
renderTime=function(){historyTime();const r=state.snapshot.run||{};if(/^(completed|shortfall|failed|cancelled)$/.test(r.status)&&num(r.wall_seconds)!==null)text('wall-time',duration(r.wall_seconds*1000));};
const historyTable=renderTable;
renderTable=function(){
 if(!['node_attempts','llm_calls'].includes(state.tab)){historyTable();return;}
 const container=$('table');container.replaceChildren();
 const search=$('search').value.toLowerCase(),status=$('filter-status').value;
 const candidates=currentRows().filter(r=>(!search||JSON.stringify(r).toLowerCase().includes(search))&&(!status||first(r.status,r.level,'')===status));
 const list=candidates.slice().reverse().slice(0,500);
 text('row-count','显示 '+list.length+' / '+candidates.length+' 条匹配');
 if(!list.length){container.append(elem('div','empty','该阶段暂无匹配记录'));return;}
 const llm=state.tab==='llm_calls';
 const names=llm?['角色 / 模型','阶段','任务','状态','耗时','输入 / 缓存 / 输出 Token','调用标识']:['阶段','任务','版本','状态','耗时','开始时间'];
 const table=elem('table'),head=elem('thead'),tr=elem('tr');for(const name of names)tr.append(elem('th',null,name));head.append(tr);table.append(head);
 const body=elem('tbody');for(const r of list){const tr=elem('tr');if(llm){const model=elem('div',null,first(r.role,'—'));model.append(elem('div','cellsub',first(r.model,'—')));cell(tr,model);cell(tr,nodeName({node_id:r.stage}));cell(tr,r.task_id,'mono');cell(tr,badge(r.status));const elapsed=cell(tr,duration(r.duration_ms));if(r.status==='running'&&r.started_at)elapsed.dataset.liveStart=r.started_at;cell(tr,fmt(r.input_tokens)+' / '+fmt(r.cached_input_tokens)+' / '+fmt(r.output_tokens));cell(tr,r.call_id,'mono');}else{cell(tr,nodeName(r));cell(tr,r.task_id,'mono');cell(tr,first(r.revision,0));cell(tr,badge(r.status));const elapsed=cell(tr,duration(r.duration_ms));if(r.status==='running'&&r.started_at)elapsed.dataset.liveStart=r.started_at;const started=timestamp(r.started_at);cell(tr,started===null?'—':new Date(started).toLocaleString('zh-CN',{hour12:false}),'mono');}body.append(tr);}table.append(body);container.append(table);
};
// Original page listeners captured their table-rendering function before this
// extension loaded. Run the enhanced renderer afterwards for these controls.
$('search').addEventListener('input',()=>renderTable());
$('filter-mode').addEventListener('change',()=>renderTable());
$('filter-status').addEventListener('change',()=>renderTable());
setInterval(()=>renderTime(),1000);
