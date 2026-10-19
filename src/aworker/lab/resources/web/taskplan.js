/* Actual model todos and evidence-backed fallback. Never advance on a timer. */
((root)=>{
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const parse=v=>{try{return typeof v==='string'?JSON.parse(v):v||{};}catch{return {};}};
  function plan(events,team,task=null){
    const own=events.filter(e=>e.team===team).sort((a,b)=>a.seq-b.seq);
    const start=own.findLast(e=>e.kind==='control.started'||e.kind==='team.turn.started');
    const current=start?own.filter(e=>e.seq>=start.seq):own,requests=new Map();let todos=null,seq=null;
    for(const e of current){
      const d=e.data||{};
      if(e.kind==='tool.started'&&d.tool==='write_todos')requests.set(String(d.tool_call),e);
      if(e.kind==='tool.completed'&&d.tool==='write_todos'&&!parse(d.output).error){
        const request=requests.get(String(d.tool_call)),items=parse(request?.data.input).todos;
        if(Array.isArray(items)){todos=items.filter(p=>p&&typeof p.content==='string'&&['pending','in_progress','completed'].includes(p.status));seq=e.seq;}
      }
    }
    if(todos?.length)return {kind:'model',label:'团队任务计划',hint:'任务状态由团队更新；验证结果单独记录。',seq,items:todos};
    if(!task?.plan)return {kind:'waiting',label:'当前调度任务',hint:'团队尚未发布细分计划；此处显示实际待办。',items:task?.next_action?[{content:task.next_action,status:task.phase==='blocked'?'failed':'in_progress',detail:task.evidence?.official_submission_id?'依据官测 '+task.evidence.official_submission_id:''}]:[]};
    const p=task.plan,build=task.last_result;
    const changed=Boolean(task.current_source&&task.starting_source&&task.current_source!==task.starting_source);
    const matching=Boolean(build?.source_sha256&&build.source_sha256===task.current_source);
    const returned=matching&&['completed','failed'].includes(build.state);
    return {kind:'evidence',label:'当前实验计划',hint:'根据实验登记、源码版本与真实回执更新。',items:[
      {content:'登记本轮实验假设',description:p.hypothesis,status:'completed',detail:'已登记待验证假设'},
      {content:'实施本轮源码修改',description:p.change,status:changed?'completed':'in_progress',detail:changed?'已产生源码修改':'等待实际修改'},
      {content:'执行计划中的验证',description:p.validation,status:returned?(build.state==='failed'?'failed':'completed'):changed?'in_progress':'pending',detail:matching?(build.evaluation_mode==='compile-only'?'仅编译 · 未验证精度':build.state):'等待当前源码的实验回执'}
    ]};
  }
  function judgePlan(events){
    const own=[...events].sort((a,b)=>a.seq-b.seq),start=own.findLast(e=>e.team==='controller'&&e.kind==='control.started');
    const current=start?own.filter(e=>e.seq>=start.seq):own;
    const tool=name=>current.filter(e=>e.team==='controller'&&e.data?.tool===name);
    const state=name=>tool(name).some(e=>e.kind==='tool.failed')?'failed':tool(name).some(e=>e.kind==='tool.completed')?'completed':tool(name).some(e=>e.kind==='tool.started')?'in_progress':'pending';
    const review=current.findLast(e=>e.kind==='candidate.reviewed');
    const nomination=current.findLast(e=>e.kind==='judge.candidate.selected');
    const submitted=current.findLast(e=>e.kind==='judge.submitted'&&(!nomination||e.data.candidate_id===nomination.data.candidate_id));
    const receipt=submitted&&current.findLast(e=>e.kind==='judge.submission.updated'&&e.data.submission_id===submitted.data.submission_id);
    const final=receipt&&!['Running','Pending','Judging','Compiling','Queued','Waiting'].includes(receipt.data.official?.status)&&receipt.data.official?.status;
    return {kind:'judge',label:'Judger · 复核与官测',hint:'工具成功、提交成功与官测全过是独立状态。',items:[
      {content:'读取规格与冻结候选',status:state('read_candidate')},
      {content:'独立审查完整源码',status:review?.data.ready===false?'failed':state('review_candidate'),detail:review?.data.ready===false?'复核发现问题 · 交回主队修正':''},
      {content:'选择本轮送测版本',status:nomination?'completed':state('nominate_candidate')},
      {content:'提交 CANN Judge',status:submitted?'completed':nomination?'in_progress':'pending',detail:submitted?.data.submission_id||''},
      {content:'收取官方反馈',status:final?'completed':submitted?'in_progress':'pending',detail:final||'等待回执'},
      {content:'所有官方测试点通过',status:final==='Pass'?'completed':final?'failed':'pending',detail:final&&final!=='Pass'?'未全过 · 反馈已记录':''}
    ]};
  }
  function markup(p,label){
    const done=p.items.filter(i=>i.status==='completed').length;
    return `<div class="task-plan-head"><span>${esc(label)}</span><b>${p.items.length?done+'/'+p.items.length:'—'}</b></div><p class="task-plan-kind">${esc(p.label)}</p><ol class="task-checklist">${p.items.map((item,i)=>`<li class="task-item ${esc(item.status)}"><span class="task-check">${item.status==='completed'?'✓':item.status==='in_progress'?'◉':item.status==='failed'?'!':String(i+1).padStart(2,'0')}</span><div><b>${esc(item.content.length>70?item.content.slice(0,70)+'…':item.content)}</b>${item.description||item.content.length>70?`<details class="task-description"><summary>展开详情</summary><p>${esc(item.description||item.content)}</p></details>`:''}${item.detail?`<small>${esc(item.detail)}</small>`:''}</div><em>${{completed:'完成',in_progress:'进行中',failed:'未通过',pending:'待执行'}[item.status]}</em></li>`).join('')}</ol>${p.items.length?'':'<p class="session-muted">等待团队发布本轮任务清单。</p>'}<p class="task-plan-hint">${esc(p.hint)}</p>`;
  }
  const api={plan,judgePlan,markup};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.JustKernelTaskPlan=api;
})(typeof window==='undefined'?{}:window);
