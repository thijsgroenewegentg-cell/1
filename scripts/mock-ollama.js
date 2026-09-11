#!/usr/bin/env node
/**
 * mock-ollama — a scripted stand-in for a real Ollama server, for demos and
 * UI development on machines without a GPU. Implements /api/tags, /api/pull,
 * /api/embed and /api/chat (streaming + one-shot). Responses are canned.
 *
 * Usage: node scripts/mock-ollama.js [port]     (default 11434)
 */
import http from 'node:http';

const PORT = Number(process.argv[2] ?? process.env.PORT ?? 11434);

function reply(messages) {
  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  const text = String(lastUser?.content ?? '').toLowerCase();
  const hasToolResult = messages.some((m) => m.role === 'tool');

  if (hasToolResult) {
    const toolMsg = [...messages].reverse().find((m) => m.role === 'tool');
    if (String(toolMsg.content).includes('remembered')) {
      return { content: 'Done — I have stored that in my knowledge vault. Ask me about it any time.' };
    }
    if (String(toolMsg.content).includes('goal')) {
      return { content: 'Goal created. I will keep an eye on the deadline and remind you when it approaches.' };
    }
    return { content: 'Tool work complete. Anything else?' };
  }

  if (/\bremember\b/.test(text)) {
    const title = text.replace(/^(please\s+)?remember\s*(that|:)?\s*/i, '').slice(0, 60) || 'note';
    return {
      tool_calls: [
        {
          function: {
            name: 'memory_remember',
            arguments: { title, body: String(lastUser.content), kind: 'note', tags: ['mock'] },
          },
        },
      ],
    };
  }

  if (/\b(goal|okr|deadline)\b/.test(text)) {
    return {
      tool_calls: [
        {
          function: {
            name: 'goal_create',
            arguments: {
              title: String(lastUser.content).slice(0, 80),
              why: 'Created from chat (mock brain)',
              deadline: new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10),
            },
          },
        },
      ],
    };
  }

  if (/what time|the time|today's date|\bdate\b/.test(text)) {
    return { content: `It is ${new Date().toLocaleString()} on this machine.` };
  }

  if (/help|what can you do/.test(text)) {
    return {
      content:
        'I am JARVIS running on a scripted mock brain right now (scripts/mock-ollama.js). ' +
        'Point me at a real Ollama server for actual intelligence. Meanwhile I can still demo: ' +
        '"remember that …" (knowledge vault), "create a goal …" (goal tracker), time queries, ' +
        'streaming tokens, the memory & goals tabs, authority gating and the live event feed.',
    };
  }

  return {
    content:
      `[mock brain] You said: "${String(lastUser.content).slice(0, 120)}". ` +
      'This demo server only knows a few scripted tricks — try "remember that I love espresso", ' +
      '"create a goal to ship v1 by Friday", "what time is it?", or "help". ' +
      'Connect a real Ollama instance for full intelligence.',
  };
}

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', async () => {
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};

    if (req.method === 'GET' && req.url === '/api/tags') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ models: [{ name: 'mock-llm', size: 42 }] }));
      return;
    }
    if (req.method === 'POST' && req.url === '/api/pull') {
      res.writeHead(200, { 'content-type': 'application/x-ndjson' });
      res.end(JSON.stringify({ status: 'success' }) + '\n');
      return;
    }
    if (req.method === 'POST' && req.url === '/api/embed') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ embeddings: [[0.1, 0.2, 0.3]] }));
      return;
    }
    if (req.method === 'POST' && req.url === '/api/chat') {
      const next = reply(body.messages ?? []);
      if (body.stream) {
        res.writeHead(200, { 'content-type': 'application/x-ndjson' });
        const words = (next.content ?? '').split(/(?<=\s)/);
        for (const w of words) {
          res.write(JSON.stringify({ message: { role: 'assistant', content: w }, done: false }) + '\n');
          await new Promise((r) => setTimeout(r, 12)); // visible streaming
        }
        const last = { message: { role: 'assistant', content: '' }, done: true };
        if (next.tool_calls) last.message.tool_calls = next.tool_calls;
        res.end(JSON.stringify(last) + '\n');
        return;
      }
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ message: { role: 'assistant', content: next.content ?? '', tool_calls: next.tool_calls }, done: true }));
      return;
    }
    res.writeHead(404);
    res.end('not found');
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`mock-ollama (scripted demo brain) listening on http://localhost:${PORT}`);
  console.log('WARNING: responses are canned. Use a real Ollama server for production.');
});
