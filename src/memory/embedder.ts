import type { JarvisConfig } from '../config.ts';
import type { OllamaClient } from '../llm/ollama.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('embedder');

/**
 * Text embeddings via Ollama (/api/embed). All vector math is plain JS —
 * the vault holds at most a few thousand memories, cosine is cheap.
 */
export class Embedder {
  private ollama: OllamaClient;
  private cfg: JarvisConfig;
  private availableCache: boolean | null = null;

  constructor(ollama: OllamaClient, cfg: JarvisConfig) {
    this.ollama = ollama;
    this.cfg = cfg;
  }

  get model(): string {
    return this.cfg.ollama.embed_model;
  }

  /** True when the configured embedding model is actually installed. */
  async available(): Promise<boolean> {
    if (this.availableCache !== null) return this.availableCache;
    try {
      const models = await this.ollama.listModels();
      this.availableCache = this.ollama.hasModel(models, this.model);
    } catch {
      this.availableCache = false;
    }
    return this.availableCache;
  }

  resetCache(): void {
    this.availableCache = null;
  }

  /** Embed one or more texts; returns [] when the model is unavailable. */
  async embed(texts: string[]): Promise<number[][]> {
    if (texts.length === 0) return [];
    if (!(await this.available())) return [];
    try {
      const vectors = await this.ollama.embed(this.model, texts);
      return vectors;
    } catch (err) {
      log.warn(`embed failed: ${err instanceof Error ? err.message : String(err)}`);
      return [];
    }
  }

  async embedOne(text: string): Promise<number[] | null> {
    const out = await this.embed([text]);
    return out.length > 0 ? out[0] : null;
  }

  static cosine(a: number[] | Float32Array, b: number[] | Float32Array): number {
    const n = Math.min(a.length, b.length);
    if (n === 0) return 0;
    let dot = 0;
    let na = 0;
    let nb = 0;
    for (let i = 0; i < n; i += 1) {
      dot += a[i] * b[i];
      na += a[i] * a[i];
      nb += b[i] * b[i];
    }
    if (na === 0 || nb === 0) return 0;
    return dot / (Math.sqrt(na) * Math.sqrt(nb));
  }

  static toBuffer(vec: number[]): Buffer {
    return Buffer.from(new Float32Array(vec).buffer);
  }

  static fromBuffer(buf: Buffer): Float32Array {
    return new Float32Array(buf.buffer, buf.byteOffset, Math.floor(buf.byteLength / 4));
  }
}
