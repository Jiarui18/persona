// Run with: node --test tests/imessage.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const Module = require('node:module');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { transform, loadBindings } = require('next/dist/build/swc');

test('preserves messages, safe links, and chat across the call lifecycle', async () => {
  await loadBindings();
  const filename = resolve(__dirname, '../app/imessage.jsx');
  const { code } = await transform(readFileSync(filename, 'utf8'), {
    filename, jsc: { parser: { syntax: 'ecmascript', jsx: true }, transform: { react: { runtime: 'automatic' } } }, module: { type: 'commonjs' },
  });
  const component = new Module(filename, module);
  component.filename = filename;
  component.paths = module.paths;
  const konsta = await import('konsta/react');
  const originalRequire = component.require.bind(component);
  component.require = name => name === 'konsta/react' ? konsta : originalRequire(name);
  component._compile(code, filename);
  const props = { name: 'Test assistant', messages: [
    { id: '1', role: 'assistant', content: '<script>alert(1)</script> https://example.com' },
    { id: 'pending:2', role: 'user', content: 'My actual message' },
  ], seconds: 65, onSend() {}, onCall() {}, onHangup() {}, onMute() {}, onSpeaker() {} };
  const render = overrides => renderToStaticMarkup(React.createElement(component.exports.IMessageFrame, { ...props, ...overrides }));
  for (const callState of ['idle', 'connecting', 'active']) {
    const html = render({ callState });
    assert.match(html, /My actual message/);
    assert.match(html, /aria-label="Battery 67 percent"/);
    assert.match(html, /aria-label="Message options unavailable" disabled=""/);
    assert.doesNotMatch(html, /composer-menu|Battery 80/);
    assert.match(html, /aria-label="Message"/);
    assert.match(html, /&lt;script&gt;/);
    assert.match(html, /href="https:\/\/example.com"/);
    assert.match(html, /Sending…/);
    assert.doesNotMatch(html, /<script>|keyboard|Bobert|McLaren/);
    if (callState === 'connecting') assert.match(html, /Calling…/);
    if (callState === 'active') assert.match(html, /1:05/);
  }
  const incoming = render({ callState: 'idle', incoming: true });
  assert.match(incoming, /aria-label="Answer call"/);
  assert.match(incoming, /aria-label="Dismiss call invitation"/);
  assert.doesNotMatch(render({ callState: 'active', incoming: true }), /aria-label="Answer call"/);
});
