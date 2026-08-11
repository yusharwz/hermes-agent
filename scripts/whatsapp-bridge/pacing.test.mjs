/**
 * Tests for the WhatsApp bridge's outbound pacing and reconnect backoff.
 *
 * These exist because the timings they cover are the ones WhatsApp can see
 * from outside, and the failure they guard against is silent: the bridge keeps
 * working perfectly while the number it runs on gets restricted.
 *
 * Everything runs on an injected clock — no test sleeps in real time.
 */

import { strict as assert } from 'node:assert';

import { createSendPacer, createReconnectBackoff } from './pacing.js';

/** A clock that only moves when something sleeps on it. */
function virtualClock() {
  let t = 0;
  return {
    now: () => t,
    sleep: async (ms) => { t += ms; },
    advance: (ms) => { t += ms; },
    get time() { return t; },
  };
}

// -- jitter: replies do not leave on a fixed beat ---------------------
{
  const clock = virtualClock();
  const draws = [0, 0.5, 1];
  let i = 0;
  const { enqueueSend } = createSendPacer({
    jitterMinMs: 400,
    jitterMaxMs: 2500,
    now: clock.now,
    sleep: clock.sleep,
    random: () => draws[i++ % draws.length],
  });

  const waits = [];
  let last = 0;
  for (let n = 0; n < 3; n++) {
    await enqueueSend(async () => { waits.push(clock.time - last); last = clock.time; });
  }

  assert.deepStrictEqual(waits, [400, 1450, 2500], 'pause spans the configured window');
  assert.ok(new Set(waits).size > 1, 'consecutive replies do not share one delay');
  console.log('  ✓ reply jitter spans its window');
}

// -- jitter disabled by configuration ---------------------------------
{
  const clock = virtualClock();
  const { enqueueSend } = createSendPacer({
    jitterMinMs: 0, jitterMaxMs: 0, now: clock.now, sleep: clock.sleep,
  });
  await enqueueSend(async () => {});
  assert.strictEqual(clock.time, 0, 'zero jitter costs nothing');
  console.log('  ✓ jitter is opt-out');
}

// -- rate limit: a burst drains at the configured rate -----------------
{
  const clock = virtualClock();
  const { enqueueSend } = createSendPacer({
    maxSendsPerMinute: 20, now: clock.now, sleep: clock.sleep,
  });

  const sentAt = [];
  for (let n = 0; n < 25; n++) {
    await enqueueSend(async () => { sentAt.push(clock.time); });
  }

  assert.strictEqual(sentAt.length, 25, 'every send eventually goes out');
  assert.strictEqual(sentAt[19], 0, 'the first 20 are not delayed');
  assert.ok(sentAt[20] >= 60000, 'the 21st waits for the window to roll');

  // No 60-second window anywhere in the run holds more than the limit.
  for (let n = 0; n < sentAt.length; n++) {
    const inWindow = sentAt.filter((t) => t >= sentAt[n] && t - sentAt[n] < 60000).length;
    assert.ok(inWindow <= 20, `window at send ${n} holds ${inWindow}, limit is 20`);
  }
  console.log('  ✓ rate limit holds across every window');
}

// -- rate limit disabled by configuration ------------------------------
{
  const clock = virtualClock();
  const { enqueueSend } = createSendPacer({
    maxSendsPerMinute: 0, now: clock.now, sleep: clock.sleep,
  });
  for (let n = 0; n < 100; n++) await enqueueSend(async () => {});
  assert.strictEqual(clock.time, 0, 'zero limit costs nothing');
  console.log('  ✓ rate limit is opt-out');
}

// -- pacing runs inside the queue, not beside it -----------------------
{
  const clock = virtualClock();
  const { enqueueSend } = createSendPacer({
    jitterMinMs: 100, jitterMaxMs: 100, now: clock.now, sleep: clock.sleep,
  });

  let inFlight = 0, maxInFlight = 0;
  await Promise.all(Array.from({ length: 10 }, () => enqueueSend(async () => {
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    inFlight -= 1;
  })));

  assert.strictEqual(maxInFlight, 1, 'pacing never lets two sends overlap');
  console.log('  ✓ pacing serialises with the queue');
}

// -- a failing send does not stall the ones behind it -------------------
{
  const clock = virtualClock();
  const { enqueueSend } = createSendPacer({ now: clock.now, sleep: clock.sleep });
  const bad = enqueueSend(async () => { throw new Error('boom'); });
  const good = enqueueSend(async () => 'ok');
  await assert.rejects(() => bad, /boom/);
  assert.strictEqual(await good, 'ok', 'the next send still runs');
  console.log('  ✓ a rejection does not poison the queue');
}

// -- reconnect: backs off, stays bounded, scatters ----------------------
{
  const backoff = createReconnectBackoff({ minMs: 5000, maxMs: 300000, random: () => 1 });
  const delays = Array.from({ length: 12 }, () => backoff.next());

  assert.ok(delays[0] < delays[1] && delays[1] < delays[2], 'delays grow');
  assert.ok(Math.max(...delays) <= 300000, 'delays never exceed the ceiling');
  assert.ok(delays.at(-1) >= 150000, 'delays reach the ceiling and stay there');

  // The old behaviour: a flat 3s retry, forever. Ten failures cost 30s then.
  const tenNow = delays.slice(0, 10).reduce((a, b) => a + b, 0);
  assert.ok(tenNow > 10 * 3000, 'ten failures now cost far more than a flat 3s beat');
  console.log('  ✓ reconnect backs off and stays bounded');
}

// -- reconnect jitter scatters simultaneous restarts --------------------
{
  const draws = [0, 0.25, 0.5, 0.75, 0.99];
  const first = draws.map((r) => createReconnectBackoff({ minMs: 5000, random: () => r }).next());
  assert.strictEqual(new Set(first).size, draws.length,
    'bridges that dropped together do not come back together');
  assert.ok(Math.min(...first) >= 2500, 'jitter never collapses the delay to zero');
  console.log('  ✓ reconnect jitter scatters restarts');
}

// -- reconnect resets only on a connection that opened ------------------
{
  const backoff = createReconnectBackoff({ minMs: 5000, random: () => 1 });
  backoff.next(); backoff.next(); backoff.next();
  assert.strictEqual(backoff.attempts, 3);
  backoff.reset();
  assert.strictEqual(backoff.attempts, 0, 'an open connection clears the backoff');
  assert.strictEqual(backoff.next(), 5000, 'and the next delay is back at the floor');
  console.log('  ✓ backoff resets on a real connection');
}

console.log('\n✅ All pacing tests passed.');
