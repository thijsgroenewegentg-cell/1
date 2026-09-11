import { watch, existsSync, type FSWatcher } from 'node:fs';
import path from 'node:path';
import type { JarvisConfig } from '../config.ts';
import type { Db } from '../store/db.ts';
import type { LlmProvider } from '../llm/provider.ts';
import type { Orchestrator } from '../agent/orchestrator.ts';
import type { ToolResult } from '../agent/tools.ts';
import { executeTool } from '../agent/tools.ts';
import type { CronScheduler } from '../cron.ts';
import { loadWorkflows, renderArgs, type Workflow } from './loader.ts';
import { bus, publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('workflows');

export interface WorkflowRun {
  id: number;
  workflow: string;
  trigger: string;
  status: string;
  log: string;
  started_at: string;
  finished_at: string | null;
}

/**
 * Lean workflow runtime: YAML-defined automations with file / cron / event /
 * webhook triggers and sequential steps (any agent tool, or an LLM call).
 */
export class WorkflowEngine {
  private cfg: JarvisConfig;
  private db: Db;
  private llm: LlmProvider;
  private orchestrator: Orchestrator;
  private cron: CronScheduler;
  private home: string;
  private workflows = new Map<string, Workflow>();
  private watchers: FSWatcher[] = [];
  private unsubscribers: (() => void)[] = [];
  private debounce = new Map<string, NodeJS.Timeout>();

  constructor(deps: {
    cfg: JarvisConfig;
    db: Db;
    llm: LlmProvider;
    orchestrator: Orchestrator;
    cron: CronScheduler;
    home: string;
  }) {
    this.cfg = deps.cfg;
    this.db = deps.db;
    this.llm = deps.llm;
    this.orchestrator = deps.orchestrator;
    this.cron = deps.cron;
    this.home = deps.home;
  }

  get dir(): string {
    return path.join(this.home, 'workflows');
  }

  /** (Re)load definitions and wire triggers. Returns loaded workflows. */
  start(): Workflow[] {
    this.stopTriggers();
    const list = loadWorkflows(this.dir);
    this.workflows.clear();
    for (const wf of list) {
      if (this.workflows.has(wf.id)) {
        log.warn(`duplicate workflow id "${wf.id}" — keeping the first`);
        continue;
      }
      this.workflows.set(wf.id, wf);
      if (!wf.enabled) continue;
      this.wireTrigger(wf);
    }
    if (list.length > 0) log.info(`loaded ${list.length} workflow(s) from ${this.dir}`);
    publish('workflows:loaded', { count: list.length });
    return list;
  }

  list(): Workflow[] {
    return [...this.workflows.values()].map((w) => ({ ...w, file: w.file }));
  }

  get(id: string): Workflow | undefined {
    return this.workflows.get(id);
  }

  private wireTrigger(wf: Workflow): void {
    const t = wf.trigger;
    if (t.type === 'cron' && t.expr) {
      this.cron.schedule(`workflow:${wf.id}`, t.expr, () => this.run(wf, { type: 'cron' }));
    } else if (t.type === 'event' && t.event) {
      const handler = (payload: unknown) => {
        void this.run(wf, { type: 'event', payload });
      };
      bus.on(t.event, handler);
      this.unsubscribers.push(() => bus.off(t.event, handler));
    } else if (t.type === 'file' && t.path) {
      const dir = path.isAbsolute(t.path) ? t.path : path.join(this.home, t.path);
      if (!existsSync(dir)) {
        log.warn(`workflow ${wf.id}: watch path missing: ${dir}`);
        return;
      }
      try {
        const w = watch(dir, { recursive: true }, (_evt, filename) => {
          if (!filename) return;
          const full = path.join(dir, filename);
          const key = `${wf.id}:${full}`;
          const pending = this.debounce.get(key);
          if (pending) clearTimeout(pending);
          this.debounce.set(
            key,
            setTimeout(() => {
              this.debounce.delete(key);
              void this.run(wf, {
                type: 'file',
                path: full,
                filename: path.basename(full),
                relpath: path.relative(this.home, full),
              });
            }, 500),
          );
        });
        this.watchers.push(w);
      } catch (err) {
        log.error(`workflow ${wf.id}: cannot watch ${dir}: ${String(err)}`);
      }
    }
    // webhook triggers need no wiring — POST /api/hooks/<id> looks them up
  }

  /** Fire a webhook-triggered workflow. */
  async webhook(id: string, body: unknown): Promise<{ ok: boolean; run?: WorkflowRun; error?: string }> {
    const wf = this.workflows.get(id);
    if (!wf || wf.trigger.type !== 'webhook') return { ok: false, error: `no webhook workflow "${id}"` };
    const run = await this.run(wf, { type: 'webhook', body });
    return { ok: run.status === 'done', run };
  }

  /** Execute a workflow end-to-end; every step's output feeds the template context. */
  async run(wf: Workflow, triggerCtx: Record<string, unknown>): Promise<WorkflowRun> {
    const res = this.db.db
      .prepare(`INSERT INTO workflow_runs (workflow, trigger) VALUES (?, ?)`)
      .run(wf.id, JSON.stringify(triggerCtx));
    const runId = Number(res.lastInsertRowid);
    publish('workflow:started', { id: wf.id, run: runId, trigger: triggerCtx.type });
    log.info(`workflow "${wf.id}" started (run ${runId})`);

    const ctx: Record<string, unknown> = { trigger: triggerCtx, steps: [] as { output: string }[] };
    const lines: string[] = [];
    let status = 'done';

    for (let i = 0; i < wf.steps.length; i += 1) {
      const step = wf.steps[i];
      const args = renderArgs(step.with ?? {}, ctx);
      let output = '';
      let ok = true;
      try {
        if (step.action === 'llm') {
          const tier = args.tier === 'smart' ? 'smart' : 'fast';
          const answer = await this.llm.complete(
            'You are one step inside an automation workflow. Do exactly what is asked, output only the result.',
            [{ role: 'user', content: String(args.prompt ?? '') }],
            { tier: tier as 'smart' | 'fast', temperature: 0.3 },
          );
          output = answer.content.trim();
        } else {
          const result: ToolResult = await executeTool(
            this.orchestrator.tools,
            step.action,
            args,
            this.orchestrator.workflowCtx(),
          );
          ok = result.ok;
          output = result.output;
        }
      } catch (err) {
        ok = false;
        output = `step threw: ${err instanceof Error ? err.message : String(err)}`;
      }
      (ctx.steps as { output: string }[]).push({ output });
      lines.push(`[${i}] ${step.action} ${ok ? '→' : '✖'} ${output.slice(0, 200)}`);
      publish('workflow:step', { id: wf.id, run: runId, step: i, action: step.action, ok });
      if (!ok) {
        status = 'failed';
        break;
      }
    }

    this.db.db
      .prepare(`UPDATE workflow_runs SET status = ?, log = ?, finished_at = datetime('now') WHERE id = ?`)
      .run(status, lines.join('\n'), runId);
    publish(status === 'done' ? 'workflow:done' : 'workflow:failed', { id: wf.id, run: runId });
    log.info(`workflow "${wf.id}" ${status}`);
    return this.getRun(runId) as WorkflowRun;
  }

  getRun(id: number): WorkflowRun | undefined {
    return this.db.db.prepare(`SELECT * FROM workflow_runs WHERE id = ?`).get(id) as WorkflowRun | undefined;
  }

  runs(limit = 30): WorkflowRun[] {
    return this.db.db.prepare(`SELECT * FROM workflow_runs ORDER BY id DESC LIMIT ?`).all(limit) as WorkflowRun[];
  }

  private stopTriggers(): void {
    for (const w of this.watchers) w.close();
    this.watchers = [];
    for (const u of this.unsubscribers) u();
    this.unsubscribers = [];
    for (const t of this.debounce.values()) clearTimeout(t);
    this.debounce.clear();
  }

  stop(): void {
    this.stopTriggers();
    this.workflows.clear();
  }
}
