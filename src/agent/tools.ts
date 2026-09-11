import path from 'node:path';
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import type { ToolSpec } from '../llm/ollama.ts';
import type { KnowledgeVault } from '../memory/vault.ts';
import type { GoalTracker } from '../goals/goals.ts';
import { publish } from '../events.ts';

/**
 * Authority levels (mirrors JARVIS):
 *   0 read-only · 1 safe writes · 2 delegation · 3 network + notify · 4 shell
 * Effective rule: a tool runs only if tool.level <= configured authority.
 */
export const AUTHORITY_LEVELS = {
  READ: 0,
  SAFE_WRITE: 1,
  DELEGATE: 2,
  NETWORK: 3,
  SHELL: 4,
} as const;

export interface ToolContext {
  authority: number;
  /** 'gate' = refuse over-authority tools outright; 'ask' = pause for human approval. */
  authorityMode: 'ask' | 'gate';
  rootDir: string;
  vault: KnowledgeVault;
  goals: GoalTracker;
  delegate?: (role: string, task: string) => Promise<string>;
  requestApproval?: (
    tool: string,
    args: Record<string, unknown>,
    reason: string,
  ) => Promise<'approved' | 'denied' | 'timeout'>;
}

export interface ToolResult {
  ok: boolean;
  output: string;
  denied?: boolean;
}

export interface Tool {
  name: string;
  level: number;
  description: string;
  parameters: Record<string, unknown>;
  run: (args: Record<string, unknown>, ctx: ToolContext) => Promise<ToolResult> | ToolResult;
}

function ok(output: string): ToolResult {
  return { ok: true, output };
}

function fail(output: string): ToolResult {
  return { ok: false, output };
}

/** Sandbox a path to stay inside rootDir. */
function safePath(rootDir: string, p: string): string {
  const resolved = path.resolve(rootDir, p);
  const root = path.resolve(rootDir);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error(`path escapes workspace: ${p}`);
  }
  return resolved;
}

function htmlToText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();
}

export function buildTools(): Record<string, Tool> {
  const tools: Tool[] = [
    {
      name: 'list_dir',
      level: AUTHORITY_LEVELS.READ,
      description: 'List files and directories at a path inside the workspace.',
      parameters: {
        type: 'object',
        properties: { path: { type: 'string', description: 'Directory path, relative to the workspace root' } },
        required: ['path'],
      },
      run: (args, ctx) => {
        const dir = safePath(ctx.rootDir, String(args.path ?? '.'));
        const entries = readdirSync(dir).map((e) => {
          const st = statSync(path.join(dir, e));
          return st.isDirectory() ? `${e}/` : e;
        });
        return ok(entries.join('\n') || '(empty directory)');
      },
    },
    {
      name: 'read_file',
      level: AUTHORITY_LEVELS.READ,
      description: 'Read a text file from the workspace.',
      parameters: {
        type: 'object',
        properties: { path: { type: 'string' } },
        required: ['path'],
      },
      run: (args, ctx) => {
        const file = safePath(ctx.rootDir, String(args.path));
        const content = readFileSync(file, 'utf8');
        return ok(content.length > 12000 ? content.slice(0, 12000) + '\n…(truncated)' : content);
      },
    },
    {
      name: 'write_file',
      level: AUTHORITY_LEVELS.SAFE_WRITE,
      description: 'Create or overwrite a file inside the workspace.',
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          content: { type: 'string' },
        },
        required: ['path', 'content'],
      },
      run: (args, ctx) => {
        const file = safePath(ctx.rootDir, String(args.path));
        mkdirSync(path.dirname(file), { recursive: true });
        writeFileSync(file, String(args.content));
        publish('fs:write', { path: String(args.path) });
        return ok(`wrote ${String(args.content).length} chars to ${args.path}`);
      },
    },
    {
      name: 'memory_remember',
      level: AUTHORITY_LEVELS.SAFE_WRITE,
      description:
        'Store a durable fact, preference, entity or observation in the knowledge vault so it survives across conversations.',
      parameters: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'Short memorable title' },
          body: { type: 'string', description: 'The fact or detail to remember' },
          kind: { type: 'string', enum: ['note', 'entity', 'observation', 'commitment'] },
          tags: { type: 'array', items: { type: 'string' } },
        },
        required: ['title', 'body'],
      },
      run: async (args, ctx) => {
        const mem = await ctx.vault.remember({
          title: String(args.title),
          body: String(args.body),
          kind: (args.kind as string) ?? 'note',
          tags: (args.tags as string[]) ?? [],
          source: 'agent',
        });
        return ok(`remembered #${mem.id}: ${mem.title}`);
      },
    },
    {
      name: 'memory_search',
      level: AUTHORITY_LEVELS.READ,
      description: 'Search the knowledge vault for facts, entities and past observations.',
      parameters: {
        type: 'object',
        properties: { query: { type: 'string' } },
        required: ['query'],
      },
      run: async (args, ctx) => {
        const hits = await ctx.vault.search(String(args.query), 8);
        if (hits.length === 0) return ok('no matching memories found');
        return ok(
          hits.map((m) => `[${m.kind}] ${m.title} — ${m.body.slice(0, 300)} (${m.created_at})`).join('\n'),
        );
      },
    },
    {
      name: 'goal_create',
      level: AUTHORITY_LEVELS.SAFE_WRITE,
      description: 'Create a goal (optionally with key results and a deadline) to pursue.',
      parameters: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          why: { type: 'string' },
          deadline: { type: 'string', description: 'ISO date, e.g. 2026-10-01' },
          key_results: { type: 'array', items: { type: 'string' } },
        },
        required: ['title'],
      },
      run: (args, ctx) => {
        const goal = ctx.goals.create({
          title: String(args.title),
          why: (args.why as string) ?? '',
          deadline: args.deadline as string | undefined,
          key_results: (args.key_results as string[]) ?? [],
        });
        return ok(`goal #${goal.id} created: ${goal.title}`);
      },
    },
    {
      name: 'goal_update',
      level: AUTHORITY_LEVELS.SAFE_WRITE,
      description: 'Change the status of a goal (open, done, dropped).',
      parameters: {
        type: 'object',
        properties: {
          id: { type: 'number' },
          status: { type: 'string', enum: ['open', 'done', 'dropped'] },
        },
        required: ['id', 'status'],
      },
      run: (args, ctx) => {
        const goal = ctx.goals.update(Number(args.id), { status: String(args.status) });
        return ok(`goal #${goal.id} is now ${goal.status}`);
      },
    },
    {
      name: 'delegate',
      level: AUTHORITY_LEVELS.DELEGATE,
      description:
        'Hand a subtask to a specialist role: researcher, coder, writer, planner or system-operator. Use this for focused work instead of doing everything yourself.',
      parameters: {
        type: 'object',
        properties: {
          role: { type: 'string', enum: ['researcher', 'coder', 'writer', 'planner', 'system-operator'] },
          task: { type: 'string', description: 'Self-contained task description for the specialist' },
        },
        required: ['role', 'task'],
      },
      run: async (args, ctx) => {
        if (!ctx.delegate) return fail('delegation is not wired in this context');
        const answer = await ctx.delegate(String(args.role), String(args.task));
        return ok(answer);
      },
    },
    {
      name: 'web_fetch',
      level: AUTHORITY_LEVELS.NETWORK,
      description: 'Fetch a URL and return its readable text content.',
      parameters: {
        type: 'object',
        properties: { url: { type: 'string' } },
        required: ['url'],
      },
      run: async (args) => {
        const url = String(args.url);
        const res = await fetch(url, {
          signal: AbortSignal.timeout(20_000),
          headers: { 'user-agent': 'jarvis/0.1 (+local)' },
        });
        if (!res.ok) return fail(`HTTP ${res.status} fetching ${url}`);
        const text = htmlToText(await res.text());
        return ok(text.slice(0, 6000));
      },
    },
    {
      name: 'notify',
      level: AUTHORITY_LEVELS.NETWORK,
      description: 'Push a notification to the user (shows as a toast in the dashboard).',
      parameters: {
        type: 'object',
        properties: { message: { type: 'string' } },
        required: ['message'],
      },
      run: (args) => {
        publish('notify', { message: String(args.message) });
        return ok('notification sent');
      },
    },
    {
      name: 'shell',
      level: AUTHORITY_LEVELS.SHELL,
      description:
        'Run a shell command in the workspace (max 60s). Use only when file tools are not enough. Refused unless authority level is 4.',
      parameters: {
        type: 'object',
        properties: { command: { type: 'string' } },
        required: ['command'],
      },
      run: (args, ctx) =>
        new Promise<ToolResult>((resolve) => {
          const cmd = String(args.command);
          const child = spawn('sh', ['-c', cmd], { cwd: ctx.rootDir, timeout: 60_000 });
          let out = '';
          let err = '';
          child.stdout.on('data', (d) => (out += d.toString()));
          child.stderr.on('data', (d) => (err += d.toString()));
          child.on('error', (e) => resolve(fail(`shell error: ${String(e)}`)));
          child.on('close', (code) => {
            const body = [out.trim(), err.trim() ? `stderr:\n${err.trim()}` : ''].filter(Boolean).join('\n');
            resolve(
              code === 0
                ? ok(body.slice(0, 8000) || '(no output)')
                : fail(`exit code ${code}\n${body.slice(0, 8000)}`),
            );
          });
        }),
    },
  ];

  return Object.fromEntries(tools.map((t) => [t.name, t]));
}

export function toolSpecs(tools: Record<string, Tool>, allowed: string[]): ToolSpec[] {
  return allowed
    .map((name) => tools[name])
    .filter(Boolean)
    .map((t) => ({
      type: 'function' as const,
      function: { name: t.name, description: t.description, parameters: t.parameters },
    }));
}

/**
 * Authority gate. In 'gate' mode over-authority tools are refused outright;
 * in 'ask' mode the agent parks and waits for a human decision (approve /
 * deny / timeout). Every path is audited on the event bus.
 */
export async function executeTool(
  tools: Record<string, Tool>,
  name: string,
  args: Record<string, unknown>,
  ctx: ToolContext,
): Promise<ToolResult> {
  const tool = tools[name];
  if (!tool) return fail(`unknown tool: ${name}`);

  if (tool.level > ctx.authority) {
    if (ctx.authorityMode === 'ask' && ctx.requestApproval) {
      publish('authority:approval-waiting', { tool: name, required: tool.level, allowed: ctx.authority });
      const decision = await ctx.requestApproval(
        name,
        args ?? {},
        `Tool "${name}" needs authority ${tool.level} (current level: ${ctx.authority}).`,
      );
      if (decision === 'approved') {
        publish('authority:approved-run', { tool: name });
      } else {
        publish('authority:denied', {
          tool: name,
          required: tool.level,
          allowed: ctx.authority,
          reason: decision === 'timeout' ? 'approval timed out' : 'user declined',
        });
        return {
          ok: false,
          denied: true,
          output:
            decision === 'timeout'
              ? `DENIED: approval for tool "${name}" timed out — the user did not respond.`
              : `DENIED: the user declined to run tool "${name}". Do not retry it unchanged.`,
        };
      }
    } else {
      publish('authority:denied', { tool: name, required: tool.level, allowed: ctx.authority });
      return {
        ok: false,
        denied: true,
        output: `DENIED: tool "${name}" requires authority level ${tool.level}, current level is ${ctx.authority}. Ask the user to raise authority.level.`,
      };
    }
  }
  try {
    return await tool.run(args ?? {}, ctx);
  } catch (err) {
    return fail(`tool "${name}" failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}
