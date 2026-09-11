#!/usr/bin/env node
// Re-exec with the experimental-SQLite warning silenced, then hand off to the CLI.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

if (!process.env.JARVIS_CLI_REEXEC) {
  const child = spawn(
    process.execPath,
    ['--disable-warning=ExperimentalWarning', fileURLToPath(import.meta.url), ...process.argv.slice(2)],
    { stdio: 'inherit', env: { ...process.env, JARVIS_CLI_REEXEC: '1' } },
  );
  child.on('exit', (code) => process.exit(code ?? 0));
} else {
  const { runCli } = await import('../src/cli.ts');
  runCli(process.argv.slice(2));
}
