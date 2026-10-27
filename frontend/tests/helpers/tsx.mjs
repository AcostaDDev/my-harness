// Compile local UI modules for server rendering with the existing TypeScript dependency.
// No bundler, browser, network or application service is started by these tests.
import { registerHooks } from 'node:module';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const sourceRoot = new URL('../../src/', import.meta.url).href;
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (globalThis.__tsxHookHarness && context.parentURL?.startsWith(sourceRoot)) {
      if (specifier === 'react') return nextResolve(new URL('./react-hooks.mjs', import.meta.url).href, context);
      if (specifier === 'react/jsx-runtime') return nextResolve(new URL('./jsx-hooks.mjs', import.meta.url).href, context);
    }
    if (specifier.startsWith('.') && context.parentURL?.startsWith(sourceRoot)) {
      const target = new URL(specifier, context.parentURL);
      for (const extension of ['.ts', '.tsx']) {
        const candidate = new URL(target.href + extension);
        if (existsSync(candidate)) return nextResolve(candidate.href, context);
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith(sourceRoot) && /\.(?:tsx?|json)$/.test(url)) {
      const source = readFileSync(new URL(url), 'utf8');
      return { format: 'module', shortCircuit: true, source: url.endsWith('.json')
        ? `export default ${source};`
        : ts.transpileModule(source, { fileName: fileURLToPath(url), compilerOptions: {
          module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
        } }).outputText };
    }
    return nextLoad(url, context);
  },
});
