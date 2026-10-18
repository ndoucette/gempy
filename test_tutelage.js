const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

// Load the production UI module; no browser is needed to resolve bonus states.
const context = vm.createContext({
  renderDetail() {}, showDetails() {}, renderCharacters() {}, renderSessions() {},
  refresh() {}, setTab() {}, document: {querySelectorAll: () => []},
  $: () => ({addEventListener() {}}),
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'static/profiles.js'), 'utf8'), context);
const state = vm.runInContext('characterProfiles.tutelageState', context);

test('Tutelage waits for every Lumnis phase and a newly reset cycle', () => {
  for (const lumnis_stage of [2, 3, 4, 5, 'ready']) {
    for (const fashlonae_state of ['inactive', 'expended']) {
      assert.equal(state({lumnis_stage, fashlonae_state}), 'waiting');
    }
  }
});

test('confirmed active, unavailable, and unknown benefits are preserved', () => {
  for (const fashlonae_state of ['active', 'unavailable', 'unknown']) {
    assert.equal(state({lumnis_stage: 3, fashlonae_state}), fashlonae_state);
  }
  assert.equal(state({lumnis_stage: 3}), 'unknown');
});

test('exhausted or missing Lumnis does not invent a weekly reset', () => {
  for (const lumnis_stage of ['expired', 'unknown', 'unavailable', undefined, null]) {
    assert.equal(state({lumnis_stage, fashlonae_state: 'expended'}), 'expended');
    assert.equal(state({lumnis_stage, fashlonae_state: 'inactive'}), 'inactive');
  }
});

test('older reporter states receive the same Lumnis correction', () => {
  for (const fashlonae_raw of [0, 1]) {
    assert.equal(state({lumnis_stage: 3, fashlonae_state: 'eligible',
      fashlonae_source: 'native_dialog', fashlonae_raw}), 'waiting');
  }
  assert.equal(state({lumnis_stage: 3, fashlonae_state: 'eligible',
    fashlonae_source: 'native_dialog', fashlonae_raw: 2}), 'active');
});

test('display correction does not modify the reported observation', () => {
  const bonuses = Object.freeze({lumnis_stage: 3, fashlonae_state: 'expended'});
  assert.equal(state(bonuses), 'waiting');
  assert.equal(bonuses.fashlonae_state, 'expended');
});
