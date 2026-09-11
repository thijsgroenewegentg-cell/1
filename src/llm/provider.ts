import type { JarvisConfig } from '../config.ts';
import type { ChatMessage, ChatOptions, OllamaClient, ToolCall } from './ollama.ts';

/**
 * The LLM tier router. The original JARVIS routes between providers/tiers;
 * here both tiers are Ollama models: a "smart" model for reasoning and a
 * "fast" model for cheap background work (observations, summaries, routing).
 */
export class LlmProvider {
  private ollama: OllamaClient;
  private cfg: JarvisConfig;

  constructor(ollama: OllamaClient, cfg: JarvisConfig) {
    this.ollama = ollama;
    this.cfg = cfg;
  }

  get smartModel(): string {
    return this.cfg.ollama.model;
  }

  get fastModel(): string {
    return this.cfg.ollama.fast_model || this.cfg.ollama.model;
  }

  async complete(
    system: string,
    messages: ChatMessage[],
    opts: ChatOptions & { tier?: 'smart' | 'fast' } = {},
  ): Promise<{ content: string; tool_calls: ToolCall[] }> {
    const model = opts.tier === 'fast' ? this.fastModel : opts.model ?? this.smartModel;
    const full: ChatMessage[] = [{ role: 'system', content: system }, ...messages];
    return this.ollama.chat(full, {
      model,
      temperature: opts.temperature ?? this.cfg.ollama.temperature,
      keep_alive: this.cfg.ollama.keep_alive,
      tools: opts.tools,
    });
  }

  async stream(
    system: string,
    messages: ChatMessage[],
    onToken: (delta: string) => void,
    opts: ChatOptions & { tier?: 'smart' | 'fast' } = {},
  ): Promise<{ content: string; tool_calls: ToolCall[] }> {
    const model = opts.tier === 'fast' ? this.fastModel : opts.model ?? this.smartModel;
    const full: ChatMessage[] = [{ role: 'system', content: system }, ...messages];
    return this.ollama.chatStream(
      full,
      {
        model,
        temperature: opts.temperature ?? this.cfg.ollama.temperature,
        keep_alive: this.cfg.ollama.keep_alive,
        tools: opts.tools,
      },
      onToken,
    );
  }
}
