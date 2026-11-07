// T023: real server-rendered components driven with synthetic HTTP, no service/browser/provider.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };
globalThis.__tsxHookHarness = {};
const { InvocationPage } = await import('../src/map/InvocationPage.tsx');
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
const { initialDocument, drawerHref, loadDocumentation } = await import('../src/map/DocsDrawer.tsx');
await loadDocumentation();
const { TraceDetails, OriginalRead } = await import('../src/map/TraceDetails.tsx');
delete globalThis.__tsxHookHarness;
const { syntheticMap, respond } = await import('../src/map/fixture/projections.ts');
const { traceStep, tracePage, relatedRecords, permissionRecords, TRACE_SIZE } = await import('../src/map/fixture/trace.ts');
const { traceItems, traceGraph, sourcePath, traceOrder } = await import('../src/map/trace.ts');
const { LevelLoader, MAX_PAGES } = await import('../src/map/loader.ts');
const { pageOf } = await import('../src/map/api.ts');
const { ManagedError } = await import('../src/managed-api.ts');
const { renderMarkdown } = await import('../src/markdown.ts');
const { forgetViewMemory } = await import('../src/map/view-mode.ts');
const t = (key, params) => translate({en, es}, 'en', key, params);
const tick = () => new Promise(resolve => setImmediate(resolve));
const decode = text => text.replaceAll('&quot;', '"').replaceAll('&amp;', '&');
const CLICK = { button: 0, detail: 1, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
const INV = 'inv-atlas-executor-2';

function env({ archive = false, list = false, doc, answer, language = 'en' } = {}) {
  const map = syntheticMap('budget', { archive });
  const project = archive ? 'kp-atlas' : 'atlas';
  const timers = new Map(), requests = [], pushes = [], listeners = new Set();
  const saved = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = (cb, ms) => { const id = {}; timers.set(id, {cb, ms}); return id; };
  globalThis.clearTimeout = id => timers.delete(id);
  const params = new URLSearchParams({ view: list ? 'list' : 'map' });
  if (doc !== undefined) params.set('doc', doc);
  const setURL = url => { const next = new URL(url, 'http://local'); window.location.pathname = next.pathname; window.location.search = next.search; };
  globalThis.window = { location: { pathname: `/projects/${project}/invocations/${INV}`, hash: "", search: '?' + params },
    history: { pushState(_a, _b, url) { pushes.push(url); setURL(url); }, replaceState(_a, _b, url) { setURL(url); } },
    addEventListener(_kind, fn) { listeners.add(fn); }, removeEventListener(_kind, fn) { listeners.delete(fn); } };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.document = { documentElement: {getAttribute: () => null}, activeElement: null, visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
  globalThis.localStorage = { getItem: () => language, setItem() {} };
  globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, method: options?.method ?? 'GET' });
    if (url === '/api/managed/preferences') return Response.json({ status: 'missing' });
    const custom = await answer?.(url);
    if (custom) return Response.json(custom.body, { status: custom.status ?? 200 });
    const result = respond(map, url);
    return Response.json(result.body, { status: result.status });
  };
  forgetViewMemory();
  return { map, project, timers, requests, pushes, setURL,
    async fire() { const due = [...timers.values()]; timers.clear(); due.forEach(({cb}) => cb()); await tick(); await tick(); },
    close() { Object.assign(globalThis, saved); for (const key of ['window','document','localStorage','sessionStorage','MutationObserver']) delete globalThis[key]; } };
}
const tree = (component, language = 'en', archive = false) => el(I18nProvider, { fixed: language }, el(ServiceModeContext.Provider, { value: { read_only_archive: archive } }, component));
const button = (host, label) => host.elements.find(item => item.type === 'button' && item.props.children === label);

// Graph structure is a persisted membership graph. Overlapping siblings must never acquire an ordering edge.
test('trace fan-out, retries, failure, gaps and client units preserve identities and relation meanings', () => {
  const steps = Array.from({length: 20}, (_, i) => traceStep(i));
  const items = traceItems(steps, [...relatedRecords(), ...permissionRecords()]);
  const {nodes, edges} = traceGraph(items, t);
  assert.equal(new Set(nodes.map(n => n.id)).size, items.length);
  assert.equal(nodes.find(n => n.id === 'step:1').statusClass, 'failed');
  assert.equal(nodes.find(n => n.id === 'step:5').statusClass, 'done', 'retry stays separate');
  assert.equal(nodes.find(n => n.id === 'step:6').status, 'not_observed');
  assert.ok(edges.some(e => e.from === 'step:0' && e.to === 'step:1' && e.kind === 'containment'));
  assert.ok(edges.some(e => e.from === 'step:0' && e.to === 'step:2' && e.kind === 'containment'));
  assert.ok(!edges.some(e => e.from === 'step:1' && e.to === 'step:2'));
  assert.ok(edges.some(e => e.from === 'step:0' && e.to === 'step:10' && e.kind === 'sequence'));
  assert.ok(edges.some(e => e.kind === 'causation'));
  assert.equal(steps[0].unit, 'codex_turn'); assert.equal(steps[10].unit, 'claude_message');
  const window = traceGraph(traceItems([traceStep(201)], []), t);
  assert.deepEqual(window.edges, [], 'no invented parent at a page boundary');
});

test('turn arrows follow persisted sequence with inverted and absent receipt times', () => {
  const first = { ...traceStep(0), started_at: '2026-11-07T11:00:00Z' };
  const second = { ...traceStep(10), started_at: '2026-11-07T10:00:00Z' };
  const unknown = { ...traceStep(20), started_at: null, finished_at: null };
  const last = { ...traceStep(30), started_at: '2026-11-07T12:00:00Z' };
  const items = traceOrder(traceItems([last, second, unknown, first], []));
  assert.deepEqual(items.map(item => item.step.seq), [0, 10, 20, 30]);
  assert.deepEqual(traceGraph(items, t).edges, [
    { from: 'step:0', to: 'step:10', kind: 'sequence' },
    { from: 'step:10', to: 'step:20', kind: 'sequence' },
    { from: 'step:20', to: 'step:30', kind: 'sequence' },
  ]);
});

test('a recorded parent and explicit causation have distinct edges', () => {
  const [root, child, cause, effect] = relatedRecords();
  effect.causation_id = cause.event_id;
  effect.parent_event_id = root.event_id;
  const { edges } = traceGraph(traceItems([], [root, child, cause, effect]), t);
  assert.deepEqual(edges.filter(edge => edge.to === `record:${child.event_id}`), [
    { from: `record:${root.event_id}`, to: `record:${child.event_id}`, kind: 'parentage' },
  ]);
  assert.deepEqual(edges.filter(edge => edge.to === `record:${effect.event_id}`), [
    { from: `record:${root.event_id}`, to: `record:${effect.event_id}`, kind: 'parentage' },
    { from: `record:${cause.event_id}`, to: `record:${effect.event_id}`, kind: 'causation' },
  ]);
  effect.parent_event_id = effect.causation_id;
  assert.deepEqual(traceGraph(traceItems([], [cause, effect]), t).edges, [
    { from: `record:${cause.event_id}`, to: `record:${effect.event_id}`, kind: 'causation' },
  ]);
});

test('5,000-step lazy history reaches the end without duplication and keeps memory/render bounded', async () => {
  const map = syntheticMap('budget');
  const header = map.invocation('atlas', INV);
  const calls = [], seen = [];
  const loader = new LevelLoader('/steps?limit=200', async (base, cursor) => {
    const path = pageOf(base, cursor);
    calls.push(path); return tracePage(header, new URL(path, 'http://local'), 'steps');
  }, () => {});
  loader.reload(); await tick();
  for (;;) {
    const page = loader.state.pages.at(-1);
    seen.push(...page.items.map(step => step.seq));
    assert.ok(page.items.length <= 200); assert.ok(loader.state.pages.length <= MAX_PAGES);
    if (!loader.canLoadMore) break;
    loader.loadMore(); await tick();
  }
  assert.equal(calls.length, 25); assert.equal(seen.length, TRACE_SIZE);
  assert.deepEqual(seen, Array.from({length: TRACE_SIZE}, (_, i) => i));
  assert.equal(new Set(seen).size, TRACE_SIZE); assert.equal(loader.state.skipped, 20);
  loader.dispose();
});

test('409 cursor_stale recovers the first page; disposal discards a late invocation response', async () => {
  const map = syntheticMap('budget'), header = map.invocation('atlas', INV);
  const paths = [];
  const loader = new LevelLoader('/steps', async (base, cursor) => {
    const path = pageOf(base, cursor);
    paths.push(path);
    if (path.includes('cursor=')) throw new ManagedError(409, 'stale', 'cursor_stale');
    return tracePage(header, new URL(path, 'http://local'), 'steps');
  }, () => {});
  loader.reload(); await tick(); loader.loadMore(); await tick(); await tick();
  assert.equal(paths.length, 3); assert.equal(paths[2], '/steps'); assert.equal(loader.state.pages[0].items[0].seq, 0);
  const changes = []; let resolve;
  const old = new LevelLoader('/old', () => new Promise(done => { resolve = done; }), value => changes.push(value));
  old.reload(); old.dispose(); const count = changes.length;
  resolve(tracePage(header, new URL('http://local'), 'steps')); await tick();
  assert.equal(changes.length, count);
  loader.dispose();
});

test('server renders graph and list with equivalent details, bounded nodes, archive without polling/actions', async () => {
  for (const language of ['en','es']) for (const archive of [false,true]) for (const list of [false,true]) {
    const e = env({archive, list, language}), host = hookHost();
    try {
      const html = decode(await host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive }), language, archive)));
      assert.equal([...html.matchAll(/data-node=/g)].length, list ? 0 : 200);
      assert.match(html, /codex_turn/); assert.ok(button(host.host, translate({en, es}, language, 'trace.group.records')));
      assert.match(html, /trace-paging/); assert.match(html, /map-inspector-body/);
      assert.ok(html.includes(translate({en, es}, language, 'trace.timing')));
      assert.equal(e.timers.size, archive ? 0 : 1);
      assert.ok(e.requests.every(r => r.method === 'GET'));
      assert.ok(!e.requests.some(r => /\/events|\/logs|\/artifacts|\/documents/.test(r.url)), 'originals and drawer are lazy');
      if (list) assert.match(html, /trace-list/);
    } finally {host.close(); e.close();}
  }
});

test('permission history keeps a grant distinct from expired authority and offers only a read', async () => {
  const e = env({archive:true}), host = hookHost();
  try {
    const html = decode(await host.render(tree(el(TraceDetails, {item:{id:'p',permission:permissionRecords()[0]}}), 'en', true)));
    assert.match(html, /Historical response/); assert.match(html, /Granted/); assert.match(html, /Current authority/); assert.match(html, /Expired/);
    assert.equal(e.requests.length, 0);
    assert.doesNotMatch(html, /Grant permission|Respond|Revoke/);
  } finally {host.close();e.close();}
});

test('original event and exact large record are read on demand, escaped, with retention and metadata preserved', async () => {
  for (const seq of [1,11]) {
    const e = env(), host = hookHost();
    try {
      let html = decode(await host.render(tree(el(TraceDetails, {item:{id:`step:${seq}`,step:traceStep(seq)}}))));
      assert.equal(e.requests.length, 0);
      if (seq === 11) assert.match(html, /Unavailable after retention/);
      button(host.host, 'Read original event').props.onClick(); await tick();
      html = decode(await host.render(tree(el(TraceDetails, {item:{id:`step:${seq}`,step:traceStep(seq)}}))));
      assert.match(html, /original_reference/);
      button(host.host, 'Inspect log metadata').props.onClick(); await tick();
      html = decode(await host.render(tree(el(TraceDetails, {item:{id:`step:${seq}`,step:traceStep(seq)}}))));
      assert.match(html, /size_bytes/);
      assert.ok(e.requests.every(r => !/sequence=/.test(r.url)), 'metadata inspection requests no original');
      button(host.host, 'Read exact large original').props.onClick(); await tick();
      html = decode(await host.render(tree(el(TraceDetails, {item:{id:`step:${seq}`,step:traceStep(seq)}}))));
      assert.equal(e.requests.filter(r => /sequence=/.test(r.url)).length, 1);
      if (seq === 1) {
        assert.match(html, /Original large synthetic record/);
        assert.match(html, /&lt;script&gt;escaped text&lt;\/script&gt;/);
        assert.doesNotMatch(html, /<script>/);
      } else assert.doesNotMatch(html, /Original large synthetic record/);
      assert.ok(e.requests.every(r => !/offset=|range=/.test(r.url)));
    } finally {host.close();e.close();}
  }
});

test('large original read refuses another reference identity before displaying its content', async () => {
  const e = env({answer: url => url.includes('/logs?sequence=') ? {body:{run_id:'foreign',content:'must not show'}} : undefined});
  const host = hookHost();
  const render = () => host.render(tree(el(TraceDetails,{item:{id:'step:1',step:traceStep(1)}})));
  try {
    await render(); button(host.host,'Read exact large original').props.onClick(); await tick();
    const html=await render();
    assert.match(html,/does not match this attempt/);
    assert.doesNotMatch(html,/must not show/);
  } finally {host.close();e.close();}
});

test('source event attempt and sequence are verified before displaying original content', async () => {
  const e = env({ answer: url => url.includes('/events') ? {body:{items:[{sequence:2,kind:'agent_event',payload:{attempt_id:'foreign',original:'must not show'}}]}} : undefined }), host = hookHost();
  const ref = traceStep(1).source_records[0];
  const render = () => host.render(tree(el(OriginalRead, {path:sourcePath(ref.event),label:'Read',source:ref})));
  try {await render(); button(host.host,'Read').props.onClick(); await tick(); const html = await render();
    assert.match(html,/does not match this attempt/);assert.doesNotMatch(html,/must not show/);
  } finally {host.close();e.close();}
});

test('drawer defaults use persisted level context and deterministic available-document fallback; URL keeps view/history', () => {
  const paths = ['docs/NEXT_STEPS.md','docs/ROADMAP.md','docs/SPECIFICATION.md'];
  assert.equal(initialDocument(paths,{level:1}), 'docs/ROADMAP.md');
  assert.equal(initialDocument(paths,{level:2,phase:'P002'}), 'docs/ROADMAP.md');
  assert.equal(initialDocument(paths,{level:3,task:'P002-T005'}), 'docs/NEXT_STEPS.md');
  assert.equal(initialDocument(paths,{level:4,task:'P002-T005'}), 'docs/NEXT_STEPS.md');
  assert.equal(initialDocument(['z.md','a.md'],{level:4}), 'a.md');
  assert.equal(drawerHref('/p','?view=list&doc=x','a.md'),'/p?view=list&doc=a.md');
  assert.equal(drawerHref('/p','?view=list&doc=x&doc_anchor=y'),'/p?view=list');
});

test('canonical drawer renders accepted Markdown and tree without checkout or actions, including archives', async () => {
  for (const archive of [false,true]) {
    const e = env({archive,doc:''}), host=hookHost();
    try {
      const html = decode(await host.render(tree(el(InvocationPage, {project:e.project,invocation:INV,archive}), 'en', archive)));
      assert.match(html,/Canonical accepted knowledge/);assert.match(html,/fixture-revision/);
      assert.match(html,/Accepted canonical knowledge/);assert.match(html,/docs-tree/);assert.match(html,/data-mermaid/);
      assert.ok(e.requests.filter(r=>r.url.includes('documents')).every(r=>r.url.includes('/map/projects/')));
      assert.doesNotMatch(html,/Export|Adopt|Edit document|href="[^"?]*\/docs\//);
      assert.equal(e.timers.size,archive?0:1);
    }finally{host.close();e.close();}
  }
});

test('canonical rendering blocks checkout images, HTML and unsafe links while keeping internal document links', () => {
  const html = renderMarkdown('<script>unsafe()</script>\n\n![x](pic.png)\n\n[x](javascript:alert(1))\n\n[Roadmap](ROADMAP.md)',{project:'kp',path:'docs/NEXT_STEPS.md',checkoutImages:false}).html;
  assert.doesNotMatch(html,/<script|<img|src=|href="javascript/);
  assert.match(html,/data-internal/);
});

test('legacy archive drawer neither requests checkout reads nor falls back after a canonical failure', async () => {
  for(const source of ['unavailable','failure']){
    const e=env({archive:true,doc:'',answer:url=>url.includes('/documents')?source==='failure'?{status:409,body:{detail:{code:'integrity_failed'}}}:{body:{source:'unavailable',tree:{files:[]},content:null,revision_id:null}}:undefined}),host=hookHost();
    try{const html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:true}),'en',true));
      assert.match(html,source==='failure'?/integrity_failed/:/unavailable for this project/);
      assert.ok(e.requests.filter(r=>r.url.includes('documents')).every(r=>r.url.includes('/map/projects/')));
      assert.equal(e.timers.size,0);
    }finally{host.close();e.close();}
  }
});

test('trace state labels preserve pending, integrity, excluded and pre-T019 evidence without backfill', async () => {
  for(const state of ['pending','integrity_failed','lane_excluded','not_projected']){
    const e=env({archive:true,answer:url=>{
      if(!url.includes('/invocations/')) return;
      const response=respond(syntheticMap('review',{archive:true}),url); const body=response.body;
      if(url.includes('/steps?')) return {body:{...body,state,items:[],reason:state==='not_projected'?'settled_before_observed_steps':state}};
      if(!url.includes('/related?')) return {body:{...body,steps:{...body.steps,state}}};
    }}),host=hookHost();
    try{const html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:true}),'en',true));
      assert.ok(html.includes(translate({en,es},'en',`map.steps_state.${state}`)));
      assert.match(html,/Run evidence/);
      assert.ok(e.requests.every(r=>r.method==='GET'));
    }finally{host.close();e.close();}
  }
});

test('changing invocation discards delayed step responses and resets the scope shown', async () => {
  let release;
  const other = 'inv-' + syntheticMap('budget').deepRun + '-1';
  const e=env({answer:url=> url.includes(`/${INV}/steps?`) ? new Promise(resolve=>{release=resolve;}) : undefined}),host=hookHost();
  try{
    await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.ok(release);
    const header=e.map.invocation(e.project,other);assert.ok(header);
    e.setURL(`/projects/${e.project}/invocations/${other}?view=map`);
    let html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:other,archive:false})));
    assert.match(html,/synthetic.lookup/);
    const old=tracePage(e.map.invocation(e.project,INV),new URL('http://local'),'steps');
    old.items[0]={...old.items[0],kind:'tool_call',tool:{name:'late-old-invocation',origin:'native'}};
    release({body:old});await tick();
    html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:other,archive:false})));
    assert.doesNotMatch(html,/late-old-invocation/);
  }finally{host.close();e.close();}
});

test('ordinary L4 refreshes changed version scopes; archive keeps every read on demand', async () => {
  for(const archive of [false,true]){
    const e=env({archive}),host=hookHost();
    try{
      await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive}),'en',archive));
      const before=e.requests.filter(r=>r.url.includes('/steps?')).length;
      e.map.bump(); await e.fire();
      await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive}),'en',archive));
      assert.equal(e.requests.filter(r=>r.url.includes('/steps?')).length,before+(archive?0:1));
      assert.equal(e.requests.filter(r=>r.url.includes('/map/activity')).length,archive?0:1);
    }finally{host.close();e.close();}
  }
});

test('all managed owner lanes and excluded lanes stay navigable; archive return avoids operational chat/check routes', async () => {
  for(const lane of ['task','chat','phase_operation','definition','planning','bootstrap','judge','roadmap_review','preparation_step','configuration_assistance']){
    const archive=true;
    const e=env({archive,answer:url=>{
      if(!url.endsWith(`/invocations/${INV}`))return;
      const head=syntheticMap('budget',{archive}).invocation('kp-atlas',INV);
      const excluded=['preparation_step','configuration_assistance'].includes(lane);
      return {body:{...head,invocation:{...head.invocation,lane:excluded?lane:'managed_attempt',purpose:lane},owner:{...head.owner,lane,
        breadcrumb:[{level:'project',id:'kp-atlas'},{level:lane==='chat'?'chat':lane==='phase_operation'?'phase_operation':'phase',id:lane==='chat'?'fixture-chat':'P002'},
          {level:'invocation',id:INV,role:'reviewer'}]},steps:{...head.steps,state:excluded?'lane_excluded':'sealed'}}};
    }}),host=hookHost();
    try{
      const html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive}),'en',archive));
      const view=host.host.elements.find(item=>item.props.className==='map-canvas');assert.ok(view);
      const {pageGestures}=await import('../src/map/controller.ts');pageGestures.end();
      view.props.onKeyDown({key:'Escape',repeat:false,preventDefault(){}});
      assert.ok(e.pushes.at(-1).includes('/phases'));
      assert.ok(!/\/chat|\/check/.test(e.pushes.at(-1)));
      assert.doesNotMatch(html,/href="[^"]*\/chat|href="[^"]*\/check/);
      assert.equal(e.timers.size,0);
    }finally{host.close();e.close();}
  }
});

test('drawer internal document navigation stays in query/history and closing restores the same map URL', async () => {
  const e=env({doc:''}),host=hookHost();
  try{
    await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    const prose=host.host.elements.find(item=>item.props.className==='doc-prose');assert.ok(prose);
    prose.props.onClick({...CLICK,target:{closest:()=>({getAttribute:()=>`/projects/${e.project}/docs/docs/ROADMAP.md#doc-p002-synthetic-phase`})}});
    assert.match(e.pushes.at(-1),/\/invocations\/inv-atlas-executor-2\?view=map&doc=docs%2FROADMAP.md/);
    let html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.match(html,/doc=docs%2FNEXT_STEPS.md/,'tree href stays in drawer');
    button(host.host,'Close').props.onClick();
    assert.equal(e.pushes.at(-1),`/projects/${e.project}/invocations/${INV}?view=map`);
    html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.doesNotMatch(html,/map-docs-drawer/);
  }finally{host.close();e.close();}
});

test('drawer Escape returns focus to its trigger, reopening focuses Close; map nodes remain keyboard controls', async () => {
  const e=env({doc:''}),host=hookHost();
  const focused=[];
  try{
    await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    const trigger=host.host.elements.find(item=>item.props.className?.includes('map-docs-trigger'));
    const close=button(host.host,'Close');
    trigger.props.ref.current={focus:()=>focused.push('trigger')};close.props.ref.current={focus:()=>focused.push('close')};
    const drawer=host.host.elements.find(item=>item.props.className==='map-docs-drawer');
    let stopped=false;drawer.props.onKeyDown({key:'Escape',stopPropagation(){stopped=true;}});
    await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.equal(stopped,true);assert.equal(focused.at(-1),'trigger');
    host.host.elements.find(item=>item.props.className?.includes('map-docs-trigger')).props.onClick();
    const html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.equal(focused.at(-1),'close');
    assert.match(html,/data-node="step:0"/);assert.match(html,/tabindex="0"/);
    assert.doesNotMatch(html,/aria-modal="true"/,'drawer leaves the map interactive and does not trap focus');
  }finally{host.close();e.close();}
});


test('point events and unknown receipt times keep native sequence order', () => {
  const turn={...traceStep(0),started_at:'2026-11-07T10:00:00Z'};
  const message={...traceStep(3),started_at:null,finished_at:'2026-11-07T11:00:01+01:00'};
  const missing={...traceStep(6),started_at:null,finished_at:null};
  const next={...traceStep(10),started_at:'2026-11-07T10:00:02Z'};
  assert.deepEqual(traceOrder(traceItems([next,missing,message,turn],[])).map(item=>item.step.seq),[0,3,6,10]);
});

test('only persisted event links anchor evidence; clocks, call IDs, parentage and causation do not', () => {
  const records = relatedRecords();
  const step = { ...traceStep(1), tool: { name: 'describe_tool', origin: 'harness_broker', links: {
    call_event_id: records[2].event_id, discovery_event_id: records[2].event_id,
  } } };
  records[0].fields.call_id = step.call_id;
  records[2].recorded_at = traceStep(4500).started_at;
  const ordered = traceOrder(traceItems([traceStep(2), step, traceStep(0)], [...records, ...permissionRecords()]));
  assert.deepEqual(ordered.slice(0, 4).map(item => item.id), ['step:0', 'step:1', `record:${records[2].event_id}`, 'step:2']);
  assert.equal(ordered[2].anchorSeq, 1);
  assert.ok(ordered.slice(4).every(item => !item.step && item.anchorSeq === undefined));
  const edges = traceGraph(ordered, t).edges;
  assert.deepEqual(edges.filter(edge => edge.kind === 'correlation'), [
    { from: 'step:1', to: `record:${records[2].event_id}`, kind: 'correlation' },
  ]);
  const ambiguous = traceOrder(traceItems([step, { ...step, seq: 5 }], [records[2]]));
  assert.equal(ambiguous.at(-1).anchorSeq, undefined);
  const offPage = traceOrder(traceItems([traceStep(200)], [records[2]]));
  assert.equal(offPage.at(-1).anchorSeq, undefined, 'an unavailable anchor cannot be inferred from cursor bounds');
});

const listIds = host => host.elements.filter(item => item.type === 'li' && item.props.children?.[0]?.type === 'button')
  .map(item => item.props.children[0].props.children[0]);

test('persisted event placement and the separate related section agree in real graph/list windows in both languages', async () => {
  for (const language of ['en', 'es']) {
    const e = env({ archive: true, list: true, language, answer: raw => {
      const url = new URL(raw, 'http://local');
      if (!url.pathname.endsWith('/steps')) return;
      const body = tracePage(syntheticMap('budget', { archive: true }).invocation('kp-atlas', INV), url, 'steps');
      if (!url.searchParams.has('cursor')) body.items[1].tool = {
        name: 'describe_tool', origin: 'harness_broker', links: { discovery_event_id: 'fixture-event-2' },
      };
      return { body };
    } }), host = hookHost();
    const render = () => host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive: true }), language, true));
    const label = key => translate({en, es}, language, key);
    const toggle = async mode => { e.setURL(`/projects/${e.project}/invocations/${INV}?view=${mode}`); return render(); };
    try {
      await render();
      const first = listIds(host.host);
      assert.deepEqual(first.slice(0, 4), ['#0', '#1', 'e3', '#2']);
      host.host.elements.find(item => item.type === 'button' && item.props.children?.[0] === 'e3').props.onClick();
      let html = await render();
      assert.ok(decode(html).includes(translate({en, es}, language, 'trace.position_step', { seq: 1 })));
      html = await toggle('map');
      assert.deepEqual([...html.matchAll(/data-node="([^"]+)"/g)].slice(0, 4).map(([, id]) => id),
        ['step:0', 'step:1', 'record:fixture-event-2', 'step:2']);
      const association = html.match(/<g class="map-edge map-edge-correlation">([\s\S]*?)<\/g>/);
      assert.ok(association);
      assert.doesNotMatch(association[1], /map-edge-head/, 'a correlation has no causal arrowhead');
      button(host.host, label('trace.window_next')).props.onClick();
      html = await render();
      assert.equal([...html.matchAll(/data-node=/g)].length, 7);
      assert.match(html, /data-trace-section="unpositioned"/);
      await toggle('list');
      const last = listIds(host.host);
      assert.deepEqual(last, ['#199', 'e1', 'e2', 'e4', 'e5', 'e6', 'fixture-request']);
      button(host.host, label('map.load_more')).props.onClick(); await render();
      assert.equal(listIds(host.host)[0], '#200');
      button(host.host, label('trace.previous')).props.onClick(); await render();
      assert.deepEqual(listIds(host.host), last);
      button(host.host, label('trace.window_previous')).props.onClick(); await render();
      assert.deepEqual(listIds(host.host), first);
      assert.equal(e.requests.filter(r => r.url.includes('/related?')).length, 2);
      assert.equal(e.timers.size, 0);
    } finally { host.close(); e.close(); }
  }
});

test('a first-page late receipt stays outside native chronology across D309 windows in graph and list', async () => {
  for (const list of [true, false]) {
    const e = env({ archive: true, list, answer: raw => {
      const url = new URL(raw, 'http://local');
      if (!url.pathname.endsWith('/related') || url.searchParams.get('group') !== 'records') return;
      const body = tracePage(syntheticMap('budget', { archive: true }).invocation('kp-atlas', INV), url, 'records');
      body.items[0] = { ...body.items[0], recorded_at: traceStep(4500).started_at };
      return { body };
    } }), host = hookHost();
    const render = () => host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive: true }), 'en', true));
    const ids = html => list ? listIds(host.host) : [...html.matchAll(/data-node="([^"]+)"/g)].map(([, id]) =>
      id.startsWith('step:') ? '#' + id.slice(5) : id.startsWith('record:') ? 'e' + (Number(id.split('-').at(-1)) + 1) : 'fixture-request');
    const click = async label => {
      const control = button(host.host, label);
      assert.ok(control && !control.props.disabled, label);
      control.props.onClick();
      return render();
    };
    try {
      let html = await render();
      const first = ids(html);
      assert.deepEqual(first, Array.from({ length: 200 }, (_, i) => `#${i}`));
      html = await click('Next render window');
      const related = ids(html);
      assert.match(html, /data-trace-section="unpositioned"/);
      assert.match(html, /Related evidence — position undetermined/);
      assert.ok(related.includes('e1'));
      assert.ok(!related.some(id => id.startsWith('#')));
      const seen = [...first, ...related];
      html = await click('Load more');
      const second = ids(html);
      assert.equal(second[0], '#200');
      seen.push(...second);
      assert.deepEqual(ids(await click('Previous held page')), related);
      assert.deepEqual(ids(await click('Previous render window')), first);
      await click('Next render window');
      assert.deepEqual(ids(await click('Next held page')), second);
      for (let page = 2; page < 25; page++) {
        html = await click('Load more');
        const window = ids(html);
        assert.equal(window.length, 200);
        seen.push(...window);
      }
      assert.deepEqual(seen.filter(id => id.startsWith('#')), Array.from({ length: TRACE_SIZE }, (_, i) => `#${i}`));
      assert.equal(seen.length, TRACE_SIZE + 7);
      assert.equal(new Set(seen).size, seen.length);
      assert.equal(e.requests.filter(r => r.url.includes('/related?')).length, 2);
      assert.equal(e.requests.filter(r => r.url.includes('/steps?')).length, 25);
      assert.equal(e.timers.size, 0);
    } finally { host.close(); e.close(); }
  }
});

test('All evidence traverses the D309 fixture once and restores exact held windows in both directions', async () => {
  const e = env({ archive: true, list: true }), host = hookHost();
  const render = () => host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive: true }), 'en', true));
  const click = async label => {
    const control = button(host.host, label);
    assert.ok(control && !control.props.disabled, label);
    control.props.onClick();
    await render();
  };
  try {
    await render();
    const first = listIds(host.host);
    assert.equal(first.length, 200);
    assert.ok(first.includes('#199'));
    const premature = button(host.host, 'Load more');
    assert.ok(!premature || premature.props.disabled, 'unseen records are still in this page');
    await click('Next render window');
    const last = listIds(host.host);
    assert.ok(last.includes('e1'));
    e.setURL(`/projects/${e.project}/invocations/${INV}?view=map`);
    const graph = await render();
    assert.deepEqual([...graph.matchAll(/data-node="record:fixture-event-(\d+)"/g)].map(match => `e${Number(match[1]) + 1}`).sort(), last.filter(id => id.startsWith('e')).sort());
    assert.match(graph, /data-node="permission:standing_permission:fixture-request"/);
    e.setURL(`/projects/${e.project}/invocations/${INV}?view=list`);
    await render();
    assert.deepEqual(listIds(host.host), last);
    await click('Load more');
    const secondPage = listIds(host.host);
    assert.ok(secondPage.includes('#200'));
    assert.ok(!secondPage.includes('e1'));
    await click('Previous held page');
    assert.deepEqual(listIds(host.host), last);
    await click('Previous render window');
    assert.deepEqual(listIds(host.host), first);
    await click('Next render window');
    await click('Next held page');
    assert.deepEqual(listIds(host.host), secondPage);
    const seen = [...first, ...last, ...secondPage];
    for (let page = 2; page < 25; page++) {
      await click('Load more');
      const ids = listIds(host.host);
      assert.equal(ids.length, 200);
      seen.push(...ids);
    }
    assert.equal(seen.at(-1), '#4999');
    assert.equal(new Set(seen).size, TRACE_SIZE + relatedRecords().length + permissionRecords().length);
    assert.equal(seen.length, new Set(seen).size);
    assert.equal(e.requests.filter(r => r.url.includes('/related?')).length, 2);
    for (let page = 1; page < MAX_PAGES; page++) await click('Previous held page');
    assert.ok(button(host.host, 'Previous held page').props.disabled);
    await click('Back to the first page');
    assert.deepEqual(listIds(host.host), first);
  } finally { host.close(); e.close(); }
});

function unevenHistory(sizes, { staleGroup, failGroup } = {}) {
  const calls = [];
  const header = syntheticMap('budget', { archive: true }).invocation('kp-atlas', INV);
  return { calls, answer(raw) {
    const url = new URL(raw, 'http://local');
    const group = url.pathname.endsWith('/steps') ? 'steps' : url.searchParams.get('group');
    if (!Object.hasOwn(sizes, group)) return;
    assert.equal(url.searchParams.get('limit'), '200');
    const cursor = url.searchParams.get('cursor');
    const prefix = `opaque+/= ${group}:`;
    const start = cursor ? Number(cursor.slice(prefix.length)) : 0;
    assert.equal(cursor, start ? prefix + start : null);
    calls.push([group, start]);
    if (start === 400 && group === staleGroup) {
      staleGroup = undefined;
      return { status: 409, body: { detail: { code: 'cursor_stale' } } };
    }
    if (cursor && group === failGroup) {
      failGroup = undefined;
      return { status: 500, body: { detail: 'synthetic failure' } };
    }
    const end = Math.min(start + 200, sizes[group]);
    const body = tracePage(header, new URL('http://local'), group);
    body.items = Array.from({ length: end - start }, (_, i) => {
      const seq = start + i;
      if (group === 'steps') return traceStep(seq);
      if (group === 'records') return { ...relatedRecords()[0], sequence: seq + 1, event_id: `synthetic-${seq}` };
      return { ...permissionRecords()[0], id: `p${seq}` };
    });
    body.next_cursor = end < sizes[group] ? prefix + end : null;
    return { body };
  } };
}

test('All evidence reaches unequal group tails when steps are empty or finish first', async () => {
  for (const steps of [0, 201]) {
    const sizes = { steps, records: 407, permissions: 203 };
    const { calls, answer } = unevenHistory(sizes);
    const e = env({ archive: true, list: true, answer }), host = hookHost();
    const render = () => host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive: true }), 'en', true));
    try {
      const windows = [];
      await render();
      for (;;) {
        const ids = listIds(host.host);
        assert.ok(ids.length && ids.length <= 200);
        windows.push(ids);
        const next = ['Next render window', 'Load more'].map(label => button(host.host, label)).find(control => control && !control.props.disabled);
        if (!next) break;
        next.props.onClick(); await render();
        assert.ok(windows.length < 10, 'finite traversal');
      }
      const expected = Object.entries(sizes).flatMap(([group, total]) =>
        Array.from({ length: total }, (_, i) => group === 'steps' ? `#${i}` : group === 'records' ? `e${i + 1}` : `p${i}`));
      assert.deepEqual(windows.flat().sort(), expected.sort());
      assert.equal(calls.length, steps ? 7 : 6);
      for (const ids of windows.slice(0, -1).reverse()) {
        const within = button(host.host, 'Previous render window');
        (within && !within.props.disabled ? within : button(host.host, 'Previous held page')).props.onClick();
        await render();
        assert.deepEqual(listIds(host.host), ids);
      }
    } finally { host.close(); e.close(); }
  }
});

test('a failed group leaves the combined window intact and a stale group resets the whole history', async () => {
  const fixture = unevenHistory({ steps: 401, records: 401, permissions: 201 }, { failGroup: 'records', staleGroup: 'steps' });
  const e = env({ archive: true, list: true, answer: fixture.answer }), host = hookHost();
  const render = () => host.render(tree(el(InvocationPage, { project: e.project, invocation: INV, archive: true }), 'en', true));
  const reachLastWindow = async () => {
    for (let next; (next = button(host.host, 'Next render window')) && !next.props.disabled;) {
      next.props.onClick(); await render();
    }
  };
  try {
    await render();
    const first = listIds(host.host);
    await reachLastWindow();
    const last = listIds(host.host);
    button(host.host, 'Load more').props.onClick(); await render();
    assert.deepEqual(listIds(host.host), last, 'a partial batch must never replace the displayed window');
    button(host.host, 'Load more').props.onClick(); await render();
    assert.notDeepEqual(listIds(host.host), last);
    await reachLastWindow();
    button(host.host, 'Load more').props.onClick(); await render();
    assert.deepEqual(listIds(host.host), first);
    for (const group of ['steps', 'records', 'permissions']) assert.equal(fixture.calls.filter(([key, start]) => key === group && start === 0).length, 2);
  } finally { host.close(); e.close(); }
});

test('the Observed steps filter pages to #4999, renders at most 200 and can return to earlier held/first pages', async () => {
  const e=env({archive:true,list:true}),host=hookHost();
  const render=()=>host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:true}),'en',true));
  try{
    await render();button(host.host,'Observed steps').props.onClick();let html=await render();
    for(let page=1;page<25;page++){
      button(host.host,'Load more').props.onClick();html=await render();
      assert.equal(host.host.elements.filter(item=>item.type==='li'&&item.props.children?.[0]?.type==='button').length,200);
    }
    assert.match(html,/#4999/);assert.doesNotMatch(html,/#0 ·/);
    button(host.host,'Previous held page').props.onClick();html=await render();assert.match(html,/#4799/);
    button(host.host,'Back to the first page').props.onClick();html=await render();assert.match(html,/#0/);assert.doesNotMatch(html,/#4999/);
  }finally{host.close();e.close();}
});

test('ordinary legacy drawer uses only the existing read-only tree/content fallback', async () => {
  const e=env({doc:'',answer:url=>{
    if(url.endsWith(`/invocations/${INV}`)){const head=syntheticMap('budget').invocation('atlas',INV);return {body:{...head,project:{...head.project,registered_project_id:'legacy-checkout'}}};}
    if(url.includes('/map/projects/')&&url.includes('/documents'))return {body:{source:'checkout',revision_id:null,tree:{files:[]},content:null}};
    if(url.endsWith('/documents/tree'))return {body:{docs:'docs',files:[{path:'README.md',kind:'other',editable:true,archived:false,bytes:10}],truncated:false,skipped:[]}};
    if(url.includes('/documents/content'))return {body:{content:'# Legacy read-only documentation\n\n![Local image](pic.png)' }};
  }}),host=hookHost();
  try{const html=await host.render(tree(el(InvocationPage,{project:e.project,invocation:INV,archive:false})));
    assert.match(html,/Legacy checkout/);assert.match(html,/Legacy read-only documentation/);
    assert.match(html,/projects\/legacy-checkout\/documents\/image/);
    assert.ok(e.requests.some(r=>r.url.includes('/projects/legacy-checkout/documents/tree')));
    assert.ok(e.requests.every(r=>r.method==='GET'));assert.doesNotMatch(html,/Edit document|Adopt|Export/);
  }finally{host.close();e.close();}
});
