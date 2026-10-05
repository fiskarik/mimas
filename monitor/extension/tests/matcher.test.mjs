import test from 'node:test';
import assert from 'node:assert/strict';
import {hostMatchesDomain, observationsForTabs, transitions} from '../matcher.js';

test('exact host and DNS subdomain match without lookalike or unrelated URLs', () => {
  assert.equal(hostMatchesDomain('https://example.ai/interview', 'example.ai'), true);
  assert.equal(hostMatchesDomain('https://app.example.ai/', 'example.ai'), true);
  assert.equal(hostMatchesDomain('https://badexample.ai/', 'example.ai'), false);
  assert.equal(hostMatchesDomain('https://example.ai.evil.test/', 'example.ai'), false);
  assert.equal(hostMatchesDomain('http://example.ai/', 'example.ai'), false);
  assert.equal(hostMatchesDomain('chrome://extensions', 'example.ai'), false);
  assert.equal(hostMatchesDomain('https://example.ai/', 'ample.ai'), false);
});

test('background tab is distinct from active focused tab, and transitions clear old state', () => {
  const products = [{id: 'known', domains: ['example.ai']}];
  const tabs = [{url: 'https://example.ai/', active: false, windowId: 1},
    {url: 'https://unrelated.test/', active: true, windowId: 1}];
  const background = observationsForTabs(products, tabs, 1);
  assert.deepEqual([...background.values()], [{product_id: 'known', kind: 'background_tab'}]);
  const active = observationsForTabs(products, [{...tabs[0], active: true}], 1);
  assert.deepEqual(transitions([...background.keys()], active), [
    {product_id: 'known', kind: 'active_tab', state: 'detected'},
    {product_id: 'known', kind: 'background_tab', state: 'cleared'}
  ]);
  assert.equal(observationsForTabs(products, [{...tabs[0], active: true}], -1).values().next().value.kind,
    'background_tab');
});
