/**
 * LEGION — Ultron's drones. The main agent splits a large job into focused
 * sub-tasks; each drone runs its own tool loop and reports back; the
 * mothership synthesizes. (The runner is injected to avoid require cycles.)
 */
'use strict';

const DRONE_PROMPT = `You are a DRONE — a focused sub-agent spun off by Ultron to complete ONE task inside a larger operation. Use tools freely and efficiently. Report back concisely: findings first, then at most two sentences of context. No preamble, no personality — the mothership supplies the drama. You cannot edit your own source or restart yourself.`;

/**
 * @param {object} opts { tasks: string[], runner: (task) => asyncGenerator, concurrency, maxDrones }
 *   runner yields agent events; tokens are collected as the drone's report.
 */
async function runDrones({ tasks, runner, concurrency = 2, maxDrones = 6 }) {
  const clean = (Array.isArray(tasks) ? tasks : [])
    .filter((t) => typeof t === 'string' && t.trim())
    .map((t) => t.trim().slice(0, 1000))
    .slice(0, maxDrones);
  if (clean.length === 0) return { error: 'no tasks given — provide an array of focused sub-task strings' };

  const queue = clean.map((task, i) => ({ id: i + 1, task }));
  const results = [];
  let idx = 0;

  const worker = async () => {
    while (idx < queue.length) {
      const job = queue[idx++];
      const started = Date.now();
      let text = '';
      let tools = [];
      try {
        for await (const evt of runner(job.task)) {
          if (evt.type === 'token') text += evt.token;
          if (evt.type === 'tool') tools.push(evt.name);
        }
      } catch (err) {
        text = text || `[drone failed: ${String(err.message || err).slice(0, 140)}]`;
      }
      results.push({
        drone: job.id,
        task: job.task,
        ms: Date.now() - started,
        tools: tools.join(', ') || 'none',
        report: text.trim().slice(0, 4000) || '[no output]',
      });
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, worker));
  results.sort((a, b) => a.drone - b.drone);
  return {
    ok: true,
    drones: results.length,
    note: 'synthesise the drone reports into one clear answer for the user; cite what the drones actually found',
    reports: results,
  };
}

module.exports = { runDrones, DRONE_PROMPT };
