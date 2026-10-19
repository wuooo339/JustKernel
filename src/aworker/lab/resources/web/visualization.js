/* Shared evidence projection for the live, recorded and explicitly simulated views. */
((root) => {
  'use strict';
  const COLORS = { generating:'#8daed5', testing:'#e6a078', passed:'#87b49b', revising:'#d38280', waiting:'#6c8ca5', queued:'#b3a0d0', unconfigured:'#61788a' };
  const STAGES = [['input','规格'],['search','搜索'],['policy','自查'],['queue','排队'],['execute','实测'],['verify','校验'],['share','共享'],['distill','蒸馏']];
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (value) => typeof value === 'number' && Number.isFinite(value);
  const modelGroup = (name) => /qwen|千问/i.test(name) ? 3 : /deepseek/i.test(name) ? 2 : /glm|zhipu/i.test(name) ? 1 : 0;

  // ---- visible connected teams and populated model clusters ----------------
  function connectedTeams(teams,models,recording=false){
    const configured=new Set(models.filter(m=>m.configured).map(m=>m.id));
    return teams.filter(t=>t.active&&(recording||configured.has(t.model)));
  }
  // ---- current model labels never replace durable team / artifact identity --
  function teamDisplayNames(teams,models){
    const profiles=new Map(models.map(m=>[m.id,m])),counts=new Map(),names=new Map();
    for(const team of teams.filter(t=>t.active).slice().sort((a,b)=>a.id.localeCompare(b.id))){
      const profile=profiles.get(team.model),provider=profile?.provider;
      const family=provider==='qwen'?'Qwen':provider==='deepseek'?'DeepSeek':['chatgpt','openai'].includes(provider)?'GPT':profile?.name||'团队';
      const serial=(counts.get(family)||0)+1;counts.set(family,serial);
      names.set(team.id,family+'-'+String(serial).padStart(3,'0'));
    }
    return names;
  }
  const nodeDisplayName=(nodes,name)=>nodes.find(n=>n.name===name)?.label||name;
  const visibleNode=n=>!['unregistered','excluded','unconfigured'].includes(n.state);
  function networkGroups(nodes){
    const labels=['GPT','GLM','DeepSeek','Qwen'],counts=new Map();
    nodes.filter(visibleNode).forEach(n=>{const key=modelGroup(n.groupKey||n.model);counts.set(key,(counts.get(key)||0)+1);});
    const count=counts.size;
    const centers=count===1?[[.5,.52]]:count===2?[[.27,.38],[.73,.68]]:count===3?[[.25,.38],[.75,.38],[.5,.76]]:[[.24,.34],[.76,.34],[.24,.76],[.76,.76]];
    const captions=count===1?[[50,8]]:count===2?[[25,9],[75,91]]:count===3?[[25,9],[75,9],[50,94]]:[[23,9],[77,9],[23,94],[77,94]];
    return [...counts.entries()].sort((a,b)=>a[0]-b[0]).map(([key,total],i)=>({key,count:total,label:labels[key],center:centers[i],caption:captions[i]}));
  }

  // ---- configured topology is separate from acknowledged message traffic --
  function networkProjection(nodes,events,at=Infinity){
    const connections=nodes.flatMap((n,i)=>visibleNode(n)?[{from:-1,to:i}]:[]);
    const indices=new Map(connections.map(e=>[nodes[e.to].name,e.to]));
    const endpoint=name=>['controller','judger'].includes(name)?-1:indices.get(name);
    const seen=new Set(),edges=new Map();let delivered=0,history=0;
    events.forEach((e,i)=>{
      if(e.kind!=='team.message'||!number(e.at)||e.at>at)return;
      const data=e.data||{},from=endpoint(e.team),to=endpoint(data.recipient);
      if(from===undefined||to===undefined||from===to)return;
      const id=data.message_id||e.seq||'event-'+i;
      if(seen.has(id))return;seen.add(id);
      const confirmed=data.transport==='a2a';confirmed?delivered++:history++;
      const key=from+':'+to,previous=edges.get(key);
      // A local historical note must not hide a newer confirmed delivery.
      if(!previous||e.at>=previous.at)edges.set(key,{from,to,at:e.at,confirmed,count:(previous?.count||0)+1});
    });
    return {connections,edges:[...edges.values()].sort((a,b)=>a.at-b.at).slice(-80),delivered,history};
  }

  // ---- traffic pulses require a real delivery at the displayed time -------
  function messageActive(edge,at,playing=true){
    return playing&&edge.confirmed&&at>=edge.at&&at-edge.at<15;
  }

  // ---- explicit display preference and actual job activity -----------------
  const motionEnabled=(mode,prefersReduced=false)=>mode==='on'||mode!=='off'&&!prefersReduced;
  const workActive=(node,playing=true)=>playing&&['generating','testing'].includes(node.state);

  // ---- size reflects visible population and verified official evidence -----
  function networkNodeSize(count,width,height,evidence={},selected=false,maxScore=0){
    const dense=count>16,base=Math.min(Math.max(Math.min(width,height)/(Math.sqrt(Math.max(count,1))*2.6),dense?10:38),dense?26:76);
    const gain=number(evidence.score)&&maxScore>0 ? .35*Math.max(0,evidence.score)/maxScore : evidence.total>0 ? .18*Math.min(1,evidence.passed/evidence.total) : 0;
    return Math.min(base*(1+gain)+(selected?4:0),dense?34:94);
  }

  // ---- fill the field, preserve the hub and separate actual node footprints --
  function networkLayout(nodes,width,height,time=0,selected=null,ranks=new Map(),maxScore=0){
    const groups=networkGroups(nodes),count=groups.reduce((sum,g)=>sum+g.count,0);
    const hub={x:width*.5,y:height*.52,r:Math.min(width,height)*.085+12};
    const indices=new Map(groups.map(g=>[g.key,0])),single=groups.length===1,gap=count>16?7:14;
    const positions=nodes.map(n=>{
      if(!visibleNode(n))return null;
      const key=modelGroup(n.groupKey||n.model),g=groups.find(g=>g.key===key);
      const index=indices.get(key);indices.set(key,index+1);
      const size=networkNodeSize(count,width,height,ranks?.get(n.name),n.id===selected,maxScore);
      const angle=(single&&count<=12?index*2*Math.PI/count-Math.PI/2:index*2.39996+key*.7)+time*.026*(key%2?-1:1);
      const radial=single&&count<=12?1:Math.sqrt((index+.8)/g.count);
      const rx=single?Math.max(12,width*.46-size/2-14):width*.22;
      const ry=single?Math.max(12,height*.43-size/2-20):height*.25;
      return {n,size,x:width*g.center[0]+Math.cos(angle)*rx*radial,
        y:height*g.center[1]+Math.sin(angle)*ry*radial};
    });
    const points=positions.filter(Boolean);
    const constrain=p=>{
      let dx=p.x-hub.x,dy=p.y-hub.y,distance=Math.hypot(dx,dy),min=hub.r+p.size/2+gap;
      if(distance<min){if(distance<.001){dx=1;dy=0;distance=1;}p.x=hub.x+dx/distance*min;p.y=hub.y+dy/distance*min;}
      const margin=p.size/2+12,top=p.size/2+28,bottom=height-p.size/2-28;
      p.x=Math.max(margin,Math.min(width-margin,p.x));p.y=Math.max(top,Math.min(bottom,p.y));
    };
    for(let fit=0;fit<8;fit++){
      for(let pass=0;pass<60;pass++){
        let overlap=0;
        for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
          const a=points[i],b=points[j];let dx=b.x-a.x,dy=b.y-a.y,distance=Math.hypot(dx,dy);
          const missing=(a.size+b.size)/2+gap-distance;
          if(missing<=0)continue;
          if(distance<.001){const angle=(i+j+1)*2.39996;dx=Math.cos(angle);dy=Math.sin(angle);distance=1;}
          const push=(missing+.1)/2;a.x-=dx/distance*push;a.y-=dy/distance*push;b.x+=dx/distance*push;b.y+=dy/distance*push;
          overlap=Math.max(overlap,missing);
        }
        points.forEach(constrain);
        if(overlap<.1)break;
      }
      const collision=points.some((a,i)=>points.slice(i+1).some(b=>Math.hypot(a.x-b.x,a.y-b.y)<(a.size+b.size)/2+gap-.25));
      if(!collision)break;
      // Small containers must fit evidence-sized nodes without covering each other.
      points.forEach(p=>{p.size*=.91;});
    }
    return positions;
  }

  // ---- one display ID per team, independent of historical provider names ----
  function networkNodeLabel(node,count){
    const id=String(node.id).padStart(3,'0');
    return count<=12?['GPT','GLM','DS','QW'][modelGroup(node.groupKey||node.model)]+'\n'+id:id;
  }

  // ---- local simulation coverage, never an official score or NPU latency ----
  function simulationAttempts(jobs, expectedCases=15, team=null, context={}, at=Infinity){
    return jobs.filter(r=>(!team||r.team===team)&&r.state!=='cancelled'&&r.created_at<=at&&(r.finished_at||r.created_at)<=at&&
      r.schema==='justkernel.simulation.v1'&&r.source==='cann-simulator'&&
      (!context.case_pack_sha256||r.case_pack_sha256===context.case_pack_sha256)&&
      (!context.worker_sha256||r.worker_sha256===context.worker_sha256))
      .sort((a,b)=>a.created_at-b.created_at).map((r,i)=>{
        const cases=[...new Map((r.cases||[]).map(c=>[c.id,c])).values()];
        const passed=cases.filter(c=>c.pass===true).length;
        const pending=['queued','running'].includes(r.state);
        const valid=r.state==='completed'&&r.functional_pass===true&&passed===expectedCases&&cases.length===expectedCases;
        return {seq:i+1,team:r.team,job:r.id,sha:r.source_sha256,at:r.finished_at||r.created_at,
          passed,total:expectedCases,coverage:cases.length,correctness:100*passed/expectedCases,
          profiles:cases.filter(c=>c.profile_pass===true).length,profileTotal:r.profile_case_ids?.length||0,
          valid,pending,failed:r.state==='failed',error:r.error||'',latency:null,score:null,local:true,
          event:{kind:'simulation.receipt',team:r.team,data:{...r,job_id:r.id,expected_cases:expectedCases}}};
      });
  }

  // ---- attemptsFromEvents --------------------------------------------------
  // A failed compile is a missing measurement, never a zero-latency success.
  function attemptsFromEvents(events, expectedCases = 15, team = null) {
    const candidates = new Map();
    const seen = new Set();
    const attempts = [];
    for (const e of events) {
      if (team && e.team !== team) continue;
      const d = e.data || {};
      if (e.kind === 'candidate.created') candidates.set(d.job_id, d.sha256);
      if (!['evaluation.completed','evaluation.failed'].includes(e.kind)) continue;
      const key = d.job_id || 'seq-' + e.seq;
      if (seen.has(key)) continue;
      seen.add(key);
      const cases = Array.isArray(d.cases) ? d.cases : [];
      const passed = cases.filter((c) => c.pass === true).length;
      const complete = cases.length === expectedCases && expectedCases > 0;
      const valid = e.kind === 'evaluation.completed' && d.pass === true && complete && passed === expectedCases;
      const times = cases.map((c) => c.measurement?.event_mean_us);
      const latency = valid && times.every((t) => number(t) && t > 0)
        ? Math.exp(times.reduce((sum,t) => sum + Math.log(t),0) / times.length) : null;
      // Group performance by the input pack AND the actual recorded device environment.
      const env = d.environment;
      const comparable = d.case_pack_sha256 && env?.host_alias && env?.device !== undefined && env?.cann_env;
      attempts.push({seq:e.seq, event:e, team:e.team, at:e.at, job:key,
        sha:d.source_sha256 || candidates.get(d.job_id) || '', passed, total:expectedCases,
        coverage:cases.length, correctness:cases.length ? Math.min(passed / expectedCases,1) * 100 : null,
        valid, latency, failed:!valid, error:e.kind === 'evaluation.failed' ? d.message || '执行失败' : '',
        group:comparable ? JSON.stringify([d.case_pack_sha256,env.host_alias,env.device,env.cann_env,env.server_profile||'',env.ssh_port??null]) : 'unverified-' + e.seq});
    }
    return attempts;
  }

  // ---- official evidence stays separate from device measurements ---------
  function officialAttemptsFromEvents(events, team=null){
    const points=new Map();
    events.filter(e=>e.kind==='judge.submission.updated'&&(!team||e.team===team)).forEach(e=>{
      const d=e.data||{},r=d.official||{},cases=Array.isArray(r.result)?r.result:[];
      const valid=r.status==='Pass'&&number(r.score);
      const status=String(r.status||'').toLowerCase().replace(/[^a-z]/g,''),failed=['fail','failed','compileerror','compilationerror','ce','runtimeerror','re','timelimitexceeded','timeout','tle','wronganswer','wa','accuracyerror','precisionerror','memorylimitexceeded','mle','error','invalid'].includes(status);
      const key=String(d.problem_id||'')+':'+String(d.submission_id||'seq-'+e.seq);
      points.set(key,{seq:points.get(key)?.seq||e.seq,event:e,team:e.team,at:e.at,job:d.submission_id,sha:d.source_sha256,
        score:valid?r.score:null,latency:null,correctness:null,valid,failed,pending:!valid&&!failed,
        error:valid?'':String(r.status||'等待官测'),passed:cases.filter(c=>c.testcase_status==='Pass').length,
        total:cases.length,coverage:cases.length,group:d.problem_id,official:true,rank:r.rank});
    });
    return [...points.values()];
  }
  function rankOfficialTeams(points,nodes){
    return nodes.filter(visibleNode).map(n=>{
      const attempts=points.filter(p=>p.team===n.name),own=attempts.filter(p=>p.valid&&number(p.score));
      const best=own.reduce((a,b)=>!a||b.score>a.score?b:a,null);
      const coverage=attempts.filter(p=>p.total>0).reduce((a,b)=>!a||b.passed/b.total>a.passed/a.total?b:a,null);
      return {name:n.name,id:n.id,score:best?.score??null,rank:best?.rank??null,
        attempts:attempts.length,passed:coverage?.passed??0,total:coverage?.total??0};
    }).sort((a,b)=>(b.score??-Infinity)-(a.score??-Infinity)||b.passed-a.passed||a.name.localeCompare(b.name));
  }

  // ---- performanceGroup ----------------------------------------------------
  function performanceGroup(attempts) {
    const group = attempts.findLast((p) => p.latency !== null)?.group;
    return attempts.map((p) => ({...p, latency:p.group === group ? p.latency : null}));
  }

  // ---- rankTeams ----------------------------------------------------------
  function rankTeams(points,nodes,includeHistory=true){
    const rows=new Map(nodes.filter(visibleNode).map(n=>[n.name,{name:n.name,id:n.id,latency:null,passed:0,total:0,attempts:0}]));
    for(const p of performanceGroup(includeHistory?points:points.filter(p=>rows.has(p.team)))){
      if(!rows.has(p.team))rows.set(p.team,{name:p.team,id:null,latency:null,passed:0,total:0,attempts:0});
      const row=rows.get(p.team);row.attempts++;
      if(p.passed>row.passed||!row.total){row.passed=p.passed;row.total=p.total;}
      if(p.valid&&number(p.latency)&&p.latency>0)row.latency=row.latency===null?p.latency:Math.min(row.latency,p.latency);
    }
    return [...rows.values()].sort((a,b)=>(a.latency??Infinity)-(b.latency??Infinity)||b.passed-a.passed||b.attempts-a.attempts||a.name.localeCompare(b.name));
  }

  // ---- View ----------------------------------------------------------------
  class View {
    // ---- construction ------------------------------------------------------
    constructor({selectAgent, showEvidence}) {
      this.selectAgent = selectAgent;
      this.showEvidence = showEvidence;
      this.data = null;
      this.points = [];
      this.lastFrame = 0;
      this.dirty = true;
      this.chartKey = '';
      this.$ = (id) => document.getElementById(id);
      this.motionMedia=window.matchMedia('(prefers-reduced-motion: reduce)');
      let motion='on';try{motion=localStorage.getItem('justkernel-motion')||'on';}catch{/* storage can be disabled */}
      this.setMotion(motion);
      this.$('motionButton').addEventListener('click',()=>this.setMotion(this.reduced?'on':'off'));
      this.motionMedia.addEventListener('change',()=>{if(this.motion==='auto')this.setMotion('auto');});
      this.$('trajectoryMetric').addEventListener('change',() => {this.chartKey='';this.renderChart();});
      this.$('trajectoryScope').addEventListener('change',() => {this.chartKey='';this.renderChart();});
      const chart = this.$('attemptChart');
      const select = (event) => {
        const target = event.target.closest('[data-point]');
        if (!target) return;
        const point = this.points[Number(target.dataset.point)];
        if (!point) return;
        if (event.type === 'click' || event.type === 'keydown' && ['Enter',' '].includes(event.key)) {
          event.preventDefault(); this.showEvidence(point.event || {source:'simulation',...point});
        } else if (['mouseover','focusin'].includes(event.type)) this.tooltip(point);
      };
      for (const type of ['click','keydown','mouseover','focusin']) chart.addEventListener(type,select);
      chart.addEventListener('mouseleave',() => {this.$('plotTooltip').hidden=true;});
      chart.addEventListener('focusout',() => {this.$('plotTooltip').hidden=true;});
      new ResizeObserver(()=>{this.chartKey='';this.renderChart();}).observe(this.$('trajectoryPlot'));
      this.$('attemptFailureButton').addEventListener('click',()=>{const p=this.points.at(-1);if(p)this.showEvidence(p.event || p);});
      this.$('stageRail').addEventListener('click',(event) => {
        const key = event.target.closest('[data-stage-evidence]')?.dataset.stageEvidence;
        if (!key) return;
        this.showEvidence(this.data.demo ? {source:'simulation',stage:key} : this.data.stages.filter((e) => e.data.stage === key));
      });
      const processSelect=(event)=>{
        const node=event.target.closest('[data-process-stage]');
        if(!node || event.type==='keydown'&&!['Enter',' '].includes(event.key))return;
        event.preventDefault();
        const keys=node.dataset.processStage.split(',');
        this.showEvidence(this.data.demo?{source:'simulation',stage:keys.join(',')}:this.data.stages.filter(e=>keys.includes(e.data.stage)));
      };
      document.addEventListener('click',processSelect);document.addEventListener('keydown',processSelect);
      new ResizeObserver(() => this.resize()).observe(this.$('swarmField'));
    }

    // ---- motion changes presentation only; never starts any agent work -----
    setMotion(mode){
      this.motion=['on','off','auto'].includes(mode)?mode:'on';
      this.reduced=!motionEnabled(this.motion,this.motionMedia.matches);
      document.documentElement.dataset.motion=this.reduced?'off':'on';
      const button=this.$('motionButton');
      button.textContent=this.reduced?'动效关闭':'动效开启';
      button.setAttribute('aria-pressed',String(!this.reduced));
      button.title='蓝色流动表示模型任务，橙色表示执行验证，白色表示真实 A2A 消息；只控制显示。';
      try{localStorage.setItem('justkernel-motion',this.motion);}catch{/* storage can be disabled */}
      this.dirty=true;
    }

    // ---- evidence projection -----------------------------------------------
    update(data) {
      const mode = data.demo ? 'demo' : data.recording ? 'recording' : data.judgeOnly ? 'judge' : 'live';
      if (mode !== this.mode) {
        this.mode = mode;
        if(!this.$('trajectoryMetric').querySelector('[value="score"]'))this.$('trajectoryMetric').add(new Option('官测分数','score'));
        this.$('trajectoryMetric').value = data.demo ? 'latency' : data.judgeOnly && !data.simulation?.required ? 'score' : 'correctness';
        this.chartKey = '';
      }
      this.data = data;
      const correctnessOption=this.$('trajectoryMetric').querySelector('[value="correctness"]');
      if(correctnessOption)correctnessOption.textContent=data.simulation?.required?'本地仿真通过率':'正确率';
      const ranks=rankOfficialTeams(officialAttemptsFromEvents(data.events),data.nodes);
      this.networkRanks=new Map(ranks.map(r=>[r.name,r]));
      this.networkMaxScore=Math.max(0,...ranks.map(r=>r.score||0));
      this.dirty = true;
      this.renderChart();
      this.renderStages();
      this.renderProcess();
      this.renderLeaderboard();
      this.renderNetworkLabels();
    }

    demoPoints() {
      return this.data.history.slice(1).map((p,i) => {
        const bad = p.round % 7 === 0;
        // Visual examples only. These values never enter a real execution receipt.
        const gain = p.value * (.8 + .18 * (.5 + .5 * Math.sin(p.round * 1.7)));
        return {seq:p.round,team:'A'+String((p.round * 11) % 100 + 1).padStart(3,'0'),
          passed:bad ? 11 : 15,total:15,coverage:15,correctness:bad ? 73.333 : 100,
          latency:bad ? null : 100 / Math.max(gain,.5),valid:!bad,failed:bad,error:'',sha:'demo',group:'simulation',job:'demo-'+i};
      });
    }

    renderChart() {
      if (!this.data) return;
      const d = this.data;
      const metric = this.$('trajectoryMetric').value;
      const selectedOnly = this.$('trajectoryScope').value === 'selected';
      const local=!d.demo&&metric==='correctness'&&d.simulation?.required;
      const replayAt=d.recording?(d.replayClock?.start||0)+(d.replayClock?.position||0):Infinity;
      let attempts = d.demo ? this.demoPoints() : metric==='score' ? officialAttemptsFromEvents(d.events,selectedOnly ? d.selectedTeam : null) : local ? simulationAttempts(d.simulationJobs||[],d.expectedCases,selectedOnly?d.selectedTeam:null,d.simulation,replayAt) : attemptsFromEvents(d.events,d.expectedCases,selectedOnly ? d.selectedTeam : null);
      if (d.demo && selectedOnly) attempts = attempts.filter((p) => p.team === 'A'+String(d.selected).padStart(3,'0'));
      if (metric === 'latency') attempts = performanceGroup(attempts);
      this.points = attempts;
      const latest = attempts.at(-1);
      const measured = attempts.filter((p) => number(p[metric]));
      const best = measured.length ? metric === 'latency' ? Math.min(...measured.map((p) => p[metric])) : Math.max(...measured.map((p) => p[metric])) : null;
      const rect=this.$('trajectoryPlot').getBoundingClientRect(),plotW=Math.max(180,Math.round(rect.width)),plotH=Math.max(65,Math.round(rect.height));
      const key = JSON.stringify([this.mode,metric,selectedOnly,d.selected,plotW,plotH,attempts.map((p) => [p.seq,p[metric]]),d.running]);
      const pending = d.pendingJobs || 0;
      this.$('plotProvenance').textContent = d.demo ? '演示数据' : metric==='score' ? 'CANN JUDGE / 官测回执' : local ? '910B4 / 本地仿真 · 当前测试集' : d.recording ? '导入记录' : '实测记录';
      this.$('attemptLabel').textContent = latest ? '最近一次尝试 · '+String(attempts.length).padStart(2,'0') : '最新尝试';
      const failureReason = latest?.error ? /\(75\)|NPU busy|outside JustKernel/i.test(latest.error) ? '当时设备被占用' : /connect|ssh|scp/i.test(latest.error) ? '连接未完成' : '评测未完成' : '未通过';
      this.$('attemptValue').textContent = latest ? metric === 'correctness' ? latest.correctness === null ? failureReason : latest.passed+'/'+latest.total : number(latest.latency) ? latest.latency.toFixed(2) : failureReason : '—';
      if(metric==='score')this.$('attemptValue').textContent=number(latest?.score)?latest.score.toFixed(2):latest?.error||'待官测';
      this.$('attemptValue').classList.toggle('status-value',Boolean(latest?.error));
      const time = latest?.at ? new Date(latest.at*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'})+' · ' : '';
      this.$('attemptDetail').textContent = latest ? time+nodeDisplayName(d.nodes,latest.team)+(metric==='score'?' · 提交 '+latest.job:latest.error ? ' · 未取得测量' : ' · '+latest.coverage+' 点回执') : d.running ? '团队正在工作，结果返回后自动更新' : d.judgeOnly?'等待首次官方回执':'等待第一次设备评测';
      if(local&&latest)this.$('attemptDetail').textContent=time+nodeDisplayName(d.nodes,latest.team)+' · 源码 '+latest.sha?.slice(0,8)+' · 流水 '+latest.profiles+'/'+latest.profileTotal+(latest.pending?' · 进行中':'');
      this.$('attemptFailureButton').hidden=!latest?.failed;
      this.$('attemptBest').textContent = best === null ? '—' : metric === 'score' ? best.toFixed(2)+' 分' : metric === 'latency' ? best.toFixed(2)+' μs' : best.toFixed(1)+'%';
      this.$('bestLabel').textContent = metric === 'score' ? '最好官测分数' : metric === 'latency' ? '当前最低耗时' : local ? '本地最好覆盖率' : '当前最好正确率';
      this.$('attemptCount').textContent = attempts.length+' 次尝试'+(pending ? ' · '+pending+' 次排队 / 实测' : '');
      this.$('plotDirection').textContent = metric === 'latency' ? '↓ 越低越好 · 仅完整通过结果' : '↑ 越高越好';
      if (key === this.chartKey) return;
      this.chartKey = key;
      this.$('plotTooltip').hidden = true;
      const left=34,right=plotW-10,top=10,bottom=Math.max(25,plotH-29),failY=plotH-17;
      const maxValue = measured.length ? Math.max(...measured.map((p) => p[metric])) : 100;
      const minValue = measured.length ? Math.min(...measured.map((p) => p[metric])) : 0;
      const padding = Math.max((maxValue-minValue)*.18,maxValue*.1,1);
      const low = metric === 'correctness' ? 0 : Math.max(0,minValue-padding);
      const high = metric === 'correctness' ? 100 : maxValue+padding;
      const y = (v) => bottom-(v-low)/Math.max(high-low,1)*(bottom-top);
      const x = (i) => attempts.length <= 1 ? left+(right-left)*.58 : left+i/(attempts.length-1)*(right-left);
      let grid = '';
      for (let i=0;i<3;i++) {
        const value = high-i*(high-low)/2, py=y(value);
        grid += `<path class="plot-grid" d="M${left} ${py}H${right}"/><text class="plot-axis" x="3" y="${py+4}">${metric==='correctness'?value.toFixed(0)+'%':measured.length?value.toFixed(value<10?1:0):'—'}</text>`;
      }
      let line='', bestLine='', prior=false, runningBest=null;
      attempts.forEach((p,i) => {
        const v = p[metric];
        if (number(v)) {
          line += `${prior?'L':'M'}${x(i).toFixed(2)} ${y(v).toFixed(2)} `; prior=true;
          const next = runningBest===null ? v : metric==='latency' ? Math.min(runningBest,v) : Math.max(runningBest,v);
          bestLine += runningBest===null ? `M${x(i)} ${y(next)}` : `H${x(i)}V${y(next)}`;
          runningBest=next;
        } else prior=false;
        if (runningBest!==null) bestLine += `H${x(i)} `;
      });
      if (attempts.length===1 && runningBest!==null) bestLine += `H${right}`;
      const marks = attempts.map((p,i) => {
        const value=p[metric], py=number(value)?y(value):failY;
        const label = nodeDisplayName(d.nodes,p.team)+' · 尝试 '+(i+1)+' · '+(number(value)?metric==='score'?value.toFixed(2)+' 官测分':metric==='latency'?value.toFixed(3)+' μs':p.passed+'/'+p.total+' 通过':p.error||'未取得完整通过耗时')+' · 点击查看回执';
        return `<g class="plot-point ${p.failed?'bad':'good'}" data-point="${i}" tabindex="0" role="button" aria-label="${escape(label)}"><title>${escape(label)}</title><circle class="hit" cx="${x(i)}" cy="${py}" r="11"/>${number(value)?`<circle class="dot" cx="${x(i)}" cy="${py}" r="${i===attempts.length-1?3:attempts.length>80?1.4:2.3}"/>`:p.pending?`<circle cx="${x(i)}" cy="${py}" r="3" fill="none" stroke="#829aaf" stroke-dasharray="2 2"/>`:`<path class="failure-cross" d="M${x(i)-3} ${py-3}l6 6m-6 0l6-6"/>`}</g>`;
      }).join('');
      const lastValue=latest?.[metric];
      const halo = number(lastValue) ? `<circle class="plot-last-halo" cx="${x(attempts.length-1)}" cy="${y(lastValue)}" r="7" pointer-events="none"/>` : '';
      const empty = !measured.length ? `<text class="plot-empty" x="${plotW/2}" y="${top+(bottom-top)/2+4}" text-anchor="middle">${metric==='score'?'等待 CANN Judge 真实回执':attempts.length ? metric==='latency'?'尚无全点通过的性能回执':'暂无数值校验结果':'等待第一条优化轨迹'}</text><text class="plot-empty-sub" x="${plotW/2}" y="${top+(bottom-top)/2+23}" text-anchor="middle">${attempts.length ? '失败记录保留在下方 × · 点击可追溯' : metric==='score'?'团队生成代码 → 提交 → 官方反馈':'每次实测自动落点 · 最好结果沿线保留'}</text>` : '';
      this.$('attemptChart').setAttribute('viewBox',`0 0 ${plotW} ${plotH}`);
      this.$('attemptChart').setAttribute('preserveAspectRatio','xMinYMin meet');
      this.$('attemptChart').innerHTML = `<defs><linearGradient id="attemptFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#8daed5" stop-opacity=".13"/><stop offset="1" stop-color="#8daed5" stop-opacity="0"/></linearGradient></defs>${grid}<rect class="plot-failure-lane" x="${left}" y="${failY-7}" width="${right-left}" height="14" rx="2"/><text class="plot-axis" x="3" y="${failY+4}">FAIL</text>${line?`<path d="${line} L${x(attempts.length-1)} ${bottom}L${left} ${bottom}Z" fill="url(#attemptFill)" opacity=".35" pointer-events="none"/>`:''}<path class="plot-attempt plot-new" d="${line}"/><path class="plot-best" d="${bestLine}"/>${d.running?`<path class="plot-scan" d="M${left} ${top}V${bottom}"/>`:''}${empty}${halo}${marks}<text class="plot-axis" x="${left}" y="${plotH-2}">${attempts.length?'ATTEMPT 001':'尚无实测'}</text><text class="plot-axis" x="${right}" y="${plotH-2}" text-anchor="end">${attempts.length?'ATTEMPT '+String(attempts.length).padStart(3,'0'):'结果实时更新'}</text>`;
    }

    tooltip(point) {
      const metric = this.$('trajectoryMetric').value;
      if(point.local){this.$('plotTooltip').textContent=point.team+' · 源码 '+point.sha?.slice(0,12)+'\n'+point.passed+'/'+point.total+' 本地数值校验 · '+point.profiles+'/'+point.profileTotal+' 流水采集\n暂拟测试集，非官方成绩 · 点击查看仿真回执';this.$('plotTooltip').hidden=false;return;}
      if(point.official){this.$('plotTooltip').textContent=point.team+' · 提交 '+point.job+'\n'+(point.valid?point.score.toFixed(2)+' 分':point.error)+'\n源码 '+(point.sha||'').slice(0,12)+' · 用户关联提交';this.$('plotTooltip').hidden=false;return;}
      this.$('plotTooltip').textContent = nodeDisplayName(this.data.nodes,point.team)+' · '+(point.sha?.slice(0,12) || point.job)+'\n'+
        (point.error ? point.error.slice(0,120) : point.passed+'/'+point.total+' 本地点通过'+(number(point.latency)?' · '+point.latency.toFixed(3)+' μs 几何均值':''))+
        (metric==='latency' && !number(point.latency)?'\n未绘入性能线：未完整通过或测量环境不同':'')+'\n点击查看原始回执';
      this.$('plotTooltip').hidden=false;
    }

    renderStages() {
      const d=this.data;
      const current=d.demo ? d.tick%8 : -1;
      const items=STAGES.map(([key,label],i) => {
        const event=d.stages.findLast((e) => e.data.stage===key);
        const status=d.demo ? i<current?'completed':i===current?'started':'pending' : event?.data.state || 'pending';
        return `<button class="stage-stop ${escape(status)}" data-stage-evidence="${key}" title="${escape(label+' · '+(event?.data.message || (d.demo?'模拟阶段':'等待实际事件')))}" aria-label="${escape(label+' · '+status+' · 查看执行证据')}"><i>${status==='completed'?'✓':String(i+1).padStart(2,'0')}</i><span>${label}</span></button>`;
      }).join('');
      if (this.$('stageRail').innerHTML!==items) this.$('stageRail').innerHTML=items;
      const latest=d.events.findLast((e) => e.team===d.selectedTeam && ['stage.updated','tool.started','team.turn.completed','evaluation.failed'].includes(e.kind));
      const activity=d.demo ? d.paused ? '预演已暂停 · 可点击数据点与团队节点查看详情' : '模拟搜索中 · 候选 / 通信 / 评测持续流入' : latest ? (latest.data.message || latest.data.tool || latest.data.answer || latest.kind) : '等待任务 · 点击节点查看团队，点击曲线查看实测';
      this.$('trajectoryActivity').textContent=activity;
      this.$('trajectoryActivity').title=activity;
      this.$('trajectoryActivity').parentElement.classList.toggle('trajectory-active',d.running);
    }

    // ---- original process diagram, driven by actual stage events ------------
    renderProcess(){
      const d=this.data;
      const groups=[['input'],['search'],['policy'],['queue','execute'],['verify'],['share'],['distill']];
      const current=d.demo?Math.floor(d.tick%8*7/8):-1;
      let moving=false;
      document.querySelectorAll('#flow .flow-node').forEach((node,i)=>{
        const e=d.stages.findLast(e=>groups[i].includes(e.data.stage));
        const status=d.demo?(i<current?'completed':i===current?'started':'pending'):e?.data.state||'pending';
        node.classList.toggle('active',['started','progress'].includes(status));
        node.classList.toggle('completed',status==='completed');node.classList.toggle('failed',status==='failed');
        moving ||= ['started','progress'].includes(status)&&(d.selectedRunning??d.running);
      });
      const running=d.demo?!d.paused:moving;
      this.$('flow').classList.toggle('flow-idle',!running);
      const svg=this.$('flow'),bounds=svg.getBoundingClientRect(),w=bounds.width,h=bounds.height;
      if(w>0&&h>0){
        svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
        const gap=h*.21,boxH=Math.min(33,gap*.58),boxW=Math.min(148,w*.40);
        const coords=[[w*.5,h*.07],[w*.24,h*.28],[w*.76,h*.28],[w*.5,h*.50],[w*.76,h*.72],[w*.24,h*.72],[w*.5,h*.93]];
        const boxes=coords.map(([x,y],i)=>({x:x-(i===3?boxW*1.08:boxW)/2,y:y-(i===3?boxH*1.25:boxH)/2,w:i===3?boxW*1.08:boxW,h:i===3?boxH*1.25:boxH,cx:x,cy:y}));
        const ns='http://www.w3.org/2000/svg';
        let defs=svg.querySelector('defs');
        if(!svg.querySelector('#layerFill'))defs.insertAdjacentHTML('beforeend','<linearGradient id="layerFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#294050"/><stop offset="1" stop-color="#14212c"/></linearGradient><linearGradient id="layerActive" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#574332"/><stop offset="1" stop-color="#253340"/></linearGradient><filter id="layerGlow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="7"/></filter>');
        const names=d.simulation?.required?['任务与约束','独立探索','规则自查','独立仿真','数值校验','共享候选','经验进化']:d.judgeOnly?['任务与约束','协同搜索','规则自查','冻结候选','官测反馈','共享 SOTA','经验进化']:['任务与约束','协同搜索','规则自查','NPU 实测','结果验证','共享 SOTA','经验进化'];
        svg.querySelectorAll('.flow-node').forEach((node,i)=>{
          const b=boxes[i],rect=node.querySelector('rect'),title=node.querySelector('.node-title');
          let depth=node.querySelector('.flow-depth');
          if(!depth){depth=document.createElementNS(ns,'path');depth.classList.add('flow-depth');node.prepend(depth);const halo=document.createElementNS(ns,'ellipse');halo.classList.add('flow-halo');node.prepend(halo);}
          depth.setAttribute('d',`M${b.x} ${b.y+b.h-3}L${b.x+7} ${b.y+b.h+5}H${b.x+b.w+7}V${b.y+7}L${b.x+b.w} ${b.y}V${b.y+b.h-3}Z`);
          const halo=node.querySelector('.flow-halo');for(const [key,value]of Object.entries({cx:b.cx+2,cy:b.cy+7,rx:b.w*.7,ry:b.h*.9}))halo.setAttribute(key,value);
          for(const [key,value]of Object.entries({x:b.x,y:b.y,width:b.w,height:b.h,rx:5}))rect.setAttribute(key,value);
          title.textContent=names[i];title.setAttribute('x',b.cx);title.setAttribute('y',b.cy+4.5);title.setAttribute('text-anchor','middle');
          node.classList.toggle('flow-chip',i===3);
        });
        const [input,search,policy,npu,verify,share,distill]=boxes;
        const path=`M${input.cx} ${input.y+input.h}C${input.cx} ${search.y-8},${search.cx} ${input.y+input.h+8},${search.cx} ${search.y}M${search.x+search.w} ${search.cy}H${policy.x}M${policy.cx} ${policy.y+policy.h}C${policy.cx} ${npu.cy-12},${npu.x+npu.w+15} ${npu.cy},${npu.x+npu.w} ${npu.cy}M${npu.cx} ${npu.y+npu.h}C${npu.cx} ${verify.y-8},${verify.cx} ${npu.y+npu.h+8},${verify.cx} ${verify.y}M${verify.x} ${verify.cy}H${share.x+share.w}M${share.cx} ${share.y+share.h}C${share.cx} ${distill.y-8},${distill.cx} ${share.y+share.h+8},${distill.cx} ${distill.y}`;
        const feedback=`M${distill.x} ${distill.cy}C${w*.03} ${distill.cy},${w*.03} ${search.cy},${search.x} ${search.cy}`;
        const revise=`M${verify.x+verify.w} ${verify.cy}C${w*.99} ${verify.cy},${w*.99} ${policy.cy},${policy.x+policy.w} ${policy.cy}`;
        svg.querySelector('.flow-line').setAttribute('d',path);const returns=svg.querySelectorAll('.flow-return');returns[0].setAttribute('d',feedback);returns[1].setAttribute('d',revise);
        svg.querySelector('.flow-share').setAttribute('d',`M${npu.cx} ${npu.y-6}V${npu.y-14}M${npu.cx} ${npu.y+npu.h+6}V${npu.y+npu.h+14}`);
        let stream=svg.querySelector('.flow-energy');if(!stream){stream=document.createElementNS(ns,'path');stream.classList.add('flow-energy');svg.querySelector('.flow-node').before(stream);}stream.setAttribute('d',path);
        const geometry=[Math.round(w),Math.round(h)].join(':');
        if(this.flowGeometry!==geometry){
          this.flowGeometry=geometry;
          const forward=svg.querySelector('.flow-packet'),back=svg.querySelector('.return-packet');
          forward.setAttribute('cx',0);forward.setAttribute('cy',0);forward.innerHTML=`<animateMotion path="${path}" dur="4s" repeatCount="indefinite"/>`;
          back.setAttribute('cx',0);back.setAttribute('cy',0);back.innerHTML=`<animateMotion path="${feedback}" dur="5s" repeatCount="indefinite"/>`;
          const first=svg.querySelector('.flow-node');first.before(forward,back);
        }
      }
      if(this.$('processLatest')){
        const latest=this.points.at(-1);
        this.$('processLatest').textContent=this.$('attemptValue').textContent==='—'?(d.judgeOnly?'等待官测':'等待实测'):this.$('attemptValue').textContent+(this.$('trajectoryMetric').value==='latency'&&number(latest?.latency)?' μs':'');
        this.$('processEvidence').disabled=!latest;
        const ownSimulations=(d.simulationJobs||[]).filter(row=>row.team===d.selectedTeam);
        const sim=ownSimulations.find(row=>row.state==='running')||ownSimulations.find(row=>row.state==='queued')||ownSimulations.find(row=>row.state!=='cancelled')||ownSimulations[0];
        this.$('processEvidence').dataset.simulationJob=sim?.id||'';
        this.$('processEvidence').textContent=sim?'查看仿真日志 ↗':'查看回执 ↗';
        if(d.simulation?.required){
          this.$('processLatest').previousElementSibling.textContent='本队仿真';
          const passed=(sim?.cases||[]).filter(c=>c.pass).length,total=sim?.case_ids?.length||0;
          this.$('processLatest').textContent=!sim?'等待实验':sim.state==='queued'?'仿真排队':sim.state==='cancelled'?'已取消排队':sim.state==='failed'?`未通过 · ${passed}/${total}`:`${passed}/${total} · ${sim.state==='completed'?'本地通过':'进行中'}`;
          if(d.simulation.available===false&&['queued','running'].includes(sim?.state))this.$('processLatest').textContent='等待仿真环境恢复';
          this.$('processEvidence').disabled=!sim;
        }else this.$('processLatest').previousElementSibling.textContent='最新实测';
      }
    }

    // ---- public team leaderboard -------------------------------------------
    renderLeaderboard(){
      const board=this.$('teamLeaderboard');if(!board)return;
      if(this.data.judgeOnly){
        const points=officialAttemptsFromEvents(this.data.events),rows=rankOfficialTeams(points,this.data.nodes),top=rows.find(r=>number(r.score));
        const coverage=rows.find(r=>r.total>0);
        if(this.data.simulation?.required){
          const d=this.data,at=d.recording?(d.replayClock?.start||0)+(d.replayClock?.position||0):Infinity;
          const visibleNames=new Set(d.nodes.filter(visibleNode).map(n=>n.name));
          const local=simulationAttempts(d.simulationJobs||[],d.expectedCases,null,d.simulation,at).filter(p=>visibleNames.has(p.team));
          const best=local.filter(p=>p.valid).at(-1),bestPartial=[...local].sort((a,b)=>b.passed-a.passed)[0];
          const shown=best||bestPartial;
          const latest=points.filter(p=>visibleNames.has(p.team)&&p.total>0).sort((a,b)=>a.at-b.at).at(-1);
          board.closest('.panel').querySelector('.mini-label').textContent='本地仿真 / 官方反馈';
          board.innerHTML=`<div class="board-best"><strong>${shown?shown.passed+'/'+shown.total+' <small>本地校验</small>':'等待本地校验'}</strong><span>${shown?'流水 '+shown.profiles+'/'+shown.profileTotal+' · '+escape(shown.sha.slice(0,8)):'独立实验返回后自动更新'}</span></div><div class="board-best official-summary"><strong>${top?top.score.toFixed(2)+' <small>官测最高分</small>':coverage?coverage.passed+'/'+coverage.total+' <small>历史官测最好</small>':'等待官测'}</strong><span>${latest?'最近官测 '+latest.passed+'/'+latest.total+' · '+escape(latest.sha?.slice(0,8)||''):'与本地结果分别记录'}</span></div><div class="board-columns local-board"><span>排名</span><span>团队</span><span>本地</span><span>官测最好</span></div><div class="board-rows">${rows.map((r,i)=>{
            const own=local.filter(p=>p.team===r.name),p=own.filter(p=>p.valid).at(-1)||own.at(-1);
            return `<button class="board-row local-board" data-rank-team="${r.id}" title="${escape(p?'本地源码 '+p.sha+' · 流水 '+p.profiles+'/'+p.profileTotal+'；官测列可能属于另一源码版本':'尚无当前测试集仿真结果')}"><span>${number(r.score)?i+1:'—'}</span><b>${escape(nodeDisplayName(d.nodes,r.name))}</b><strong>${p?p.passed+'/'+p.total:'未测'}</strong><strong>${number(r.score)?r.score.toFixed(2):r.total?r.passed+'/'+r.total:r.attempts?'判题中':'未提交'}</strong></button>`;
          }).join('')}</div>`;
          board.onclick=e=>{const id=Number(e.target.closest('[data-rank-team]')?.dataset.rankTeam);if(id)this.selectAgent(id);};return;
        }
        board.closest('.panel').querySelector('.mini-label').textContent='CANN Judge / 官方反馈';
        board.innerHTML=`<div class="board-best"><strong>${top?top.score.toFixed(2)+' <small>分</small>':coverage?coverage.passed+'/'+coverage.total+' <small>官测通过</small>':'等待官测'}</strong><span>${top?escape(nodeDisplayName(this.data.nodes,top.name)):coverage?escape(nodeDisplayName(this.data.nodes,coverage.name))+' · 尚未全点通过': '候选代码尚未取得官方回执'}</span></div><div class="board-columns"><span>排名</span><span>团队</span><span>官测最好</span></div><div class="board-rows">${rows.map((r,i)=>`<button class="board-row" data-rank-team="${r.id}"><span>${number(r.score)?i+1:'—'}</span><b>${escape(nodeDisplayName(this.data.nodes,r.name))}</b><strong>${number(r.score)?r.score.toFixed(2)+' 分':r.total?r.passed+'/'+r.total+' · 未全过':r.attempts?'判题中':'未提交'}</strong></button>`).join('')}</div>`;
        board.onclick=e=>{const id=Number(e.target.closest('[data-rank-team]')?.dataset.rankTeam);if(id)this.selectAgent(id);};return;
      }
      const d=this.data,points=d.demo?this.demoPoints():attemptsFromEvents(d.events,d.expectedCases);
      const rows=rankTeams(points,d.nodes,Boolean(d.recording)),top=rows.find(r=>number(r.latency));
      const heading=board.closest('.panel').querySelector('h2');heading.innerHTML='<span>//</span> SOTA / 团队榜单';
      board.closest('.panel').querySelector('.mini-label').textContent=d.demo?'模拟榜单':'同环境实测';
      board.innerHTML=`<div class="board-best"><strong>${top?top.latency.toFixed(2)+' <small>μs</small>':'等待完整通过'}</strong><span>${top?escape(nodeDisplayName(this.data.nodes,top.name)):'尚无有效性能成绩'}</span></div><div class="board-columns"><span>排名</span><span>团队</span><span>最好结果</span></div><div class="board-rows">${rows.map((r,i)=>`<button type="button" class="board-row ${r.id===d.selected?'selected':''}" ${r.id?'data-rank-team="'+r.id+'"':'disabled'} title="${escape(nodeDisplayName(this.data.nodes,r.name))}"><span>${number(r.latency)?String(i+1).padStart(2,'0'):'—'}</span><b>${escape(nodeDisplayName(this.data.nodes,r.name))}</b><strong>${number(r.latency)?r.latency.toFixed(2)+' μs':r.total?r.passed+'/'+r.total:'未测'}</strong></button>`).join('')}</div>`;
      board.onclick=e=>{const id=Number(e.target.closest('[data-rank-team]')?.dataset.rankTeam);if(id)this.selectAgent(id);};
    }

    // ---- spatial network ---------------------------------------------------
    renderNetworkLabels() {
      const d=this.data, groups=networkGroups(d.nodes);
      this.$('networkClusters').innerHTML=groups.map(g=>`<span style="left:${g.caption[0]}%;top:${g.caption[1]}%">${escape(g.label)}<b>${g.count}</b></span>`).join('');
      this.$('swarmField').classList.toggle('network-dense',groups.reduce((a,g)=>a+g.count,0)>16);
      const selected=d.nodes[d.selected-1];
      this.$('networkSelection').textContent=selected&&visibleNode(selected) ? (selected.label||selected.name)+' · '+selected.model+(selected.effort?' · '+selected.effort:'') : '组建团队后在这里查看协作';
      const at=d.recording?(d.replayClock?.start||0)+(d.replayClock?.position||0):Date.now()/1000;
      this.network=networkProjection(d.nodes,d.events,at);
      this.$('networkEdges').textContent=d.demo ? '演示通信' : `${this.network.connections.length} 队已连接 · A2A ${this.network.delivered} 次送达`;
      this.$('networkEdges').title='送达数包含团队消息和系统官测反馈；一条广播发给 8 队记为 8 次，不是 Token 数。节点大小优先参考官测得分；未全过时参考官测通过点数。蓝/橙亮点表示作业活动，白色亮点表示近期真实 A2A 消息。';
      this.$('broadcast').classList.toggle('visible',d.broadcasting && !d.recording);
    }

    resize() {
      const rect=this.$('swarmField').getBoundingClientRect();
      this.width=rect.width; this.height=rect.height;
      this.dpr=Math.min(window.devicePixelRatio || 1,2);
      const canvas=this.$('linksCanvas');
      canvas.width=Math.round(this.width*this.dpr); canvas.height=Math.round(this.height*this.dpr);
      this.dirty=true;
      if(this.data)this.renderProcess();
    }

    frame(now) {
      if (!this.data || now-this.lastFrame<40 || this.reduced && !this.dirty) return;
      this.lastFrame=now; this.dirty=false;
      if (!this.width || !this.height) this.resize();
      const d=this.data, w=this.width,h=this.height;
      const t=this.reduced?0:d.paused||d.recording&&!d.playbackPlaying?this.frozenTime||0:now/1000;
      this.frozenTime=t;
      const count=d.nodes.filter(visibleNode).length;
      const positions=networkLayout(d.nodes,w,h,t,d.selected,this.networkRanks,this.networkMaxScore);
      d.nodes.forEach((n,i) => {
        const node=this.$('agentGrid').children[i],visible=Boolean(positions[i]);
        node.hidden=!visible;node.style.display=visible?'':'none';
        if(!visible){node.tabIndex=-1;return;}
        const {x,y,size}=positions[i];
        const dense=this.$('swarmField').classList.contains('network-dense');
        const proof=this.networkRanks?.get(n.name);
        node.title='A'+String(n.id).padStart(3,'0')+' · '+(n.label||n.name)+' · '+n.model+(n.effort?' · '+n.effort:'')+' · '+(number(proof?.score)?'官测 '+proof.score+' 分':proof?.total?'官测通过 '+proof.passed+'/'+proof.total+'（尚未全过）':d.demo?'演示节点':'暂无本队官测回执');
        const label=networkNodeLabel(n,count);
        if(node.textContent!==label)node.textContent=label;
        node.style.whiteSpace='pre';node.style.fontSize=dense&&n.id!==d.selected&&n.state!=='testing'?'0':Math.max(9,Math.min(16,size*.22))+'px';
        node.style.setProperty('line-height','1.15','important');
        node.style.width=size+'px';node.style.setProperty('height',size+'px','important');
        node.style.transform=`translate(${(x-size/2).toFixed(2)}px,${(y-size/2).toFixed(2)}px)`;
        node.tabIndex=0;
      });
      const ctx=this.$('linksCanvas').getContext('2d');
      if(!ctx)return;
      ctx.setTransform(this.dpr,0,0,this.dpr,0,0);ctx.clearRect(0,0,w,h);
      const hub={x:w*.5,y:h*.52};
      // These persistent curves show connections, not invented communications.
      for(const edge of this.network?.connections||[]){
        const b=positions[edge.to];if(!b)continue;
        const dx=b.x-hub.x,dy=b.y-hub.y,distance=Math.hypot(dx,dy)||1;
        const bend=Math.min(distance*.25,52)*(edge.to%2?1:-1);
        const mx=(hub.x+b.x)/2-dy/distance*bend,my=(hub.y+b.y)/2+dx/distance*bend;
        const selected=b.n.id===d.selected;
        ctx.beginPath();ctx.moveTo(hub.x,hub.y);ctx.quadraticCurveTo(mx,my,b.x,b.y);
        ctx.strokeStyle=selected?'#e6a07818':'#8daed50b';ctx.lineWidth=selected?8:5;ctx.stroke();
        const gradient=ctx.createLinearGradient(hub.x,hub.y,b.x,b.y);
        gradient.addColorStop(0,selected?'#e6a078a0':'#8daed582');
        gradient.addColorStop(1,selected?'#e6a07868':'#8daed54d');
        ctx.strokeStyle=gradient;ctx.lineWidth=selected?1.6:1.1;ctx.stroke();
        if(workActive(b.n,!d.paused&&(!d.recording||d.playbackPlaying))&&!this.reduced){
          const u=(t*.32+edge.to*.13)%1,color=b.n.state==='testing'?'#e6a078':'#8daed5';
          for(let tail=7;tail>=0;tail--){
            const v=(u-tail*.014+1)%1,px=(1-v)**2*hub.x+2*(1-v)*v*mx+v**2*b.x,py=(1-v)**2*hub.y+2*(1-v)*v*my+v**2*b.y;
            ctx.beginPath();ctx.arc(px,py,tail?1.5:3.2,0,Math.PI*2);ctx.fillStyle=color;
            ctx.globalAlpha=1-tail*.12;ctx.shadowColor=color;ctx.shadowBlur=tail?4:14;ctx.fill();
          }
          ctx.globalAlpha=1;ctx.shadowBlur=0;
        }
      }
      const at=d.recording?(d.replayClock?.start||0)+(d.replayClock?.position||0):Date.now()/1000;
      const messages=d.demo ? d.demoEvents.filter((e) => e.type==='agent.message').slice(-12).map((e) => ({from:e.agent_id-1,to:Number(e.message.match(/→ A(\d+)/)?.[1])-1,active:!d.paused})) :
        (this.network?.edges||[]).map(e=>({...e,active:messageActive(e,at,!d.paused&&(!d.recording||d.playbackPlaying))}));
      for (let k=0;k<messages.length;k++) {
        const e=messages[k],a=e.from===-1?hub:positions[e.from],b=e.to===-1?hub:positions[e.to];
        if(!a || !b || a===b) continue;
        const mx=(a.x+b.x)/2+(k%2?15:-15),my=(a.y+b.y)/2-25;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo(mx,my,b.x,b.y);
        ctx.strokeStyle=e.active?'#b4d5efbd':e.confirmed?'#8daed561':'#8daed531';ctx.lineWidth=e.active?1.8:1;
        ctx.setLineDash(e.active?[]:[3,6]);ctx.stroke();ctx.setLineDash([]);
        if(e.active && !this.reduced) {
          const u=(t*.25+k*.17)%1;
          for(let trail=5;trail>=0;trail--){
            const v=(u-trail*.018+1)%1;
            const px=(1-v)**2*a.x+2*(1-v)*v*mx+v**2*b.x,py=(1-v)**2*a.y+2*(1-v)*v*my+v**2*b.y;
            ctx.beginPath();ctx.arc(px,py,trail?1.5:2.8,0,Math.PI*2);ctx.globalAlpha=1-trail*.15;
            ctx.fillStyle='#cee7fa';ctx.shadowColor='#8daed5';ctx.shadowBlur=trail?3:12;ctx.fill();
          }
          ctx.globalAlpha=1;ctx.shadowBlur=0;
        }
      }
      for(const p of positions) {
        if(!p)continue;
        if(!['generating','testing'].includes(p.n.state) || d.paused || d.recording)continue;
        const phase=(t*.45+p.n.id*.17)%1;
        ctx.beginPath();ctx.arc(p.x,p.y,p.size*.65+phase*11,0,Math.PI*2);ctx.strokeStyle=COLORS[p.n.state]+Math.round((1-phase)*70).toString(16).padStart(2,'0');ctx.lineWidth=.8;ctx.stroke();
      }
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports={View,simulationAttempts,attemptsFromEvents,performanceGroup,rankTeams,connectedTeams,teamDisplayNames,networkGroups,networkProjection,messageActive,motionEnabled,workActive,networkNodeSize,networkLayout,networkNodeLabel,officialAttemptsFromEvents,rankOfficialTeams};
  else root.JustKernelVisuals={View,connectedTeams,teamDisplayNames};
})(typeof window === 'undefined' ? {} : window);
