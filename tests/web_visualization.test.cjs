const {test} = require('node:test');
const assert = require('node:assert/strict');
const {networkLayout,networkNodeLabel} = require('../src/aworker/lab/resources/web/visualization.js');

test('one model uses the field around the hub without overlapping evidence-sized nodes',()=>{
  const nodes=Array.from({length:8},(_,i)=>({id:i+1,name:(i%2?'deepseek-':'gpt-')+String(Math.floor(i/2)+1).padStart(3,'0'),model:'deepseek-flash',state:'testing'}));
  const ranks=new Map(nodes.map(n=>[n.name,{passed:14,total:15}]));
  for(const [w,h] of [[790,600],[600,400],[320,260]])for(const time of [0,60,180]){
    const points=networkLayout(nodes,w,h,time,1,ranks);
    for(const [i,a] of points.entries()){
      assert.ok(a.x-a.size/2>=10&&a.x+a.size/2<=w-10,'horizontal bounds');
      assert.ok(a.y-a.size/2>=20&&a.y+a.size/2<=h-20,'vertical bounds');
      assert.ok(Math.hypot(a.x-w*.5,a.y-h*.52)>=a.size/2+Math.min(w,h)*.085+11,'hub remains clear');
      for(const b of points.slice(i+1))assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>=(a.size+b.size)/2+6,'circles remain separated');
    }
    assert.ok(Math.max(...points.map(p=>p.y))-Math.min(...points.map(p=>p.y))>h*.45,'uses lower field too');
  }
  assert.equal(new Set(nodes.map(n=>networkNodeLabel(n,8))).size,8,'historical provider suffixes cannot duplicate labels');
  assert.equal(networkNodeLabel(nodes[0],8),'DS\n001');
  assert.equal(networkNodeLabel(nodes[1],8),'DS\n002');
  assert.notEqual(networkLayout(nodes,790,600,0)[0].x,networkLayout(nodes,790,600,60)[0].x,'orbital motion remains enabled');
});

test('dense and mixed model layouts remain within bounds and preserve hidden slots',()=>{
  for(const mixed of [false,true]){
    const nodes=Array.from({length:100},(_,i)=>({id:i+1,name:'team-'+i,model:mixed?['GPT','DeepSeek','Qwen','GLM'][i%4]:'DeepSeek',state:'waiting'}));
    nodes.push({id:101,name:'offline',model:'GPT',state:'unconfigured'});
    const points=networkLayout(nodes,720,520,20,1);
    assert.equal(points[100],null);
    for(const [i,a] of points.slice(0,100).entries()){
      assert.ok(Number.isFinite(a.x)&&Number.isFinite(a.y));
      for(const b of points.slice(i+1,100))assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>=(a.size+b.size)/2+3,'dense nodes do not overlap');
    }
  }
});
const {View,attemptsFromEvents, performanceGroup, rankTeams, connectedTeams, networkGroups, networkProjection,messageActive,motionEnabled,workActive,networkNodeSize, officialAttemptsFromEvents,rankOfficialTeams} = require('../src/aworker/lab/resources/web/visualization.js');

test('sparse teams grow and official coverage affects size without becoming a score',()=>{
  const sparse=networkNodeSize(8,600,400),dense=networkNodeSize(100,600,400);
  assert.ok(sparse>dense*2);
  assert.ok(networkNodeSize(8,600,400,{passed:14,total:15})>networkNodeSize(8,600,400,{passed:7,total:15}));
  assert.ok(networkNodeSize(8,600,400,{score:10},false,10)>networkNodeSize(8,600,400,{passed:14,total:15}));
  assert.ok(networkNodeSize(1,1200,900,{},true)<=94);
});

test('explicit animation preference can enable motion while static mode always pauses it',()=>{
  assert.equal(motionEnabled('on',true),true);assert.equal(motionEnabled('off',false),false);
  assert.equal(motionEnabled('auto',true),false);assert.equal(motionEnabled('auto',false),true);
  assert.equal(workActive({state:'generating'}),true);assert.equal(workActive({state:'testing'}),true);
  assert.equal(workActive({state:'queued'}),false);assert.equal(workActive({state:'testing'},false),false);
});

test('canvas draws a live job stream without manufacturing an A2A message',()=>{
  const nodes=[{id:1,name:'a',model:'GPT',state:'testing'},{id:2,name:'b',model:'DeepSeek',state:'waiting'}];
  let curves=0,fills=0;
  const ctx={setTransform(){},clearRect(){},beginPath(){},moveTo(){},quadraticCurveTo(){curves++;},stroke(){},
    createLinearGradient(){return {addColorStop(){}};},arc(){},fill(){fills++;},setLineDash(){}};
  const elements={agentGrid:{children:nodes.map(()=>({style:{setProperty(){}},tabIndex:0}))},
    swarmField:{classList:{contains(){return false;}}},linksCanvas:{getContext(){return ctx;}}};
  const view=Object.create(View.prototype);Object.assign(view,{data:{nodes,selected:1,paused:false,events:[]},width:600,height:400,dpr:1,reduced:false,lastFrame:0,network:networkProjection(nodes,[]),$:id=>elements[id]});
  view.frame(1000);assert.ok(curves>=2);assert.ok(fills>0);assert.equal(view.network.delivered,0);
  fills=0;view.data.nodes[0].state='queued';view.frame(2000);assert.equal(fills,0);
});

test('failed official attempts retain actual coverage without creating a SOTA score',()=>{
  const points=[{team:'a',valid:false,score:null,passed:14,total:15},{team:'b',valid:false,score:null,passed:13,total:15}];
  const ranks=rankOfficialTeams(points,[{id:1,name:'a',state:'waiting'},{id:2,name:'b',state:'waiting'}]);
  assert.equal(ranks[0].passed,14);assert.equal(ranks[0].total,15);assert.equal(ranks[0].score,null);
  assert.equal(ranks[0].attempts,1);
});

test('connected topology remains visible without inventing any messages or empty teams',()=>{
  const nodes=[{name:'a',state:'waiting'},{name:'b',state:'generating'},{name:'empty',state:'unregistered'},{name:'offline',state:'unconfigured'}];
  const projection=networkProjection(nodes,[]);
  assert.equal(projection.connections.length,2);
  assert.equal(projection.delivered,0);assert.deepEqual(projection.edges,[]);
});

test('network includes actual Judger feedback, deduplicates acknowledgements and excludes future deliveries',()=>{
  const nodes=[{name:'a',state:'waiting'},{name:'b',state:'generating'}];
  const message=(seq,at,team,recipient,transport='a2a')=>({seq,at,team,kind:'team.message',data:{recipient,transport,message_id:'delivery-'+seq}});
  const first=message(1,100,'judger','a');
  const events=[first,{...first,seq:2},message(3,104,'a','b','local'),message(4,106,'b','a'),message(5,106,'a','unknown')];
  const past=networkProjection(nodes,events,105);
  assert.equal(past.delivered,1);assert.equal(past.history,1);assert.equal(past.edges[0].from,-1);
  assert.equal(past.edges.length,2);assert.equal(past.edges[1].confirmed,false);
  const now=networkProjection(nodes,events,110);
  assert.equal(now.delivered,2);assert.equal(now.edges.length,3);
});

test('traffic pulses expire, never animate local notes or future events, and pause with replay',()=>{
  const edge={confirmed:true,at:100};
  assert.equal(messageActive(edge,105),true);
  assert.equal(messageActive(edge,115),false);
  assert.equal(messageActive(edge,99),false);
  assert.equal(messageActive(edge,105,false),false);
  assert.equal(messageActive({...edge,confirmed:false},105),false);
});

test('official scores never become local device timings or include the public ladder as our teams',()=>{
  const events=[receipt(1),{seq:2,team:'team-a',kind:'judge.submission.updated',data:{submission_id:'123',source_sha256:'hash',problem_id:'problem',official:{status:'Pass',score:7.5,rank:6}}},
    {seq:3,team:'team-a',kind:'judge.submission.updated',data:{submission_id:'124',official:{status:'Fail',score:90}}}];
  const points=officialAttemptsFromEvents(events);
  assert.equal(points.length,2);assert.equal(points[0].score,7.5);assert.equal(points[0].latency,null);assert.equal(points[1].score,null);
  const ranks=rankOfficialTeams(points,[{id:1,name:'team-a',state:'waiting'},{id:2,name:'team-b',state:'waiting'}]);
  assert.equal(ranks[0].score,7.5);assert.equal(ranks[1].score,null);assert.equal(attemptsFromEvents(events).length,1);
});

const environment = {host_alias:'fixture-host', device:0, cann_env:'fixture-cann'};
function receipt(seq, patch = {}) {
  return {seq, team:'team-a', kind:'evaluation.completed', data:{job_id:'job-'+seq,
    pass:true, case_pack_sha256:'fixture-pack', environment,
    cases:Array.from({length:15}, () => ({pass:true, measurement:{event_mean_us:4}})), ...patch}};
}

test('a failed compile has no correctness or latency measurement, and is deduplicated by job', () => {
  const event = {seq:2, team:'team-a', kind:'evaluation.failed', data:{job_id:'compile-failure', message:'compiler diagnostic'}};
  const points = attemptsFromEvents([receipt(1), event, {...event, seq:3}]);
  assert.equal(points.length,2);
  assert.equal(points[1].correctness,null);
  assert.equal(points[1].latency,null);
  assert.equal(points[1].error,'compiler diagnostic');
});

test('one official submission remains one attempt as waiting, score and rank update',()=>{
 const event=(seq,status,score,rank)=>({seq,kind:'judge.submission.updated',team:'team-a',data:{submission_id:'123',problem_id:'problem',official:{status,score,rank}}});
 const pending=officialAttemptsFromEvents([event(1,'Waiting',0,null)]);
 assert.equal(pending[0].failed,false);assert.equal(pending[0].pending,true);assert.equal(pending[0].score,null);
 const updated=officialAttemptsFromEvents([event(1,'Waiting',0,null),event(2,'Pass',7.5,5),event(3,'Pass',7.5,6)]);
 assert.equal(updated.length,1);assert.equal(updated[0].rank,6);assert.equal(updated[0].score,7.5);assert.equal(updated[0].seq,1);
});

test('only a full numerical pass contributes performance; partial correctness stays visible', () => {
  const partial = receipt(2); partial.data.cases.pop();
  const numerical = receipt(3,{pass:false}); numerical.data.cases[0].pass=false;
  const points = attemptsFromEvents([receipt(1),partial,numerical]);
  assert.ok(Math.abs(points[0].latency-4)<1e-8);
  assert.equal(points[1].latency,null);
  assert.equal(points[1].correctness,14/15*100);
  assert.equal(points[2].latency,null);
  assert.equal(points[2].passed,14);
});

test('performance comparisons exclude other input packs and physical environments', () => {
  const points = attemptsFromEvents([receipt(1),receipt(2,{case_pack_sha256:'other-pack'}),
    receipt(3,{environment:{...environment, device:1}}),
    receipt(4,{environment:{...environment, ssh_port:2222, server_profile:'other-server'}}),receipt(5)]);
  const comparable = performanceGroup(points);
  assert.ok(comparable[0].latency>0);
  assert.equal(comparable[1].latency,null);
  assert.equal(comparable[2].latency,null);
  assert.equal(comparable[3].latency,null);
  assert.ok(comparable[4].latency>0);
  assert.equal(attemptsFromEvents([receipt(1)],15,'team-b').length,0);
});

test('team leaderboard ranks only complete comparable measurements and keeps partial teams visible', () => {
  const a=receipt(1);a.team='a';
  const b=receipt(2,{pass:false});b.team='b';b.data.cases[0].pass=false;
  const c=receipt(3,{environment:{...environment,ssh_port:2222}});c.team='c';
  const failed={seq:4,team:'d',kind:'evaluation.failed',data:{job_id:'failed',message:'compile error'}};
  const rows=rankTeams(attemptsFromEvents([a,b,c,failed]),['a','b','c','d'].map((name,i)=>({id:i+1,name,state:'waiting'})));
  assert.equal(rows[0].name,'c');
  assert.ok(rows[0].latency>0);
  assert.equal(rows.find(r=>r.name==='a').latency,null);
  assert.equal(rows.find(r=>r.name==='b').latency,null);
  assert.equal(rows.find(r=>r.name==='b').passed,14);
  assert.equal(rows.find(r=>r.name==='d').latency,null);
});

test('live teams require configured connections and archived teams remain in source history', () => {
  const teams=[{id:'gpt-001',active:1,model:'gpt'},{id:'deepseek-001',active:1,model:'ds'},
    {id:'unused',active:1,model:'glm'},{id:'old',active:0,model:'gpt'}];
  const models=[{id:'gpt',configured:true},{id:'ds',configured:true},{id:'glm',configured:false}];
  assert.deepEqual(connectedTeams(teams,models).map(t=>t.id),['gpt-001','deepseek-001']);
  assert.equal(teams.length,4);
  assert.equal(connectedTeams(teams,[],true).length,3);
  const current=receipt(1);current.team='gpt-001';
  const old=receipt(2,{environment:{...environment,device:1}});old.team='old';
  const rows=rankTeams(attemptsFromEvents([current,old]),[{id:1,name:'gpt-001',state:'waiting'}],false);
  assert.equal(rows.length,1);
  assert.ok(rows[0].latency>0);
});

test('network has no empty provider labels or unused slot groups', () => {
  const nodes=[{model:'GPT',state:'waiting'},{model:'DeepSeek',state:'testing'},
    {model:'GLM',state:'unconfigured'},{model:'GPT',state:'unregistered'},
    {model:'GLM',state:'excluded'}];
  const groups=networkGroups(nodes);
  assert.deepEqual(groups.map(g=>g.label),['GPT','DeepSeek']);
  assert.deepEqual(groups.map(g=>g.count),[1,1]);
  assert.notDeepEqual(groups[0].center,groups[1].center);
  assert.deepEqual(networkGroups([]),[]);
});

test('local simulation tracks full-pack coverage, filters old packs and never invents scores',()=>{
  const {simulationAttempts}=require('../src/aworker/lab/resources/web/visualization.js');
  const context={case_pack_sha256:'current',worker_sha256:'worker'};
  const job=(id,count,overrides={})=>({schema:'justkernel.simulation.v1',source:'cann-simulator',id,team:'main',created_at:id,
    source_sha256:'source'+id,...context,state:'completed',functional_pass:true,profile_case_ids:['p0','p1','p2'],
    cases:Array.from({length:count},(_,i)=>({id:'p'+i,pass:true,profile_pass:i<3})),...overrides});
  const rows=simulationAttempts([job(1,3),job(2,15,{case_pack_sha256:'old'}),job(3,15),job(4,15,{worker_sha256:'old'})],15,null,context);
  assert.equal(rows.length,2);
  assert.equal(rows[0].correctness,20);assert.equal(rows[0].valid,false);
  assert.equal(rows[0].total,15);
  assert.equal(rows[1].valid,true);assert.equal(rows[1].profiles,3);assert.equal(rows[1].profileTotal,3);
  assert.equal(rows[1].latency,null);assert.equal(rows[1].score,null);
  assert.equal(rows[1].event.kind,'simulation.receipt');
  assert.equal(simulationAttempts([job(1,15),job(3,15)],15,null,context,2).length,1);
  assert.equal(simulationAttempts([job(1,15,{finished_at:10})],15,null,context,2).length,0);
  assert.equal(simulationAttempts([job(1,15)],15,'another-team',context).length,0);
  assert.equal(simulationAttempts([job(1,15,{cases:Array(15).fill({id:'duplicate',pass:true})})],15,null,context)[0].valid,false);
});

test('judge-only dashboard keeps local and official results visibly separate',()=>{
  const {View}=require('../src/aworker/lab/resources/web/visualization.js');
  const label={},board={closest:()=>({querySelector:()=>label})};
  const data={judgeOnly:true,expectedCases:15,simulation:{required:true,case_pack_sha256:'pack',worker_sha256:'worker'},
    events:[],nodes:[{id:1,name:'main',state:'waiting'}],simulationJobs:[{
      schema:'justkernel.simulation.v1',source:'cann-simulator',id:'full',team:'main',created_at:1,state:'completed',functional_pass:true,
      source_sha256:'source',case_pack_sha256:'pack',worker_sha256:'worker',profile_case_ids:['p0','p1','p2'],
      cases:Array.from({length:15},(_,i)=>({id:'p'+i,pass:true,profile_pass:i<3}))
    }]};
  View.prototype.renderLeaderboard.call({data,$:()=>board});
  assert.match(board.innerHTML,/15\/15/);assert.match(board.innerHTML,/流水 3\/3/);
  assert.match(board.innerHTML,/等待官测/);assert.match(board.innerHTML,/本地校验/);
  assert.doesNotMatch(board.innerHTML,/100.*官测分/);
});
