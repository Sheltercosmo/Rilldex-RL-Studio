'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {TrainingContext:{resolve,scopedHref,switchHref,graphsForScope}}=require('../tracker/web/workspace-layout.js');
const options=[{id:'old'},{id:'trainer'},{id:'rollouts'}],recent=[
 {experiment:'old',logs:9,last_received:'2026-10-01'},
 {experiment:'trainer',logs:8,last_received:'2026-10-22'},
 {experiment:'rollouts',logs:0,last_received:'2026-10-23'}];
test('fresh overview opens recent native training; explicit scope and remembered choices win',()=>{
 assert.equal(resolve('',null,options,recent).experiment,'trainer');
 assert.equal(resolve('',{experiment:'old'},options,recent).experiment,'old');
 assert.equal(resolve('',{experiment:'deleted'},options,recent).experiment,'trainer');
 assert.deepEqual(resolve('?experiment=outside&environment=terminal',{experiment:'old'},options,recent),{experiment:'outside',environment:'terminal'});
 assert.equal(resolve('?scope=all',{experiment:'old'},options,recent).experiment,'');
 assert.equal(resolve('',{experiment:''},options,recent).experiment,'');
 assert.equal(resolve('?experiment=',null,options,recent).experiment,'');
 assert.equal(resolve('',null,[],[]).experiment,'');
});
test('archived runs are never chosen automatically; malformed remembered environment is ignored',()=>{
 assert.equal(resolve('',null,options,recent.map(r=>({...r,archived:r.experiment==='trainer'}))).experiment,'old');
 assert.equal(resolve('',{experiment:'trainer',environment:{}},options,recent).environment,'');
 assert.equal(resolve('?environment=cartpole',{experiment:'trainer',environment:'old'},options,recent).environment,'cartpole');
});
test('shared links retain one run and environment; explicit all stays explicit after reload',()=>{
 assert.equal(scopedHref('/monitors?view=reward',{experiment:'run / a&b',environment:'env'}),'/monitors?view=reward&experiment=run+%2F+a%26b&environment=env');
 assert.equal(scopedHref('/?experiment=old&environment=old',{}),'/?scope=all');
 assert.equal(scopedHref('/?scope=all',{experiment:'new'}),'/?experiment=new');
});
test('switching run preserves the view but drops comparison windows and frozen evidence',()=>{
 const next=switchHref('/','?view=health&health_panel=diagnostics&signals_compare=old&signals_from=12&signals_cutoffs=77',{experiment:'new'});
 assert.equal(next,'/?view=health&health_panel=diagnostics&experiment=new');
 assert.equal(switchHref('/investigate','?saved=frozen&run=r',{experiment:'new'}),'/?experiment=new');
 assert.equal(switchHref('/semantic-map','?run=r&graph=g&observer=o',{experiment:'new'}),'/?experiment=new');
 assert.equal(switchHref('/','?view=experiments',{experiment:'new'}),'/?experiment=new');
});
test('map entry obeys shared scope while explicit evidence remains accessible',()=>{
 const rows=[{run_id:'a',metadata:{experiment:'A',environment:'terminal'}},{run_id:'b',metadata:{experiment:'B',environment:'terminal'}},{run_id:'c',metadata:{experiment:'A',environment:'browser'}},{run_id:'d',metadata:{}}];
 assert.deepEqual(graphsForScope(rows,{experiment:'A',environment:'terminal'}).map(r=>r.run_id),['a']);
 assert.deepEqual(graphsForScope(rows,{experiment:'A'},'b').map(r=>r.run_id),['b']);
 assert.deepEqual(graphsForScope(rows,{experiment:'missing'}),[]);
 assert.deepEqual(graphsForScope(rows,{experiment:'__unassigned__'}).map(r=>r.run_id),['d']);
 assert.equal(graphsForScope(rows,{},'old-immutable-snapshot').length,4);
});
