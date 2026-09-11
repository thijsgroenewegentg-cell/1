import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { parse } from 'yaml';

export interface JarvisConfig {
  daemon: { host: string; port: number; data_dir: string; log_level: string };
  ollama: {
    base_url: string;
    model: string;
    fast_model: string;
    embed_model: string;
    temperature: number;
    keep_alive: string;
  };
  authority: { level: number; mode: 'ask' | 'gate'; ask_timeout_ms: number };
  agent: { max_turns: number; max_delegation_depth: number };
  observer: { enabled: boolean; paths: string[]; interval_ms: number; debounce_ms: number };
  cron: { morning: string; evening: string; hourly: string };
  personality: { name: string; core_traits: string[] };
  voice: {
    tts_provider: 'browser' | 'piper';
    piper_path: string;
    piper_voice: string;
    stt_provider: 'browser' | 'whisper';
    whisper_path: string;
    whisper_model: string;
  };
}

export const DEFAULT_CONFIG: JarvisConfig = {
  daemon: { host: '0.0.0.0', port: 3142, data_dir: './data', log_level: 'info' },
  ollama: {
    base_url: 'http://localhost:11434',
    model: 'llama3.2',
    fast_model: 'llama3.2:1b',
    embed_model: 'nomic-embed-text',
    temperature: 0.7,
    keep_alive: '30m',
  },
  authority: { level: 3, mode: 'ask', ask_timeout_ms: 300_000 },
  agent: { max_turns: 8, max_delegation_depth: 2 },
  observer: { enabled: false, paths: [], interval_ms: 2000, debounce_ms: 800 },
  cron: { morning: '0 7 * * *', evening: '0 20 * * *', hourly: '37 * * * *' },
  personality: { name: 'Jarvis', core_traits: ['loyal', 'efficient', 'proactive', 'respectful'] },
  voice: {
    tts_provider: 'browser',
    piper_path: 'piper',
    piper_voice: '',
    stt_provider: 'browser',
    whisper_path: 'whisper-cli',
    whisper_model: '',
  },
};

/** JARVIS_HOME is where config.yaml + the sqlite db live. Defaults to ./data-less repo dir. */
export function jarvisHome(): string {
  return process.env.JARVIS_HOME ?? process.cwd();
}

function deepMerge<T>(base: T, override: unknown): T {
  if (override === null || override === undefined) return base;
  if (typeof base !== 'object' || base === null || Array.isArray(base)) return override as T;
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(override as Record<string, unknown>)) {
    out[k] = deepMerge((base as Record<string, unknown>)[k], v);
  }
  return out as T;
}

function envOverrides(cfg: JarvisConfig): JarvisConfig {
  const env = process.env;
  if (env.JARVIS_HOST) cfg.daemon.host = env.JARVIS_HOST;
  if (env.JARVIS_PORT) cfg.daemon.port = Number(env.JARVIS_PORT);
  if (env.JARVIS_DATA_DIR) cfg.daemon.data_dir = env.JARVIS_DATA_DIR;
  if (env.JARVIS_LOG_LEVEL) cfg.daemon.log_level = env.JARVIS_LOG_LEVEL;
  if (env.JARVIS_OLLAMA_URL || env.OLLAMA_HOST) {
    cfg.ollama.base_url = env.JARVIS_OLLAMA_URL ?? `http://${env.OLLAMA_HOST}`;
  }
  if (env.JARVIS_OLLAMA_MODEL) cfg.ollama.model = env.JARVIS_OLLAMA_MODEL;
  if (env.JARVIS_OLLAMA_FAST_MODEL) cfg.ollama.fast_model = env.JARVIS_OLLAMA_FAST_MODEL;
  if (env.JARVIS_AUTHORITY_LEVEL) cfg.authority.level = Number(env.JARVIS_AUTHORITY_LEVEL);
  return cfg;
}

export function loadConfig(home: string = jarvisHome()): JarvisConfig {
  let cfg = structuredClone(DEFAULT_CONFIG);
  const file = path.join(home, 'config.yaml');
  if (existsSync(file)) {
    const parsed = parse(readFileSync(file, 'utf8')) as Partial<JarvisConfig> | null;
    cfg = deepMerge(cfg, parsed ?? {});
  }
  cfg = envOverrides(cfg);
  // Clamp authority into the documented 0..4 band.
  if (!Number.isInteger(cfg.authority.level)) cfg.authority.level = 3;
  cfg.authority.level = Math.max(0, Math.min(4, cfg.authority.level));
  const dataDir = path.isAbsolute(cfg.daemon.data_dir)
    ? cfg.daemon.data_dir
    : path.join(home, cfg.daemon.data_dir);
  cfg.daemon.data_dir = dataDir;
  mkdirSync(dataDir, { recursive: true });
  return cfg;
}
