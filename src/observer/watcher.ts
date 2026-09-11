import { watch, type FSWatcher } from 'node:fs';
import { readFileSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';
import type { JarvisConfig } from '../config.ts';
import type { LlmProvider } from '../llm/provider.ts';
import type { KnowledgeVault } from '../memory/vault.ts';
import { publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('observer');

/**
 * Observer layer: watches configured directories; new/changed text files are
 * summarized by the fast model and filed in the knowledge vault, giving the
 * agent ambient awareness of the user's working folders.
 */
export class Observer {
  private cfg: JarvisConfig;
  private llm: LlmProvider;
  private vault: KnowledgeVault;
  private watchers: FSWatcher[] = [];
  private debounce = new Map<string, NodeJS.Timeout>();

  constructor(cfg: JarvisConfig, llm: LlmProvider, vault: KnowledgeVault) {
    this.cfg = cfg;
    this.llm = llm;
    this.vault = vault;
  }

  start(): void {
    if (!this.cfg.observer.enabled) return;
    for (const p of this.cfg.observer.paths) {
      const dir = path.isAbsolute(p) ? p : path.resolve(p);
      if (!existsSync(dir)) {
        log.warn(`watch path does not exist, skipping: ${dir}`);
        continue;
      }
      try {
        const w = watch(dir, { recursive: true }, (_event, filename) => {
          if (filename) this.onChange(path.join(dir, filename));
        });
        this.watchers.push(w);
        log.info(`watching ${dir}`);
      } catch (err) {
        log.error(`failed to watch ${dir}:`, err);
      }
    }
    publish('observer:started', { paths: this.cfg.observer.paths });
  }

  private onChange(file: string): void {
    const pending = this.debounce.get(file);
    if (pending) clearTimeout(pending);
    this.debounce.set(
      file,
      setTimeout(() => {
        this.debounce.delete(file);
        void this.ingest(file).catch((err) => log.error(`ingest ${file}:`, err));
      }, this.cfg.observer.debounce_ms),
    );
  }

  async ingest(file: string): Promise<void> {
    if (!existsSync(file)) return; // deleted
    const st = statSync(file);
    if (!st.isFile() || st.size > 200_000) return;
    const ext = path.extname(file).toLowerCase();
    if (!['', '.txt', '.md', '.markdown', '.log', '.json', '.yaml', '.yml', '.csv'].includes(ext)) return;

    let raw: string;
    try {
      raw = readFileSync(file, 'utf8');
    } catch {
      return; // binary or unreadable
    }
    publish('observation', { file });

    const snippet = raw.slice(0, 4000);
    let summary = snippet.slice(0, 400);
    try {
      const res = await this.llm.complete(
        'Summarize the following file content in one or two factual sentences. Output only the summary.',
        [{ role: 'user', content: `File: ${file}\n\n${snippet}` }],
        { tier: 'fast', temperature: 0.2 },
      );
      summary = res.content.trim() || summary;
    } catch (err) {
      log.warn('fast-model summary failed, storing raw excerpt:', err);
    }

    this.vault.remember({
      kind: 'observation',
      title: `file changed: ${path.basename(file)}`,
      body: summary,
      tags: ['observer', path.extname(file).replace('.', '') || 'file'],
      source: file,
    });
  }

  stop(): void {
    for (const w of this.watchers) w.close();
    this.watchers = [];
    for (const t of this.debounce.values()) clearTimeout(t);
    this.debounce.clear();
  }
}
