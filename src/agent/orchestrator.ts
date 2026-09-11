import type { JarvisConfig } from '../config.ts';
import type { Db } from '../store/db.ts';
import type { LlmProvider } from '../llm/provider.ts';
import type { ChatMessage } from '../llm/ollama.ts';
import type { KnowledgeVault } from '../memory/vault.ts';
import type { GoalTracker } from '../goals/goals.ts';
import { buildTools, executeTool, toolSpecs, type Tool, type ToolContext } from './tools.ts';
import type { ApprovalManager } from './approvals.ts';
import { roleFor } from './roles.ts';
import { publish } from '../events.ts';
import { jarvisHome } from '../config.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('agent');

export interface OrchestratorDeps {
  cfg: JarvisConfig;
  db: Db;
  llm: LlmProvider;
  vault: KnowledgeVault;
  goals: GoalTracker;
  approvals?: ApprovalManager;
}

export interface RunResult {
  conversationId: number;
  answer: string;
  turns: number;
}

let toolCallSeq = 0;

export class Orchestrator {
  readonly tools: Record<string, Tool> = buildTools();
  private deps: OrchestratorDeps;

  constructor(deps: OrchestratorDeps) {
    this.deps = deps;
  }

  private toolCtx(conversationId: number | null): ToolContext {
    const approvals = this.deps.approvals;
    return {
      authority: this.deps.cfg.authority.level,
      authorityMode: this.deps.cfg.authority.mode,
      rootDir: jarvisHome(),
      vault: this.deps.vault,
      goals: this.deps.goals,
      delegate: async (role: string, task: string) => this.runSpecialist(role, task, 1),
      requestApproval: approvals
        ? (tool, args, reason) => approvals.request({ tool, args, conversationId, reason })
        : undefined,
    };
  }

  private async systemPrompt(roleId: string, userQuery: string): Promise<string> {
    const { cfg, vault, goals } = this.deps;
    const role = roleFor(roleId);
    const openGoals = goals.list();
    const goalBlock =
      openGoals.length > 0
        ? `\n\nOpen goals:\n${openGoals
            .map((g) => `- #${g.id} ${g.title}${g.deadline ? ` (deadline ${g.deadline})` : ''}`)
            .join('\n')}`
        : '';
    const memoryBlock = await vault.contextFor(userQuery);
    return [
      `You are ${cfg.personality.name}, an always-on personal AI system running locally on the user's machine via Ollama. Core traits: ${cfg.personality.core_traits.join(', ')}.`,
      role.instructions,
      `Today is ${new Date().toISOString().slice(0, 10)}.`,
      goalBlock,
      memoryBlock ? `\n${memoryBlock}` : '',
      'When you use tools, rely on their results rather than guessing. When done, answer the user directly.',
    ]
      .filter(Boolean)
      .join('\n');
  }

  private loadHistory(conversationId: number, limit = 30): ChatMessage[] {
    const rows = this.deps.db.db
      .prepare(
        `SELECT role, content, tool_calls FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?`,
      )
      .all(conversationId, limit) as { role: string; content: string; tool_calls: string | null }[];
    rows.reverse();
    return rows.map((r) => {
      const msg: ChatMessage = { role: r.role as ChatMessage['role'], content: r.content };
      if (r.tool_calls) {
        try {
          msg.tool_calls = JSON.parse(r.tool_calls) as ChatMessage['tool_calls'];
        } catch {
          /* skip malformed */
        }
      }
      return msg;
    });
  }

  private saveMessage(
    conversationId: number,
    role: string,
    content: string,
    agent = 'jarvis',
    toolCalls?: unknown[],
  ): void {
    this.deps.db.db
      .prepare(
        `INSERT INTO messages (conversation_id, role, content, agent, tool_calls) VALUES (?, ?, ?, ?, ?)`,
      )
      .run(conversationId, role, content, agent, toolCalls ? JSON.stringify(toolCalls) : null);
    this.deps.db.db
      .prepare(`UPDATE conversations SET updated_at = datetime('now') WHERE id = ?`)
      .run(conversationId);
  }

  /** Handle one user message end-to-end, including the tool-call loop. */
  async run(opts: {
    conversationId?: number | null;
    userInput: string;
    roleId?: string;
    onToken?: (delta: string) => void;
  }): Promise<RunResult> {
    const { db } = this.deps;
    let conversationId = opts.conversationId ?? null;
    if (!conversationId) {
      const res = db.db
        .prepare(`INSERT INTO conversations (title) VALUES (?)`)
        .run(opts.userInput.slice(0, 60).trim() || 'New conversation');
      conversationId = Number(res.lastInsertRowid);
      publish('conversation:new', { id: conversationId });
    }
    this.saveMessage(conversationId, 'user', opts.userInput, 'user');
    publish('agent:user', { conversationId, text: opts.userInput.slice(0, 200) });

    const roleId = opts.roleId ?? 'orchestrator';
    const role = roleFor(roleId);
    const system = await this.systemPrompt(roleId, opts.userInput);
    const history = this.loadHistory(conversationId);
    const allowedTools = toolSpecs(this.tools, role.tools);

    let turns = 0;
    let answer = '';
    while (turns < this.deps.cfg.agent.max_turns) {
      turns += 1;
      publish('agent:turn', { conversationId, turn: turns, role: roleId });
      const result = await this.deps.llm.stream(system, history, opts.onToken ?? (() => {}), {
        tools: allowedTools,
      });

      const toolCalls = (result.tool_calls ?? []).map((tc) => ({
        function: {
          name: tc.function?.name ?? '',
          arguments:
            typeof tc.function?.arguments === 'string'
              ? safeJson(tc.function.arguments)
              : (tc.function?.arguments ?? {}),
        },
      }));

      if (toolCalls.length === 0) {
        answer = result.content.trim();
        this.saveMessage(conversationId, 'assistant', answer, roleId);
        publish('agent:done', { conversationId, turns, answer: answer.slice(0, 300) });
        return { conversationId, answer, turns };
      }

      // Assistant turn that requests tools.
      history.push({ role: 'assistant', content: result.content, tool_calls: toolCalls });
      this.saveMessage(conversationId, 'assistant', result.content, roleId, toolCalls);

      for (const call of toolCalls) {
        const name = call.function.name;
        const args = call.function.arguments as Record<string, unknown>;
        const callId = `call_${++toolCallSeq}`;
        log.info(`tool ${name} ${JSON.stringify(args).slice(0, 160)}`);
        publish('agent:tool', { conversationId, tool: name, args });
        const res = await executeTool(this.tools, name, args, this.toolCtx(conversationId));
        const output = res.output || (res.ok ? 'ok' : 'failed');
        history.push({ role: 'tool', content: output, tool_call_id: callId, name });
        this.saveMessage(conversationId, 'tool', `[${name}] ${output}`, roleId);
        publish('agent:tool-result', { conversationId, tool: name, ok: res.ok, denied: res.denied ?? false });
      }
    }

    answer = 'I hit my tool-call budget for this turn without a final answer. Try narrowing the request.';
    this.saveMessage(conversationId, 'assistant', answer, roleId);
    publish('agent:done', { conversationId, turns, truncated: true });
    return { conversationId, answer, turns };
  }

  /** Tool context for out-of-band automation (workflows): full authority rules, no conversation. */
  workflowCtx(): ToolContext {
    return this.toolCtx(null);
  }

  /** Run a specialist on a subtask inside an ephemeral context (delegation). */
  async runSpecialist(roleId: string, task: string, depth: number): Promise<string> {
    if (depth >= this.deps.cfg.agent.max_delegation_depth) {
      return 'Delegation depth limit reached — handling this directly instead.';
    }
    publish('agent:delegate', { role: roleId, task: task.slice(0, 200) });
    const role = roleFor(roleId);
    const system = await this.systemPrompt(roleId, task);
    const history: ChatMessage[] = [{ role: 'user', content: task }];
    const allowedTools = toolSpecs(
      this.tools,
      role.tools.filter((t) => t !== 'delegate'), // specialists never delegate further
    );

    for (let turn = 0; turn < this.deps.cfg.agent.max_turns; turn += 1) {
      const result = await this.deps.llm.complete(system, history, { tools: allowedTools });
      const toolCalls = result.tool_calls ?? [];
      if (toolCalls.length === 0) {
        publish('agent:delegate-done', { role: roleId });
        return result.content.trim() || '(specialist returned no answer)';
      }
      history.push({ role: 'assistant', content: result.content, tool_calls: toolCalls });
      for (const tc of toolCalls) {
        const name = tc.function?.name ?? '';
        const args =
          typeof tc.function?.arguments === 'string'
            ? safeJson(tc.function.arguments)
            : ((tc.function?.arguments ?? {}) as Record<string, unknown>);
        publish('agent:tool', { specialist: roleId, tool: name, args });
        const res = await executeTool(this.tools, name, args, this.toolCtx(null));
        history.push({ role: 'tool', content: res.output, name });
      }
    }
    return '(specialist exhausted its tool budget without a final answer)';
  }
}

function safeJson(text: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}
