import { readdirSync, readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { parse } from 'yaml';
import { createLogger } from '../logger.ts';

const log = createLogger('workflows');

export interface WorkflowTrigger {
  type: 'file' | 'cron' | 'event' | 'webhook';
  path?: string; // file trigger (relative to the JARVIS home)
  expr?: string; // cron trigger
  event?: string; // event-bus trigger
  // webhook triggers are addressed by workflow id: POST /api/hooks/<id>
}

export interface WorkflowStep {
  action: string; // a tool name, or "llm"
  with?: Record<string, unknown>;
}

export interface Workflow {
  id: string;
  name: string;
  enabled: boolean;
  trigger: WorkflowTrigger;
  steps: WorkflowStep[];
  file: string;
}

/** Load and validate every workflow definition from <home>/workflows/*.yaml */
export function loadWorkflows(dir: string): Workflow[] {
  if (!existsSync(dir)) return [];
  const out: Workflow[] = [];
  for (const entry of readdirSync(dir)) {
    if (!/\.(ya?ml)$/i.test(entry)) continue;
    const file = path.join(dir, entry);
    try {
      const doc = parse(readFileSync(file, 'utf8')) as Partial<Workflow> & Record<string, unknown>;
      if (!doc || typeof doc !== 'object') continue;
      const wf = normalize(doc, file);
      if (wf) out.push(wf);
    } catch (err) {
      log.error(`skipping ${entry}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  return out;
}

function normalize(doc: Partial<Workflow> & Record<string, unknown>, file: string): Workflow | null {
  const trigger = doc.trigger as WorkflowTrigger | undefined;
  if (!trigger || !['file', 'cron', 'event', 'webhook'].includes(trigger.type)) {
    log.warn(`${path.basename(file)}: missing/invalid trigger — skipped`);
    return null;
  }
  if (trigger.type === 'file' && !trigger.path) return warnNull(file, 'file trigger needs a path');
  if (trigger.type === 'cron' && !trigger.expr) return warnNull(file, 'cron trigger needs an expr');
  if (trigger.type === 'event' && !trigger.event) return warnNull(file, 'event trigger needs an event name');
  const steps = Array.isArray(doc.steps) ? (doc.steps as WorkflowStep[]) : [];
  if (steps.length === 0) return warnNull(file, 'no steps defined');
  for (const [i, s] of steps.entries()) {
    if (!s || typeof s.action !== 'string') return warnNull(file, `step ${i} needs an action`);
  }
  return {
    id: String(doc.id ?? path.basename(file).replace(/\.(ya?ml)$/i, '')),
    name: String(doc.name ?? doc.id ?? path.basename(file)),
    enabled: doc.enabled !== false,
    trigger,
    steps,
    file,
  };
}

function warnNull(file: string, why: string): null {
  log.warn(`${path.basename(file)}: ${why} — skipped`);
  return null;
}

/**
 * Tiny mustache-ish templating: {{a.b.c}} resolves against the context.
 * Unknown paths become empty strings; objects are JSON-stringified.
 */
export function renderTemplate(template: string, ctx: Record<string, unknown>): string {
  return template.replace(/\{\{\s*([\w.[\]]+)\s*\}\}/g, (_match, key: string) => {
    const value = key.split('.').reduce<unknown>((acc, part) => {
      if (acc && typeof acc === 'object' && part in (acc as Record<string, unknown>)) {
        return (acc as Record<string, unknown>)[part];
      }
      return undefined;
    }, ctx);
    if (value === undefined || value === null) return '';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  });
}

/** Deep-render every string inside a step's `with` args. */
export function renderArgs(args: Record<string, unknown>, ctx: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(args)) {
    if (typeof v === 'string') out[k] = renderTemplate(v, ctx);
    else if (Array.isArray(v)) out[k] = v.map((x) => (typeof x === 'string' ? renderTemplate(x, ctx) : x));
    else out[k] = v;
  }
  return out;
}
