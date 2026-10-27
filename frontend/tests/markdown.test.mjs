import { test } from 'node:test';
import assert from 'node:assert/strict';
import { blockBody, decisionHref, classify, renderMarkdown, resolvePath, splitBlocks } from '../src/markdown.ts';

const ctx = { project: 'mi-web', path: 'docs/STATE.md' };
const render = source => renderMarkdown(source, ctx).html;

// All produced HTML fits in this table: tags, attributes and targets. Anything else is a failure.
const TAGS = new Set(['p', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'em', 'strong', 's', 'code', 'pre',
  'blockquote', 'hr', 'br', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'section', 'figure']);
const ATTRS = new Set(['href', 'src', 'alt', 'title', 'class', 'id', 'target', 'rel', 'loading', 'start', 'style',
  'data-internal', 'data-block', 'data-mermaid', 'data-blocked', 'data-alt']);
const DESTINATION = /^(\/projects\/mi-web\/docs\/|\/api\/managed\/projects\/mi-web\/documents\/image\?path=|#doc-|https?:\/\/)/;

function assertSafe(html) {
  for (const [, closing, tag, attrs] of html.matchAll(/<(\/?)([a-zA-Z][\w-]*)([^>]*)>/g)) {
    assert.ok(TAGS.has(tag.toLowerCase()), `etiqueta no admitida <${closing}${tag}> en ${html}`);
    for (const [, name, value] of attrs.matchAll(/([^\s=]+)(?:="([^"]*)")?/g)) {
      assert.ok(ATTRS.has(name.toLowerCase()), `atributo no admitido ${name} en ${html}`);
      if (name === 'href') assert.match(value, DESTINATION, `destino no admitido ${value}`);
      if (name === 'src') assert.match(value, /^\/api\/managed\/projects\/mi-web\/documents\/image\?path=/, `imagen no admitida ${value}`);
      if (name === 'style') assert.match(value, /^text-align:(left|right|center)$/);
      assert.ok(!/[<>]/.test(value ?? ''), `valor sin escapar ${value}`);
    }
  }
  assert.ok(!/<script|javascript:|vbscript:|data:/i.test(html.replace(/&[a-z#0-9]+;/gi, '')
    .replace(/<pre[^>]*>[\s\S]*?<\/pre>|<code>[\s\S]*?<\/code>/g, '').replace(/>[^<]*</g, '><')), `contenido ejecutable en ${html}`);
}

const HOSTILE = {
  script: '<script>alert(1)</script>',
  inlineScript: 'texto <script>alert(1)</script> y más',
  imgOnerror: '<img src=x onerror=alert(1)>',
  svgOnload: '<svg onload="alert(1)"><circle /></svg>',
  svgForeign: '<svg><foreignObject><iframe src="javascript:alert(1)"></iframe></foreignObject></svg>',
  iframe: '<iframe src="https://evil.example"></iframe>',
  javascriptLink: '[clic](javascript:alert(1))',
  mixedCase: '[clic](JaVaScRiPt:alert(1))',
  entity: '[clic](&#106;avascript:alert(1))',
  tabbed: '[clic](java\tscript:alert(1))',
  autolink: '<javascript:alert(1)>',
  vbscript: '[clic](vbscript:msgbox(1))',
  dataLink: '[clic](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
  dataImage: '![x](data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+)',
  fileLink: '[clic](file:///etc/passwd)',
  protocolRelative: '[clic](//evil.example/x.md)',
  externalImage: '![seguimiento](https://evil.example/pixel.png)',
  titleBreakout: '[clic](otro.md "a\\" onmouseover=\\"alert(1)")',
  altBreakout: '![a" onerror="alert(1)](img/a.png)',
  referenceStyle: '[clic][x]\n\n[x]: javascript:alert(1)',
  headingInjection: '# "><img src=x onerror=alert(1)>',
  onAttributeText: 'Texto con onclick=alert(1) y on*= sueltos',
  htmlComment: '<!-- harness-local:managed-evil:start -->\n<script>x</script>',
  mermaidHtml: '```mermaid\ngraph TD\nA["<img src=x onerror=alert(1)>"] --> B["<script>alert(1)</script>"]\nclick A call alert(1)\n```',
  mermaidSvg: '```mermaid\n%%{init: {"securityLevel": "loose"}}%%\ngraph TD\nA[<svg onload=alert(1)>]\n```',
  fenceInfo: '```"><script>alert(1)</script>\ncódigo\n```',
  tableStyle: '| a | b |\n|:--|--:|\n| <b onclick=x>1</b> | 2 |',
};

test('the safety check itself rejects executable HTML', () => {
  for (const html of ['<script>x</script>', '<a href="javascript:x">a</a>', '<p onclick="x">a</p>', '<img src="https://e/x.png">',
    '<iframe src="/projects/mi-web/docs/a.md"></iframe>', '<a href="data:text/html,x">a</a>']) {
    assert.throws(() => assertSafe(html), undefined, html);
  }
});

for (const [name, source] of Object.entries(HOSTILE)) {
  test(`hostile markdown is inert: ${name}`, () => assertSafe(render(source)));
}

test('raw HTML is shown as text, never interpreted', () => {
  assert.match(render('<script>alert(1)</script>'), /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(render('<img src=x onerror=alert(1)>'), /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test('blocked links keep their text but never navigate', () => {
  const html = render('[clic](javascript:alert(1)) [otro](../../../etc/passwd.md) [código](../src/app.py)');
  assert.ok(!/href=/.test(html.replace(/href="\/projects[^"]*"/g, '')), html);
  assert.match(html, /clic/);
  // Codes only: the viewer names the reason in the visual language (no own text inside the HTML).
  assert.match(html, /<a class="doc-unlinked" data-blocked="outside">otro<\/a>/);
  assert.match(html, /<a class="doc-unlinked" data-blocked="not_markdown">código<\/a>/);
});

test('relative Markdown links open in the viewer and keep their anchor', () => {
  const html = render('[a](../README.md#Primeros-pasos) [b](DECISIONS.md#d001-usar-git) [c](/docs/ROADMAP.md) [d](flows/) [e](#Base-Acumulada)');
  assert.match(html, /href="\/projects\/mi-web\/docs\/README.md#doc-primeros-pasos" data-internal="true"/);
  assert.match(html, /href="\/projects\/mi-web\/docs\/docs\/DECISIONS.md#doc-d001-usar-git" data-internal="true"/);
  assert.match(html, /href="\/projects\/mi-web\/docs\/docs\/ROADMAP.md" data-internal="true"/);
  assert.match(html, /href="\/projects\/mi-web\/docs\/docs\/flows\/README.md" data-internal="true"/);
  assert.match(html, /href="#doc-base-acumulada"/);
});

test('external links open apart without opener or referrer', () => {
  const html = render('[web](https://example.org/a?b=1) <https://example.org>');
  assert.equal((html.match(/rel="noopener noreferrer nofollow"/g) ?? []).length, 2);
  assert.match(html, /href="https:\/\/example.org\/a\?b=1" target="_blank"/);
});

test('images come only from the checkout through the session API', () => {
  const html = render('![diagrama](img/flujo.png "Flujo") ![fuera](https://cdn.example/x.png) ![texto](notas.txt)');
  assert.match(html, /<img src="\/api\/managed\/projects\/mi-web\/documents\/image\?path=docs%2Fimg%2Fflujo.png" alt="diagrama" title="Flujo" loading="lazy">/);
  assert.match(html, /<span class="doc-image-blocked" data-blocked="external_image" data-alt="fuera"><\/span>/);
  assert.match(html, /<span class="doc-image-blocked" data-blocked="image_format" data-alt="texto"><\/span>/);
  assert.equal((html.match(/<img/g) ?? []).length, 1);
});

test('mermaid fences only keep escaped source for the isolated renderer', () => {
  const { html, mermaid } = renderMarkdown(HOSTILE.mermaidHtml, ctx);
  assert.equal(mermaid.length, 1);
  assert.match(mermaid[0], /^graph TD/);
  assert.match(html, /<figure class="doc-mermaid" data-mermaid="0"><pre class="doc-mermaid-source">graph TD\nA\[&quot;&lt;img src=x onerror=alert\(1\)&gt;&quot;\]/);
  assert.ok(!/<img/.test(html));
});

test('headings get unique, prefixed ids that cannot clash with the app', () => {
  const html = render('# Base acumulada\n\n## Base acumulada\n\n# main');
  assert.match(html, /<h1 id="doc-base-acumulada">/);
  assert.match(html, /<h2 id="doc-base-acumulada-1">/);
  assert.match(html, /<h1 id="doc-main">/);
});

const STATE = '# Estado\n\n<!-- harness-local:managed-state:start -->\n**Fase:** P001\n<!-- harness-local:managed-state:end -->\n\n## Notas\r\n\r\nLibre.\n';

test('managed blocks split exactly, render apart and hide their markers', () => {
  const { segments, error } = splitBlocks(STATE);
  assert.equal(error, undefined);
  assert.deepEqual(segments.map(s => s.kind), ['prose', 'block', 'prose']);
  assert.equal(segments.map(s => s.text).join(''), STATE);
  assert.equal(blockBody(segments[1]), '**Fase:** P001\n');
  const html = render(STATE);
  assert.match(html, /<section class="doc-managed" data-block="state"><p class="doc-managed-label"><\/p>/);
  assert.ok(!html.includes('harness-local:managed'), html);
});

test('malformed or unknown markers are reported and the text stays prose', () => {
  for (const text of [
    '<!-- harness-local:managed-state:start -->\nsin cierre\n',
    'texto <!-- harness-local:managed-state:start -->\nx\n<!-- harness-local:managed-state:end -->\n',
    '<!-- harness-local:managed-evil:start -->\nx\n<!-- harness-local:managed-evil:end -->\n',
  ]) {
    const { segments, error } = splitBlocks(text);
    assert.ok(['incomplete', 'own_lines', 'unknown', 'overlap'].includes(error?.code), text);
    assert.deepEqual(segments, [{ kind: 'prose', text }]);
  }
});

test('paths resolve inside the checkout only', () => {
  assert.equal(resolvePath('docs/STATE.md', '../README.md'), 'README.md');
  assert.equal(resolvePath('docs/STATE.md', './flows/./tareas.md'), 'docs/flows/tareas.md');
  assert.equal(resolvePath('README.md', '../x.md'), undefined);
  assert.equal(resolvePath('docs/a/b.md', '/docs/c.md'), 'docs/c.md');
  assert.deepEqual(classify('%E0%A4%A.md', ctx), { kind: 'blocked', reason: 'encoding' });
  assert.equal(classify('mailto:a@b.c', ctx).kind, 'blocked');
});

// The index link and the rendered heading must match, accents and Markdown included.
test('decision index links to the heading inside the single register', () => {
  const title = 'Persistencia con **SQLite** y réplica';
  const target = decisionHref('mi web', 'manual', 'D093', title);
  assert.equal(target, '/projects/mi%20web/docs/manual/DECISIONS.md#doc-d093-persistencia-con-sqlite-y-replica');
  const { html } = renderMarkdown(`## D093 — ${title}\n\nEstado: aceptada.`, { project: 'mi web', path: 'manual/DECISIONS.md' });
  assert.ok(html.includes(`id="${target.split('#')[1]}"`));
});
