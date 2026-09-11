import { spawn } from 'node:child_process';
import { existsSync, readFileSync, openSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';
import { loadConfig, jarvisHome } from './config.ts';
import { OllamaClient } from './llm/ollama.ts';
import { createLogger } from './logger.ts';

const log = createLogger('cli');
const REPO_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const DAEMON_ENTRY = path.join(REPO_ROOT, 'src/daemon.ts');

function dataDir(): string {
  return loadConfig().daemon.data_dir;
}

function pidFile(): string {
  return path.join(dataDir(), 'jarvis.pid');
}

function logFile(): string {
  return path.join(dataDir(), 'daemon.log');
}

function readPid(): number | null {
  const file = pidFile();
  if (!existsSync(file)) return null;
  const pid = Number(readFileSync(file, 'utf8').trim());
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

function isRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function portOpen(port: number): Promise<boolean> {
  try {
    const res = await fetch(`http://localhost:${port}/api/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}

function cmdStart(detach: boolean): void {
  const cfg = loadConfig();
  const existing = readPid();
  if (existing && isRunning(existing)) {
    console.log(`JARVIS is already running (pid ${existing}) — http://localhost:${cfg.daemon.port}`);
    return;
  }
  const nodeArgs = ['--disable-warning=ExperimentalWarning'];
  if (!detach) {
    console.log('Starting JARVIS in the foreground (Ctrl+C to stop)…');
    const child = spawn(process.execPath, [...nodeArgs, DAEMON_ENTRY], { stdio: 'inherit', env: process.env });
    child.on('exit', (code) => process.exit(code ?? 0));
    return;
  }
  mkdirSync(cfg.daemon.data_dir, { recursive: true });
  const out = openSync(logFile(), 'a');
  const child = spawn(process.execPath, [...nodeArgs, DAEMON_ENTRY], {
    detached: true,
    stdio: ['ignore', out, out],
    env: process.env,
  });
  child.unref();
  console.log(`JARVIS starting in background (pid ${child.pid}), logs → ${logFile()}`);
  console.log(`Dashboard: http://localhost:${cfg.daemon.port}`);
}

function cmdStop(): void {
  const pid = readPid();
  if (!pid || !isRunning(pid)) {
    console.log('JARVIS is not running.');
    return;
  }
  process.kill(pid, 'SIGTERM');
  console.log(`Sent SIGTERM to pid ${pid}.`);
  for (let i = 0; i < 20; i += 1) {
    if (!isRunning(pid)) {
      console.log('Stopped.');
      return;
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
  }
  console.warn('Still running after 5s — consider `kill -9`.');
}

async function cmdStatus(): Promise<void> {
  const cfg = loadConfig();
  const pid = readPid();
  const running = pid !== null && isRunning(pid);
  console.log(`pid:        ${pid ?? '-'} (${running ? 'running' : 'not running'})`);
  console.log(`port:       ${cfg.daemon.port}`);
  console.log(`model:      ${cfg.ollama.model}`);
  console.log(`authority:  ${cfg.authority.level}`);
  console.log(`data dir:   ${cfg.daemon.data_dir}`);
  if (await portOpen(cfg.daemon.port)) {
    const res = await fetch(`http://localhost:${cfg.daemon.port}/api/health`);
    const health = (await res.json()) as Record<string, unknown>;
    console.log(`ollama:     ${(health.ollama as { reachable: boolean }).reachable ? 'reachable' : 'UNREACHABLE'}`);
  }
}

async function cmdDoctor(): Promise<void> {
  console.log('JARVIS doctor\n');
  const major = Number(process.versions.node.split('.')[0]);
  console.log(`${major >= 22 ? '✓' : '✗'} Node ${process.versions.node} (>= 22.13 required for built-in sqlite)`);

  const cfg = loadConfig();
  const ollama = new OllamaClient(cfg.ollama.base_url);
  const up = await ollama.ok();
  console.log(`${up ? '✓' : '✗'} Ollama at ${cfg.ollama.base_url}${up ? '' : ' — start it with `ollama serve`'}`);
  if (up) {
    const models = await ollama.listModels();
    console.log(`  installed models: ${models.map((m) => m.name).join(', ') || '(none)'}`);
    for (const wanted of [cfg.ollama.model, cfg.ollama.fast_model, cfg.ollama.embed_model]) {
      const have = ollama.hasModel(models, wanted);
      const note = wanted === cfg.ollama.embed_model ? ' (semantic memory)' : '';
      console.log(`${have ? '✓' : '✗'} ${wanted}${note}${have ? '' : ` — pull it with \`ollama pull ${wanted}\``}`);
    }
  }

  const busy = await portOpen(cfg.daemon.port);
  const pid = readPid();
  if (busy && pid && isRunning(pid)) console.log(`✓ daemon already on port ${cfg.daemon.port} (pid ${pid})`);
  else if (busy) console.log(`! port ${cfg.daemon.port} is taken by something else`);
  else console.log(`✓ port ${cfg.daemon.port} is free`);

  console.log(`✓ JARVIS_HOME: ${jarvisHome()}`);
  console.log(`✓ authority level: ${cfg.authority.level} (0 read-only … 4 shell)`);
}

async function cmdChat(): Promise<void> {
  const cfg = loadConfig();
  const base = `http://localhost:${cfg.daemon.port}`;
  if (!(await portOpen(cfg.daemon.port))) {
    console.log(`JARVIS daemon is not responding on port ${cfg.daemon.port}. Start it with \`jarvis start\`.`);
    process.exit(1);
  }
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  let conversationId: number | null = null;
  console.log('Chat with JARVIS. Commands: /new (new conversation) /quit');
  const ask = (): void => {
    rl.question('\nyou › ', async (line) => {
      const text = line.trim();
      if (!text) return ask();
      if (text === '/quit') {
        rl.close();
        return;
      }
      if (text === '/new') {
        conversationId = null;
        console.log('(new conversation)');
        return ask();
      }
      process.stdout.write('jarvis › ');
      try {
        const res = await fetch(`${base}/api/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ message: text, conversation_id: conversationId, stream: true }),
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
            if (!dataLine) continue;
            const data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;
            if (block.startsWith('event: token')) process.stdout.write(String(data.delta ?? ''));
            if (block.startsWith('event: done')) {
              conversationId = Number(data.conversation_id);
              process.stdout.write('\n');
            }
            if (block.startsWith('event: error')) console.error(`\n[error] ${data.message}`);
          }
        }
      } catch (err) {
        console.error(`\n[error] ${err instanceof Error ? err.message : String(err)}`);
      }
      ask();
    });
  };
  ask();
}

export function runCli(argv: string[]): void {
  const [cmd, ...rest] = argv;
  switch (cmd) {
    case undefined:
    case 'help':
    case '--help':
      console.log(`JARVIS — Just A Rather Very Intelligent System (Ollama Edition)

Usage: jarvis <command>

  start [-d]     Start the daemon (foreground, or detached with -d)
  stop           Stop the background daemon
  restart        Restart the daemon
  status         Show daemon status
  doctor         Check environment (node, ollama, models, port)
  chat           Chat with the running daemon in the terminal
  logs           Show the daemon log (add -f to follow)
  pull <model>   Pull a model from the Ollama registry
  help           This help
`);
      break;
    case 'start':
      cmdStart(rest.includes('-d'));
      break;
    case 'stop':
      cmdStop();
      break;
    case 'restart':
      cmdStop();
      setTimeout(() => cmdStart(rest.includes('-d')), 500);
      break;
    case 'status':
      void cmdStatus();
      break;
    case 'doctor':
      void cmdDoctor();
      break;
    case 'chat':
      void cmdChat();
      break;
    case 'logs': {
      const file = logFile();
      if (!existsSync(file)) {
        console.log('No log file yet (start the daemon with `jarvis start -d`).');
        break;
      }
      const args = rest.includes('-f') ? ['-F', file] : ['-n', '200', file];
      const child = spawn('tail', args, { stdio: 'inherit' });
      child.on('exit', (code) => process.exit(code ?? 0));
      break;
    }
    case 'pull': {
      const model = rest[0];
      if (!model) {
        console.log('Usage: jarvis pull <model>');
        process.exit(1);
      }
      void (async () => {
        const cfg = loadConfig();
        const ollama = new OllamaClient(cfg.ollama.base_url);
        if (!(await ollama.ok())) {
          console.error(`Cannot reach Ollama at ${cfg.ollama.base_url} — run \`ollama serve\` first.`);
          process.exit(1);
        }
        console.log(`Pulling ${model}…`);
        await ollama.pull(model, (status) => process.stdout.write(`\r${status.padEnd(60)}`));
        console.log(`\nDone: ${model}`);
      })().catch((err) => {
        console.error(String(err));
        process.exit(1);
      });
      break;
    }
    default:
      console.error(`Unknown command: ${cmd}. Try \`jarvis help\`.`);
      process.exit(1);
  }
}
