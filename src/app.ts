import path from 'node:path';
import type { JarvisConfig } from './config.ts';
import { jarvisHome } from './config.ts';
import { Db } from './store/db.ts';
import { OllamaClient } from './llm/ollama.ts';
import { LlmProvider } from './llm/provider.ts';
import { Embedder } from './memory/embedder.ts';
import { KnowledgeVault } from './memory/vault.ts';
import { GoalTracker } from './goals/goals.ts';
import { Orchestrator } from './agent/orchestrator.ts';
import { ApprovalManager } from './agent/approvals.ts';
import { Routines } from './goals/routines.ts';
import { Observer } from './observer/watcher.ts';
import { WorkflowEngine } from './workflows/engine.ts';
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
  embedder: Embedder;
  vault: KnowledgeVault;
  goals: GoalTracker;
  approvals: ApprovalManager;
  orchestrator: Orchestrator;
  routines: Routines;
  observer: Observer;
  workflows: WorkflowEngine;
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
  const embedder = new Embedder(ollama, cfg);
  const vault = new KnowledgeVault(db, embedder);
  const goals = new GoalTracker(db);
  const approvals = new ApprovalManager(db, cfg.authority.ask_timeout_ms);
  const orchestrator = new Orchestrator({ cfg, db, llm, vault, goals, approvals });
  const routines = new Routines(llm, goals, vault);
  const observer = new Observer(cfg, llm, vault);
  const cron = new CronScheduler();
  const workflows = new WorkflowEngine({ cfg, db, llm, orchestrator, cron, home: jarvisHome() });

  const app: App = {
    cfg,
    db,
    ollama,
    llm,
    embedder,
    vault,
    goals,
    approvals,
    orchestrator,
    routines,
    observer,
    workflows,
    cron,
    startedAt: new Date(),

    start() {
      cron.schedule('morning', cfg.cron.morning, () => routines.morning());
      cron.schedule('evening', cfg.cron.evening, () => routines.evening());
      cron.schedule('hourly', cfg.cron.hourly, () => routines.hourlyHeartbeat());
      observer.start();
      workflows.start();
      // Best-effort: index any vault entries that predate the embedder.
      void (async () => {
        try {
          if (await embedder.available()) await vault.backfill();
        } catch (err) {
          log.warn(`embedding backfill skipped: ${err instanceof Error ? err.message : String(err)}`);
        }
      })();
      publish('daemon:started', {
        port: cfg.daemon.port,
        model: cfg.ollama.model,
        authority: cfg.authority.level,
        authority_mode: cfg.authority.mode,
      });
      log.info(
        `JARVIS online — port ${cfg.daemon.port}, model ${cfg.ollama.model}, authority ${cfg.authority.level} (${cfg.authority.mode})`,
      );
    },

    stop() {
      cron.stop();
      observer.stop();
      workflows.stop();
      db.close();
      publish('daemon:stopped', {});
    },
  };
  return app;
}
