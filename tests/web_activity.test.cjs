const {test}=require('node:test');
const assert=require('node:assert/strict');
const {teamProgress,teamMonitor,projectRecord}=require('../src/aworker/lab/resources/web/activity.js');
const e=(seq,kind,data={},team='gpt-001')=>({seq,at:100+seq,kind,team,data});

test('malformed model todos never break the live supervision panel',()=>{
 for(const todos of ['not an array',{content:'wrong shape'},null,[null,'invalid',{content:'valid',status:'completed'}]]){
  const events=[e(1,'control.started'),e(2,'tool.started',{tool:'write_todos',input:JSON.stringify({todos})})];
  const result=teamProgress(events,'gpt-001');assert.ok(Array.isArray(result.plan));
  assert.doesNotThrow(()=>teamMonitor(events,'gpt-001'));
 }
});

test('diagnostic compilation never appears as full local correctness',()=>{
 const {iterationSummary}=require('../src/aworker/lab/resources/web/activity.js');
 const view=iterationSummary({phase:'awaiting-official',validation_mode:'official-feedback',
   evidence:{},last_result:{id:'fixture',evaluation_mode:'compile-only',compile_pass:true,functional_pass:false,cases:[],case_ids:['draft-01']}});
 assert.match(view.title,/诊断送测/);assert.match(view.result,/未执行数值验证/);
 assert.doesNotMatch(view.title,/完整验证通过/);assert.doesNotMatch(view.result,/本地通过|1\/1/);
});

test('repair task shows evidence, actual source and experiment outcome without inventing an official pass',()=>{
 const {iterationSummary}=require('../src/aworker/lab/resources/web/activity.js');
 const task={team:'gpt-001',phase:'full-validation',evidence:{official_submission_id:'official',status:'Wrong Answer',failed_cases:[{},{}]},
  starting_source:'oldsource',current_source:'newsource',experiment_count:1,
  plan:{hypothesis:'Fixture hypothesis',change:'Fixture source modification'},
  last_result:{id:'fixture-job',state:'completed',case_ids:['draft-01'],cases:[{pass:true}]},next_action:'Fixture full validation next'};
 const view=iterationSummary(task);
 assert.match(view.evidence,/Wrong Answer/);assert.match(view.result,/1\/1/);
 assert.match(view.source,/oldsourc.*newsourc/);assert.match(view.title,/完整验证/);
 assert.doesNotMatch(JSON.stringify(view),/官测通过|SOTA/);
 const record={snapshot:{iterations:[task]},events:[e(1,'iteration.created',{task:{...task,phase:'needs-plan',plan:null}}),e(2,'iteration.updated',{task})]};
 assert.equal(projectRecord(record,0).iterations.length,0);
 assert.equal(projectRecord(record,1).iterations[0].plan,null);
 assert.equal(projectRecord(record,2).iterations[0].plan.hypothesis,'Fixture hypothesis');
});

test('progress uses public output and actual plans, never private model reasoning',()=>{
 const events=[e(1,'control.started',{operation_id:'op',action:'run'}),e(2,'model.slot.acquired'),
 e(3,'tool.started',{tool:'write_todos',input:JSON.stringify({todos:[{content:'实现',status:'completed'},{content:'复核',status:'in_progress'}]})}),
 e(4,'workspace.changed',{source_sha256:'baseline'}),e(5,'workspace.changed',{source_sha256:'changed'}),e(6,'workspace.changed',{source_sha256:'changed'}),
 e(7,'agent.message',{text:'正在修复尾块对齐。',reasoning_content:'PRIVATE-REASONING'}),e(8,'tool.started',{tool:'edit_file'})];
 const p=teamProgress(events,'gpt-001',[{team:'gpt-001',state:'running'}],'baseline');
 assert.equal(p.title,'修正代码');assert.equal(p.done,1);assert.equal(p.changes,1);
 assert.equal(p.summary,'正在修复尾块对齐。');assert.ok(!JSON.stringify(p).includes('PRIVATE-REASONING'));
 const interrupted=teamProgress([...events,e(9,'control.failed',{message:'step limit'})],'gpt-001');
 assert.match(interrupted.title,/中断/);assert.equal(interrupted.summary,'step limit');
});

test('replay projects only events reached, without leaking future scores or completion',()=>{
 const events=[e(1,'team.joined',{runtime:'deepagents'}),e(2,'control.started',{operation_id:'op',action:'run'}),
 e(3,'team.turn.started',{run_id:'run'}),e(4,'candidate.created',{job_id:'job'}),
 e(5,'evaluation.completed',{job_id:'job',pass:true}),e(6,'control.completed',{operation_id:'op'}),
 e(7,'judge.submission.updated',{official:{status:'Pass',score:99}})];
 const record={events,snapshot:{continuous:{enabled:true},teams:[{id:'gpt-001',active:1},{id:'future-team',active:1}],operations:[{id:'op',state:'completed'}],public:[{score:99}]}};
 const first=projectRecord(record,4);
 assert.equal(first.operations[0].state,'running');assert.equal(first.jobs[0].state,'queued');
 assert.equal(first.latest,null);assert.equal(first.public.length,0);assert.equal(first.teams.length,1);
 assert.equal(first.continuous.enabled,false);
 assert.ok(!first.events.some(e=>e.kind==='judge.submission.updated'));
 const last=projectRecord(record,7);
 assert.equal(last.operations[0].state,'completed');assert.equal(last.jobs[0].state,'completed');
 assert.equal(last.latest.pass,true);
});

test('official progress appears in order and a newer model turn takes precedence',()=>{
 const events=[e(1,'judge.candidate.staged'),e(2,'candidate.reviewed',{ready:true}),
 e(3,'judge.submit.started'),e(4,'judge.submitted',{submission_id:'fixture-id'}),
 e(5,'judge.submission.updated',{official:{status:'Pass',score:12}})];
 assert.match(teamProgress(events.slice(0,2),'gpt-001').title,/已复核/);
 assert.match(teamProgress(events.slice(0,3),'gpt-001').title,/正在提交/);
 assert.match(teamProgress(events.slice(0,4),'gpt-001').title,/等待回执/);
 assert.match(teamProgress(events,'gpt-001').title,/Pass/);
 const next=[...events,e(6,'control.started',{operation_id:'next',action:'run'}),e(7,'tool.started',{tool:'edit_file'})];
 assert.equal(teamProgress(next,'gpt-001',[{team:'gpt-001',state:'running'}]).title,'修正代码');
});

test('supervision folds public deltas and tool arguments, with provider-reported usage only',()=>{
 const events=[e(1,'control.started',{operation_id:'op'}),e(2,'model.started',{model_call_id:'m',agent:'engineer'}),
 e(3,'model.output.delta',{model_call_id:'m',agent:'engineer',text:'修改',tools:[{index:0,name:'edit_file',args:'{"path":'}],reasoning_content:'PRIVATE'}),
 e(4,'model.output.delta',{model_call_id:'m',text:'归约',tools:[{index:0,name:'',args:'"kernel.h"}'}]})];
 const active=[{team:'gpt-001',state:'running'}];
 const live=teamMonitor(events,'gpt-001',active,[],110);
 assert.equal(live.text,'修改归约');assert.equal(live.modelBusy,true);assert.equal(live.elapsed,8);
 assert.equal(live.tools[0].args,'{"path":"kernel.h"}');assert.equal(live.usage.reported,false);
 assert.ok(!JSON.stringify(live).includes('PRIVATE'));
 events.push(e(5,'model.completed',{model_call_id:'m',usage:{input_tokens:11,output_tokens:7}}));
 const completed=teamMonitor(events,'gpt-001',active,[],110);
 assert.equal(completed.modelBusy,false);assert.deepEqual(completed.usage,{input:11,output:7,reported:true});
 events.push(e(6,'control.started',{operation_id:'next'}));
 assert.equal(teamMonitor(events,'gpt-001',active).usage.reported,false);
});

test('supervision distinguishes queued experiments, real tool returns and delivered A2A notices',()=>{
 const events=[e(1,'control.started',{operation_id:'op'}),e(2,'tool.started',{tool:'edit_file',tool_call:'t',agent:'engineer',input:'{"file_path":"/project/kernel.h"}'}),
 e(3,'tool.completed',{tool:'edit_file',tool_call:'t'}),
 e(4,'team.message',{recipient:'gpt-001',transport:'a2a',topic:'judge-feedback'},'judger')];
 const jobs=[{team:'gpt-001',state:'queued',id:'own-job'}];
 const p=teamMonitor(events,'gpt-001',[],jobs);
 assert.equal(p.title,'等待 CPU 仿真槽位');
 assert.equal(p.steps[0].title,'收到官测反馈');assert.equal(p.steps[0].detail,'A2A 已送达');
 assert.equal(p.steps[1].state,'已返回');assert.equal(p.steps[1].detail,'/project/kernel.h');
 const offline=teamMonitor(events,'gpt-001',[],jobs,110,false);
 assert.equal(offline.simulatorOffline,true);assert.match(offline.title,/离线/);
});

test('replay excludes future simulation results, output deltas and token totals',()=>{
 const events=[e(1,'simulation.status.updated',{job_id:'sim',state:'running',passed_cases:1,requested_cases:9}),
 e(2,'model.started',{model_call_id:'m'}),e(3,'model.output.delta',{model_call_id:'m',text:'visible now'}),
 e(4,'simulation.status.updated',{job_id:'sim',state:'completed',passed_cases:9,requested_cases:9}),
 e(5,'model.completed',{model_call_id:'m',usage:{input_tokens:100,output_tokens:100}}),
 e(6,'simulation.worker.updated',{available:false,state:'unavailable'},'controller')];
 const record={events,snapshot:{teams:[{id:'gpt-001',active:1}],simulation:{required:true,available:false},simulation_jobs:[{id:'future',state:'completed'}],a2a_notices:[{id:'future',state:'delivered'}]}};
 const projection=projectRecord(record,3);
 assert.equal(projection.simulation_jobs.length,1);assert.equal(projection.simulation_jobs[0].passed_cases,1);
 const progress=teamMonitor(projection.events,'gpt-001',[],projection.simulation_jobs);
 assert.equal(progress.text,'visible now');assert.equal(progress.usage.reported,false);
 assert.ok(!projection.simulation_jobs.some(j=>j.id==='future'));
 assert.deepEqual(projection.a2a_notices,[]);
 assert.equal(projection.simulation.available,null);
 assert.equal(projectRecord(record,6).simulation.available,false);
});
