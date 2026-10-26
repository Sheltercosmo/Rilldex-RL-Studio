const {test}=require('node:test');const assert=require('node:assert/strict');
const {cells}=require('../tracker/web/context-mix.js');
test('matrix preserves exact volume including tiny blocks and mixed cells',()=>{
 const blocks=[{id:'a',category:'system',chars:1},{id:'b',category:'tool',chars:10000},{id:'c',category:'user',chars:7}];
 const result=cells(blocks);assert.ok(result.length<=288);
 const counts={};for(const cell of result){assert.equal(cell.parts.reduce((s,p)=>s+p.length,0),cell.end-cell.start);for(const part of cell.parts)counts[part.id]=(counts[part.id]||0)+part.length;}
 assert.deepEqual(counts,{a:1,b:10000,c:7});assert.equal(result[0].start,0);assert.equal(result.at(-1).end,10008);
});
test('empty context and empty blocks render without phantom volume',()=>{assert.deepEqual(cells([]),[]);assert.deepEqual(cells([{chars:0}]),[]);assert.equal(cells([{chars:0},{id:'x',category:'user',chars:1}]).length,1);});
