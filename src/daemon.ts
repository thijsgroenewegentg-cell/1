import { writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { loadConfig } from './config.ts';
import { createApp } from './app.ts';
import { createServer } from './server/http.ts';
import { createLogger } from './logger.ts';

const log = createLogger('daemon');

/**
 * JARVIS daemon entrypoint: loads config, wires every module, serves the
 * dashboard + API, and stays up 24/7 until stopped.
 */
async function main(): Promise<void> {
  const cfg = loadConfig();
  const app = createApp(cfg);
  const server = createServer(app);

  const pidFile = path.join(cfg.daemon.data_dir, 'jarvis.pid');

  server.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      log.error(`port ${cfg.daemon.port} is already in use — is another JARVIS running? (\`jarvis stop\`)`);
      process.exit(1);
    }
    log.error('server error:', err);
  });

  await new Promise<void>((resolve) => {
    server.listen(cfg.daemon.port, cfg.daemon.host, resolve);
  });
  writeFileSync(pidFile, String(process.pid));
  log.info(`dashboard → http://localhost:${cfg.daemon.port}`);

  app.start();

  const shutdown = (signal: string): void => {
    log.info(`received ${signal}, shutting down…`);
    server.close();
    app.stop();
    try {
      rmSync(pidFile, { force: true });
    } catch {
      /* ignore */
    }
    process.exit(0);
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

main().catch((err) => {
  console.error('JARVIS failed to start:', err);
  process.exit(1);
});
