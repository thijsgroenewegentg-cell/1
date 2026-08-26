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
const SELF_EDIT_TOOLS = new Set(['edit_source', 'restart_server']);

async function* agentChat({ ollamaUrl, model, messages, temperature, toolsEnabled, shellAllowed, systemPrompt, requestApproval, approval = { general: false, selfEdit: false }, maxRounds = 6, profile }) {
  const tools = toolsEnabled ? await toolSpecs({ shellAllowed }) : undefined;
  const convo = [{ role: 'system', content: systemPrompt }, ...messages];

  const needsApproval = (name) =>
    (SELF_EDIT_TOOLS.has(name) && approval.selfEdit) ||
    (DANGEROUS_TOOLS.has(name) && approval.general);

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

      // Approval gate: dangerous tools — and ALWAYS his own code — wait for a human decision.
      // If a gated tool has no approval channel (e.g. a background run), it is DENIED, never bypassed.
      if (needsApproval(name)) {
        const approved = typeof requestApproval === 'function' ? await requestApproval(name, args) : false;
        if (!approved) {
          yield { type: 'tool_result', name, result: { denied: true, note: 'no approval channel — denied by default' } };
          convo.push({ role: 'tool', name, content: JSON.stringify({ denied: true }) });
          continue;
        }
      }

      const result = await executeTool(name, args, { shellAllowed, ollamaUrl, profile });
      yield { type: 'tool_result', name, result };
      // Self-modifications get a mandatory, system-enforced change report.
      if (name === 'edit_source' && result && result.ok) {
        yield {
          type: 'self_edit',
          path: result.path,
          mode: result.mode,
          backup: result.backup,
          generation: result.generation,
          changed_from: result.changed_from,
          changed_to: result.changed_to,
          bytes_changed: result.bytes_changed,
        };
        convo.push({ role: 'tool', name: 'system_note', content: 'REMINDER: you just modified your own source. In your final reply you MUST tell the user exactly what you changed, why, and how to undo it (backup path above).' });
      }
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
