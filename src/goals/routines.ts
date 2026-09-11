import type { LlmProvider } from '../llm/provider.ts';
import type { GoalTracker } from './goals.ts';
import type { KnowledgeVault } from '../memory/vault.ts';
import { publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('routines');

/**
 * Daily/weekly routines, JARVIS-style: a morning plan built from open goals,
 * an evening review, and an hourly heartbeat that flags deadlines.
 */
export class Routines {
  private llm: LlmProvider;
  private goals: GoalTracker;
  private vault: KnowledgeVault;

  constructor(llm: LlmProvider, goals: GoalTracker, vault: KnowledgeVault) {
    this.llm = llm;
    this.goals = goals;
    this.vault = vault;
  }

  async morning(): Promise<string> {
    const open = this.goals.list();
    const prompt =
      open.length === 0
        ? 'There are no open goals. Propose 1-3 meaningful goals for today.'
        : `Open goals:\n${open
            .map((g) => {
              const krs = this.goals.keyResults(g.id);
              const krText = krs.map((k) => `    - ${k.title} (${k.current}/${k.target})`).join('\n');
              return `- #${g.id} ${g.title}${g.deadline ? ` [deadline ${g.deadline}]` : ''}\n${krText}`;
            })
            .join('\n')}\n\nCreate a short, prioritized plan for today: top 3 actions, each tied to a goal when possible.`;
    const plan = await this.ask(`You are planning the user's day. Be concrete and brief.`, prompt);
    this.vault.remember({
      kind: 'commitment',
      title: `Morning plan — ${new Date().toISOString().slice(0, 10)}`,
      body: plan,
      tags: ['routine', 'morning'],
      source: 'cron',
    });
    publish('routine:morning', { plan: plan.slice(0, 500) });
    log.info('morning plan generated');
    return plan;
  }

  async evening(): Promise<string> {
    const open = this.goals.list();
    const observations = this.vault.search('observation', 5);
    const prompt = `Open goals:\n${open.map((g) => `- #${g.id} ${g.title}`).join('\n') || '(none)'}\n\nRecent observations:\n${
      observations.map((o) => `- ${o.title}: ${o.body.slice(0, 120)}`).join('\n') || '(none)'
    }\n\nWrite a short end-of-day review: what likely progressed, what stalled, and one thing to do first tomorrow.`;
    const review = await this.ask(
      "You are reviewing the user's day. Be encouraging and concrete.",
      prompt,
    );
    this.vault.remember({
      kind: 'observation',
      title: `Evening review — ${new Date().toISOString().slice(0, 10)}`,
      body: review,
      tags: ['routine', 'evening'],
      source: 'cron',
    });
    publish('routine:evening', { review: review.slice(0, 500) });
    log.info('evening review generated');
    return review;
  }

  hourlyHeartbeat(): { goal: { id: number; title: string }; days_left: number }[] {
    const alerts = this.goals.heartbeat();
    if (alerts.length > 0) log.info(`heartbeat: ${alerts.length} deadline alert(s)`);
    publish('routine:heartbeat', { alerts: alerts.length });
    return alerts.map((a) => ({ goal: { id: a.goal.id, title: a.goal.title }, days_left: a.days_left }));
  }

  private async ask(system: string, prompt: string): Promise<string> {
    try {
      const res = await this.llm.complete(system, [{ role: 'user', content: prompt }], { temperature: 0.5 });
      return res.content.trim() || '(the model returned an empty response)';
    } catch (err) {
      const msg = `Routine failed to reach the LLM: ${err instanceof Error ? err.message : String(err)}`;
      log.warn(msg);
      return msg;
    }
  }
}
