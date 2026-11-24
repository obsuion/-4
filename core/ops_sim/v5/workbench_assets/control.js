'use strict';
(function(root){
  const canonical=v=>JSON.stringify(v,(k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(n=>[n,x[n]])):x);
  const fields=p=>({title:p.title,placement:p.placement,payload_area_m2:p.payload_area_m2,
    requirements:JSON.stringify(p.requirements,Object.keys(p.requirements).sort())});
  class Draft {
    constructor(){this.generation=0;this.project=null;this.applied=null;this.value=null;this.revision=null;}
    select(p){this.generation++;this.project=p.project_id;this.revision=p.revision;this.applied=fields(p);this.value={...this.applied};}
    edit(p){this.generation++;this.value=fields(p);}
    get dirty(){return !this.applied||canonical(this.value)!==canonical(this.applied);}
    requireApplied(){if(this.dirty)throw Error('Есть неприменённые поля: сначала Apply и новый preview.');}
    token(){return {generation:this.generation,project:this.project,revision:this.revision};}
    accepts(t){return t.generation===this.generation&&t.project===this.project&&t.revision===this.revision;}
    appliedResponse(t,p){if(t.project!==this.project)return false;if(!this.accepts(t)){
      this.applied=fields(p);this.revision=p.revision;return false;
    }this.select(p);return true;}
    poll(p){if(p.project_id!==this.project)return false;if(p.revision!==this.revision){
      // A changed server revision never erases a local draft.
      if(this.dirty)return false;this.select(p);
    }return true;}
  }
  class Intents {
    constructor(storage,key='kaz-durable-intent-v1'){this.storage=storage;this.key=key;this.busy=false;}
    current(){const s=this.storage.getItem(this.key);return s?JSON.parse(s):null;}
    begin(body){const old=this.current();if(old){if(canonical(old)!==canonical(body))throw Error('Сначала reconcile сохранённое действие; новые параметры нельзя подменить.');return old;}
      this.storage.setItem(this.key,JSON.stringify(body));return body;}
    async send(body,submit,reconcile){if(this.busy)throw Error('Это действие уже отправляется.');this.busy=true;
      try{const pinned=this.begin(body);const found=await reconcile(pinned);if(found)return found;
        return await submit(pinned);
      }finally{this.busy=false;}
    }
    newAction(settled){if(this.busy||!settled)throw Error('Нельзя заменить неизвестное действие новым ключом.');this.storage.removeItem(this.key);}
  }
  const api={Draft,Intents,fields,canonical};root.KazControls=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
