import path from 'node:path';
import type { JarvisConfig } from './config.ts';
import { Db } from './store/db.ts';
import { OllamaClient } from './llm/ollama.ts';
import { LlmProvider } from './llm/provider.ts';
import { KnowledgeVault } from './memory/vault.ts';
import { GoalTracker } from './goals/goals.ts';
import { Orchestrator } from './agent/orchestrator.ts';
import { Routines } from './goals/routines.ts';
import { Observer } from './observer/watcher.ts';
import { CronScheduler } from './cron.ts';
import { setLogLevel, createLogger } from './logger.ts';
import { publish } from './events.ts';

const log = createLogger('app');

/** Everything wired together — the object the HTTP server and CLI consume. */
export interface App {
  cfg: JarvisConfig;
  db: Db;
  ollama: OllamaClient;
  llm: LlmProvider;
  vault: KnowledgeVault;
  goals: GoalTracker;
  orchestrator: Orchestrator;
  routines: Routines;
  observer: Observer;
  cron: CronScheduler;
  startedAt: Date;
  start(): void;
  stop(): void;
}

export function createApp(cfg: JarvisConfig): App {
  setLogLevel(cfg.daemon.log_level);
  const db = new Db(path.join(cfg.daemon.data_dir, 'jarvis.db'));
  const ollama = new OllamaClient(cfg.ollama.base_url);
  const llm = new LlmProvider(ollama, cfg);
  const vault = new KnowledgeVault(db);
  const goals = new GoalTracker(db);
  const orchestrator = new Orchestrator({ cfg, db, llm, vault, goals });
  const routines = new Routines(llm, goals, vault);
  const observer = new Observer(cfg, llm, vault);
  const cron = new CronScheduler();

  const app: App = {
    cfg,
    db,
    ollama,
    llm,
    vault,
    goals,
    orchestrator,
    routines,
    observer,
    cron,
    startedAt: new Date(),

    start() {
      cron.schedule('morning', cfg.cron.morning, () => routines.morning());
      cron.schedule('evening', cfg.cron.evening, () => routines.evening());
      cron.schedule('hourly', cfg.cron.hourly, () => routines.hourlyHeartbeat());
      observer.start();
      publish('daemon:started', {
        port: cfg.daemon.port,
        model: cfg.ollama.model,
        authority: cfg.authority.level,
      });
      log.info(
        `JARVIS online — port ${cfg.daemon.port}, model ${cfg.ollama.model}, authority ${cfg.authority.level}`,
      );
    },

    stop() {
      cron.stop();
      observer.stop();
      db.close();
      publish('daemon:stopped', {});
    },
  };
  return app;
}
