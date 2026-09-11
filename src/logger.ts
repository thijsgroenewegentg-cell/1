const LEVELS: Record<string, number> = { debug: 10, info: 20, warn: 30, error: 40, silent: 99 };

let currentLevel = LEVELS[process.env.JARVIS_LOG_LEVEL ?? 'info'] ?? LEVELS.info;

export function setLogLevel(level: string): void {
  if (LEVELS[level] !== undefined) currentLevel = LEVELS[level];
}

function emit(level: string, scope: string, args: unknown[]): void {
  if (LEVELS[level] < currentLevel) return;
  const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
  const line = `[${ts}] ${level.toUpperCase().padEnd(5)} ${scope.padEnd(12)}`;
  if (level === 'error') console.error(line, ...args);
  else if (level === 'warn') console.warn(line, ...args);
  else console.log(line, ...args);
}

export function createLogger(scope: string) {
  return {
    debug: (...args: unknown[]) => emit('debug', scope, args),
    info: (...args: unknown[]) => emit('info', scope, args),
    warn: (...args: unknown[]) => emit('warn', scope, args),
    error: (...args: unknown[]) => emit('error', scope, args),
  };
}
