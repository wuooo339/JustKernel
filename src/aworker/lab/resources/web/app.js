/* JustKernel: real Deep Agents events and explicitly labeled local simulation. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const MODELS = ['GPT', 'DeepSeek'];
  const ROLES = ['算法分析', 'Kernel 实现', 'Tiling 优化', '性能诊断', '经验整理'];
  const STRATEGIES = [
    ['访存与数据复用', 'buffer-reuse'], ['向量化计算', 'vectorize'],
    ['分块与核划分', 'tile-schedule'], ['流水与同步', 'pipeline'],
    ['精度与数学实现', 'precision'], ['负载均衡', 'load-balance'],
    ['布局与对齐', 'alignment'], ['稀疏结构选择', 'sparse-layout']
  ];
  const STATE_LABELS = { generating: '生成候选', testing: '执行验证', passed: '候选通过', revising: '修正实现', waiting: '等待任务', queued: '等待执行槽位', excluded: '已停用', unconfigured: '未绑定模型' };
  const TASKS = {
    ConfusionMulGrad: { shape: 'input0/input1/input2=(M,N), FP16/FP32', description: '实现 output0=input0*input1 与 output1=ReduceSum(input1*input2, axis, keep_dims)，中间计算使用 FP32。从官方空工程开始。', flow: 'ConfusionMulGrad / 官方空工程' },
  };
  const agents = Array.from({ length: 100 }, (_, i) => ({
    id: i + 1, team: Math.floor(i / 5) + 1, model: MODELS[(i * 7) % MODELS.length],
    role: ROLES[i % 5], strategy: STRATEGIES[Math.floor(i / 5) % STRATEGIES.length],
    state: 'waiting', candidate: 0
  }));
  const state = {
    paused: false, speed: 2, tick: 0, selected: 17, tab: 'path', core: 'search',
    operator: 'ConfusionMulGrad', version: 1, speedup: 1, champion: null,
    candidateCount: 0, events: [], history: [{ round: 0, value: 1 }], skills: [],
    enabled: new Set(MODELS), source: 'demo', originSource: 'demo', replay: [], replayIndex: 0,
    broadcastUntil: 0, following: false, positions: [], lastAnimation: 0
  };
  const demoAgents = agents.map((a) => ({ ...a }));
  const live = { teams: [], devices: [], jobs: [], operations: [], events: [], latest: null, latestError: '', seq: 0, stream: null, timer: null, status: {}, code: new Map(), codePending: new Set(), challenge: null, busy: false };
  let liveGeneration = 0;
  let liveRenderTimer = null;
  const pendingLiveReceipts = [];
  STATE_LABELS.unregistered = '未注册'; STATE_LABELS.model_queued='等待团队执行槽位';
  const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (v, size = 3) => String(v).padStart(size, '0');
  const currentAgent = () => agents[state.selected - 1];
  let toastTimeout;
  const toast = (message) => {
    $('toast').textContent = message;
    $('toast').classList.add('visible');
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => $('toast').classList.remove('visible'), 3000);
  };
  function savedConfig() {
    try { return JSON.parse(localStorage.getItem('justkernel-demo-config') || '{}'); }
    catch { return {}; }
  }
  let config = savedConfig();
  function saveConfig() {
    try { localStorage.setItem('justkernel-demo-config', JSON.stringify(config)); } catch { /* local file storage can be disabled */ }
  }
  function virtualTime() {
    const sec = state.tick;
    return `${pad(Math.floor(sec / 3600), 2)}:${pad(Math.floor(sec / 60) % 60, 2)}:${pad(sec % 60, 2)}`;
  }
  function addReceipt(type, agentId, text, detail = {}) {
    const event = { type, agent_id: agentId || null, message: text, at: virtualTime(), ...detail };
    state.events.push(event);
    if (state.events.length > 6000) state.events.shift();
    const item = document.createElement('div');
    item.className = `receipt ${type === 'candidate.rejected' ? 'warn' : type === 'sota.updated' ? 'sota' : type === 'skill.created' ? 'skill' : ''}`;
    const actualTeam=state.source==='live'&&detail.evidence?live.teams.find(t=>t.id===detail.evidence.team):null;
    const actualModel=actualTeam?profile(actualTeam):null;
    const label=actualTeam?.id || (state.source==='live'?detail.evidence?.team||'系统':agentId?`A${pad(agentId)}`:'SYS');
    const names = { 'agent.state': 'search', 'candidate.created': 'patch', 'candidate.rejected': 'revise', 'evaluation.completed': 'verify', 'sota.updated': 'sota ↑', 'skill.created': 'distill', 'agent.message': state.source==='live'?'reply':'a2a', 'run.started': 'start', 'policy.checked': 'policy' };
    item.innerHTML = `<time>${esc(event.at)}</time><span class="receipt-agent" title="${esc(actualModel?actualModel.model+' · '+(actualModel.effort||'默认强度'):label)}">${esc(label)}${actualModel?`<small>${esc(actualModel.model)}</small>`:''}</span><span class="receipt-text"><b>${esc(names[type] || type)}</b> ${esc(text)}</span>`;
    $('receiptList').prepend(item);
    while ($('receiptList').children.length > 7) $('receiptList').lastChild.remove();
    $('receiptCount').textContent = String(state.events.length);
    return event;
  }
  function setMode(source) {
    state.source = source;
    if (source === 'live') {
      $('modeBadge').innerHTML = '<i></i> 真实运行';
      $('disclaimer').textContent = '真实执行记录 · 本地评测';
      $('flowNpu').textContent = 'physical NPU / 调度队列';
      document.querySelector('.sota-panel .mini-label').textContent = '本地输入验证结果';
      return;
    }
    const demo = source === 'demo';
    $('modeBadge').innerHTML = `<i></i> ${demo ? '演示预演 · 模拟数据' : source === 'recording' ? '导入记录 / REPLAY' : '外部事件 / EVENT INPUT'}`;
    $('connectionText').textContent = demo ? '本地事件驱动 · NPU 未连接' : source === 'recording' ? '本地记录回放 · 来源未经本界面核验' : '接收外部事件 · 本界面不执行评测';
    $('disclaimer').textContent = demo ? '预演事件与示例成绩 · 未调用模型 API / NPU' : '显示导入或外部提供的记录 · 不代表已验证成绩';
    $('flowNpu').textContent = demo ? '8 virtual slots / 预演' : 'external evaluator / 记录';
    document.querySelector('.sota-panel .mini-label').textContent = demo ? '示例性能曲线' : '记录中的性能曲线';
  }
  function buildAgents() {
    $('agentGrid').innerHTML = agents.map((a) => `<button class="agent waiting${a.id === state.selected ? ' selected' : ''}" data-agent="${a.id}" aria-label="智能体 ${pad(a.id)}，${a.model}，${a.role}" title="AGENT_${pad(a.id)} · ${a.model} · ${a.role}">${pad(a.id)}</button>`).join('');
    $('deviceStrip').innerHTML = Array.from({ length: 8 }, (_, i) => `<div class="device">NPU ${i}<b id="device${i}"><i></i> --</b></div>`).join('');
  }
  function renderAgents() {
    if (state.source === 'live') { renderLiveAgents(); return; }
    $('agentGrid').setAttribute('aria-label','100 个预演智能体节点');
    let active = 0;
    let queued = 0;
    for (const a of agents) {
      const element = $('agentGrid').children[a.id - 1];
      element.className = `agent ${a.state}${a.id === state.selected ? ' selected' : ''}${a.id === state.champion ? ' champion' : ''}`;
      element.setAttribute('aria-pressed', String(a.id === state.selected));
      element.title = `AGENT_${pad(a.id)} · ${a.model} · ${a.role} · ${STATE_LABELS[a.state]}`;
      element.setAttribute('aria-label', element.title);
      if (a.state === 'testing' || a.state === 'generating') active++;
      if (a.state === 'queued' || a.state === 'waiting') queued++;
    }
    $('activeCount').textContent = String(active);
    $('queueCount').textContent = String(queued);
    const testing = agents.filter((a) => a.state === 'testing');
    for (let i = 0; i < 8; i++) $('device' + i).innerHTML = `<i></i>${testing[i] ? 'A' + pad(testing[i].id) : '--'}`;
  }
  function renderInspector() {
    document.querySelector('[data-tab="overview"]').hidden=state.source!=='live';
    if(state.source!=='live'&&state.tab==='overview')state.tab='path';
    if (state.source === 'live') { renderLiveInspector(); return; }
    $('teamProgress').hidden=true;
    const a = currentAgent();
    $('agentAvatar').textContent = pad(a.id);
    $('agentName').textContent = `AGENT_${pad(a.id)}`;
    $('agentModel').textContent = a.model;
    $('agentRole').textContent = a.role + ' / ' + a.strategy[0];
    $('agentStatus').textContent = STATE_LABELS[a.state] || '记录状态';
    $('agentTeam').textContent = `${pad(a.team, 2)} / ${a.strategy[0]}`;
    $('agentBranch').textContent = `a${pad(a.id)}/${a.strategy[1]}`;
    $('agentParent').textContent = `public/sota-v${pad(state.version)}`;
    $('followButton').textContent = state.following ? '已跟随 SOTA · 取消' : '跟随公共 SOTA ↗';
    document.querySelectorAll('[data-tab]').forEach((el) => el.setAttribute('aria-selected', String(el.dataset.tab === state.tab)));
    const demo = state.source === 'demo';
    if (!demo) {
      const related = state.events.filter((e) => e.agent_id === a.id).slice(-6).reverse();
      $('inspectorContent').innerHTML = related.length ? related.map((e) => `<div class="path-step"><i>›</i><div><b>${esc(e.type)}</b><p>${esc(e.message || '无附加说明')}</p></div></div>`).join('') : '<p class="dim">此智能体暂无导入记录。</p>';
      return;
    }
    if (state.tab === 'path') {
      const steps = [
        ['读取公共 SOTA 与算子规格', `parent v${pad(state.version)} · ${state.operator}`],
        ['检查优化经验的适用条件', `${a.strategy[0]} / 不复用历史计算结果`],
        [`提出${a.strategy[0]}候选`, `branch a${pad(a.id)} · 独立源码工作区`],
        ['编译、校验与设备计时', '由独立执行器返回证据'],
        ['共享候选并提炼经验', '代码 / 版本 / 成败原因可追溯']
      ];
      const current = a.state === 'testing' ? 3 : a.state === 'passed' ? 4 : a.state === 'generating' ? 2 : a.state === 'revising' ? 2 : 1;
      $('inspectorContent').innerHTML = steps.map((s, i) => `<div class="path-step ${i === current ? 'current' : ''}"><i>${i < current ? '✓' : i === current ? '›' : '·'}</i><div><b>${esc(s[0])}</b><p>${esc(s[1])}</p></div></div>`).join('');
    } else if (state.tab === 'code') {
      $('inspectorContent').innerHTML = `<pre class="code-view"><span class="code-comment">// 示例补丁 · 非可提交完整 Kernel\n// a${pad(a.id)}/${esc(a.strategy[1])}</span>\n<span class="code-del">- tileLength = DEFAULT_TILE;</span>\n<span class="code-add">+ tileLength = PickAlignedTile(\n+   ubCapacity, elementBytes, tail);</span>\n\n<span class="code-comment">// 单次调用内复用，保留尾部计算</span>\n<span class="code-add">+ CopyIn(tile);\n+ ComputeFullTileAndTail(tile);\n+ CopyOut(tile);</span>\n\n<span class="code-comment">// 候选必须重新通过完整评测</span></pre>`;
    } else {
      const peer = (a.id + 12) % 100 + 1;
      $('inspectorContent').innerHTML = `<div class="chat-message"><b>A${pad(a.id)} → A${pad(peer)} / 示例通信</b><p>我在探索${esc(a.strategy[0])}。请检查当前候选的尾块处理和同步依赖。</p></div><div class="chat-message reply"><b>A${pad(peer)} → A${pad(a.id)}</b><p>已引用公共 v${pad(state.version)}。建议保留通用尾部路径，提交独立验证后再比较收益。</p></div><div class="chat-message"><b>PUBLIC SOTA → ALL</b><p>共享完整代码与验证记录。其他团队可以继续创建分支。</p></div>`;
    }
  }
  function renderChart() {
    if (state.source === 'live') { renderLiveResults(); return; }
    const points = state.history;
    const maxRound = Math.max(state.tick, points[points.length - 1]?.round || 0, 1);
    const ceiling = Math.max(3, ...points.map((p) => p.value));
    const floor = Math.min(1, ...points.map((p) => p.value));
    const xy = points.map((p) => [32 + (p.round / maxRound) * 331, 79 - ((p.value - floor) / Math.max(ceiling - floor, 1)) * 64]);
    let path = xy.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(' ');
    if (xy.length === 1) path += ' L363 79';
    $('chartLine').setAttribute('d', path);
    const last = xy[xy.length - 1] || [32, 79];
    $('chartArea').setAttribute('d', path + ` L${xy.length === 1 ? 363 : last[0]} 80 L32 80 Z`);
    $('chartDot').setAttribute('cx', xy.length === 1 ? 363 : last[0]);
    $('chartDot').setAttribute('cy', last[1]);
    const labels = $('sotaChart').querySelectorAll('.chart-label');
    labels[0].textContent = ceiling.toFixed(1) + '×';
    labels[1].textContent = ((ceiling + floor) / 2).toFixed(1) + '×';
    labels[2].textContent = floor.toFixed(1) + '×';
    $('chartRound').textContent = 'round ' + state.tick;
    $('sotaValue').textContent = state.speedup.toFixed(2);
    $('sotaVersion').textContent = 'v' + pad(state.version);
    $('flowSota').textContent = `public / version v${pad(state.version)}`;
    $('candidateCount').textContent = state.candidateCount + ' candidates';
    $('sotaAuthor').textContent = state.champion ? `from A${pad(state.champion)}` : 'public baseline';
  }
  function renderKnowledge() {
    if (state.source === 'live') {
      renderLiveKnowledge();
      return;
    }
    $('skillCount').textContent = state.skills.length + ' skills';
    if (state.core === 'sparse') {
      const cells = Array.from({ length: 144 }, (_, i) => `<i class="${((i * 31 + Math.floor(i / 24) * 17) % 23) < 5 ? 'filled' : ''}"></i>`).join('');
      $('knowledgeView').innerHTML = `<div class="sparse-caption">结构分布示意 / 非输入张量实读</div><div class="sparse-heatmap" aria-label="示例稀疏结构">${cells}</div><div class="skill-row"><span class="skill-symbol">▦</span><div><b>结构 → 格式 → 分块 → 实测择优</b><p>比较候选策略，同时核算格式处理成本</p></div></div>`;
      $('knowledgeFooter').textContent = '策略适用性受任务规则约束';
    } else if (state.skills.length) {
      $('knowledgeView').innerHTML = state.skills.slice(-3).reverse().map((s) => `<div class="skill-row"><span class="skill-symbol">◇</span><div><b>${esc(s.name)}</b><p>${esc(s.description)}</p></div><span class="skill-state">${esc(s.status || 'draft')}</span></div>`).join('');
      $('knowledgeFooter').textContent = '同算子复用 / 跨算子迁移 / 反例修订';
    } else {
      $('knowledgeView').innerHTML = '<div class="skill-row"><span class="skill-symbol">◇</span><div><b>等待经验蒸馏</b><p>从候选补丁与评测轨迹形成可复用方法</p></div><span class="skill-state">pending</span></div>';
    }
  }
  function renderAll() {
    renderAgents(); renderInspector(); renderChart(); renderKnowledge();
    renderVisuals();
  }
  function renderVisuals() {
    const real = state.source === 'live';
    const recording = Boolean(live.recording) && real;
    const pendingSimulations = real && live.simulation?.available!==false ? (live.simulation_jobs || []).filter(j=>['queued','running'].includes(j.state)) : [];
    const connectedNames = new Set(real ? visibleTeams().map(t=>t.id) : []);
    const nodes = agents.map((a) => {
      const team = real ? teamForId(a.id) : null;
      return {id:a.id,name:real ? team?.id || '未注册' : 'A'+pad(a.id),
        model:real ? profile(team)?.model || team?.model || '' : a.model,effort:real?profile(team)?.effort:'',
        groupKey:real ? [profile(team)?.provider,profile(team)?.model,profile(team)?.name].join(' ') : a.model,state:a.state};
    });
    visuals.update({demo:state.source === 'demo',recording,judgeOnly:real && live.status.execution_mode==='judge-only',selected:state.selected,
      replayClock:recording?live.replayClock:null,
      simulation:real?live.simulation:null,simulationJobs:real?(live.simulation_jobs||[]):[],
      selectedTeam:real ? activeTeam()?.id || '__unregistered__' : null,
      nodes,events:real ? live.events.filter(e=>recording||connectedNames.has(e.team)||['controller','judger'].includes(e.team)&&e.kind==='team.message') : [],demoEvents:state.events,history:state.history,
      expectedCases:live.challenge?.cases?.length ?? 15,
      stages:real ? flowEvents(activeTeam()).filter((e)=>e.kind==='stage.updated') : [],
      tick:state.tick,paused:real ? recording&&!live.replayClock?.playing : state.paused,playbackPlaying:Boolean(recording&&live.replayClock?.playing),
      broadcasting:performance.now()<state.broadcastUntil,
      pendingJobs:real ? live.jobs.filter((j)=>['queued','running'].includes(j.state)).length + pendingSimulations.length : 0,
      selectedRunning:real ? (!recording||live.replayClock?.playing) && (live.operations.some(o=>o.team===activeTeam()?.id&&o.state==='running')||live.jobs.some(j=>j.team===activeTeam()?.id&&j.state==='running')||pendingSimulations.some(j=>j.team===activeTeam()?.id)):!state.paused,
      running:real ? (!recording||live.replayClock?.playing) && (live.operations.some((o)=>o.state==='running') || live.jobs.some((j)=>j.state==='running') || pendingSimulations.length>0) : !state.paused});
  }
  function refreshPositions() {
    visuals.resize();
  }
  function announceSota() {
    $('broadcastVersion').textContent = 'v' + pad(state.version);
    $('broadcast').classList.add('visible');
    state.broadcastUntil = performance.now() + 1500;
  }
  function addSkill() {
    const templates = [
      ['容量约束下的对齐分块', '条件：UB 容量与尾部边界 · 动作：选择对齐 Tile'],
      ['同调用内的数据复用', '条件：依赖与精度允许 · 保留全部输出计算'],
      ['流水深度的适用边界', '失败反例回流 · 调整缓冲与同步策略'],
      ['跨算子的访存经验迁移', '从当前算子提炼动作 · 新算子重新验证']
    ];
    const index = state.skills.length;
    const t = templates[index % templates.length];
    state.skills.push({ id: 'SK-' + pad(index + 1), name: t[0], description: t[1], status: index % 3 === 2 ? '反例修订' : '待回归', source_agent: state.champion || 17 });
    if (state.skills.length > 50) state.skills.shift();
    addReceipt('skill.created', state.champion, `${t[0]} · 示例条目待回归`);
  }
  function demoTick() {
    state.tick++;
    const enabled = agents.filter((a) => state.enabled.has(a.model));
    const testing = new Set(Array.from({ length: Math.min(8, enabled.length) }, (_, i) => enabled[(state.tick * 3 + i * 13) % enabled.length].id));
    for (const a of agents) {
      if (!state.enabled.has(a.model)) { a.state = 'excluded'; continue; }
      const p = (state.tick + a.id * 7) % 17;
      a.state = testing.has(a.id) ? 'testing' : p < 5 ? 'generating' : p < 9 ? 'queued' : p < 12 ? 'passed' : p === 12 ? 'revising' : 'waiting';
      if (a.state === 'testing') a.candidate++;
    }
    const actor = enabled[(state.tick * 11) % enabled.length];
    const peer = enabled[(state.tick * 11 + 7) % enabled.length];
    state.candidateCount += 8;
    addReceipt('candidate.created', actor.id, `${actor.model} / ${actor.strategy[0]} / candidate ${pad(state.candidateCount, 4)}`);
    if (state.tick % 4 === 0) addReceipt('candidate.rejected', peer.id, '示例：尾部验证未通过，退回修正');
    else addReceipt('evaluation.completed', peer.id, '示例：精度通过，保留完整计时记录');
    if (state.tick % 3 === 0) addReceipt('agent.message', actor.id, `→ A${pad(peer.id)} · 共享候选与优化建议`);
    if (state.tick % 6 === 0) {
      state.version++;
      state.speedup = Number((1 + 1.98 * (1 - Math.exp(-state.tick / 34))).toFixed(2));
      state.champion = actor.id;
      addReceipt('sota.updated', actor.id, `v${pad(state.version)} · ${state.speedup.toFixed(2)}×（预演示例）`, { version: state.version, speedup: state.speedup });
      announceSota();
      if (state.following) state.selected = actor.id;
    }
    if (state.tick % 10 === 0) addSkill();
    state.history.push({ round: state.tick, value: state.speedup });
    if (state.history.length > 600) state.history = state.history.filter((_, i) => i % 2 === 0);
    renderAll();
  }
  function applyEvent(event, record = true) {
    if (!event || typeof event !== 'object' || typeof event.type !== 'string') throw new Error('事件需要包含 type 字段');
    const agentId = Number(event.agent_id);
    const a = Number.isInteger(agentId) && agentId >= 1 && agentId <= 100 ? agents[agentId - 1] : null;
    if (event.type === 'agent.state' && a && Object.hasOwn(STATE_LABELS, event.state)) a.state = event.state;
    if (event.type === 'candidate.created') state.candidateCount++;
    if (event.type === 'sota.updated') {
      const speedup = Number(event.speedup);
      if (!Number.isFinite(speedup) || speedup <= 0 || speedup > 10000) throw new Error('无效的 speedup');
      state.speedup = speedup;
      state.version = Number.isInteger(event.version) && event.version > 0 ? event.version : state.version + 1;
      state.champion = a?.id || null;
      state.history.push({ round: state.tick, value: speedup });
      announceSota();
    }
    if (event.type === 'skill.created') state.skills.push({ id: String(event.skill_id || 'imported'), name: String(event.name || event.message || '导入经验').slice(0, 120), description: String(event.description || '来自外部记录').slice(0, 300), status: String(event.status || '未核验').slice(0, 20) });
    if (record) {
      const { type, agent_id, message, ...extra } = event;
      addReceipt(type.slice(0, 80), a?.id, String(message || '').slice(0, 500), { ...extra, at: String(event.at || virtualTime()).slice(0, 30) });
    }
  }
  function reset(source = 'demo') {
    state.tick = 0; state.version = 1; state.speedup = 1; state.champion = null;
    state.candidateCount = 0; state.events = []; state.skills = [];
    state.history = [{ round: 0, value: 1 }]; state.replayIndex = 0;
    for (const a of agents) { a.state = 'waiting'; a.candidate = 0; }
    $('receiptList').replaceChildren();
    $('receiptCount').textContent = '0';
    $('broadcast').classList.remove('visible');
    $('flowTask').textContent = TASKS[state.operator]?.flow || state.operator;
    setMode(source);
    state.originSource = source === 'demo' ? 'demo' : 'unknown';
    if (source === 'demo') {
      $('searchPhase').textContent='exploring';$('knowledgePhase').textContent='learning';$('sparsePhase').textContent='concept';
      addReceipt('run.started', null, `${state.operator} · 100 agents / 8 virtual NPU slots`);
      addReceipt('policy.checked', null, '任务规则加载 · 示例核查策略');
      demoTick();
    } else renderAll();
    requestAnimationFrame(refreshPositions);
  }
  function setPaused(paused) {
    state.paused = paused;
    $('playButton').textContent = paused ? '▶ 继续播放' : state.source === 'demo' ? 'Ⅱ 暂停预演' : 'Ⅱ 暂停回放';
    $('loopState').textContent = paused ? '已暂停' : '预演中';
    $('footerStatus').textContent = paused ? 'PLAYBACK PAUSED' : state.source === 'demo' ? 'DEMO ENGINE RUNNING' : 'EVENT PLAYBACK';
    $('terminal').classList.toggle('paused', paused);
    if (state.source === 'live') {
      $('playButton').textContent = '启动团队 PK →';
      $('loopState').textContent = live.operations.some((o) => o.state === 'running') ? '优化中' : '待开始';
      $('footerStatus').textContent = 'REAL EXECUTION / ' + visibleTeams().length + ' TEAMS';
    }
    renderVisuals();
  }
  function selectAgent(id) {
    state.selected = id;
    renderAgents(); renderInspector();
    renderVisuals();
    document.dispatchEvent(new CustomEvent('justkernel:team-selected'));
  }
  function setCore(core) {

    state.core = core;
    document.querySelectorAll('[data-core]').forEach((button) => button.classList.toggle('selected', button.dataset.core === core));
    $('knowledgePanel').classList.toggle('core-highlight', core !== 'search');
    $('flowCaption').textContent = core === 'knowledge' ? '经验携带适用条件与验证证据回流' : core === 'sparse' ? '结构与执行策略联合选择，统一评测' : '每个候选留下代码与评测记录';

    $('sparsePhase').textContent = core === 'sparse' ? 'exploring' : 'standby';
    renderKnowledge();
  }
  function changeOperator(value) {
    if (!Object.hasOwn(TASKS, value)) return;
    state.operator = value;
    $('operator').value = value;
    $('taskDescription').value = TASKS[value].description;
    $('taskShape').value = TASKS[value].shape;
    config.operator = value;
    config.description = TASKS[value].description;
    config.shape = TASKS[value].shape;
    saveConfig();
    reset();
    setPaused(false);
    $('sparsePhase').textContent = 'standby';
  }
  function showKnowledge() {
    if (state.source === 'live') {
      $('knowledgeDetail').innerHTML = '<h2>有证据的条件经验</h2><pre class="event-detail">' + esc(JSON.stringify(live.experiences || [], null, 2)) + '</pre>';
      $('knowledgeDialog').showModal(); return;
    }
    const s = state.skills[state.skills.length - 1];
    $('knowledgeDetail').innerHTML = `<h2>${s ? esc(s.name) : '经验如何形成'}</h2><dl><dt>适用条件</dt><dd>算子语义、输入规格、精度、设备与 CANN 版本满足条目要求。</dd><dt>优化动作</dt><dd>${s ? esc(s.description) : '从代码差异中提取可复用动作，并记录适用边界。'}</dd><dt>来源证据</dt><dd>${state.source === 'demo' ? '当前为演示条目，无真实评测证据。' : '来源于导入或外部事件，需在独立评测系统核验。'}</dd><dt>回归与反例</dt><dd>新 Shape 与跨算子迁移需要重新通过正确性和性能验证；失败后修订条件。</dd></dl>`;
    $('knowledgeDialog').showModal();
  }
  function animate(now) {
    visuals.frame(now);
    if (now > state.broadcastUntil) $('broadcast').classList.remove('visible');
    requestAnimationFrame(animate);
  }
  async function lab(path, data) {
    const response = await fetch('/api/lab' + path, {
      method: data === undefined ? 'GET' : 'POST',
      headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result));
    return result;
  }
  function visibleTeams() { return window.JustKernelVisuals.connectedTeams(live.teams,live.status.models||[],Boolean(live.recording)); }
  function activeTeam() { return teamForId(state.selected); }
  function teamForId(id) { return visibleTeams()[id - 1]; }
  const STAGES = [['input','读取规格与技能'],['search','规划 · 协作 · 改码'],['policy','硬约束自查'],['queue','申请逻辑 NPU'],['execute','编译与设备运行'],['verify','逐点正确性与计时'],['share','发布公共候选'],['distill','蒸馏条件经验']];
  const stageLabels = { started:'执行中', progress:'执行中', completed:'已完成', failed:'失败', skipped:'跳过', pending:'未执行' };
  function profile(team) { return (live.status.models || []).find((m) => m.id === team?.model); }
  function teamEvents(team) { return live.events.filter((e) => e.team === team?.id); }
  function currentRun(team) {
    return [...(live.runs || [])].filter((r) => r.team === team?.id).sort((a,b) => b.started-a.started)[0];
  }
  function flowEvents(team) {
    const entries = teamEvents(team);
    const start = entries.findLast((e) => e.kind === 'control.started' || e.kind === 'team.turn.started');
    return start ? entries.filter((e) => e.seq >= start.seq) : entries;
  }
  function teamState(team) {
    if (!team || !team.active) return team ? 'excluded' : 'unregistered';
    if(live.simulation?.available && (live.simulation_jobs||[]).some(j=>j.team===team.id&&j.state==='running'))return 'testing';
    if(live.simulation?.available && (live.simulation_jobs||[]).some(j=>j.team===team.id&&j.state==='queued'))return 'queued';
    if (live.jobs.some((j) => j.team === team.id && j.state === 'running')) return 'testing';
    if (live.jobs.some((j) => j.team === team.id && j.state === 'queued')) return 'queued';
    if (live.operations.some((o) => o.team === team.id && o.state === 'running')) { const slot=teamEvents(team).findLast(e=>e.kind.startsWith('model.slot.')); return slot?.kind==='model.slot.waiting'?'model_queued':'generating'; }
    const event = teamEvents(team).findLast((e) => ['team.turn.failed','control.failed','team.turn.completed','evaluation.completed'].includes(e.kind));
    if (event?.kind.endsWith('failed') || event?.data.pass === false) return 'revising';
    if (event?.kind === 'evaluation.completed') return 'passed';
    return profile(team)?.configured ? 'waiting' : 'unconfigured';
  }
  function renderLiveFlow() {
    const team = activeTeam(), entries = flowEvents(team);
    $('liveFlow').innerHTML = `<div class="flow-context">${esc(team?.id || '选择团队')} <span>${esc(currentRun(team)?.id.slice(0,8) || '等待任务')}</span></div>` + STAGES.map(([key,label],i) => {
      const e = entries.findLast((e) => e.kind === 'stage.updated' && e.data.stage === key);
      const status = e?.data.state || 'pending';
      return `<button class="live-step ${esc(status)}" data-live-stage="${key}"><span class="step-number">${String(i+1).padStart(2,'0')}</span><span><b>${label}</b><small>${esc(e?.data.message || '等待实际事件')}</small></span><em>${stageLabels[status]}</em></button>`;
    }).join('');
  }
  function renderLiveAgents() {
    $('agentGrid').setAttribute('aria-label',`${visibleTeams().length} 支已配置团队`);
    let active = 0;
    for (const a of agents) {
      const team = teamForId(a.id); a.state = teamState(team);
      const el = $('agentGrid').children[a.id - 1];
      el.className = `agent ${a.state}${a.id === state.selected ? ' selected' : ''}`;
      const model=profile(team);
      const label = team ? `${team.id} · ${model?.model || team.model}${model?.effort?' · '+model.effort:''} · ${STATE_LABELS[a.state]}` : `槽位 ${pad(a.id)} · 未注册`;
      el.title = label; el.setAttribute('aria-label', label); el.setAttribute('aria-pressed', String(a.id === state.selected));
      if (['generating','testing'].includes(a.state)) active++;
    }
    $('activeCount').textContent = String(active);
    $('queueCount').textContent = String(visibleTeams().filter(t=>['queued','model_queued'].includes(teamState(t))).length);
    for (let i = 0; i < 8; i++) {
      const device = live.devices[i], job = device && live.jobs.find((j) => j.device === device.id && j.state === 'running');
      $('device'+i).textContent = !device ? '未接入' : job ? job.team : '空闲';
    }
    document.querySelector('.swarm-panel .mini-label').textContent = `${visibleTeams().length} 支团队`;
    document.querySelectorAll('.swarm-models input').forEach((el) => {
      el.closest('label').hidden=state.source==='live'&&!visibleTeams().some((t)=>new RegExp(el.value,'i').test(profile(t)?.name || t.model));
      el.checked = visibleTeams().some((t) => new RegExp(el.value,'i').test(profile(t)?.name || t.model));
    });
    $('deviceStrip').hidden=live.status.execution_mode==='judge-only';
    $('evaluateButton').hidden=live.status.execution_mode==='judge-only';
    const judgeOnly=live.status.execution_mode==='judge-only';
    const simulated=Boolean(live.simulation?.required);
    document.querySelector('.flow-node[data-stage="3"] .node-title').textContent=simulated?'kernel · simulate':judgeOnly?'candidate · freeze':'npu · execute';
    document.querySelector('.flow-node[data-stage="4"] .node-value').textContent=simulated?'本队输入 / 数值与流水证据':judgeOnly?'CANN Judge / 官测反馈':'correctness + latency';
    $('flowNpu').textContent=simulated?'910B4 / CPU 仿真队列':judgeOnly?'代码包 / 等待提交':'physical NPU / 调度队列';
    renderLiveFlow();
  }
  function meaningfulEvent(e) { return !['model.completed','model.output.delta'].includes(e.kind); }
  function eventSummary(e) {
    const d = e.data || {};
    if(e.kind==='team.message')return `${e.team} → ${d.recipient} · ${d.transport==='a2a'?'A2A 已送达':'共享消息'} · ${d.message}`;
    if(e.kind==='simulation.status.updated')return `独立仿真 · ${d.phase||d.state} · ${d.passed_cases||0}/${d.requested_cases||0} 本地点`;
    if (e.kind === 'stage.updated') return `${d.stage} / ${stageLabels[d.state] || d.state} · ${d.message}`;
    if (e.kind === 'tool.started') return `${d.agent} → ${d.tool} · ${d.input}`;
    if (e.kind === 'tool.completed' || e.kind === 'tool.failed') return `${d.agent} ← ${d.tool} · ${d.output}`;
    if (e.kind === 'evaluation.completed') return `${d.pass ? '通过' : '未通过'} · ${(d.cases || []).length} 点 · SHA ${String(d.source_sha256).slice(0,10)}`;
    return d.answer || d.text || d.message || d.agent || d.prompt || d.path || d.source_sha256 || d.action || e.kind;
  }
  function evidenceButton(e) {
    return `<button class="evidence-row" data-evidence="${e.seq}"><b>${esc(e.data.agent || 'team')} / ${esc(e.data.tool || e.kind)}</b><span>${esc(String(eventSummary(e)).slice(0,280))}</span></button>`;
  }
  function renderLiveInspector() {
    const team = activeTeam(), slot = state.selected, model = profile(team);
    $('agentAvatar').textContent = team?pad(slot):'—'; $('agentName').textContent = team?.id || '暂无团队';
    $('agentModel').textContent = model?model.model+(model.effort?' · '+model.effort:''):'';
    $('agentRole').textContent = team ? `${model?.name || team.model} · Deep Agents · ${model?.model||team.model}${model?.effort ? ' · '+model.effort : ''}` : '先配置模型并组建团队';
    $('agentStatus').textContent = STATE_LABELS[teamState(team)];
    $('teamProgress').hidden=false;
    const planOpen=$('teamProgress').querySelector('details')?.open;
    const progress=window.JustKernelActivity.teamProgress(live.events,team?.id,live.operations,live.challenge?.manifest?.baseline_sha256);
    const monitor=window.JustKernelActivity.teamMonitor(live.events,team?.id,live.operations,live.simulation_jobs||[],live.recording?(live.events.at(-1)?.at||0):Date.now()/1000,live.simulation?.available);
    const usage=monitor.usage.reported?`本轮已返回 Token · 输入 ${monitor.usage.input.toLocaleString()} / 输出 ${monitor.usage.output.toLocaleString()}`:'Token 用量等待提供商返回';
    $('teamProgress').innerHTML=`<strong>${esc(monitor.title)}</strong><div class="progress-facts">${esc(usage)}</div><div class="progress-facts">${progress.changes} 个源码版本${monitor.elapsed!==null?` · 最近模型调用 ${monitor.elapsed} 秒`:''}${progress.lastAt?' · 更新 '+new Date(progress.lastAt*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):''}</div>${progress.plan.length?`<details${planOpen?' open':''}><summary>开发计划 ${progress.done}/${progress.plan.length}</summary>${progress.plan.map(p=>`<div>${p.status==='completed'?'✓':p.status==='in_progress'?'→':'○'} ${esc(p.content)}</div>`).join('')}</details>`:''}`;
    $('agentTeam').textContent = team?.id || '—'; $('agentBranch').textContent = team ? `${team.id}/${live.challenge?.manifest?.project_files?'project/':'kernel.asc'}` : '—';
    $('agentParent').textContent = live.code.get(team?.id)?.sha256?.slice(0,16) || '冻结基准 / 见任务';
    $('agentFooter').textContent = '统一工具轨迹 · 检查点 · 条件经验'; $('followButton').textContent = '查看团队任务 ↗';
    document.querySelectorAll('[data-tab]').forEach((el) => el.setAttribute('aria-selected',String(el.dataset.tab === state.tab)));
    if (!team) { $('inspectorContent').innerHTML = '<p class="dim">点击已注册团队查看过程，或组建新团队。</p>'; return; }
    if (state.tab === 'code') {
      const code = live.code.get(team.id);
      $('inspectorContent').innerHTML = code ? `<pre class="code-view">${live.recording?'// 导出时源码快照，非当前播放时刻的完整源码\n':''}// SHA256 ${esc(code.sha256)}\n${esc(code.source)}</pre>` : `<p class="dim">${live.recording?'此导入文件没有附带该团队源码。':'正在读取真实源码…'}</p>`;
      if (!code && !live.codePending.has(team.id) && team.active && !live.recording) {
        live.codePending.add(team.id);
        lab('/control/teams/'+encodeURIComponent(team.id)+'/source').then((data) => {live.code.set(team.id,data); if(state.source==='live') renderInspector();}).catch((e)=>toast(e.message)).finally(()=>live.codePending.delete(team.id));
      }
      return;
    }
    if(state.tab==='overview'){
      $('inspectorContent').innerHTML=`<div class="monitor-team-list">${visibleTeams().map(t=>{
        const m=window.JustKernelActivity.teamMonitor(live.events,t.id,live.operations,live.simulation_jobs||[],live.recording?(live.events.at(-1)?.at||0):Date.now()/1000,live.simulation?.available);
        return `<button class="monitor-team" data-monitor-team="${esc(t.id)}"><b>${esc(t.id)}</b><span>${esc(m.title)}</span><small>${m.usage.reported?'输出 '+m.usage.output.toLocaleString()+' Token':'等待用量回执'}${m.lastAt?' · '+new Date(m.lastAt*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):''}</small></button>`;
      }).join('')}</div>`;
      return;
    }
    let related = teamEvents(team).filter(meaningfulEvent);
    const members = (live.members || []).filter((m) => m.team === team.id);
    const roster = `<div class="member-list">${members.map((m) => {
      const activity = related.findLast((e) => ['member.started','member.completed'].includes(e.kind) && e.data.agent === m.name);
      return `<span class="member-chip ${activity?.kind === 'member.started' ? 'working' : ''}">${esc(m.name)} <small>${esc(m.role)} · ${esc(m.model || team.model)}</small></span>`;
    }).join('')}</div>`;
    if (state.tab === 'chat') {
      const notices=(live.a2a_notices||[]).filter(n=>n.recipient===team.id);
      const deliverySummary=`<div class="monitor-simulation"><b>系统 A2A 投递</b><span>已送达 ${notices.filter(n=>n.state==='delivered').length} · 待送达 ${notices.filter(n=>n.state==='pending').length}</span>${notices.filter(n=>n.state==='pending'&&n.error).map(n=>`<small>${esc(n.topic)} · 重试等待 · ${esc(n.error)}</small>`).join('')}</div>`;
      related = live.events.filter((e) => e.kind === 'team.message' && (e.team === team.id || e.data.recipient === team.id) || e.team === team.id && e.kind === 'agent.message');
      $('inspectorContent').innerHTML = deliverySummary + (live.recording ? '<p class="dim">离线通信记录</p>' : `<button class="text-button" id="sendMessage">跨团队发消息 ↗</button>`) + (related.length ? related.slice(-20).reverse().map(evidenceButton).join('') : '<p class="dim">等待真实成员回复或团队通信。</p>');
      const sendMessageButton=$('sendMessage'); if(sendMessageButton)sendMessageButton.onclick = () => {
        $('messageTeam').innerHTML = visibleTeams().filter((t)=>t.id!==team.id).map((t)=>`<option>${esc(t.id)}</option>`).join('');
        $('messageDialog').showModal();
      };
    } else {
      const run = currentRun(team);
      const oldOutput=$('inspectorContent').querySelector('.monitor-stream');
      const keepTop=oldOutput?.scrollTop||0,atBottom=!oldOutput||oldOutput.scrollHeight-oldOutput.scrollTop-oldOutput.clientHeight<24;
      const parentTop=$('inspectorContent').scrollTop;
      const toolOpen=$('inspectorContent').querySelector('.monitor-tool')?.open??true,rawOpen=$('inspectorContent').querySelector('.monitor-raw')?.open||false;
      const sim=monitor.simulation,simState={queued:'排队中',running:'执行中',completed:'本次通过',failed:'失败，需修正',cancelled:'未执行，已取消'};
      const simTotal=sim?.requested_cases??sim?.case_ids?.length??0,fullTotal=live.challenge?.cases?.length||15;
      const simPassed=sim?.passed_cases??(sim?.cases||[]).filter(c=>c.pass).length;
      $('inspectorContent').innerHTML = roster +
        `<section class="monitor-output"><div class="monitor-section-title"><b>${esc(monitor.agent)} · 公开输出</b><span>${monitor.modelBusy?'正在接收':'最近一次'}</span></div><pre class="monitor-stream">${esc(monitor.text|| (monitor.tools.length?'模型正在生成工具请求，展开下方查看参数。':monitor.modelBusy?'模型调用进行中，尚无公开输出；收到后实时显示。':'暂无公开文本，执行步骤见下方。'))}</pre>${monitor.tools.length?`<details class="monitor-tool"${toolOpen?' open':''}><summary>工具请求 · ${esc(monitor.tools.map(t=>t.name||'生成中').join(' / '))}</summary>${monitor.tools.map(t=>`<b>${esc(t.name||'工具名接收中')}</b><pre>${esc(t.args)}</pre>`).join('')}</details>`:''}${monitor.truncated?'<small>当前展示已截取；完整工程保留在源码中。</small>':''}</section>`+
        (sim?`<div class="monitor-simulation"><b>本队独立仿真 · ${esc(monitor.simulatorOffline?'心跳中断，等待恢复':simState[sim.state]||sim.state)}</b><span>本次 ${simPassed}/${simTotal} · 全套 ${fullTotal} 个暂拟点${simTotal<fullTotal?' · 子集探针，未覆盖全套':''}</span><span>${esc(monitor.simulationPhase)} · ${esc(sim.source_sha256?.slice(0,8)||'')} · 官方对应待确认</span></div>`:'')+
        `<div class="monitor-section-title"><b>实际执行步骤</b><span>点击查看证据</span></div><div class="monitor-steps">${monitor.steps.length?monitor.steps.map(s=>`<button class="monitor-step ${s.state==='执行失败'?'failed':''}" data-evidence="${s.evidence||s.seq}"><span class="monitor-step-time">${new Date(s.at*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}</span><span><b>${esc(s.title)}</b><small>${esc(s.agent)}${s.detail?' · '+esc(s.detail):''}</small></span><em>${esc(s.state)}</em></button>`).join(''):'<p class="dim">等待实际任务，不生成示意步骤。</p>'}</div>`+
        (run?.trace_url&&/^https:\/\//.test(run.trace_url)?`<a class="trace-link" href="${esc(run.trace_url)}" target="_blank" rel="noreferrer">在 LangSmith 查看完整数据流 ↗</a>`:'')+
        `<details class="monitor-raw"${rawOpen?' open':''}><summary>原始事件记录</summary>${related.slice(-30).reverse().map(evidenceButton).join('')}</details>`;
      const output=$('inspectorContent').querySelector('.monitor-stream');
      if(output)output.scrollTop=atBottom?output.scrollHeight:keepTop;
      $('inspectorContent').scrollTop=parentTop;
    }
  }
  function renderLiveKnowledge() {
    const skills = live.experiences || [];
    $('skillCount').textContent = skills.length+' 条';
    $('knowledgePhase').textContent = skills.length ? 'evolving' : 'awaiting evidence';
    $('sparsePhase').textContent = 'research';
    if (state.core === 'sparse') {
      $('knowledgeView').innerHTML = '<div class="skill-row"><span class="skill-symbol">▦</span><div><b>结构分析扩展入口</b><p>当前只有 ConfusionMulGrad，没有经过验证的稀疏加速结果。可通过技能与工具接入结构分析，再用相同评测链验证。</p></div></div>';
    } else {
      $('knowledgeView').innerHTML = skills.length ? skills.slice(0,5).map((s)=>`<div class="skill-row"><span class="skill-symbol">◇</span><div><b>${esc(s.data.title)}</b><p>${esc(s.data.conditions)} · ${esc(s.data.action)}</p></div><span class="skill-state">${esc(s.data.scope)}</span></div>`).join('') : '<div class="skill-row"><span class="skill-symbol">◇</span><div><b>等待真实实验形成经验</b><p>通过验证的优化方法会沉淀到这里，供团队继续学习。</p></div></div>';
    }
    $('knowledgeFooter').textContent = '同算子条件复用 / 跨算子假设待复测';
  }
  function renderLiveResults() {
    $('sotaChart').style.display='none';
    const r=live.latest,cases=r?.cases || [], published=live.public || [];
    $('sotaValue').textContent=cases.length ? cases.filter((c)=>c.pass).length+'/'+cases.length : '—';
    document.querySelector('.sota-value small').textContent='通过';
    document.querySelector('.sota-caption').textContent='本地首次 / 重复';
    $('sotaVersion').textContent=r ? r.source_sha256.slice(0,8) : '待评测';
    document.querySelector('.sota-panel .panel-heading h2').innerHTML='评测结果';
    document.querySelector('.sota-panel .mini-label').textContent=`回执 ${cases.length} 点 / 当前 ${live.challenge?.cases.length ?? 15} 点`;
    $('realResults').innerHTML=(cases.length ? `<table>${cases.map((c)=>`<tr><td>${esc(c.input?.dtype || c.input?.id || 'case')} [${esc((c.input?.shape || []).join(','))}]</td><td class="${c.pass?'passed':''}">${c.pass?'✓':'失败'}</td><td>${Number.isFinite(c.measurement?.event_mean_us) ? c.measurement.event_mean_us.toFixed(3)+' μs':'—'}</td></tr>`).join('')}</table>` : '<p class="dim">尚无设备实测。点击“验证当前代码”。</p>') + (published.length ? `<div class="public-list">${published.map((p)=>`<button class="text-button" data-public="${esc(p.artifact_id)}">${esc(p.sha256.slice(0,8))} · ${p.geomean_us?.toFixed(3) || '—'} μs 几何均值 · 查看共享源码 ↗</button>`).join('')}</div>` : '');
    $('candidateCount').textContent=live.jobs.length+' 次设备提交';
    $('sotaAuthor').textContent=published.length+' 个公开候选 · 不换算官分';
  }
  function renderLiveStatus() {
    const count=visibleTeams().length,running=live.operations.filter((o)=>o.state==='running');
    const verified=new Set((live.runs || []).filter((r)=>r.state==='completed').map((r)=>r.team)).size;
    const continuous=Boolean(live.continuous?.enabled);
    const budget=live.judge_budget,simulation=live.simulation,waiting=live.continuous?.waiting_for==='simulator';
    $('liveStatusLine').textContent=`${count} 支登记团队 · ${live.continuous?.strategy==='parallel'?'多队并行':'单主队基线'}${live.continuous?.main_team?' · '+live.continuous.main_team:''} · ${live.continuous?.blocked_reason|| (waiting?'等待仿真环境':continuous?'持续搜索':'已暂停')} · ${running.length} 个任务进行中${simulation?.required?' · '+(simulation.available?`实验 ${simulation.worker?.concurrency||simulation.concurrency||1} 槽 / 采集 ${simulation.worker?.profiling_concurrency||simulation.profiling_concurrency||1} 槽`:'仿真未连接'):''} · ${live.status.execution_mode==='judge-only'?(budget?`今日官测 ${budget.used}/${budget.limit} · 精选挑战`:'精选候选官测'):'混合执行'}`;
    $('playButton').textContent=continuous?'暂停持续优化':'启动持续优化';
    $('playButton').title=continuous?'暂停派发新一轮，当前任务继续完成；官测独立控制':'持续搜索、相互学习和提出候选，直到暂停';
    $('liveStatusLine').title=live.latestError || `${verified} 支团队完成过模型会话`;
    $('liveStatusLine').classList.toggle('error',Boolean(live.latestError));
    $('connectionText').textContent=running.length ? `${running.length} 个任务执行中` : '已连接';
    $('loopState').textContent=waiting?'等待仿真':continuous?'持续优化':running.length?'优化中':'待开始';
    $('searchPhase').textContent=running.length?'working':'ready';
    const deviceBusy=live.jobs.some(j=>j.state==='running')||live.simulation?.available&&(live.simulation_jobs||[]).some(j=>j.state==='running');
    $('terminal').classList.toggle('paused',!running.length&&!deviceBusy);
    $('footerStatus').textContent=`真实模式 · ${count} 支团队`;
    $('runStatus').textContent=running.length ? running.map((o)=>`${o.team} / ${o.kind} / ${o.id.slice(0,8)} 正在执行`).join('\n') : '优化过程和设备实测会自动记录，可随时回看。';
  }
  async function refreshLive() {
    const generation = liveGeneration;
    try {
      const [snapshot,status]=await Promise.all([lab('/snapshot'),lab('/control/status')]);
      if(state.source!=='live'||generation!==liveGeneration)return;
      const selected=activeTeam()?.id;
      Object.assign(live,snapshot,{status});
      document.dispatchEvent(new CustomEvent('justkernel:live-updated',{detail:snapshot}));
      state.selected=Math.max(0,visibleTeams().findIndex(t=>t.id===selected))+1;
      renderAll(); renderLiveStatus();
    } catch(error) { if(state.source==='live'&&generation===liveGeneration) { $('connectionText').textContent='后端未连接'; $('liveStatusLine').textContent=error.message; } }
  }
  function receiveLive(entry) {
    if(state.source!=='live'||live.recording||entry.seq<=live.seq)return;
    live.seq=entry.seq;
    live.totalEvents=(live.totalEvents||0)+1;
    if(!live.teams.some((t)=>t.id===entry.team)&&!['controller','judger'].includes(entry.team))return;
    if(entry.kind==='harness.event')return;
    live.events.push(entry);if(live.events.length>20000)live.events.shift();
    if(entry.kind==='evaluation.completed')live.latest=entry.data;
    if(['team.turn.failed','control.failed','evaluation.failed'].includes(entry.kind))live.latestError=entry.data.message || '执行失败';
    if(entry.kind==='team.turn.started')live.latestError='';
    if(entry.kind==='workspace.changed')live.code.delete(entry.team);
    if(entry.kind==='judge.sota.updated'){
      if(Date.now()/1000-entry.at<15){state.broadcastUntil=performance.now()+4000;$('broadcastVersion').textContent=`${entry.data.team} · ${entry.data.official?.score??'Pass'} 分`;}
      if(state.following){const index=visibleTeams().findIndex(t=>t.id===entry.data.team);if(index>=0)state.selected=index+1;}
    }
    if(meaningfulEvent(entry)){pendingLiveReceipts.push(entry);if(pendingLiveReceipts.length>7)pendingLiveReceipts.shift();}
    if(liveRenderTimer===null)liveRenderTimer=setTimeout(()=>{
      liveRenderTimer=null;
      const receipts=pendingLiveReceipts.splice(0);
      if(state.source!=='live'||live.recording)return;
      for(const item of receipts){
        const index=visibleTeams().findIndex(t=>t.id===item.team);
        addReceipt(item.kind,index<0?null:index+1,String(eventSummary(item)).slice(0,500),{at:new Date(item.at*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}),evidence:item});
        $('receiptList').firstElementChild.dataset.seq=item.seq;
      }
      $('receiptCount').textContent=live.totalEvents||live.events.length;
      renderAll();renderLiveStatus();
    },80);
  }
  function stopLive() {
    live.replayClock=null;$('replayBar').hidden=true;$('replayCurrent').disabled=false;
    liveGeneration++;
    live.recording=null; for(const id of ['playButton','teamButton','evaluateButton','resetButton'])$(id).disabled=false;
    live.stream?.close(); live.stream = null;
    clearInterval(live.timer); live.timer = null;
    $('terminal').classList.remove('live-mode');
    $('liveFlow').hidden=true; $('flow').style.display='';
    $('liveStatusLine').hidden = true; $('realResults').hidden = true;
    $('sotaChart').style.display = '';
    $('operator').disabled = false;
    $('speed').parentElement.hidden = false;
    $('resetButton').textContent = '↺ 重置';
    $('teamButton').hidden = true; $('evaluateButton').hidden = true;
    document.querySelectorAll('.swarm-models input').forEach((e) => { e.disabled = false; e.closest('label').hidden=false; e.checked = state.enabled.has(e.value); });
    $('runId').textContent = 'JK-DEMO-001';
    $('resetButton').title = '重新播放预演';
    $('receiptList').setAttribute('aria-label', '预演执行记录');
    $('deviceStrip').setAttribute('aria-label', '8个预演NPU槽位');
    document.querySelector('.flow-node[data-stage="1"] .node-value').textContent = '100 agents / 多路搜索';
    document.querySelector('.swarm-panel .panel-heading h2').innerHTML = '百智能体协作';
    agents.forEach((a, i) => Object.assign(a, demoAgents[i]));
    document.querySelector('.swarm-panel .mini-label').textContent = '点击节点查看路径';
    document.querySelector('.sota-panel .panel-heading h2').innerHTML = '示例结果';
    document.querySelector('.sota-value small').textContent = '×';
    document.querySelector('.sota-caption').textContent = '相对初始候选';
  }
  async function startLive() {
    if(window.JUSTKERNEL_DEMO_ONLY){toast('当前为轻量预演，真实优化请启动 justkernel serve');return;}
    live.recording=null; for(const id of ['playButton','teamButton','evaluateButton','resetButton'])$(id).disabled=false;
    stopLive(); live.seq = 0; live.events = []; live.totalEvents=0; live.latest = null; live.latestError = '';
    const generation = liveGeneration;
    reset('live'); state.selected = 1;
    state.originSource = 'real-execution';
    $('runId').textContent = 'JK-LIVE-CMG';
    $('searchPhase').textContent = 'ready';
    $('knowledgePhase').textContent = 'pending';
    $('sparsePhase').textContent = 'pending';
    $('resetButton').title = '重新加载界面和最新执行记录';
    $('receiptList').setAttribute('aria-label', '真实执行记录');
    $('deviceStrip').setAttribute('aria-label', '物理设备与未接入扩展槽位');
    document.querySelector('.swarm-panel .panel-heading h2').innerHTML = '协作团队';
    $('operator').disabled = false;
    $('flowTask').textContent = 'ConfusionMulGrad / 官方空工程';
    $('executionMode').value = 'live';
    $('terminal').classList.add('live-mode'); $('liveStatusLine').hidden = false;
    $('liveFlow').hidden=false; $('flow').style.display='none';
    $('realResults').hidden = false; $('speed').parentElement.hidden = true;
    $('resetButton').textContent = '↻ 刷新'; $('teamButton').hidden = false; $('evaluateButton').hidden = false;
    document.querySelectorAll('.swarm-models input').forEach((e) => { e.disabled = true; e.checked = e.value === 'GPT'; });
    setPaused(true);
    await refreshLive();
    if (state.source !== 'live' || generation !== liveGeneration) return;
    state.operator = live.status.operator || 'ConfusionMulGrad';
    $('operator').value = state.operator;
    document.querySelector('#runForm h2').textContent = state.operator + ' · 优化目标';
    if ($('runPrompt').dataset.operator !== state.operator) {
      $('runPrompt').value = `读取当前 ${state.operator} 的 TEAM.md、工程规格、暂拟 INPUT 和硬约束，继续本队独立分支，不覆盖已有改进。完成全部 editable_paths，先 inspect_policy，再 simulate_kernel 运行本队当前源码；根据真实诊断修正重试。独立仿真成功后再学习公开候选与 A2A 消息；借鉴后重新仿真。默认本地点完整通过后，由 reviewer 复核同一 SHA，queue_official_test 冻结完整候选。Judger 精选后提交官测并广播回执。无实机时不得自行 SSH 或声称 NPU 实测。每阶段给出简短公开进展、计划和未知项，不处理登录凭据。`;
      $('runPrompt').dataset.operator = state.operator;
    }
    const completed=[...(live.runs||[])].filter((r)=>r.state==='completed').sort((a,b)=>b.started-a.started)[0];
    const executing=(live.simulation?.available?live.simulation_jobs||[]:[]).find(j=>j.state==='running')?.team || live.operations.find(o=>o.state==='running')?.team;
    const preferred=visibleTeams().findIndex((t)=>t.id===(executing||completed?.team));
    if(preferred>=0)state.selected=preferred+1;
    if (state.source !== 'live') return;
    try {
      const challenge = await lab('/challenge');
      if (state.source !== 'live' || generation !== liveGeneration) return;
      live.challenge = challenge;
      $('liveCases').textContent = JSON.stringify(live.challenge.cases, null, 2);
      const cases = live.challenge.cases;
      $('liveCaseTitle').textContent = `暂拟 INPUT · ${cases.length} 点规格`;
      $('liveCaseSource').textContent = state.operator === 'ConfusionMulGrad' && live.challenge.manifest.input_source
        ? 'INPUT 为暂拟本地测试；官方公开了 15 个测试点 ID，但未公开逐点完整输入。Judger 负责同步公开证据，未知部分保持未确认。'
        : '当前使用公开／自建输入，详细生成定义见下方。';
      $('liveCaseTable').innerHTML = `<table><thead><tr><th>本地用例</th><th>输入规格</th><th>类型</th><th>axis / keep_dims</th><th>官方对应</th></tr></thead><tbody>${cases.map((c, i) => `<tr><td>${esc(c.id || i + 1)}</td><td>${esc(c.shape ? '['+c.shape.join(', ')+']' : JSON.stringify(c.inputs || c))}</td><td>${esc(c.dtype || '见规格')}</td><td>${esc(JSON.stringify(c.axis??[]))} / ${esc(String(c.keep_dims??false))}</td><td>${esc(c.official_case_id||'未确认')}</td></tr>`).join('')}</tbody></table>`;
      $('liveStatement').textContent = live.challenge.statement;
      $('liveConstraints').textContent = live.challenge.constraints;
    } catch (error) { toast(error.message); }
    if (state.source !== 'live' || generation !== liveGeneration) return;
    try{
      const bootstrap=await lab('/events/bootstrap');
      if(state.source!=='live'||generation!==liveGeneration)return;
      live.events=bootstrap.events;live.seq=bootstrap.cursor;live.totalEvents=bootstrap.total;
      $('receiptList').innerHTML='';
      for(const e of live.events.filter(meaningfulEvent).slice(-7)){
        const index=visibleTeams().findIndex(t=>t.id===e.team);
        addReceipt(e.kind,index<0?null:index+1,String(eventSummary(e)).slice(0,500),{at:new Date(e.at*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}),evidence:e});
        $('receiptList').firstElementChild.dataset.seq=e.seq;
      }
      $('receiptCount').textContent=live.totalEvents;
      $('receiptCount').title='累计事件数；此处先加载最新进展，完整历史可导出或回放。';
    }catch(error){toast('最新记录加载失败，正在通过执行流补齐：'+error.message);}
    if(state.source!=='live'||generation!==liveGeneration)return;
    live.stream = new EventSource('/api/lab/stream?after='+live.seq);
    live.stream.onmessage = (event) => { try { receiveLive(JSON.parse(event.data)); } catch (error) { toast(error.message); } };
    live.stream.onerror = () => { if (state.source === 'live') $('connectionText').textContent = '执行流重连中…'; };
    live.timer = setInterval(refreshLive, 2500);
    renderAll(); renderLiveStatus(); requestAnimationFrame(refreshPositions);
  }
  function mainModel() {
    const models=live.status.models||[],saved=live.continuous?.model;
    return models.some(m=>m.id===saved&&m.configured)?saved:models.find(m=>m.provider==='qwen'&&m.configured)?.id||saved||'qwen-api';
  }
  function openRun() {
    if(live.recording){toast('当前为离线记录；切换运行模式后连接真实执行器');return;}
    $('runStrategy').value=live.continuous?.strategy||'baseline';
    $('runTeam').innerHTML='<option value="__swarm__">全部活动团队 · PK（仅多队模式）</option>';
    for (const team of visibleTeams()) {
      const option = document.createElement('option'); option.value = team.id;
      option.textContent = `${team.id} / ${profile(team)?.name || team.model}`; $('runTeam').append(option);
    }
    $('runTeam').value=live.continuous?.main_team||activeTeam()?.id||visibleTeams()[0]?.id||'';
    const preferred=mainModel();
    $('runModel').innerHTML=(live.status.models||[]).filter(m=>m.configured||m.provider==='qwen').map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${esc(m.model)}${m.configured?'':' · 先在配置中填写 API Key'}</option>`).join('');
    $('runModel').value=preferred;
    $('runModel').disabled=$('runStrategy').value==='parallel';
    renderLiveStatus(); $('runDialog').showModal();
  }
  async function submitLive(action) {
    if(live.recording){toast('离线记录不会启动模型或设备');return;}
    if (live.busy) return;
    const team = $('runDialog').open ? $('runTeam').value : live.continuous?.main_team||activeTeam()?.id;
    if (!team) { toast('先选择或组建一个团队'); return; }
    live.busy = true;
    try {
      const strategy=$('runDialog').open?$('runStrategy').value:live.continuous?.strategy||'baseline';
      const model=$('runDialog').open?$('runModel').value:mainModel();
      if(action==='run'&&strategy==='baseline'&&!(live.status.models||[]).some(m=>m.id===model&&m.configured))throw new Error('先在「配置 → 添加连接 → Qwen」保存 API Key 并测试连接，再启动主队。');
      if(action==='run'&&strategy==='baseline'&&team==='__swarm__')throw new Error('单主队模式请选择一支具体团队。');
      const result = action==='run' ? await lab('/control/swarm/continuous',{enabled:true,strategy,main_team:strategy==='baseline'?team:null,teams:strategy==='baseline'?[team]:team==='__swarm__'?null:[team],model:strategy==='baseline'?model:null,prompt:$('runPrompt').value}) : await lab('/control/' + action, { team, prompt: $('runPrompt').value });
      toast(action==='run'?(strategy==='baseline'?`单主队 ${team} 已启动，先修失败点，再完整验证与官测`:'多队持续优化已开启'):`已提交 ${team} · 真实设备评测 · ${result.operation_id.slice(0, 8)}`);
      $('runDialog').close(); await refreshLive();
    } catch (error) { toast(error.message); $('runStatus').textContent = error.message; }
    finally { live.busy = false; }
  }
  $('runStrategy').onchange=()=>{$('runModel').disabled=$('runStrategy').value==='parallel';if($('runStrategy').value==='parallel')$('runTeam').value='__swarm__';else $('runTeam').value=live.continuous?.main_team||activeTeam()?.id||visibleTeams()[0]?.id||'';};
  const resultsBox = document.createElement('div'); resultsBox.id = 'realResults'; resultsBox.className = 'real-cases'; resultsBox.hidden = true;
  $('sotaChart').after(resultsBox);
  buildAgents();
  const visuals = new window.JustKernelVisuals.View({selectAgent,showEvidence});
  if (Object.hasOwn(TASKS, config.operator)) state.operator = config.operator;
  $('operator').value = state.operator;
  $('taskDescription').value = String(config.description || TASKS[state.operator].description);
  $('taskShape').value = String(config.shape || TASKS[state.operator].shape);
  if (config.target) $('taskTarget').value = String(config.target);
  $('agentGrid').addEventListener('click', (event) => {
    const button = event.target.closest('[data-agent]');
    if (button) { state.following = false; selectAgent(Number(button.dataset.agent)); }
  });
  document.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => { state.tab = button.dataset.tab; renderInspector(); }));
  document.querySelectorAll('[data-core]').forEach((button) => button.addEventListener('click', () => setCore(button.dataset.core)));
  $('playButton').addEventListener('click', async() => {
    if(state.source!=='live'){setPaused(!state.paused);return;}
    if(live.recording){toast('回放不会改变正在执行的工作');return;}
    if(live.continuous?.enabled){try{await lab('/control/swarm/continuous',{...live.continuous,enabled:false});await refreshLive();toast('已暂停派发新一轮，当前任务继续完成；官测独立运行');}catch(e){toast(e.message);}return;}
    submitLive('run');
  });
  $('resetButton').addEventListener('click', () => { if (state.source === 'live') { window.location.reload(); return; } reset(); setPaused(false); toast('已重新开始本地预演'); });
  $('speed').addEventListener('change', () => { state.speed = Number($('speed').value); });
  $('operator').addEventListener('change', () => { if(state.source==='live')return;changeOperator($('operator').value); toast('已切换算子并重新预演'); });
  $('taskButton').addEventListener('click', () => state.source === 'live' ? openRun() : $('taskDialog').showModal());
  $('executionMode').addEventListener('change', () => {
    if ($('executionMode').value === 'live') startLive();
    else { stopLive(); reset(); setPaused(false); toast('已切换为明确标记的预演模式'); }
  });
  $('teamButton').addEventListener('click', () => { $('teamDialog').showModal(); refreshModels(); });
  $('evaluateButton').addEventListener('click', () => submitLive('evaluate'));
  $('dialogEvaluate').addEventListener('click', () => submitLive('evaluate'));
  $('runForm').addEventListener('submit', (event) => { event.preventDefault(); submitLive('run'); });
  $('cancelOperation').addEventListener('click', async () => {
    const op = live.operations.find((o) => o.team === $('runTeam').value && o.kind === 'run' && o.state === 'running');
    if (!op) { toast('该队没有运行中的模型任务'); return; }
    try { await lab('/control/operations/' + op.id + '/cancel', {}); toast('已请求停止模型任务；已开始的设备评测仍由执行器收尾'); await refreshLive(); }
    catch (error) { toast(error.message); }
  });
  async function refreshModels() {
    $('modelStatus').textContent='正在读取统一模型配置…';
    try {
      const catalog=await lab('/control/models');
      const selected=$('newTeamPreset').value;
      const configured=catalog.models.filter(m=>m.configured);
      $('newTeamPreset').innerHTML='<option value="">自动均衡分配</option>'+configured.map((m)=>`<option value="${esc(m.id)}">${esc(m.name)}${m.effort?' · '+esc(m.effort):''}</option>`).join('');
      if(configured.some((m)=>m.id===selected))$('newTeamPreset').value=selected;
      $('teamForm').querySelector('[type="submit"]').disabled=!configured.length;
      $('modelStatus').textContent=configured.length?`已配置 ${configured.length} 个模型连接；数量由你选择，不固定为 3 队。`:'先在顶部“模型”中添加一个可用连接。';
    } catch(error) { $('modelStatus').textContent=error.message; }
  }
  $('refreshModels').addEventListener('click',refreshModels);
  $('teamForm').addEventListener('submit',async(event)=>{
    event.preventDefault();
    try {
      const result=await lab('/control/teams/auto',{count:Number($('newTeamCount').value),model:$('newTeamPreset').value||null});
      await refreshLive();state.selected=visibleTeams().findIndex((t)=>t.id===result.teams[0]?.team)+1;
      $('teamDialog').close();renderAll();toast(`已自动组建 ${result.teams.length} 支团队，可以开始真实任务`);
    } catch(error) { toast(error.message); }
  });
  let rosterTeam='';
  $('rosterButton').addEventListener('click',()=>{
    rosterTeam=$('runTeam').value;if(!rosterTeam)return;
    $('rosterTitle').textContent=rosterTeam+' / 成员分工';
    $('rosterText').value=(live.members||[]).filter((m)=>m.team===rosterTeam).map((m)=>[m.name,m.role,m.model||''].join(', ')).join('\n');
    $('rosterDialog').showModal();
  });
  $('rosterForm').addEventListener('submit',async(event)=>{
    event.preventDefault();
    try {
      const members=$('rosterText').value.split('\n').filter((s)=>s.trim()).map((line)=>{const [name,role,model]=line.split(',').map((s)=>s.trim());return {name,role,model:model||null};});
      await lab('/control/teams/'+encodeURIComponent(rosterTeam)+'/members',{members});
      $('rosterDialog').close();await refreshLive();toast('团队分工已保存');
    } catch(error){toast(error.message);}
  });
  $('messageForm').addEventListener('submit',async(event)=>{
    event.preventDefault();
    try {await lab('/control/messages',{team:activeTeam().id,recipient:$('messageTeam').value,message:$('messageText').value});$('messageDialog').close();toast('消息已记录，接收团队可通过工具读取');}
    catch(error){toast(error.message);}
  });
  function showEvidence(entries){$('eventDetail').textContent=JSON.stringify(entries,null,2);document.dispatchEvent(new CustomEvent('justkernel:evidence',{detail:entries}));$('eventDialog').showModal();}
  $('liveFlow').addEventListener('click',(event)=>{
    const key=event.target.closest('[data-live-stage]')?.dataset.liveStage;
    if(key)showEvidence(flowEvents(activeTeam()).filter((e)=>e.kind==='stage.updated'&&e.data.stage===key));
  });
  $('inspectorContent').addEventListener('click',(event)=>{
    const name=event.target.closest('[data-monitor-team]')?.dataset.monitorTeam;
    if(name){const index=visibleTeams().findIndex(t=>t.id===name);if(index>=0){state.selected=index+1;state.tab='path';renderAll();}return;}
    const seq=Number(event.target.closest('[data-evidence]')?.dataset.evidence);
    if(seq)showEvidence(live.events.find((e)=>e.seq===seq));
  });
  $('realResults').addEventListener('click',async(event)=>{
    const key=event.target.closest('[data-public]')?.dataset.public;
    if(key){try{showEvidence(live.recording ? {source:(live.public||[]).find((p)=>p.artifact_id===key)?.source} : await lab('/public/'+key+'/source'));}catch(error){toast(error.message);}}
  });
  $('leaveTeam').addEventListener('click', async () => {
    const team = activeTeam();
    if (!team) { toast('请先在主面板选择一个团队'); return; }
    try { await lab('/control/teams/' + encodeURIComponent(team.id) + '/leave', {}); await refreshLive(); $('teamDialog').close(); toast('团队已退出；源码与记录保留'); }
    catch (error) { toast(error.message); }
  });
  $('receiptList').addEventListener('click', (event) => {
    if (state.source !== 'live') return;
    const seq = Number(event.target.closest('[data-seq]')?.dataset.seq);
    const entry = live.events.find((e) => e.seq === seq);
    if (entry) { $('eventDetail').textContent = JSON.stringify(entry, null, 2); $('eventDialog').showModal(); }
  });
  document.querySelectorAll('.close-dialog').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } }));
  $('taskForm').addEventListener('submit', (event) => {
    event.preventDefault();
    config = { operator: state.operator, description: $('taskDescription').value, shape: $('taskShape').value, target: $('taskTarget').value };
    saveConfig(); $('taskDialog').close(); reset(); setPaused(false); toast('任务配置已应用 · 当前仍为预演模式');
  });
  document.querySelectorAll('.swarm-models input').forEach((input) => input.addEventListener('change', () => {
    const checked = [...document.querySelectorAll('.swarm-models input:checked')];
    if (!checked.length) { input.checked = true; toast('至少保留一种模型'); return; }
    state.enabled = new Set(checked.map((e) => e.value));
    if (state.source === 'demo') { demoTick(); toast(`${input.value} ${input.checked ? '加入' : '退出'}预演，未调用模型 API`); }
  }));
  $('followButton').addEventListener('click', () => {
    if (state.source === 'live') {
      openRun();
      return;
    }
    state.following = !state.following; renderInspector(); toast(state.following ? '新 SOTA 产生时自动切换到对应智能体' : '已取消自动跟随');
  });
  $('knowledgeButton').addEventListener('click', showKnowledge);
  async function toggleFullscreen() {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await $('terminal').requestFullscreen(); }
    catch { toast('当前预览不支持全屏，请在浏览器中直接打开演示'); }
  }
  $('fullscreenButton').addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', () => setTimeout(refreshPositions, 100));
  document.addEventListener('keydown', (event) => {
    if (/INPUT|TEXTAREA|SELECT|BUTTON/.test(document.activeElement?.tagName || '') || document.querySelector('dialog[open]')) return;
    if (event.code === 'Space') { event.preventDefault(); if(live.recording)toggleRecord();else if (state.source === 'live') openRun(); else setPaused(!state.paused); }
    if (event.key.toLowerCase() === 'f') toggleFullscreen();
  });
  document.querySelectorAll('.flow-node').forEach((node) => {
    const act = () => {
      if (state.source === 'live') { const groups=[['input'],['search'],['policy'],['queue','execute'],['verify'],['share'],['distill']];showEvidence(flowEvents(activeTeam()).filter(e=>e.kind==='stage.updated'&&groups[Number(node.dataset.stage)].includes(e.data.stage))); return; }
      const stage = Number(node.dataset.stage);
      if (stage === 0 || stage === 2) $('taskDialog').showModal();
      else if (stage === 6) showKnowledge();
      else if (stage === 5 && state.champion) { selectAgent(state.champion); toast(`正在查看公共 SOTA 来源 A${pad(state.champion)}`); }
      else if (stage === 3) toast('8 个虚拟 NPU 槽位用于视觉预演；尚未连接服务器');
      else if (stage === 4) { state.tab = 'path'; renderInspector(); toast('在右侧查看候选验证路径'); }
      else { setCore('search'); toast('100 个智能体节点均可点击查看'); }
    };
    node.addEventListener('click', act);
    node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); act(); } });
  });
  $('exportButton').addEventListener('click', () => {
    if (state.source === 'live' && !live.recording) { const a=document.createElement('a'); a.href='/api/lab/export'; a.download='justkernel-real-events.json'; a.click(); return; }
    const payload = live.recording || { schema: 'justkernel.events.v1', source: state.source, original_source: state.originSource, is_simulation: state.source === 'demo' || state.originSource === 'demo', operator: state.operator, exported_at: new Date().toISOString(), note: state.source === 'demo' || state.originSource === 'demo' ? 'Simulated events. Not NPU measurements or model calls.' : 'External records. Not independently verified by this viewer.', events: state.events };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = `justkernel-${state.source}-events.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000); toast('已导出事件记录，保留数据来源标记');
  });
  $('importButton').addEventListener('click', () => $('importFile').click());
  $('importFile').addEventListener('change', async () => {
    const file = $('importFile').files[0]; if (!file) return;
    try {
      if (file.size > 50 * 1024 * 1024) throw new Error('文件需小于 50 MB');
      const data = JSON.parse(await file.text());
      if(data.schema==='justkernel.events.v2') { openExecutionRecord(data); return; }
      const events = Array.isArray(data) ? data : data.events;
      if (!Array.isArray(events) || !events.length || events.length > 50000 || !events.every((e) => e && typeof e.type === 'string')) throw new Error('需要 1–50000 条包含 type 的事件');
      if (data.operator && Object.hasOwn(TASKS, data.operator)) { state.operator = data.operator; $('operator').value = data.operator; }
      state.replay = events;
      stopLive();
      reset('recording');
      state.originSource = data.is_simulation === true || data.source === 'demo' || data.original_source === 'demo' ? 'demo' : String(data.original_source || data.source || 'unknown').slice(0, 40);
      if (state.originSource === 'demo') {
        $('modeBadge').innerHTML = '<i></i> 预演记录 / REPLAY';
        $('disclaimer').textContent = '导入的预演数据 · 非真实模型调用或 NPU 测量';
        document.querySelector('.sota-panel .mini-label').textContent = '预演记录曲线';
      }
      setPaused(false); toast(`正在回放 ${events.length} 条本地记录`);
    } catch (error) { toast('无法导入：' + error.message); }
    $('importFile').value = '';
  });
  function openExecutionRecord(data) {
    if(!Array.isArray(data.events)||!data.events.length||data.events.length>200000||!data.events.every((e,i)=>Number.isInteger(e.seq)&&Number.isFinite(e.at)&&typeof e.kind==='string'&&(!i||e.seq>data.events[i-1].seq)))throw new Error('无效的 v2 执行记录，需要有序事件与真实时间戳');
    if(!data.snapshot){
      const map=new Map();
      for(const e of data.events){if(e.kind==='team.joined'&&e.data?.runtime==='deepagents')map.set(e.team,{id:e.team,runtime:'deepagents',model:e.data.model,active:1});}
      data.snapshot={teams:[...map.values()],members:data.events.filter((e)=>e.kind==='team.roster.updated').flatMap((e)=>(e.data.members||[]).map((m)=>({...m,team:e.team}))),devices:[],jobs:[],operations:[],runs:[],experiences:data.events.filter((e)=>e.kind==='skill.created').map((e)=>({id:e.data.skill_id,team:e.team,data:e.data})),public:[]};
    }
    stopLive(); reset('live'); state.selected=1;
    Object.assign(live,data.snapshot,{events:[],seq:0,latest:null,latestError:'',challenge:data.challenge,status:{models:data.models||[],execution_mode:data.execution_mode||(data.challenge?.manifest?.project_files?'judge-only':'hybrid')},recording:data});
    $('terminal').classList.add('live-mode');$('flow').style.display='none';$('liveFlow').hidden=false;$('realResults').hidden=false;
    live.code.clear(); for(const [team,source] of Object.entries(data.sources||{}))live.code.set(team,source); for(const p of data.snapshot.public||[]){if(p.result?.team&&p.source)live.code.set(p.result.team,{source:p.source,sha256:p.sha256});}
    for(const id of ['playButton','teamButton','evaluateButton','resetButton'])$(id).disabled=true;
    $('modeBadge').innerHTML='<i></i> 导入执行记录 / REPLAY';
    $('disclaimer').textContent='来自导入文件的执行证据 · 当前未运行模型或设备 · 来源需独立核验';
    $('connectionText').textContent='离线查看 / 不连接执行器';
    $('liveStatusLine').hidden=false;$('liveStatusLine').textContent='离线记录 · '+data.events.length+' 个事件 · 可点击步骤、工具、代码与经验查看证据';
    if(!$('executionMode').querySelector('[value=recording]')){const option=document.createElement('option');option.value='recording';option.textContent='离线执行记录';option.hidden=true;$('executionMode').append(option);}$('executionMode').value='recording';
    $('runId').textContent='JK-RECORD-'+(currentRun(activeTeam())?.id.slice(0,8)||'IMPORTED');$('speed').parentElement.hidden=true;$('operator').disabled=true;renderAll();
    $('loopState').textContent='REPLAY';
    const first=data.events[0].at||0,last=data.events.at(-1).at||first;
    live.replayClock={start:first,duration:Math.max(last-first,1),position:0,playing:true,stamp:performance.now(),count:-1};
    $('replayBar').hidden=false;$('replayCurrent').disabled=true;
    renderRecord(0);toast('按时间回放真实记录，可暂停、拖动、加速；不会启动模型任务');
  }
  function renderRecord(position){
    const clock=live.replayClock;if(!clock||!live.recording)return;
    clock.position=Math.max(0,Math.min(position,clock.duration));clock.stamp=performance.now();
    const data=live.recording,target=clock.start+clock.position;
    const count=clock.position>=clock.duration?data.events.length:data.events.findIndex(e=>e.at>target);
    const end=count<0?data.events.length:count;
    $('replaySeek').value=String(Math.round(clock.position/clock.duration*1000));
    const time=x=>Math.floor(x/60)+':'+String(Math.floor(x%60)).padStart(2,'0');
    $('replayPosition').textContent=time(clock.position)+' / '+time(clock.duration);
    $('replayPause').textContent=clock.playing?'暂停':'播放';
    if(end===clock.count)return;clock.count=end;
    Object.assign(live,window.JustKernelActivity.projectRecord(data,end));live.seq=live.events.at(-1)?.seq||0;
    if(!visibleTeams().some(t=>t.id===activeTeam()?.id))state.selected=1;
    $('receiptList').innerHTML='';for(const e of live.events.slice(-60)){const index=visibleTeams().findIndex(t=>t.id===e.team);addReceipt(e.kind,index<0?null:index+1,String(eventSummary(e)).slice(0,500),{at:new Date(e.at*1000).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}),evidence:e});$('receiptList').firstElementChild.dataset.seq=e.seq;}
    $('receiptCount').textContent=end;renderAll();renderLiveStatus();
    $('connectionText').textContent='真实记录回放 · 当前未执行模型';
    $('liveStatusLine').textContent='回放至 '+new Date(target*1000).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})+' · '+end+' / '+data.events.length+' 条真实事件';
    $('modeBadge').innerHTML='<i></i> 真实记录回放 / REPLAY';
  }
  function toggleRecord(){if(!live.replayClock)return;live.replayClock.playing=!live.replayClock.playing;live.replayClock.stamp=performance.now();$('replayPause').textContent=live.replayClock.playing?'暂停':'播放';renderVisuals();}
  $('replayPause').onclick=toggleRecord;
  $('replaySeek').oninput=()=>renderRecord(Number($('replaySeek').value)/1000*live.replayClock.duration);
  $('replayExit').onclick=()=>{ $('replayCurrent').disabled=false;startLive(); };
  $('replayCurrent').onclick=async()=>{try{const r=await fetch('/api/lab/export');if(!r.ok)throw new Error('无法读取执行记录');openExecutionRecord(await r.json());}catch(e){toast(e.message);}};
  setInterval(()=>{const c=live.replayClock;if(!c||!c.playing)return;const next=c.position+(performance.now()-c.stamp)/1000*Number($('replaySpeed').value);if(next>=c.duration){c.playing=false;c.count=-1;}renderRecord(next);},250);
  window.JustKernel = Object.freeze({
    ingest(event) { if (state.source !== 'external') { reset('external'); setPaused(true); } state.tick++; applyEvent(event); renderAll(); },
    snapshot() { return { source: state.source, tick: state.tick, agentCount: agents.length, selectedAgent: state.selected, version: state.version, speedup: state.speedup, eventCount: state.events.length, paused: state.paused, operator: state.operator }; }
  });
  window.addEventListener('justkernel:workspace-changed',()=>startLive());
  window.addEventListener('justkernel:models-changed',()=>{refreshLive();if($('teamDialog').open)refreshModels();});
  if(window.JUSTKERNEL_DEMO_ONLY){
    reset('demo');setPaused(false);
    const liveOption=$('executionMode').querySelector('[value=live]');if(liveOption)liveOption.disabled=true;
    for(const id of ['operatorAddButton','taskButton','teamButton','evaluateButton','modelSettingsButton','serverSettingsButton']){
      $(id).disabled=true;$(id).title='真实配置与优化请启动 justkernel serve';
    }
  }else{reset('external');setPaused(true);startLive();}
  let previousTick = performance.now();
  setInterval(() => {
    $('clock').textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
    const now = performance.now();
    if (state.paused || state.source === 'external' || state.source === 'live') { previousTick = now; return; }
    if (now - previousTick < 1200 / state.speed) return;
    previousTick = now;
    if (state.source === 'demo') demoTick();
    else {
      if (state.replayIndex >= state.replay.length) { setPaused(true); toast('记录回放完成'); return; }
      state.tick++;
      try { applyEvent(state.replay[state.replayIndex++]); } catch (error) { toast('跳过无效事件：' + error.message); }
      renderAll();
    }
  }, 100);
  new ResizeObserver(refreshPositions).observe($('swarmField'));
  requestAnimationFrame(animate);
})();
