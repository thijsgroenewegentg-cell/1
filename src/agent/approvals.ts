import { EventEmitter } from 'node:events';
import type { Db } from '../store/db.ts';
import { publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('approvals');

export interface Approval {
  id: number;
  tool: string;
  args: string;
  conversation_id: number | null;
  reason: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

export type ApprovalDecision = 'approved' | 'denied' | 'timeout';

/**
 * Runtime approval flow for tools above the current authority level.
 * The agent loop parks on request(); the dashboard (or API) resolves it.
 */
export class ApprovalManager {
  private db: Db;
  private timeoutMs: number;
  private waiters = new EventEmitter();

  constructor(db: Db, timeoutMs: number) {
    this.db = db;
    this.timeoutMs = timeoutMs;
    this.waiters.setMaxListeners(50);
  }

  setTimeoutMs(ms: number): void {
    this.timeoutMs = ms;
  }

  /**
   * Create a pending approval and wait for the human's decision.
   * Resolves to 'approved' | 'denied' | 'timeout'.
   */
  request(input: {
    tool: string;
    args: Record<string, unknown>;
    conversationId?: number | null;
    reason: string;
  }): Promise<ApprovalDecision> {
    const res = this.db.db
      .prepare(`INSERT INTO approvals (tool, args, conversation_id, reason) VALUES (?, ?, ?, ?)`)
      .run(input.tool, JSON.stringify(input.args ?? {}), input.conversationId ?? null, input.reason);
    const id = Number(res.lastInsertRowid);
    log.info(`approval #${id} requested for tool "${input.tool}"`);

    // Register the waiter BEFORE publishing — otherwise an instant human
    // decision would be emitted into an empty room and lost.
    const wait = new Promise<ApprovalDecision>((resolve) => {
      const timer = setTimeout(() => {
        this.finalize(id, 'timeout');
        resolve('timeout');
      }, this.timeoutMs);
      this.waiters.once(`decision:${id}`, (decision: Exclude<ApprovalDecision, 'timeout'>) => {
        clearTimeout(timer);
        resolve(decision);
      });
    });
    publish('approval:requested', {
      id,
      tool: input.tool,
      args: input.args,
      reason: input.reason,
      conversation_id: input.conversationId ?? null,
    });
    return wait;
  }

  /** Human decision from the dashboard/API. Returns false for unknown ids. */
  resolve(id: number, decision: 'approved' | 'denied'): boolean {
    const row = this.get(id);
    if (!row || row.status !== 'pending') return false;
    this.finalize(id, decision);
    this.waiters.emit(`decision:${id}`, decision);
    return true;
  }

  private finalize(id: number, status: string): void {
    this.db.db
      .prepare(`UPDATE approvals SET status = ?, resolved_at = datetime('now') WHERE id = ?`)
      .run(status, id);
    publish('approval:resolved', { id, status });
    log.info(`approval #${id} → ${status}`);
  }

  get(id: number): Approval | undefined {
    return this.db.db.prepare(`SELECT * FROM approvals WHERE id = ?`).get(id) as Approval | undefined;
  }

  pending(): Approval[] {
    return this.db.db
      .prepare(`SELECT * FROM approvals WHERE status = 'pending' ORDER BY id DESC`)
      .all() as Approval[];
  }

  recent(limit = 20): Approval[] {
    return this.db.db.prepare(`SELECT * FROM approvals ORDER BY id DESC LIMIT ?`).all(limit) as Approval[];
  }
}
