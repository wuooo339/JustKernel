/* Public progress and chronological evidence replay. No private reasoning fields. */
((root)=>{
  'use strict';
  function teamProgress(events,team,operations=[],baseline=null){
    const own=events.filter(e=>e.team===team),start=own.findLast(e=>e.kind==='control.started');
    const current=start?own.filter(e=>e.seq>=start.seq):own;
    const active=operations.some(o=>o.team===team&&o.state==='running');
    const latest=current.at(-1),tool=current.findLast(e=>e.kind==='tool.started');
    const names={read_file:'阅读工程与规格',ls:'检查工程目录',write_file:'编写代码',edit_file:'修正代码',task:'成员协作与复核',inspect_policy:'检查硬约束',record_review:'记录源码复核',queue_official_test:'冻结候选工程',run_python:'运行静态辅助检查',write_todos:'更新开发计划',read_judge_status:'读取官方反馈',read_judge_candidate:'学习公开候选',simulate_kernel:'本队独立仿真',read_simulation_results:'分析本队实验反馈'};
    const planEvent=current.findLast(e=>e.kind==='tool.started'&&e.data?.tool==='write_todos');
    let plan=[];try{plan=JSON.parse(planEvent?.data.input||'{}').todos||[];}catch{}
    const message=current.findLast(e=>e.kind==='agent.message'&&e.data?.text)?.data.text||'';
    const failure=current.findLast(e=>['control.failed','team.turn.failed'].includes(e.kind));
    const staged=current.findLast(e=>e.kind==='judge.candidate.staged');
    const slot=current.findLast(e=>e.kind.startsWith('model.slot.'));
    const lastModel=current.findLast(e=>e.kind==='stage.updated'&&e.data?.message==='Model planning / tool selection');
    const official=current.findLast(e=>['candidate.reviewed','judge.submit.started','judge.submitted','judge.submission.updated'].includes(e.kind));
    const officialTitle=official?.kind==='judge.submission.updated'?'官测状态：'+(official.data.official?.status||'等待回执'):official?.kind==='judge.submitted'?'官测已提交，等待回执':official?.kind==='judge.submit.started'?'正在提交官测':official?.kind==='candidate.reviewed'?(official.data.ready?'源码已复核，等待官测':'复核发现问题，等待修正'):'';
    let title=active?(slot?.kind==='model.slot.waiting'?'等待团队执行槽位':lastModel&&(!tool||lastModel.seq>tool.seq)?'模型正在生成下一步':names[tool?.data.tool]||'团队正在工作'):failure?'任务中断，可继续保存的会话':officialTitle|| (staged?'候选已冻结，等待官测':latest?'本轮结束，等待下一步':'等待启动');
    return {title,active,plan,done:plan.filter(p=>p.status==='completed').length,
      changes:new Set(own.filter(e=>e.kind==='workspace.changed'&&e.data?.source_sha256&&e.data.source_sha256!==baseline).map(e=>e.data.source_sha256)).size,
      summary:failure&&!active?failure.data.message:message.replace(/^#+\s*/,'').slice(0,220),
      lastAt:latest?.at||null};
  }
  function teamMonitor(events,team,operations=[],simulationJobs=[],now=Date.now()/1000,simulatorAvailable=null){
    const own=events.filter(e=>e.team===team),start=own.findLast(e=>e.kind==='control.started');
    const current=start?own.filter(e=>e.seq>=start.seq):own;
    const lastModel=current.findLast(e=>['model.started','model.output.delta','agent.message','model.completed'].includes(e.kind));
    const callId=lastModel?.data.model_call_id;
    const callEvents=callId?current.filter(e=>e.data.model_call_id===callId):[];
    const begin=callEvents.find(e=>e.kind==='model.started');
    const end=callEvents.findLast(e=>e.kind==='model.completed');
    let text='',tools=new Map(),truncated=false;
    for(const e of callEvents){
      if(e.kind==='model.output.delta'){
        text+=e.data.text||'';truncated ||= Boolean(e.data.display_truncated);
        for(const part of e.data.tools||[]){
          const item=tools.get(part.index)||{name:'',args:''};
          item.name+=part.name||'';item.args+=part.args||'';tools.set(part.index,item);
        }
      }
      if(e.kind==='agent.message'&&e.data.text)text=e.data.text;
    }
    if(!callId)text=current.findLast(e=>e.kind==='agent.message')?.data.text||'';
    const completed=new Map();
    for(const e of current.filter(e=>e.kind==='model.completed'))completed.set(e.data.model_call_id||e.seq,e.data.usage||{});
    const usage=[...completed.values()].reduce((a,u)=>({input:a.input+(Number(u.input_tokens)||0),output:a.output+(Number(u.output_tokens)||0),reported:a.reported||typeof u.input_tokens==='number'||typeof u.output_tokens==='number'}),{input:0,output:0,reported:false});
    const labels={read_file:'阅读文件',ls:'检查目录',write_file:'写入源码',edit_file:'修改源码',task:'委派成员',inspect_policy:'自查硬约束',simulate_kernel:'运行独立仿真',read_simulation_results:'读取仿真诊断',queue_official_test:'冻结完整工程',record_review:'复核冻结版本',read_judge_status:'读取官测反馈',read_judge_candidate:'学习公开候选',send_team_message:'通过 A2A 发送消息',read_team_messages:'读取协作消息',run_python:'辅助分析',write_todos:'制定计划'};
    const rows=new Map();
    for(const e of current){
      const d=e.data||{};
      if(e.kind==='tool.started'){
        let detail='';try{const args=JSON.parse(d.input||'{}');detail=args.file_path||args.path||args.subagent_type||args.recipient||'';}catch{}
        rows.set(d.tool_call||e.seq,{seq:e.seq,at:e.at,agent:d.agent||'coordinator',title:labels[d.tool]||d.tool,detail,state:'进行中'});
      }
      if(['tool.completed','tool.failed'].includes(e.kind)){
        const row=rows.get(d.tool_call);if(row){row.state=e.kind==='tool.failed'?'执行失败':'已返回';row.evidence=e.seq;}
      }
    }
    const incoming=events.filter(e=>e.kind==='team.message'&&e.data.recipient===team).slice(-4);
    for(const e of incoming)rows.set('message-'+e.seq,{seq:e.seq,at:e.at,agent:e.team,title:e.data.topic==='sota'?'收到已验证 SOTA':e.data.topic==='judge-feedback'?'收到官测反馈':'收到协作消息',detail:e.data.transport==='a2a'?'A2A 已送达':'共享收件箱',state:'已送达'});
    const jobs=simulationJobs.filter(j=>j.team===team);
    const simulation=jobs.find(j=>j.state==='running')||jobs.find(j=>j.state==='queued')||jobs.find(j=>j.state!=='cancelled')||jobs[0];
    const phaseLabels={configure:'配置构建',compile:'编译 Host 与 Kernel',package:'打包算子',install:'部署算子',runner:'准备执行程序',inputs:'生成本队输入',completed:'实验完成'};
    const simulationPhase=phaseLabels[simulation?.phase]||String(simulation?.phase||'等待 CPU 资源').replace(/^waiting-profiler:/,'等待性能采集槽 · ').replace(/^simulate:/,'运行用例 ');
    const active=operations.some(o=>o.team===team&&o.state==='running');
    const modelBusy=Boolean(begin&&!end&&active);
    const simulatorOffline=simulatorAvailable===false&&['running','queued'].includes(simulation?.state);
    const title=simulatorOffline?'等待仿真环境恢复（Worker 离线）':simulation?.state==='running'?'独立仿真：'+simulationPhase:simulation?.state==='queued'?'等待 CPU 仿真槽位':teamProgress(events,team,operations).title;
    return {title,usage,text:text.slice(-16000),tools:[...tools.values()].map(t=>({...t,args:t.args.slice(-12000)})),truncated,
      modelBusy,agent:lastModel?.data.agent||'coordinator',elapsed:begin?Math.max(0,Math.floor((end?.at||now)-begin.at)):null,
      lastAt:own.at(-1)?.at||null,simulation,simulationPhase,simulatorOffline,
      steps:[...rows.values()].sort((a,b)=>b.seq-a.seq).slice(0,14)};
  }
  function projectRecord(record,count){
    const events=record.events.slice(0,count),snapshot=record.snapshot||{},operations=new Map(),runs=new Map(),jobs=new Map(),simulations=new Map(),notices=new Map();
    const continuous=events.findLast(e=>e.kind==='swarm.continuous.configured')?.data||{enabled:false};
    let simulation=snapshot.simulation?{...snapshot.simulation,available:null}:null;
    const known=new Set(),active=new Map();
    for(const e of events){
      const d=e.data||{};
      if(e.kind==='team.joined'){known.add(e.team);active.set(e.team,1);}
      if(e.kind==='team.left')active.set(e.team,0);
      if(e.kind==='control.started')operations.set(d.operation_id,{id:d.operation_id,team:e.team,kind:d.action,state:'running'});
      if(['control.completed','control.failed','control.cancelled'].includes(e.kind)&&operations.has(d.operation_id))Object.assign(operations.get(d.operation_id),{state:e.kind.split('.')[1],error:d.message});
      if(e.kind==='team.turn.started')runs.set(d.run_id,{id:d.run_id,team:e.team,model:d.model,state:'running'});
      if(['team.turn.completed','team.turn.failed','team.turn.cancelled'].includes(e.kind)&&runs.has(d.run_id))runs.get(d.run_id).state=e.kind.split('.').at(-1);
      if(e.kind==='candidate.created')jobs.set(d.job_id,{id:d.job_id,team:e.team,state:'queued'});
      if(['evaluation.completed','evaluation.failed'].includes(e.kind)&&jobs.has(d.job_id))jobs.get(d.job_id).state=e.kind==='evaluation.completed'?'completed':'failed';
      if(e.kind==='simulation.status.updated')simulations.set(d.job_id,{...d,id:d.job_id,team:e.team,seq:e.seq});
      if(e.kind==='simulation.worker.updated')simulation={...simulation,...d};
      if(e.kind==='a2a.notice.queued')notices.set(d.delivery_id,{id:d.delivery_id,...d,state:'pending'});
      if(['a2a.notice.delivered','a2a.notice.retry'].includes(e.kind)&&notices.has(d.delivery_id))Object.assign(notices.get(d.delivery_id),{state:e.kind==='a2a.notice.delivered'?'delivered':'pending',error:d.error});
    }
    const hasJoins=record.events.some(e=>e.kind==='team.joined');
    return {...snapshot,teams:(snapshot.teams||[]).filter(t=>!hasJoins||known.has(t.id)).map(t=>({...t,active:active.get(t.id)??t.active})),
      events,continuous,operations:[...operations.values()],runs:[...runs.values()],jobs:[...jobs.values()],simulation,simulation_jobs:[...simulations.values()].sort((a,b)=>b.seq-a.seq),a2a_notices:[...notices.values()],
      experiences:events.filter(e=>e.kind==='skill.created').map(e=>({id:e.data.skill_id,team:e.team,data:e.data})),
      public:[],latest:events.findLast(e=>e.kind==='evaluation.completed')?.data||null};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={teamProgress,teamMonitor,projectRecord};
  else root.JustKernelActivity={teamProgress,teamMonitor,projectRecord};
})(typeof window==='undefined'?{}:window);
