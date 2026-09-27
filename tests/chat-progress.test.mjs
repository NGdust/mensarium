import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/web/app.js', import.meta.url), 'utf8');
const start = source.indexOf('  function handle({ event, payload: p, created_at: createdAt }, live) {');
const end = source.indexOf('  const openedAt = Date.now();', start);
assert.ok(start >= 0 && end > start, 'Chat event handler must exist');

for (const live of [false, true]) {
  const messages = [];
  const calls = [];
  let items = [];
  const context = vm.createContext({
    finishWork: () => calls.push('finish'),
    agentMsg: node => { calls.push('message'); messages.push(node); },
    h: (tag, attrs) => ({ tag, ...attrs }),
    markdown: text => text,
    stamp: () => calls.push('stamp'),
    plan: { set: value => { items = value; } },
  });
  vm.runInContext(source.slice(start, end), context);
  const event = (name, payload) => context.handle({ event: name, payload, created_at: '2026-09-27T12:00:00Z' }, live);
  event('llm.response', { text: 'Inspecting the code', tool_call: { name: 'files.read' } });
  event('llm.response', { text: 'Testing the fix', tool_call: { name: 'shell.bash' } });
  assert.deepEqual(messages.map(m => m.html), ['Inspecting the code', 'Testing the fix']);
  assert.deepEqual(calls, ['finish', 'message', 'stamp', 'finish', 'message', 'stamp']);
  assert.ok(messages.every(m => m.class === 'prose'), 'Progress must render as messages');
  event('llm.response', { text: 'Final answer', tool_call: null });
  assert.equal(messages.length, 2, 'Final responses must not be duplicated as progress');
  const next = [{ title: 'Editing', status: 'done' }, { title: 'Testing', status: 'in_progress' }];
  event('task.plan', { items: next });
  assert.equal(items, next, 'Plan transitions must render synchronously');
}
console.log('Chat progress and plan event checks passed for live events and history replay');
