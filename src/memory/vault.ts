import type { Db } from '../store/db.ts';
import { publish } from '../events.ts';

export interface Memory {
  id: number;
  kind: string;
  title: string;
  body: string;
  tags: string;
  source: string;
  created_at: string;
}

/**
 * Knowledge vault: notes, entities, observations and commitments, with a
 * lightweight keyword+recency search good enough for a local daemon.
 */
export class KnowledgeVault {
  private db: Db;

  constructor(db: Db) {
    this.db = db;
  }

  remember(input: {
    kind?: string;
    title: string;
    body?: string;
    tags?: string[];
    source?: string;
  }): Memory {
    const stmt = this.db.db.prepare(
      `INSERT INTO memories (kind, title, body, tags, source) VALUES (?, ?, ?, ?, ?)`,
    );
    const res = stmt.run(
      input.kind ?? 'note',
      input.title,
      input.body ?? '',
      (input.tags ?? []).join(','),
      input.source ?? '',
    );
    const mem = this.get(Number(res.lastInsertRowid));
    publish('memory:new', { id: mem.id, title: mem.title, kind: mem.kind });
    return mem;
  }

  get(id: number): Memory {
    const row = this.db.db.prepare(`SELECT * FROM memories WHERE id = ?`).get(id) as Memory | undefined;
    if (!row) throw new Error(`memory ${id} not found`);
    return row;
  }

  list(limit = 50): Memory[] {
    return this.db.db
      .prepare(`SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT ?`)
      .all(limit) as Memory[];
  }

  delete(id: number): void {
    this.db.db.prepare(`DELETE FROM memories WHERE id = ?`).run(id);
    publish('memory:deleted', { id });
  }

  /** Token-overlap scoring with a small recency boost. */
  search(query: string, limit = 8): Memory[] {
    const tokens = query
      .toLowerCase()
      .split(/[^\p{L}\p{N}]+/u)
      .filter((t) => t.length > 2);
    if (tokens.length === 0) return this.list(limit);
    const rows = this.db.db
      .prepare(`SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT 500`)
      .all() as Memory[];
    const now = Date.now();
    const scored = rows
      .map((m) => {
        const hay = `${m.title} ${m.body} ${m.tags}`.toLowerCase();
        let score = 0;
        for (const t of tokens) {
          if (hay.includes(t)) score += m.title.toLowerCase().includes(t) ? 3 : 1;
        }
        const ageDays = (now - new Date(m.created_at + 'Z').getTime()) / 86_400_000;
        score += Math.max(0, 0.5 - ageDays / 60);
        return { m, score };
      })
      .filter((s) => s.score > 0.4)
      .sort((a, b) => b.score - a.score);
    return scored.slice(0, limit).map((s) => s.m);
  }

  /** Render top memories as a prompt block so the agent knows what it knows. */
  contextFor(query: string, limit = 5): string {
    const hits = this.search(query, limit);
    if (hits.length === 0) return '';
    const lines = hits.map((m) => `- [${m.kind}] ${m.title}${m.body ? ` — ${m.body.slice(0, 200)}` : ''}`);
    return `Relevant knowledge vault entries:\n${lines.join('\n')}`;
  }
}
