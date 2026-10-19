/* A chronological public work session. Provider-private reasoning is never projected. */
((root)=>{
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const time=at=>finite(at)?new Date(at*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):'时间未记录';
  const names={read_spec:'读取官方规格',list_candidates:'检查冻结候选池',read_candidate:'读取完整候选源码',review_candidate:'独立源码复核',nominate_candidate:'选择送测版本',read_file:'读取文件',ls:'查看目录',grep:'搜索源码',glob:'查找文件',edit_file:'修改源码',write_file:'写入文件',run_python:'辅助检查',simulate_kernel:'编译与本地仿真',compile_kernel:'仅编译 · 官测诊断',propose_local_cases:'补充本地测试假设',list_local_cases:'读取本地测试覆盖',read_simulation_results:'读取实验诊断',inspect_policy:'检查硬约束',record_experiment_plan:'登记实验假设',report_progress:'公开工作说明',read_judge_status:'读取官测反馈',queue_official_test:'冻结候选',task:'成员协作',write_todos:'更新计划'};
  const parse=v=>{if(typeof v!=='string')return v||{};try{return JSON.parse(v);}catch{return {};}};
  const pretty=v=>{try{return JSON.stringify(JSON.parse(v),null,2);}catch{return String(v??'');}};

  // ---- official API values are microseconds; absent values stay unknown ----
  function officialCases(official,ids=[]){
    return (official?.result||[]).map((c,i)=>{
      const ratio=c.precision_ratio,index=ids.indexOf(c.testcase_id);
      return {number:index<0?i+1:index+1,testcase_id:c.testcase_id,status:c.testcase_status,
        error_percent:finite(ratio)&&ratio>=0&&ratio<=1?(1-ratio)*100:null,
        time_us:finite(c.time)?c.time:null,best_time_us:finite(c.best_time)?c.best_time:null};
    }).sort((a,b)=>a.number-b.number);
  }
  const formatTime=value=>!finite(value)?'未提供':value>=1000?(value/1000).toFixed(2)+'ms':value.toFixed(2)+'μs';
  function caseTable(cases){
    return `<div class="official-cases-scroll"><table class="official-cases"><thead><tr><th>测试点</th><th>结果</th><th>输出错误占比</th><th>用时</th><th>最优用时</th></tr></thead><tbody>${cases.map(c=>`<tr class="${c.status&&c.status!=='Pass'?'case-failed':''}"><td title="${esc(c.testcase_id)}">${esc(c.number)}</td><td>${esc(c.status||'未提供')}</td><td title="${esc(c.error_percent)}">${finite(c.error_percent)?c.error_percent.toFixed(2)+'%':'未提供'}</td><td title="${esc(c.time_us)} μs">${formatTime(c.time_us)}</td><td title="${esc(c.best_time_us)} μs">${formatTime(c.best_time_us)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  // ---- retain all rounds, correlate streamed output and actual tool returns --
  function timeline(events,team,operations=[],now=Date.now()/1000){
    const rows=[],calls=new Map(),tools=new Map(),runs=new Map(),last=new Map(),receipts=new Map();
    const judgeEvents=['judge.submitted','judge.submission.updated','judge.candidate.selected','candidate.reviewed'];
    const own=[...new Map(events.filter(e=>e.team===team||team==='controller'&&judgeEvents.includes(e.kind)).map(e=>[e.seq,e])).values()].sort((a,b)=>a.seq-b.seq);
    let currentRun=null;
    const call=(id,e)=>{
      if(!calls.has(id)){
        const row={type:'call',id,seq:e.seq,at:e.at,run:e.data?.run_id||currentRun,agent:e.data?.agent||'coordinator',text:'',notes:[],tools:[],drafts:[],patches:[],state:'running',started:null};
        calls.set(id,row);rows.push(row);
      }
      return calls.get(id);
    };
    const owner=e=>e.data?.model_call_id?call(e.data.model_call_id,e):last.get((e.data?.run_id||currentRun)+':'+(e.data?.agent||'coordinator'));
    for(const e of own){
      const d=e.data||{},kind=e.kind;
      if(['control.started','team.turn.started'].includes(kind)){
        const id=d.run_id||d.operation_id||'round-'+e.seq;currentRun=id;
        if(!runs.has(id)){const row={type:'round',id,seq:e.seq,at:e.at,model:d.model||'',state:'running'};runs.set(id,row);rows.push(row);}
        else if(d.model)runs.get(id).model=d.model;
      }
      if(['team.turn.completed','team.turn.failed','team.turn.cancelled','control.completed','control.failed','control.cancelled'].includes(kind)){
        const id=d.run_id||d.operation_id||currentRun;if(runs.has(id))runs.get(id).state=kind.split('.').at(-1);
        if(kind.endsWith('failed')||kind.endsWith('cancelled'))rows.push({type:'notice',id:'end-'+e.seq,seq:e.seq,at:e.at,title:kind.endsWith('failed')?'本轮中断':'本轮已停止',text:d.message||'工作区与已记录的实验保留。',bad:true});
      }
      if(kind==='model.started'){
        const row=call(d.model_call_id||'call-'+e.seq,e);Object.assign(row,{started:e.at,model:d.model||'',profile:d.model_profile||'',effort:d.effort||''});
        last.set(row.run+':'+row.agent,row);
      }
      if(kind==='model.output.delta'){
        const row=call(d.model_call_id||'stream-'+e.seq,e);row.text+=d.text||'';row.truncated ||= Boolean(d.display_truncated);
        for(const part of d.tools||[]){let draft=row.drafts.find(t=>t.index===part.index);if(!draft){draft={index:part.index,name:'',args:''};row.drafts.push(draft);}draft.name+=part.name||'';draft.args+=part.args||'';}
      }
      if(kind==='agent.message'&&d.model_call_id){const row=call(d.model_call_id,e);row.text=d.text||'';row.truncated=Boolean(d.truncated);}
      if(kind==='agent.message'&&!d.model_call_id&&d.text)rows.push({type:'notice',id:'message-'+e.seq,seq:e.seq,at:e.at,title:'模型公开说明',text:d.text});
      if(kind==='model.completed'){
        const row=call(d.model_call_id||'call-'+e.seq,e);Object.assign(row,{state:'completed',ended:e.at,duration:d.duration_ms,usage:d.usage||{},requests:d.tool_requests||[]});
        last.set(row.run+':'+row.agent,row);
      }
      if(kind==='tool.started'){
        let row=owner(e);
        if(!row){row=call('tools-'+e.seq,e);row.state='unlinked';}
        const args=parse(d.input),t={id:String(d.tool_call||e.seq),name:d.tool||'tool',seq:e.seq,at:e.at,input:d.input||'',detail:args.file_path||args.path||args.script_path||'',state:'running',output:'',patches:[]};
        row.tools.push(t);tools.set(t.id,t);
      }
      if(['tool.completed','tool.failed'].includes(kind)){
        let t=tools.get(String(d.tool_call));
        if(!t){const row=owner(e)||call('tools-'+e.seq,e);t={id:String(d.tool_call||e.seq),name:d.tool||'tool',seq:e.seq,at:null,input:'',detail:'',patches:[]};row.tools.push(t);tools.set(t.id,t);}
        const result=parse(d.output),job=result.job||result;
        Object.assign(t,{output:d.output||'',ended:e.at,evidence:e.seq,truncated:d.truncated,state:kind==='tool.failed'||result.error?'failed':job.state==='failed'?'experiment-failed':'completed'});
      }
      if(kind==='workspace.patch'){
        const patch={seq:e.seq,path:d.path,patch:d.patch||'',truncated:d.truncated,source:d.source_sha256};
        const t=tools.get(String(d.tool_call));if(t)t.patches.push(patch);
        else rows.push({type:'patch',id:'patch-'+e.seq,seq:e.seq,at:e.at,...patch});
      }
      if(kind==='agent.progress'){
        const row=owner(e);const note={id:'progress-'+e.seq,title:'工作说明',text:d.summary||'',next:d.next_action||''};
        if(row)row.notes.push(note);else rows.push({type:'notice',seq:e.seq,at:e.at,...note});
      }
      if(kind==='iteration.planned'&&d.task?.plan){
        const p=d.task.plan,note={id:'plan-'+e.seq,title:'公开分析摘要',text:p.hypothesis,change:p.change,next:p.validation};
        const row=owner(e);if(row)row.notes.push(note);else rows.push({type:'notice',seq:e.seq,at:e.at,...note});
      }
      if(kind==='iteration.blocked')rows.push({type:'notice',id:'blocked-'+e.seq,seq:e.seq,at:e.at,title:'任务等待新证据',text:d.message,bad:true});
      if(kind==='judge.selector.message')rows.push({type:'notice',id:'judge-note-'+e.seq,seq:e.seq,at:e.at,title:'Judger 公开结论',text:d.text});
      if(kind==='judge.selector.failed')rows.push({type:'notice',id:'judge-error-'+e.seq,seq:e.seq,at:e.at,title:'Judger 执行失败',text:d.message,bad:true});
      if(kind==='candidate.reviewed')rows.push({type:'notice',id:'review-'+e.seq,seq:e.seq,at:e.at,title:d.ready?'源码复核完成':'源码复核未通过',text:d.notes||d.message||'详见候选复核记录',bad:d.ready===false});
      if(kind==='judge.submitted')rows.push({type:'notice',id:'submitted-'+e.seq,seq:e.seq,at:e.at,title:'已提交 CANN Judge',text:`${d.submission_id} · 源码 ${(d.source_sha256||'').slice(0,8)}`});
      if(kind==='simulation.status.updated'){
        const key=d.job_id;if(!receipts.has(key)){const row={type:'receipt',id:'receipt-'+key,seq:e.seq,at:e.at,title:'本地实验回执'};receipts.set(key,row);rows.push(row);}
        Object.assign(receipts.get(key),{state:d.state,text:d.evaluation_mode==='compile-only'?`${d.compile_pass?'编译通过 · 未执行数值校验':d.state==='failed'?'编译失败':'编译中'} · ${(d.source_sha256||'').slice(0,8)}`:`${d.passed_cases??0}/${d.requested_cases??0} 本地用例 · ${d.phase||d.state} · ${(d.source_sha256||'').slice(0,8)}`,evidence:e.seq,bad:d.state==='failed'});
      }
      if(kind==='judge.submission.updated'){
        const id=d.submission_id||d.candidate_id||e.seq,key='judge-'+id,r=d.official||{};
        if(!receipts.has(key)){const row={type:'receipt',id:key,seq:e.seq,at:e.at,title:'独立 Judger 官测回执'};receipts.set(key,row);rows.push(row);}
        const cases=officialCases(r,d.official_testcase_ids);Object.assign(receipts.get(key),{state:r.status,text:`${r.status||'等待回执'} · ${cases.filter(c=>c.status==='Pass').length}/${cases.length} · 提交 ${id}`,cases,source:d.source_sha256,evidence:e.seq,bad:r.status==='Wrong Answer'});
      }
    }
    const active=new Set(operations.filter(o=>o.team===team&&o.state==='running').map(o=>o.id));
    for(const row of calls.values()){
      if(row.state==='running'&&!active.has(row.run))row.state='interrupted';
      row.elapsed=finite(row.duration)?row.duration/1000:finite(row.started)&&(row.ended||row.state==='running')?Math.max(0,(row.ended||now)-row.started):null;
      for(const t of row.tools)if(t.state==='running'&&!active.has(row.run))t.state='interrupted';
    }
    return rows.sort((a,b)=>a.seq-b.seq);
  }

  // ---- escaped, collapsible public explanations, tool output and code diffs --
  const diff=p=>`<pre class="session-diff">${String(p.patch).split('\n').map(line=>`<span class="${line.startsWith('+')?'added':line.startsWith('-')?'removed':''}">${esc(line)}\n</span>`).join('')}</pre>${p.truncated?'<p class="session-muted">差异已截取，完整源码见代码页。</p>':''}`;
  function markup(rows,opens=new Map()){
    const latest=rows.findLast(r=>r.type==='call')?.id;
    const isOpen=(key,defaultValue=false)=>opens.has(key)?opens.get(key):defaultValue;
    const duration=r=>r.elapsed===null?'耗时未记录':r.elapsed.toFixed(1)+'s';
    const note=n=>`<section class="session-note"><b>${esc(n.title)}</b><div class="session-prose">${esc(n.text)}</div>${n.change?`<div class="session-prose"><b>拟定改动</b> ${esc(n.change)}</div>`:''}${n.next?`<div class="session-next">${esc(n.next)}</div>`:''}</section>`;
    return rows.map(r=>{
      if(r.type==='round')return `<div class="session-round"><span>${time(r.at)} · 优化回合</span><span>${esc(r.model)} · ${esc({running:'进行中',completed:'已结束',failed:'中断',cancelled:'已停止'}[r.state]||r.state)}</span></div>`;
      if(r.type==='call'){
        const reads=r.tools.filter(t=>['read_file','ls','grep','glob'].includes(t.name)).length;
        const summary=r.text.trim().split('\n').find(Boolean)||r.notes.at(-1)?.text?.split('\n')[0]|| (reads?`读取 / 搜索 ${reads} 项`:r.tools.length?`${r.tools.length} 项工具操作`:'本次调用尚无公开说明');
        const title=r.text||r.notes.length?'分析说明':'模型生成';
        return `<article class="session-turn"><details class="session-call" data-fold-key="call-${esc(r.id)}"${isOpen('call-'+r.id,r.id===latest)?' open':''}><summary><span class="session-call-title">${title} <span data-call-duration="${esc(r.id)}">${duration(r)}</span></span><small>${esc(summary.slice(0,160))}</small><em>${esc(r.state==='running'?'处理中':r.state==='interrupted'?'已中断':'已返回')}</em></summary><div class="session-call-body"><div class="session-meta">${time(r.at)} · ${esc(r.agent)}${r.model?' · '+esc(r.model):''}${r.effort?' · '+esc(r.effort):''}${finite(r.usage?.output_tokens)?' · 输出 '+r.usage.output_tokens+' Token':''}</div>${r.text?`<div class="session-prose">${esc(r.text)}</div>`:!r.notes.length?'<p class="session-muted">模型未提供公开说明；下方为实际工具请求与结果。调用耗时包含生成与等待时间。</p>':''}${r.notes.map(note).join('')}${r.drafts?.length&&r.state==='running'?`<details class="session-tool" data-fold-key="draft-${esc(r.id)}"${isOpen('draft-'+r.id,true)?' open':''}><summary>工具请求 · 正在生成</summary>${r.drafts.map(t=>`<b>${esc(names[t.name]||t.name||'工具名接收中')}</b><pre>${esc(t.args)}</pre>`).join('')}</details>`:''}</div></details>${r.tools.map(t=>`<details class="session-tool" data-fold-key="tool-${esc(t.id)}"${isOpen('tool-'+t.id,t.state==='running')?' open':''}><summary><span>${esc(names[t.name]||t.name)}${t.detail?' · '+esc(t.detail):''}</span><em>${esc({running:'进行中',completed:'已返回',failed:'失败',interrupted:'已中断','experiment-failed':'实验失败'}[t.state]||t.state)}</em></summary><div class="session-meta">${time(t.at)}${t.at&&t.ended?' · '+Math.max(0,t.ended-t.at).toFixed(1)+'s':''}</div>${t.input?`<b>请求</b><pre>${esc(pretty(t.input))}</pre>`:''}<b>实际返回</b><pre>${esc(t.output||'等待工具结果…')}</pre>${t.truncated?'<p class="session-muted">此返回已截取，原始实验回执可单独查看。</p>':''}${t.evidence?`<button type="button" class="text-button" data-evidence="${t.evidence}">查看事件证据 ↗</button>`:''}</details>${t.patches.map(p=>`<details class="session-patch" data-fold-key="patch-${p.seq}"${isOpen('patch-'+p.seq)?' open':''}><summary>实际代码差异 · ${esc(p.path)} · ${esc(p.source?.slice(0,8))}</summary>${diff(p)}</details>`).join('')}`).join('')}${r.truncated?'<p class="session-muted">公开输出已截取。</p>':''}</article>`;
      }
      if(r.type==='patch')return `<details class="session-patch"><summary>实际代码差异 · ${esc(r.path)}</summary>${diff(r)}</details>`;
      return `<section class="session-notice${r.bad?' failed':''}"><div class="session-meta">${time(r.at)}${r.state?' · '+esc(r.state):''}</div>${note(r)}${r.cases?.length?`<details data-fold-key="cases-${esc(r.id)}"${isOpen('cases-'+r.id)?' open':''}><summary>完整官测结果 · ${r.cases.length} 点</summary><p class="session-meta">源码 ${esc(r.source||'未记录')}</p>${caseTable(r.cases)}</details>`:''}${r.evidence?`<button type="button" class="text-button" data-evidence="${r.evidence}">查看回执 ↗</button>`:''}</section>`;
    }).join('')||'<p class="session-muted">等待实际工作会话。模型说明、工具结果与实验回执将在这里连续显示。</p>';
  }

  // ---- preserve user folds and scroll position while following a live session --
  class View{
    constructor(element){
      this.element=element;this.opens=new Map();this.follow=true;this.key='';
      element.addEventListener('click',e=>{const summary=e.target.closest('summary'),details=summary?.parentElement;if(details?.dataset.foldKey)this.opens.set(details.dataset.foldKey,!details.open);});
      element.addEventListener('scroll',()=>{this.follow=element.scrollHeight-element.clientHeight-element.scrollTop<60;});
    }
    update(rows){
      const key=JSON.stringify(rows.map(r=>[r.id,r.state,r.text,r.notes,r.tools,r.drafts,r.patches,r.evidence,r.cases,r.model,r.usage]));
      if(key===this.key){for(const r of rows.filter(r=>r.type==='call')){const el=[...this.element.querySelectorAll('[data-call-duration]')].find(el=>el.dataset.callDuration===r.id);if(el)el.textContent=r.elapsed===null?'耗时未记录':r.elapsed.toFixed(1)+'s';}return;}
      const top=this.element.scrollTop,follow=this.follow;this.key=key;
      this.element.innerHTML=markup(rows,this.opens);
      this.element.scrollTop=follow?this.element.scrollHeight:top;
    }
    latest(){this.follow=true;this.element.scrollTop=this.element.scrollHeight;}
  }
  const api={timeline,markup,View,officialCases,caseTable,formatTime};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.JustKernelConversation=api;
})(typeof window==='undefined'?{}:window);
