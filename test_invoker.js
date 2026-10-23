const {test} = require('node:test');
const assert = require('node:assert/strict');
const invoker = require('./static/workspace.js');
const at = iso => invoker.state(Date.parse(iso));

test('uses the daylight and standard Eastern schedules regardless of local timezone', () => {
  assert.equal(at('2026-10-23T13:59:30Z').nextIn, 30); // 10am EDT
  assert.equal(at('2026-12-23T12:59:30Z').nextIn, 30); // 8am EST
  assert.equal(at('2026-10-23T12:00:00Z').nextIn, 7200); // no 8am EDT visit
});

test('starts at arrival, ends after exactly 15 minutes, and retains next countdown while live', () => {
  assert.equal(at('2026-10-23T13:59:59Z').remaining, 0);
  assert.deepEqual(at('2026-10-23T14:00:00Z'), {
    remaining: 900, nextIn: 14400, nextAt: Date.parse('2026-10-23T18:00:00Z')
  });
  assert.equal(at('2026-10-23T14:14:59Z').remaining, 1);
  assert.equal(at('2026-10-23T14:15:00Z').remaining, 0);
  assert.equal(at('2026-10-23T14:00:00.500Z').remaining, 900);
});

test('rolls over midnight and the year', () => {
  assert.equal(at('2027-01-01T04:59:59Z').nextIn, 1);
  assert.equal(at('2027-01-01T05:00:00Z').remaining, 900);
});

test('handles skipped and repeated Eastern hours at daylight saving transitions', () => {
  assert.equal(at('2026-03-08T06:59:59Z').nextIn, 3601); // 2am does not exist
  assert.equal(at('2026-03-08T08:00:00Z').remaining, 900); // 4am EDT
  assert.equal(at('2026-11-01T05:59:59Z').nextIn, 3601); // 1am repeats
  assert.equal(at('2026-11-01T07:00:00Z').remaining, 900); // 2am EST
  assert.equal(at('2026-11-01T09:15:00Z').nextIn, 13500); // next at 8am EST
});

test('formats stable countdowns with seconds', () => {
  assert.equal(invoker.duration(5025), '01:23:45');
  assert.equal(invoker.duration(754, true), '12:34');
  assert.equal(invoker.duration(0, true), '00:00');
});

test('shows arrival times in Pacific time with the correct seasonal abbreviation', () => {
  assert.equal(invoker.arrival(Date.parse('2026-10-24T00:00:00Z')), '5:00 PM PDT');
  assert.equal(invoker.arrival(Date.parse('2026-12-24T01:00:00Z')), '5:00 PM PST');
});
