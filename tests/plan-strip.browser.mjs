// Run with PLAYWRIGHT_MODULE pointing to a Playwright installation if it is not on NODE_PATH.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = await readFile(new URL('../src/web/app.js', import.meta.url), 'utf8');
const helper = source.slice(source.indexOf('function h('), source.indexOf('const ICONS ='));
const component = source.slice(source.indexOf('function planStrip('), source.indexOf('// Sub-agents of a chat:'));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.setContent('<body></body>');
  const result = await page.evaluate(({ helper, component }) => {
    const tr = (s) => s;
    const isRunning = (s) => ['PLANNING', 'EXECUTING', 'OBSERVING', 'WAITING_APPROVAL'].includes(s);
    const icon = () => document.createElement('i');
    const create = new Function('tr', 'isRunning', 'icon', `${helper}\n${component}\nreturn planStrip;`)(tr, isRunning, icon);
    const items = [{ title: 'Old task', status: 'in_progress' }];
    const plan = create(items);
    document.body.append(plan.el);
    const snapshot = () => ({ hidden: plan.el.hidden, spinners: plan.el.querySelectorAll('.spinner').length });
    plan.setStatus('PLANNING');
    const running = snapshot();
    plan.set([
      { title: 'Editing complete', status: 'done' },
      { title: 'Verification started', status: 'in_progress' },
    ]);
    assertTransition();
    function assertTransition() {
      if (!plan.el.textContent.includes('Verification started')) throw new Error('Plan did not render the next phase immediately');
      if (plan.el.querySelectorAll('.spinner').length !== 1) throw new Error('Plan must show exactly one active phase');
    }
    plan.setStatus('FAILED');
    const failed = snapshot();
    plan.setStatus('PLANNING');
    const nextRequest = snapshot();
    plan.set([{ title: 'New task', status: 'in_progress' }]);
    const newPlan = snapshot();
    plan.setStatus('PAUSED');
    const paused = snapshot();
    plan.setStatus('PLANNING');
    const resumed = snapshot();
    plan.setStatus('SUCCEEDED');
    const finished = snapshot();
    const historical = create(items);
    historical.setStatus('SUCCEEDED');
    const oldChatHidden = historical.el.hidden;
    return { running, failed, nextRequest, newPlan, paused, resumed, finished, oldChatHidden };
  }, { helper, component });
  assert.deepEqual(result.running, { hidden: false, spinners: 1 });
  assert.deepEqual(result.failed, { hidden: true, spinners: 0 });
  assert.deepEqual(result.nextRequest, { hidden: true, spinners: 0 });
  assert.deepEqual(result.newPlan, { hidden: false, spinners: 1 });
  assert.deepEqual(result.paused, { hidden: false, spinners: 0 });
  assert.deepEqual(result.resumed, { hidden: false, spinners: 1 });
  assert.deepEqual(result.finished, { hidden: true, spinners: 0 });
  assert.equal(result.oldChatHidden, true);
  console.log('Plan browser regression checks passed');
} finally {
  await browser.close();
}
