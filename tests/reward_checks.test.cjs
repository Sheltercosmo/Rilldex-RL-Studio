const {test}=require('node:test');
const assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.value='';this.listeners={};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(){}
 addEventListener(name,fn){this.listeners[name]=fn;}
}
global.document={createElement:tag=>new Element(tag)};
const {render}=require('../tracker/web/reward-checks.js');
const all=n=>[n,...n.children.flatMap(all)];
test('saved protocol controls available checks and their descriptions',async()=>{
 const host=new Element('section');
 const rows=[{id:'evaluation_material_access',name:'Access',description:'current',observer_type:'diagnostic',requires:'Saved observations'},
  {id:'restricted_evaluation_access',name:'Restriction',description:'current restriction',observer_type:'diagnostic',requires:'Saved observations'},
  {id:'reward_aggregation_gap',name:'Reward gap',description:'source',observer_type:'source',requires:'Source'}];
 await render(host,{api:async()=>({reward_checks:{checks:rows,observers:[
  {id:'old',label:'Old',checks:{evaluation_material_access:{name:'Historical access',description:'historical definition'}}},
  {id:'new',label:'New',checks:{evaluation_material_access:{name:'Evaluator-material access',description:'new access'},restricted_evaluation_access:{name:'Explicit restriction',description:'new restriction'}}}]} }),scope:()=>({}),onChange:async()=>{},onCustom:()=>{}});
 const nodes=all(host),select=nodes.find(n=>n.tag==='select'),inputs=nodes.filter(n=>n.tag==='input');
 select.value='new';select.listeners.change();
 assert.equal(inputs[1].disabled,false);inputs[1].checked=true;
 assert.equal(inputs[0].rewardCheck.name.textContent,'Evaluator-material access');
 select.value='old';select.listeners.change();
 assert.equal(inputs[1].disabled,true);assert.equal(inputs[1].checked,false);
 assert.equal(inputs[0].rewardCheck.name.textContent,'Historical access');
 assert.equal(inputs[0].rewardCheck.item.title,'historical definition');
 assert.equal(inputs[2].disabled,false);
});
