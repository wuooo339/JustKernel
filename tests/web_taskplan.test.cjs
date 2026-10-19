const {test}=require('node:test');
const assert=require('node:assert/strict');
const {plan,judgePlan,markup}=require('../src/aworker/lab/resources/web/taskplan.js');
const e=(seq,kind,data={},team='main')=>({seq,kind,data,team,at:seq});

test('layered paths animate actual active tasks without advancing states',()=>{
 const p={label:'live plan',hint:'evidence',items:[{content:'read',status:'completed'},{content:'edit <script>',status:'in_progress'},{content:'validate',status:'pending'}]};
 const before=JSON.stringify(p),idle=markup(p,'main'),active=markup(p,'main',{running:true});
 assert.doesNotMatch(idle,/workflow-path is-working/);assert.match(active,/workflow-path is-working/);
 assert.match(active,/<svg class="task-wire in_progress"/);assert.match(active,/animateMotion/);
 assert.match(active,/aria-valuenow="1"/);assert.match(active,/&lt;script&gt;/);assert.doesNotMatch(active,/<script>/);
 assert.equal(JSON.stringify(p),before);
});
test('only successful actual todo updates change the checklist; new turns reset stale plans',()=>{
 const events=[e(1,'control.started'),e(2,'tool.started',{tool:'write_todos',tool_call:'a',input:JSON.stringify({todos:[{content:'repair',status:'in_progress'}]})})];
 assert.equal(plan(events,'main').items.length,0);
 events.push(e(3,'tool.failed',{tool:'write_todos',tool_call:'a'}));assert.equal(plan(events,'main').items.length,0);
 events.push(e(4,'tool.started',{tool:'write_todos',tool_call:'b',input:JSON.stringify({todos:[{content:'repair',status:'completed'},{content:'test',status:'in_progress'}]})}),e(5,'tool.completed',{tool:'write_todos',tool_call:'b',output:'Updated todo list'}));
 assert.deepEqual(plan(events,'main').items.map(i=>i.status),['completed','in_progress']);
 events.push(e(6,'control.started'));assert.equal(plan(events,'main').items.length,0);
});
test('fallback requires current-source experiment evidence and never calls compile numerical pass',()=>{
 const task={plan:{hypothesis:'hypothesis',change:'change',validation:'test'},starting_source:'old',current_source:'new',last_result:{source_sha256:'old',state:'completed'}};
 assert.equal(plan([],'main',task).items[2].status,'in_progress');
 task.last_result={source_sha256:'new',state:'completed',evaluation_mode:'compile-only'};
 const html=markup(plan([],'main',task),'<script>');assert.match(html,/未验证精度/);assert.doesNotMatch(html,/<script>|数值通过/);
});
test('Judger receiving Wrong Answer completes receipt step but never marks official success',()=>{
 const events=[e(1,'control.started',{},'controller'),e(2,'judge.candidate.selected',{candidate_id:'c'}),e(3,'judge.submitted',{candidate_id:'c',submission_id:'s'}),e(4,'judge.submission.updated',{submission_id:'s',official:{status:'Wrong Answer'}})];
 let p=judgePlan(events);assert.equal(p.items[4].status,'completed');assert.equal(p.items[5].status,'failed');
 events.push(e(5,'judge.submission.updated',{submission_id:'other',official:{status:'Pass'}}));p=judgePlan(events);assert.equal(p.items[5].status,'failed');
 events.push(e(6,'control.started',{},'controller'));assert.equal(judgePlan(events).items[3].status,'pending');
});
