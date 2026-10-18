const {test} = require('node:test');
const assert = require('node:assert/strict');
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
