import { createLogger } from '../logger.ts';

const log = createLogger('ollama');

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ToolCall {
  function: { name: string; arguments: Record<string, unknown> };
}

export interface ToolSpec {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface ChatOptions {
  model?: string;
  temperature?: number;
  keep_alive?: string;
  tools?: ToolSpec[];
}

export interface OllamaModel {
  name: string;
  size: number;
  modified_at?: string;
}

export class OllamaError extends Error {}

/** Client for a local (or remote) Ollama server. No SDK, just HTTP + ndjson. */
export class OllamaClient {
  baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  /** True when the server is reachable at all. */
  async ok(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/api/tags`, { signal: AbortSignal.timeout(2500) });
      return res.ok;
    } catch {
      return false;
    }
  }

  async listModels(): Promise<OllamaModel[]> {
    const res = await this.request('GET', '/api/tags');
    const data = (await res.json()) as { models?: OllamaModel[] };
    return data.models ?? [];
  }

  hasModel(models: OllamaModel[], wanted: string): boolean {
    const norm = (n: string) => n.replace(/:latest$/, '');
    return models.some((m) => norm(m.name) === norm(wanted));
  }

  /** Pull a model, reporting progress lines via onProgress. */
  async pull(model: string, onProgress?: (status: string) => void): Promise<void> {
    const res = await this.request('POST', '/api/pull', { model, stream: true });
    for await (const line of this.ndjsonLines(res)) {
      const obj = JSON.parse(line) as { status?: string; error?: string };
      if (obj.error) throw new OllamaError(`ollama pull failed: ${obj.error}`);
      if (obj.status && onProgress) onProgress(obj.status);
    }
  }

  /** Non-streaming chat completion. Returns the final assistant message. */
  async chat(messages: ChatMessage[], opts: ChatOptions = {}): Promise<{ content: string; tool_calls: ToolCall[] }> {
    const res = await this.request('POST', '/api/chat', this.chatBody(messages, { ...opts }, false));
    const data = (await res.json()) as {
      message?: { content?: string; tool_calls?: ToolCall[] };
      error?: string;
    };
    if (data.error) throw new OllamaError(`ollama chat error: ${data.error}`);
    return { content: data.message?.content ?? '', tool_calls: data.message?.tool_calls ?? [] };
  }

  /**
   * Streaming chat completion. `onToken` fires for every content delta.
   * Tool-call models stream tool_calls on the final chunk; we accumulate them.
   */
  async chatStream(
    messages: ChatMessage[],
    opts: ChatOptions,
    onToken: (delta: string) => void,
  ): Promise<{ content: string; tool_calls: ToolCall[] }> {
    const res = await this.request('POST', '/api/chat', this.chatBody(messages, opts, true));
    let content = '';
    const toolCalls: ToolCall[] = [];
    for await (const line of this.ndjsonLines(res)) {
      let obj: {
        message?: { content?: string; tool_calls?: ToolCall[] };
        done?: boolean;
        error?: string;
      };
      try {
        obj = JSON.parse(line) as typeof obj;
      } catch {
        continue;
      }
      if (obj.error) throw new OllamaError(`ollama chat error: ${obj.error}`);
      const delta = obj.message?.content ?? '';
      if (delta) {
        content += delta;
        onToken(delta);
      }
      if (obj.message?.tool_calls?.length) toolCalls.push(...obj.message.tool_calls);
    }
    return { content, tool_calls: toolCalls };
  }

  /** Embeddings via /api/embed (used for semantic memory search when available). */
  async embed(model: string, input: string | string[]): Promise<number[][]> {
    const res = await this.request('POST', '/api/embed', { model, input });
    const data = (await res.json()) as { embeddings?: number[][]; error?: string };
    if (data.error) throw new OllamaError(`ollama embed error: ${data.error}`);
    return data.embeddings ?? [];
  }

  private chatBody(messages: ChatMessage[], opts: ChatOptions, stream: boolean): Record<string, unknown> {
    const body: Record<string, unknown> = {
      model: opts.model,
      messages,
      stream,
      keep_alive: opts.keep_alive ?? '30m',
      options: { temperature: opts.temperature ?? 0.7 },
    };
    if (opts.tools?.length) body.tools = opts.tools;
    return body;
  }

  private async request(method: string, pathName: string, body?: unknown): Promise<Response> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${pathName}`, {
        method,
        headers: { 'content-type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new OllamaError(
        `Cannot reach Ollama at ${this.baseUrl} — is it running? Start it with \`ollama serve\`. (${String(err)})`,
      );
    }
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new OllamaError(`Ollama ${method} ${pathName} → HTTP ${res.status}: ${text.slice(0, 300)}`);
    }
    return res;
  }

  private async *ndjsonLines(res: Response): AsyncGenerator<string> {
    if (!res.body) return;
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for await (const chunk of res.body as unknown as AsyncIterable<Uint8Array>) {
        buffer += decoder.decode(chunk, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (line) yield line;
        }
      }
      if (buffer.trim()) yield buffer.trim();
    } catch (err) {
      log.error('stream read failed:', err);
      throw new OllamaError(`Ollama stream interrupted: ${String(err)}`);
    }
  }
}
