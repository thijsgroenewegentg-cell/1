import type { Db } from '../store/db.ts';
import { Embedder } from './embedder.ts';
import { publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('vault');

export interface Memory {
  id: number;
  kind: string;
  title: string;
  body: string;
  tags: string;
  source: string;
  created_at: string;
}

interface MemoryRow extends Memory {
  embedding: Buffer | null;
}

/**
 * Knowledge vault with hybrid retrieval: embedding cosine similarity +
 * keyword overlap + recency. Degrades gracefully to keyword-only when the
 * embedding model isn't installed.
 */
export class KnowledgeVault {
  private db: Db;
  private embedder: Embedder | null;

  constructor(db: Db, embedder: Embedder | null = null) {
    this.db = db;
    this.embedder = embedder;
  }

  setEmbedder(embedder: Embedder): void {
    this.embedder = embedder;
  }

  async remember(input: {
    kind?: string;
    title: string;
    body?: string;
    tags?: string[];
    source?: string;
  }): Promise<Memory> {
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
    const id = Number(res.lastInsertRowid);
    await this.embedRows([id]);
    const mem = this.get(id);
    publish('memory:new', { id: mem.id, title: mem.title, kind: mem.kind });
    return mem;
  }

  get(id: number): Memory {
    const row = this.db.db
      .prepare(`SELECT id, kind, title, body, tags, source, created_at FROM memories WHERE id = ?`)
      .get(id) as Memory | undefined;
    if (!row) throw new Error(`memory ${id} not found`);
    return row;
  }

  list(limit = 50): Memory[] {
    return this.db.db
      .prepare(
        `SELECT id, kind, title, body, tags, source, created_at FROM memories ORDER BY created_at DESC, id DESC LIMIT ?`,
      )
      .all(limit) as Memory[];
  }

  delete(id: number): void {
    this.db.db.prepare(`DELETE FROM memories WHERE id = ?`).run(id);
    publish('memory:deleted', { id });
  }

  /**
   * Hybrid search. Keyword: title hits weigh 3, body/tags 1 (normalized).
   * Semantic: cosine against the embedding of title+body. Recency adds a
   * small boost. Falls back to keyword-only when no vectors exist.
   */
  async search(query: string, limit = 8): Promise<Memory[]> {
    const tokens = query
      .toLowerCase()
      .split(/[^\p{L}\p{N}]+/u)
      .filter((t) => t.length > 2);
    const rows = this.db.db
      .prepare(`SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT 500`)
      .all() as MemoryRow[];
    if (rows.length === 0) return [];
    if (tokens.length === 0 && !this.embedder) return this.list(limit);

    let queryVec: number[] | null = null;
    if (this.embedder && query.trim()) {
      queryVec = await this.embedder.embedOne(query);
    }
    const now = Date.now();

    const scored = rows
      .map((m) => {
        const hay = `${m.title} ${m.body} ${m.tags}`.toLowerCase();
        let kw = 0;
        for (const t of tokens) {
          if (hay.includes(t)) kw += m.title.toLowerCase().includes(t) ? 3 : 1;
        }
        const ageDays = (now - new Date(m.created_at + 'Z').getTime()) / 86_400_000;
        const recency = Math.max(0, 0.5 - ageDays / 60);

        let score: number;
        if (queryVec && m.embedding) {
          const memVec = Embedder.fromBuffer(m.embedding);
          const sem = Math.max(0, Embedder.cosine(queryVec, memVec));
          const kwNorm = tokens.length > 0 ? Math.min(1, kw / (tokens.length * 3)) : 0;
          score = 0.9 * sem + 0.5 * kwNorm + recency * 0.3;
          if (score < 0.25) score = 0;
        } else {
          score = kw > 0 ? kw + recency : 0;
          if (score < 0.4) score = 0;
        }
        return { m, score };
      })
      .filter((s) => s.score > 0)
      .sort((a, b) => b.score - a.score);

    return scored.slice(0, limit).map((s) => s.m);
  }

  /** Render top memories as a prompt block so the agent knows what it knows. */
  async contextFor(query: string, limit = 5): Promise<string> {
    const hits = await this.search(query, limit);
    if (hits.length === 0) return '';
    const lines = hits.map((m) => `- [${m.kind}] ${m.title}${m.body ? ` — ${m.body.slice(0, 200)}` : ''}`);
    return `Relevant knowledge vault entries:\n${lines.join('\n')}`;
  }

  /** Embed (or re-embed) memories missing vectors. Returns rows updated. */
  async backfill(reembedAll = false): Promise<number> {
    if (!this.embedder || !(await this.embedder.available())) return 0;
    const where = reembedAll ? '' : ' WHERE embedding IS NULL';
    const rows = this.db.db.prepare(`SELECT id FROM memories${where}`).all() as { id: number }[];
    if (rows.length === 0) return 0;
    let done = 0;
    for (let i = 0; i < rows.length; i += 24) {
      const ids = rows.slice(i, i + 24).map((r) => r.id);
      done += await this.embedRows(ids);
    }
    if (done > 0) {
      log.info(`embedded ${done} memories`);
      publish('memory:indexed', { count: done });
    }
    return done;
  }

  /** Compute and store embeddings for the given memory ids. */
  private async embedRows(ids: number[]): Promise<number> {
    if (!this.embedder || ids.length === 0) return 0;
    const placeholders = ids.map(() => '?').join(',');
    const rows = this.db.db
      .prepare(`SELECT id, title, body, tags FROM memories WHERE id IN (${placeholders})`)
      .all(...ids) as { id: number; title: string; body: string; tags: string }[];
    if (rows.length === 0) return 0;
    const texts = rows.map((r) => `${r.title}. ${r.body} ${r.tags}`.trim());
    const vectors = await this.embedder.embed(texts);
    if (vectors.length !== rows.length) return 0;
    const update = this.db.db.prepare(`UPDATE memories SET embedding = ? WHERE id = ?`);
    rows.forEach((r, i) => update.run(Embedder.toBuffer(vectors[i]), r.id));
    return rows.length;
  }
}
