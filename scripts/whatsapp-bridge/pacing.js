/**
 * How fast the WhatsApp bridge is willing to look.
 *
 * Baileys is an unofficial client, and WhatsApp decides whether a number
 * keeps working partly on behaviour. Three timings are visible from the
 * outside, and all three used to be constants that no human could produce:
 *
 *   - replies left on a fixed sub-second beat after every inbound message,
 *   - no ceiling on how many could leave in a burst,
 *   - a dropped connection retried on a flat three-second metronome, for as
 *     long as the process lived, whether or not retrying could ever help.
 *
 * The queue lives here too rather than in bridge.js, because the pause and
 * the ordering are one decision: pacing that ran beside the queue instead of
 * inside it would let a burst slip past while the queue was busy. It is also
 * the reason this file exists at all — the send queue's own regression test
 * used to re-implement `enqueueSend` locally to avoid importing bridge.js,
 * so the tested copy and the shipped copy were free to drift apart.
 *
 * Every timing is injectable so tests drive them on a virtual clock instead
 * of sleeping in real time.
 */

/**
 * Serialises sends and paces them.
 *
 * @param {object}   [opts]
 * @param {number}   [opts.jitterMinMs]      floor of the pre-send pause
 * @param {number}   [opts.jitterMaxMs]      ceiling of the pre-send pause
 * @param {number}   [opts.maxSendsPerMinute] 0 disables the rate limit
 * @param {function} [opts.now]              clock source, for tests
 * @param {function} [opts.sleep]            delay source, for tests
 * @param {function} [opts.random]           randomness source, for tests
 * @param {function} [opts.onThrottle]       called with the hold in ms
 */
export function createSendPacer({
  jitterMinMs = 0,
  jitterMaxMs = 0,
  maxSendsPerMinute = 0,
  now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  random = Math.random,
  onThrottle = () => {},
} = {}) {
  const floor = Math.max(0, jitterMinMs);
  const ceiling = Math.max(floor, jitterMaxMs);
  const limit = Math.max(0, maxSendsPerMinute);

  // Timestamps of sends inside the trailing minute.
  let sendTimes = [];
  let queue = Promise.resolve();

  async function pace() {
    if (ceiling > 0) {
      // The +1 makes the ceiling reachable given Math.random() < 1; the clamp
      // keeps the window honest for any other source (a test's, or a future
      // seeded one) that can return exactly 1.
      const drawn = floor + Math.floor(random() * (ceiling - floor + 1));
      await sleep(Math.min(drawn, ceiling));
    }

    if (limit > 0) {
      const at = now();
      sendTimes = sendTimes.filter((t) => at - t < 60000);
      if (sendTimes.length >= limit) {
        // Wait exactly until the oldest send falls out of the window rather
        // than sleeping a fixed slice and re-checking, so a burst drains at
        // the rate the limit describes instead of in lumps.
        const waitMs = 60000 - (at - sendTimes[0]) + 1;
        onThrottle(waitMs);
        await sleep(waitMs);
        const after = now();
        sendTimes = sendTimes.filter((t) => after - t < 60000);
      }
      sendTimes.push(now());
    }
  }

  /**
   * Runs `fn` after every previously queued send has settled, and after this
   * send has waited its turn. Rejections do not poison the queue — a failed
   * send must not stop the next one.
   */
  function enqueueSend(fn) {
    const run = () => pace().then(fn, fn);
    const task = queue.then(run, run);
    queue = task.catch(() => {});
    return task;
  }

  return { enqueueSend };
}

/**
 * Reconnect delays that back off, stay bounded, and scatter.
 *
 * Full jitter over the window (half the base, plus up to half again) rather
 * than a fixed delay: several bridges restarted by the same event — a machine
 * waking, a gateway restart — would otherwise retry in lockstep forever.
 *
 * @param {object} [opts]
 * @param {number} [opts.minMs] first delay, and the floor after a reset
 * @param {number} [opts.maxMs] ceiling the doubling stops at
 * @param {function} [opts.random] randomness source, for tests
 */
export function createReconnectBackoff({
  minMs = 5000,
  maxMs = 300000,
  random = Math.random,
} = {}) {
  const floor = Math.max(1000, minMs);
  const ceiling = Math.max(floor, maxMs);
  let attempt = 0;

  return {
    next() {
      const base = Math.min(floor * Math.pow(2, attempt), ceiling);
      attempt += 1;
      return Math.floor(base / 2 + random() * (base / 2));
    },
    /**
     * Called when a connection actually opens, not when one is attempted: a
     * socket that opens and drops immediately — what a contested session
     * does — would otherwise retry at the floor forever.
     */
    reset() {
      attempt = 0;
    },
    get attempts() {
      return attempt;
    },
  };
}
