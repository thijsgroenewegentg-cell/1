import type { Db } from '../store/db.ts';
import { publish } from '../events.ts';

export interface Goal {
  id: number;
  title: string;
  why: string;
  status: string;
  deadline: string | null;
  created_at: string;
  updated_at: string;
}

export interface KeyResult {
  id: number;
  goal_id: number;
  title: string;
  target: number;
  current: number;
  status: string;
}

/** OKR-style goal pursuit: goals + key results, deadlines, heartbeat checks. */
export class GoalTracker {
  private db: Db;

  constructor(db: Db) {
    this.db = db;
  }

  create(input: { title: string; why?: string; deadline?: string; key_results?: string[] }): Goal {
    const res = this.db.db
      .prepare(`INSERT INTO goals (title, why, deadline) VALUES (?, ?, ?)`)
      .run(input.title, input.why ?? '', input.deadline ?? null);
    const goal = this.get(Number(res.lastInsertRowid));
    for (const kr of input.key_results ?? []) this.addKeyResult(goal.id, kr);
    publish('goal:created', { id: goal.id, title: goal.title });
    return goal;
  }

  get(id: number): Goal {
    const row = this.db.db.prepare(`SELECT * FROM goals WHERE id = ?`).get(id) as Goal | undefined;
    if (!row) throw new Error(`goal ${id} not found`);
    return row;
  }

  list(includeClosed = false): Goal[] {
    const sql = includeClosed
      ? `SELECT * FROM goals ORDER BY id DESC`
      : `SELECT * FROM goals WHERE status = 'open' ORDER BY id DESC`;
    return this.db.db.prepare(sql).all() as Goal[];
  }

  update(id: number, patch: Partial<Pick<Goal, 'title' | 'why' | 'status' | 'deadline'>>): Goal {
    const goal = this.get(id);
    const next = { ...goal, ...patch };
    this.db.db
      .prepare(
        `UPDATE goals SET title = ?, why = ?, status = ?, deadline = ?, updated_at = datetime('now') WHERE id = ?`,
      )
      .run(next.title, next.why, next.status, next.deadline ?? null, id);
    publish('goal:updated', { id, status: next.status, title: next.title });
    return this.get(id);
  }

  addKeyResult(goalId: number, title: string, target = 1): KeyResult {
    this.get(goalId); // exists check
    const res = this.db.db
      .prepare(`INSERT INTO key_results (goal_id, title, target) VALUES (?, ?, ?)`)
      .run(goalId, title, target);
    return this.db.db
      .prepare(`SELECT * FROM key_results WHERE id = ?`)
      .get(Number(res.lastInsertRowid)) as KeyResult;
  }

  keyResults(goalId: number): KeyResult[] {
    return this.db.db
      .prepare(`SELECT * FROM key_results WHERE goal_id = ? ORDER BY id`)
      .all(goalId) as KeyResult[];
  }

  advanceKeyResult(krId: number, delta: number): KeyResult {
    this.db.db
      .prepare(`UPDATE key_results SET current = current + ? WHERE id = ?`)
      .run(delta, krId);
    const kr = this.db.db.prepare(`SELECT * FROM key_results WHERE id = ?`).get(krId) as KeyResult;
    if (kr && kr.current >= kr.target && kr.status === 'open') {
      this.db.db.prepare(`UPDATE key_results SET status = 'done', current = target WHERE id = ?`).run(krId);
      publish('keyresult:done', { id: krId, title: kr.title });
    }
    return this.db.db.prepare(`SELECT * FROM key_results WHERE id = ?`).get(krId) as KeyResult;
  }

  /** Pure read: goals whose deadline is within `windowDays` or already past. */
  dueAlerts(windowDays = 3): { goal: Goal; days_left: number }[] {
    const alerts: { goal: Goal; days_left: number }[] = [];
    for (const goal of this.list()) {
      if (!goal.deadline) continue;
      const daysLeft = (new Date(goal.deadline).getTime() - Date.now()) / 86_400_000;
      if (daysLeft <= windowDays) alerts.push({ goal, days_left: Math.round(daysLeft * 10) / 10 });
    }
    return alerts;
  }

  /** Hourly heartbeat: surface near/overdue deadlines and publish alerts. */
  heartbeat(): { goal: Goal; days_left: number }[] {
    const alerts = this.dueAlerts();
    for (const { goal, days_left } of alerts) {
      publish('goal:deadline', {
        id: goal.id,
        title: goal.title,
        days_left,
        overdue: days_left < 0,
      });
    }
    return alerts;
  }
}
