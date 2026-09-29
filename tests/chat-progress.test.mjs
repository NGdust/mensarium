import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/web/app.js', import.meta.url), 'utf8');
const start = source.indexOf('  // The answer the model is writing for the llm.request');
const handler = source.indexOf('  function handle({ event, seq, payload: p, created_at: createdAt }, live) {', start);
const end = source.indexOf('  const openedAt = Date.now();', handler);
assert.ok(start >= 0 && handler > start && end > handler, 'Chat event handler must exist');

function chat() {
  const messages = [];
  const calls = [];
  let items = [];
  const context = vm.createContext({
    finishWork: () => calls.push('finish'),
    agentMsg: (body, live) => {
      calls.push('message');
      const node = { live, children: [].concat(body), removed: false };
      node.replaceChildren = (...children) => { node.live = false; node.children = children; };
      node.remove = () => { node.removed = true; };
      messages.push(node);
      return node;
    },
    h: (tag, attrs, ...children) => ({ tag, ...attrs, children }),
    orb: () => 'orb',
    markdown: text => text,
    stamp: () => calls.push('stamp'),
    say: () => {},
    tr: text => text,
    statusOf: status => [status],
    reasonText: text => text,
    note: () => {},
    setStatus: () => {},
    isRunning: status => !['SUCCEEDED', 'FAILED', 'PAUSED', 'CANCELED'].includes(status),
    plan: { set: value => { items = value; } },
    usage: { later: () => {} },
    stick: false,
    past: false,
    work: null,
  });
  vm.runInContext(source.slice(start, end), context);
  const event = (name, payload, seq = null, live = true) => context.handle({ event: name, seq, payload, created_at: '2026-09-27T12:00:00Z' }, live);
  const shown = () => messages.filter(m => !m.removed);
  return { messages, calls, event, shown, items: () => items };
}

for (const live of [false, true]) {
  const { messages, calls, event, items } = chat();
  event('llm.response', { text: 'Inspecting the code', tool_call: { name: 'files.read' } }, null, live);
  event('llm.response', { text: 'Testing the fix', tool_call: { name: 'shell.bash' } }, null, live);
  assert.deepEqual(messages.map(m => m.children[0].html), ['Inspecting the code', 'Testing the fix']);
  assert.deepEqual(calls, ['finish', 'message', 'stamp', 'finish', 'message', 'stamp']);
  assert.ok(messages.every(m => m.children[0].class === 'prose'), 'Progress must render as messages');
  event('llm.response', { text: 'Final answer', tool_call: null }, null, live);
  assert.equal(messages.length, 2, 'Final responses must not be duplicated as progress');
  const next = [{ title: 'Editing', status: 'done' }, { title: 'Testing', status: 'in_progress' }];
  event('task.plan', { items: next }, null, live);
  assert.equal(items(), next, 'Plan transitions must render synchronously');
}

{
  const { messages, event, shown } = chat();
  event('llm.request', { step: 1 }, 10);
  event('llm.delta', { request: 10, offset: 0, text: '   ' });
  assert.equal(messages.length, 0, 'Whitespace alone must not open a message');
  event('llm.delta', { request: 10, offset: 3, text: 'Hel' });
  event('llm.delta', { request: 10, offset: 0, text: '   Hello' });
  event('llm.delta', { request: 10, offset: 8, text: ' world' });
  event('llm.delta', { request: 9, offset: 0, text: 'stale answer' });
  event('llm.delta', { request: 10, offset: 40, text: 'after a gap' });
  assert.equal(messages.length, 1);
  assert.equal(messages[0].children[0].innerHTML, '   Hello world', 'Overlapping, stale and gapped chunks must be skipped');
  assert.ok(messages[0].live, 'A draft shows the live orb');
  event('llm.response', { text: 'Hello world, reading files', tool_call: { name: 'files.read' } }, 11);
  assert.equal(messages.length, 1, 'The stored response must settle the draft, not add a message');
  assert.equal(messages[0].children[1].children[0].html, 'Hello world, reading files');
  assert.ok(!messages[0].live);
  event('llm.delta', { request: 10, offset: 14, text: ' late' });
  assert.equal(messages.length, 1, 'Chunks after the response must be ignored');

  event('llm.request', { step: 2 }, 12);
  event('llm.delta', { request: 12, offset: 0, text: 'Done: ' });
  event('llm.response', { text: 'Done: all good', tool_call: null }, 13);
  event('task.status', { status: 'SUCCEEDED' }, 14);
  event('task.final', { text: 'Done: all good' }, 15);
  assert.equal(shown().length, 2, 'A final answer must settle its draft');
  assert.equal(messages[1].children[1].children[0][0].html, 'Done: all good');

  event('llm.request', { step: 3 }, 16);
  event('llm.delta', { request: 16, offset: 0, text: 'Let me check' });
  event('llm.response', { text: '', tool_call: { name: 'files.read' } }, 17);
  assert.equal(shown().length, 2, 'A draft of a bare tool call must be removed');

  event('llm.request', { step: 4 }, 18);
  event('llm.delta', { request: 18, offset: 0, text: 'Half an answ' });
  event('task.status', { status: 'PAUSED' }, 19);
  assert.equal(shown().length, 2, 'An interrupted draft must be removed');
}
console.log('Chat progress, plan and streaming draft checks passed');
