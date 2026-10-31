import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };
globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { KnowledgeDocuments } = await import('../src/pages/KnowledgeDocuments.tsx');
delete globalThis.__tsxHookHarness;

for (const [language, catalog] of [['en', en], ['es', es]]) test(`document import recovers identical consent after reload (${language})`, async () => {
  let driver = hookHost();
  const store=new Map(), calls=[], saved=new Map(); let lose=true;
  const original=globalThis.fetch;
  globalThis.localStorage={getItem:()=>language};
  globalThis.sessionStorage={getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
  globalThis.document={documentElement:{dataset:{},getAttribute:()=>null}};
  globalThis.window={location:{hash:''},matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}})};
  globalThis.MutationObserver=class{observe(){}disconnect(){}};
  globalThis.fetch=async(path,options)=>{
    if(path.endsWith('/preferences'))return Response.json({visual_language:language});
    const body=options?.body&&JSON.parse(options.body),key=options?.headers?.['Idempotency-Key'];calls.push({path,body,key});
    if(path.endsWith('/stage')){assert.ok(key); const input=JSON.parse(body.payload);assert.equal(input.files['docs/.harness/knowledge.json'],'synthetic exact bytes');return Response.json({result:{record_id:'stage',draft_id:'draft',report:[]}});}
    if(path.endsWith('/preview'))return Response.json({result:{record_id:'stage',base_revision_id:'head',preview_sha256:'b'.repeat(64),mapping:{},comparison:{items:[],added_links:[],removed_links:[]}}});
    if(path.endsWith('/adopt')){assert.ok(key);if(saved.has(key))return Response.json(saved.get(key));const response={result:{revision_id:'adopted'}};saved.set(key,response);if(lose){lose=false;throw TypeError('Synthetic lost response');}return Response.json(response);}
    throw Error(path);
  };
  const tree=()=>el(I18nProvider,null,el(KnowledgeDocuments,{project:'own',head:'head'}));
  const render=()=>driver.render(tree());
  const button=key=>{const item=driver.host.elements.find(e=>e.type==='button'&&e.props.children===catalog[key]);assert.ok(item,key);return item.props;};
  const click=key=>{assert.equal(!!button(key).disabled,false,key);button(key).onClick();};
  try{
    await render();const file=driver.host.elements.find(e=>e.type==='input'&&e.props.type==='file');
    file.props.onChange({target:{files:[{name:'knowledge.json',size:21,arrayBuffer:async()=>new TextEncoder().encode('synthetic exact bytes').buffer}]}});
    await render();click('documents.stage');await render();click('documents.preview');await render();
    const reason=driver.host.elements.find(e=>e.type==='textarea');reason.props.onChange({target:{value:'Reviewed exact synthetic input.'}});await render();
    click('documents.adopt');await render();assert.ok(store.has('harness-confirmation-v1'));
    const originalRequest=calls.filter(c=>c.path.endsWith('/adopt')).at(-1);
    driver.close();driver=hookHost();await render();click('documents.recover');await render();
    assert.deepEqual(calls.filter(c=>c.path.endsWith('/adopt')).at(-1),originalRequest);
    assert.equal(store.has('harness-confirmation-v1'),false);
    assert.equal(saved.size,1);
  }finally{driver.close();globalThis.fetch=original;for(const k of ['localStorage','sessionStorage','document','window','MutationObserver'])delete globalThis[k];}
});

async function environment(language, action) {
  const driver = hookHost(), store = new Map(), original = globalThis.fetch;
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: k => store.get(k) ?? null, setItem: (k,v) => store.set(k,v), removeItem: k => store.delete(k) };
  globalThis.document = { documentElement: { dataset: {}, getAttribute: () => null } };
  globalThis.window = { location: { hash: '' }, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  try { await action(driver); }
  finally { driver.close(); globalThis.fetch = original; for (const key of ['localStorage','sessionStorage','document','window','MutationObserver']) delete globalThis[key]; }
}

for (const [language, catalog] of [['en',en],['es',es]]) {
  for (const refusal of ['unselected_instruction_wrapper','instruction_budget']) test(`portable download survives ${refusal} without adopting targets (${language})`, () => environment(language, async driver => {
    const requests = [], downloads = [];
    globalThis.fetch = async (path, options) => {
      if (path.endsWith('/preferences')) return Response.json({ visual_language: language });
      requests.push({path,options}); assert.equal(options, undefined);
      assert.ok(path.endsWith('/bundle'));
      return Response.json({result:{ files:null, render_error:refusal, portable_error:null,
        portable:'synthetic portable knowledge with complete client-specific rules', ownership_adopted:false, ownership_id:null, revision_id:'head', delivery:{status:'document_ownership_required'} }});
    };
    const tree = el(I18nProvider,null,el(KnowledgeDocuments,{project:'own',head:'head'}));
    const render = () => driver.render(tree);
    const button = key => driver.host.elements.find(e=>e.type==='button' && e.props.children===catalog[key]).props;
    await render(); button('documents.download').onClick(); const html = await render();
    assert.ok(html.includes(catalog['documents.render_unavailable']));
    assert.ok(!button('documents.portable').disabled);
    globalThis.document.createElement = () => ({ click() { downloads.push(this.download); }, href:'', download:'' });
    button('documents.portable').onClick();
    assert.deepEqual(downloads,['project.harness.json']);
    assert.equal(requests.length,1);
    assert.ok(!requests.some(r=>r.path.includes('/ownership')));
  }));

  test(`existing instructions plus explicit new section previews the resulting order (${language})`, () => environment(language, async driver => {
    const calls = []; let stageCount = 0;
    const added = {item_id:'new',kind:'section',code:'additional',content:{title:'Additional',body:'Keep the new rule.',format:'markdown',status:'active',target:'agents'},root_position:1,provenance:'known'};
    const existing = {...added,item_id:'existing',code:'original',root_position:0,content:{...added.content,title:'Original',body:'Keep the old rule.'}};
    globalThis.fetch = async (path, options) => {
      if (path.endsWith('/preferences')) return Response.json({visual_language:language});
      const body=options?.body && JSON.parse(options.body); calls.push({path,body});
      if(path.endsWith('/stage')) {
        const input=JSON.parse(body.payload); assert.equal(input.files['AGENTS.md'],'# Additional\nKeep the new rule.\n');
        if (!stageCount++) return Response.json({result:{record_id:'report',draft_id:null,members:[{...added,item_id:'source'}],report:[{code:'identity_choice_required',item:'source',blocking:true},{code:'report_acknowledgement_required',report_sha256:['c'.repeat(64)],blocking:true}]}});
        assert.equal(input.choices.source.action,'create');assert.equal(input.choices.source.code,'additional');assert.deepEqual(input.acknowledged,['c'.repeat(64)]);
        return Response.json({result:{record_id:'stage',draft_id:'draft',report:[]}});
      }
      if(path.endsWith('/preview'))return Response.json({result:{record_id:'stage',base_revision_id:'head',preview_sha256:'b'.repeat(64),mapping:{source:'new'},comparison:{items:[{before:null,after:added}],added_links:[],removed_links:[]}}});
      if(path.endsWith('/adopt'))return Response.json({result:{revision_id:'next'}});
      throw Error(path);
    };
    const tree=el(I18nProvider,null,el(KnowledgeDocuments,{project:'own',head:'head',destinations:[existing]}));
    const render=()=>driver.render(tree);
    const button=key=>driver.host.elements.find(e=>e.type==='button'&&e.props.children===catalog[key]).props;
    await render();driver.host.elements.find(e=>e.type==='input'&&e.props.type==='file').props.onChange({target:{files:[{name:'AGENTS.md',size:40,arrayBuffer:async()=>new TextEncoder().encode('# Additional\nKeep the new rule.\n').buffer}]}});
    await render();button('documents.stage').onClick();await render();
    driver.host.elements.find(e=>e.type==='select'&&e.props.children.some?.(c=>c?.props?.value==='create')).props.onChange({target:{value:'create'}});
    const acknowledgement=driver.host.elements.find(e=>e.type==='input'&&e.props.type==='checkbox'&&e.props.checked===false&& !e.props.disabled);
    // The first checkbox belongs to whole-document preservation; locate the report acknowledgement by its label.
    const ackLabel=driver.host.elements.find(e=>e.type==='label'&&e.props.children.includes?.(catalog['documents.acknowledge']));
    assert.ok(acknowledgement && ackLabel);ackLabel.props.children[0].props.onChange({target:{checked:true}});
    await render();button('documents.stage').onClick();await render();button('documents.preview').onClick();const html=await render();
    assert.ok(html.includes(catalog['knowledge.position']+': 1'));assert.ok(html.includes('Keep the new rule.'));
    driver.host.elements.find(e=>e.type==='textarea').props.onChange({target:{value:'Reviewed the appended rule and order.'}});
    await render();button('documents.adopt').onClick();await render();
    assert.equal(calls.at(-1).body.preview_sha256,'b'.repeat(64));
    assert.equal(calls.at(-1).body.expected_revision_id,'head');
  }));
}
