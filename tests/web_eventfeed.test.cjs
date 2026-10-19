const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Feed}=require('../src/aworker/lab/resources/web/eventfeed.js');
function fixture(limit=3){
 const handlers={},button={hidden:true,addEventListener:(n,f)=>handlers['button-'+n]=f};
 const element={children:[],scrollTop:0,addEventListener:(n,f)=>handlers[n]=f,
  prepend(item){this.children.unshift(item);item.remove=()=>{this.children=this.children.filter(x=>x!==item);};},
  get lastElementChild(){return this.children.at(-1);},set innerHTML(v){this.children=[];}};
 const item=id=>({id,classList:{values:[],add(v){this.values.push(v);}}});
 return {element,button,handlers,item,feed:new Feed(element,button,limit)};
}
test('history rows are static and only an actual arriving receipt is animated',()=>{
 const {feed,item,element}=fixture();const old=item(1),fresh=item(2);
 feed.insert(old,false);feed.insert(fresh);
 assert.deepEqual(old.classList.values,[]);assert.deepEqual(fresh.classList.values,['receipt-arriving']);
 assert.deepEqual(element.children.map(x=>x.id),[2,1]);
});
test('reading history freezes insertion until explicitly following new events',()=>{
 const {feed,item,element,button,handlers}=fixture();feed.insert(item(1),false);
 element.scrollTop=50;handlers.scroll();feed.insert(item(2));feed.insert(item(3));
 assert.deepEqual(element.children.map(x=>x.id),[1]);assert.equal(element.scrollTop,50);
 assert.equal(button.hidden,false);assert.match(button.textContent,/2 条新事件/);
 handlers['button-click']();assert.deepEqual(element.children.map(x=>x.id),[3,2,1]);
 assert.equal(element.scrollTop,0);assert.equal(button.hidden,true);
});
test('bounded pending events reset when changing replay or live contexts',()=>{
 const {feed,item,element,button,handlers}=fixture(2);element.scrollTop=50;handlers.scroll();
 for(let i=0;i<9;i++)feed.insert(item(i));assert.equal(feed.pending.length,2);
 feed.reset();assert.deepEqual(feed.pending,[]);assert.equal(feed.follow,true);assert.equal(button.hidden,true);
 feed.insert(item('new-context'),false);assert.deepEqual(element.children.map(x=>x.id),['new-context']);
});
