const {test}=require('node:test');
const assert=require('node:assert/strict');
const {timeline,markup,officialCases,caseTable,formatTime,View}=require('../src/aworker/lab/resources/web/conversation.js');
const e=(seq,kind,data={},team='qwen-001')=>({seq,at:100+seq,kind,team,data});

test('chronological rounds retain previous explanations and group actual tools/diffs',()=>{
 const events=[e(1,'control.started',{operation_id:'r1'}),e(2,'model.started',{run_id:'r1',model_call_id:'m1',model:'configured-model'}),
 e(3,'model.output.delta',{model_call_id:'m1',text:'partial'}),e(4,'agent.message',{model_call_id:'m1',text:'public explanation',reasoning_content:'PRIVATE'}),
 e(5,'model.completed',{run_id:'r1',model_call_id:'m1',duration_ms:4200,usage:{output_tokens:45}}),
 e(6,'tool.started',{run_id:'r1',model_call_id:'m1',tool_call:'t1',tool:'edit_file',input:'{"file_path":"/kernel.asc"}'}),
 e(7,'tool.completed',{run_id:'r1',tool_call:'t1',output:'actual return'}),
 e(8,'workspace.patch',{tool_call:'t1',path:'kernel.asc',patch:'-old\n+new\n',source_sha256:'newsha'}),
 e(9,'control.completed',{operation_id:'r1'}),e(10,'control.started',{operation_id:'r2'}),
 e(11,'model.started',{run_id:'r2',model_call_id:'m2'}),e(12,'agent.progress',{run_id:'r2',summary:'observed failure',next_action:'run probe'}),
 e(13,'agent.message',{model_call_id:'other',text:'OTHER TEAM'},'other-team')];
 const rows=timeline([...events,events[7]],'qwen-001',[{id:'r2',team:'qwen-001',state:'running'}],120);
 assert.deepEqual(rows.map(r=>r.type),['round','call','round','call']);
 assert.equal(rows[0].state,'completed');assert.equal(rows[1].text,'public explanation');assert.equal(rows[1].elapsed,4.2);
 assert.equal(rows[1].tools.length,1);assert.equal(rows[1].tools[0].patches.length,1);
 assert.equal(rows[3].notes[0].next,'run probe');assert.equal(rows[3].state,'running');
 const html=markup(rows);assert.match(html,/actual return/);assert.match(html,/newsha/);assert.match(html,/configured-model/);
 assert.doesNotMatch(html,/PRIVATE|OTHER TEAM|partial/);
});

test('public output and raw tool/diff text are escaped; no invented thinking or duration',()=>{
 const rows=timeline([e(1,'agent.message',{model_call_id:'legacy',text:'<script>bad</script>',reasoning_content:'PRIVATE'}),
 e(2,'tool.completed',{model_call_id:'legacy',tool_call:'x',tool:'read_file',output:'<img src=x onerror=bad()>'}),
 e(3,'workspace.patch',{tool_call:'x',path:'kernel.asc',patch:'+<script>\n'})],'qwen-001');
 const html=markup(rows);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>|<img |PRIVATE/);
 assert.match(html,/耗时未记录/);assert.doesNotMatch(html,/Thought|思考了/);
});

test('stream/final replacement, cancellation and replay cutoff preserve known state',()=>{
 const events=[e(1,'control.started',{operation_id:'r'}),e(2,'model.started',{run_id:'r',model_call_id:'m'}),e(3,'model.output.delta',{model_call_id:'m',text:'hello '}),
 e(4,'model.output.delta',{model_call_id:'m',text:'world'}),e(5,'agent.message',{model_call_id:'m',text:'final'}),e(6,'model.completed',{model_call_id:'m',duration_ms:900}),
 e(7,'control.cancelled',{operation_id:'r'})];
 assert.equal(timeline(events.slice(0,4),'qwen-001',[{team:'qwen-001',id:'r',state:'running'}],105)[1].text,'hello world');
 const rows=timeline(events,'qwen-001');assert.equal(rows[1].text,'final');assert.equal(rows[1].elapsed,.9);
 assert.equal(rows[0].state,'cancelled');
 assert.equal(timeline(events.slice(0,2),'qwen-001',[])[1].state,'interrupted');
});

test('in-flight tool arguments are shown before execution without claiming a result',()=>{
 const rows=timeline([e(1,'control.started',{operation_id:'r'}),e(2,'model.started',{run_id:'r',model_call_id:'m'}),
 e(3,'model.output.delta',{model_call_id:'m',tools:[{index:0,name:'edit_file',args:'{"file_'}]}),
 e(4,'model.output.delta',{model_call_id:'m',tools:[{index:0,args:'path":"/kernel.asc"}'}]})],'qwen-001',[{team:'qwen-001',id:'r',state:'running'}]);
 assert.equal(rows[1].drafts[0].args,'{"file_path":"/kernel.asc"}');
 const html=markup(rows);assert.match(html,/工具请求 · 正在生成/);assert.match(html,/kernel.asc/);assert.doesNotMatch(html,/实际返回/);
});

test('all official cases include error percentage and microsecond/millisecond timings',()=>{
 const result=Array.from({length:15},(_,i)=>({testcase_id:'case-'+(i+1),testcase_status:[8,11,13].includes(i)?'Wrong Answer':'Pass',precision_ratio:i===8?.99951148:i===11?.99902352:i===13?.99822852:1,time:i===10?44000:6.72,best_time:i===10?1680:5.76}));
 const cases=officialCases({result});assert.equal(cases.length,15);assert.ok(Math.abs(cases[8].error_percent-.048852)<1e-8);
 const html=caseTable(cases);for(const value of ['0.05%','0.10%','0.18%','44.00ms','1.68ms','6.72μs','5.76μs','最优用时','输出错误占比'])assert.ok(html.includes(value),value);
 assert.equal((html.match(/<tr /g)||[]).length,15);
 const receipt=timeline([e(1,'judge.submission.updated',{submission_id:'official-id',source_sha256:'frozen-sha',official:{status:'Wrong Answer',result}})],'qwen-001');
 assert.equal(receipt[0].cases.length,15);assert.match(markup(receipt),/official-id/);assert.match(markup(receipt),/frozen-sha/);
});

test('missing, string or invalid measurements stay unknown and official order uses IDs',()=>{
 const cases=officialCases({result:[{testcase_id:'b',testcase_status:'Pass',precision_ratio:2,time:null,best_time:'12'},{testcase_id:'a',precision_ratio:0,time:0,best_time:0}]},['a','b']);
 assert.equal(cases[0].number,1);assert.equal(cases[0].error_percent,100);assert.equal(cases[1].error_percent,null);
 assert.equal(cases[1].best_time_us,null);assert.match(caseTable(cases),/未提供/);
 assert.equal(formatTime(0),'0.00μs');assert.equal(formatTime(undefined),'未提供');
});

test('view preserves folds and reading position; unchanged state avoids DOM replacement',()=>{
 const handlers={},el={innerHTML:'',scrollTop:5,scrollHeight:500,clientHeight:100,addEventListener:(name,fn)=>handlers[name]=fn,querySelectorAll:()=>[]};
 const view=new View(el);view.follow=false;
 const rows=timeline([e(1,'agent.message',{model_call_id:'m',text:'read here'})],'qwen-001');view.update(rows);assert.equal(el.scrollTop,5);
 handlers.click({target:{closest:()=>({parentElement:{dataset:{foldKey:'call-m'},open:true}})}});assert.equal(view.opens.get('call-m'),false);
 el.innerHTML='unchanged';view.update(rows);assert.equal(el.innerHTML,'unchanged');
 view.latest();assert.equal(el.scrollTop,500);assert.equal(view.follow,true);
});
