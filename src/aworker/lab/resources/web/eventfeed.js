/* Receipt motion represents arriving events only; browsing history freezes insertion. */
((root)=>{
  'use strict';
  class Feed{
    constructor(element,button,limit=160){
      this.element=element;this.button=button;this.limit=limit;this.pending=[];this.follow=true;
      element.addEventListener('scroll',()=>{
        this.follow=element.scrollTop<12;
        if(this.follow&&this.pending.length)this.latest();
      });
      button.addEventListener('click',()=>this.latest());
    }
    insert(item,animate=true){
      if(animate)item.classList.add('receipt-arriving');
      if(!this.follow&&animate){
        this.pending.push(item);
        if(this.pending.length>this.limit)this.pending.shift();
        this.button.hidden=false;this.button.textContent=`${this.pending.length} 条新事件 · 跟随最新 ↑`;return;
      }
      this.element.prepend(item);
      while(this.element.children.length>this.limit)this.element.lastElementChild.remove();
      if(this.follow)this.element.scrollTop=0;
    }
    latest(){
      this.follow=true;
      for(const item of this.pending)this.insert(item,false);
      this.pending=[];this.button.hidden=true;this.element.scrollTop=0;
    }
    reset(){this.pending=[];this.follow=true;this.button.hidden=true;this.element.innerHTML='';}
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={Feed};else root.JustKernelEventFeed={Feed};
})(typeof window==='undefined'?{}:window);
