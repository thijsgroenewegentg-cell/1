/**
 * Minimal cron: standard 5-field expressions (m h dom mon dow) supporting
 * `*`, numbers, `a-b` ranges, `a,b,c` lists and `*\/n` steps. Good enough for
 * morning/evening/hourly routines; zero dependencies.
 */

function parseField(field: string, min: number, max: number): Set<number> {
  const values = new Set<number>();
  for (const part of field.split(',')) {
    let [rangePart, stepPart] = part.split('/');
    const step = stepPart === undefined ? 1 : Number(stepPart);
    if (!Number.isInteger(step) || step < 1) throw new Error(`bad cron step: ${part}`);
    let lo: number;
    let hi: number;
    if (rangePart === '*') {
      lo = min;
      hi = max;
    } else if (rangePart.includes('-')) {
      const [a, b] = rangePart.split('-').map(Number);
      lo = a;
      hi = b;
    } else {
      lo = hi = Number(rangePart);
      if (stepPart !== undefined) hi = max; // "5/15" style: from 5, every 15
    }
    if (!Number.isInteger(lo) || !Number.isInteger(hi)) throw new Error(`bad cron field: ${field}`);
    if (lo < min || hi > max || lo > hi) throw new Error(`cron field out of range: ${field}`);
    for (let v = lo; v <= hi; v += step) values.add(v);
  }
  return values;
}

export interface CronExpr {
  minutes: Set<number>;
  hours: Set<number>;
  daysOfMonth: Set<number>;
  months: Set<number>;
  daysOfWeek: Set<number>;
  source: string;
}

export function parseCron(expr: string): CronExpr {
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) throw new Error(`cron expression must have 5 fields: "${expr}"`);
  return {
    minutes: parseField(fields[0], 0, 59),
    hours: parseField(fields[1], 0, 23),
    daysOfMonth: parseField(fields[2], 1, 31),
    months: parseField(fields[3], 1, 12),
    daysOfWeek: parseField(fields[4], 0, 6),
    source: expr,
  };
}

export function cronMatches(cron: CronExpr, date: Date): boolean {
  return (
    cron.minutes.has(date.getMinutes()) &&
    cron.hours.has(date.getHours()) &&
    cron.daysOfMonth.has(date.getDate()) &&
    cron.months.has(date.getMonth() + 1) &&
    cron.daysOfWeek.has(date.getDay())
  );
}

export class CronScheduler {
  private timers: NodeJS.Timeout[] = [];
  private lastFired = new Map<string, string>();

  /** Register jobs; call start() to begin ticking. */
  schedule(name: string, expr: string, fn: () => void | Promise<void>): void {
    const cron = parseCron(expr);
    const timer = setInterval(() => {
      const now = new Date();
      const stamp = `${now.getHours()}:${now.getMinutes()}`;
      if (cronMatches(cron, now) && this.lastFired.get(name) !== stamp) {
        this.lastFired.set(name, stamp);
        Promise.resolve(fn()).catch((err) => {
          // keep the scheduler alive no matter what a job does
          console.error(`cron job ${name} failed:`, err);
        });
      }
    }, 15_000);
    timer.unref?.();
    this.timers.push(timer);
  }

  stop(): void {
    for (const t of this.timers) clearInterval(t);
    this.timers = [];
  }
}
