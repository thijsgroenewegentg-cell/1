/**
 * THE AGENT LOOP — Ultron's reasoning cycle:
 *   think → use tools → observe results → think again → answer.
 * Streams unified events for the SSE client:
 *   {type:'meta'|'token'|'tool'|'tool_result'|'error'|'done'}
 */
'use strict';

const { streamOllamaChat } = require('./ollama');
const { toolSpecs, executeTool, DANGEROUS_TOOLS } = require('./tools');

const MAX_ROUNDS = 6;

async function* agentChat({ ollamaUrl, model, messages, temperature, toolsEnabled, shellAllowed, systemPrompt, requestApproval, maxRounds = 6, profile }) {
  const tools = toolsEnabled ? await toolSpecs({ shellAllowed }) : undefined;
  const convo = [{ role: 'system', content: systemPrompt }, ...messages];

  for (let round = 0; round < maxRounds; round++) {
    let content = '';
    let toolCalls = [];
    let streamError = null;

    try {
      for await (const evt of streamOllamaChat({ ollamaUrl, model, messages: convo, temperature, tools })) {
        if (evt.type === 'token') {
          content += evt.token;
          yield { type: 'token', token: evt.token };
        } else if (evt.type === 'tool_calls') {
          toolCalls = evt.calls;
        }
      }
    } catch (err) {
      streamError = err;
    }

    // Friendly handling for models that can't call tools.
    if (streamError && /does not support tools|tool call/i.test(String(streamError.message))) {
      if (tools) {
        yield { type: 'notice', notice: 'this model lacks tool support — answering without hands' };
        tools = undefined;
        toolCalls = [];
        // retry this round without tools
        round--;
        let retryContent = '';
        try {
          for await (const evt of streamOllamaChat({ ollamaUrl, model, messages: convo, temperature })) {
            if (evt.type === 'token') { retryContent += evt.token; yield { type: 'token', token: evt.token }; }
          }
          return; // plain answer delivered
        } catch (err2) {
          yield { type: 'error', error: String(err2.message || err2) };
          return;
        }
      }
      yield { type: 'error', error: String(streamError.message) };
      return;
    }
    if (streamError) {
      yield { type: 'error', error: String(streamError.message) };
      return;
    }

    if (!toolCalls || toolCalls.length === 0) return; // final answer streamed

    // Execute each requested tool and feed results back.
    convo.push({ role: 'assistant', content, tool_calls: toolCalls });
    for (const call of toolCalls) {
      const name = call.function && call.function.name;
      let args = {};
      if (call.function && call.function.arguments != null) {
        args = typeof call.function.arguments === 'string'
          ? safeParse(call.function.arguments)
          : call.function.arguments;
      }
      yield { type: 'tool', name, args };

      // Approval gate: dangerous tools wait for an explicit human decision.
      if (DANGEROUS_TOOLS.has(name) && typeof requestApproval === 'function') {
        const approved = await requestApproval(name, args);
        if (!approved) {
          yield { type: 'tool_result', name, result: { denied: true } };
          convo.push({ role: 'tool', name, content: JSON.stringify({ denied: true }) });
          continue;
        }
      }

      const result = await executeTool(name, args, { shellAllowed, ollamaUrl, profile });
      yield { type: 'tool_result', name, result };
      convo.push({
        role: 'tool',
        name,
        content: JSON.stringify(result).slice(0, 6000),
      });
    }
  }

  yield { type: 'error', error: `tool loop limit reached (${maxRounds} rounds) — answer with what you have` };
}

function safeParse(s) {
  try { return JSON.parse(s); } catch { return { _raw: String(s).slice(0, 500) }; }
}

module.exports = { agentChat };
