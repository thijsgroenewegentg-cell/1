import { spawn, spawnSync } from 'node:child_process';
import { writeFileSync, unlinkSync, mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { JarvisConfig } from '../config.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('voice');

/**
 * Optional server-side voice: Piper TTS and whisper.cpp STT. Both are plain
 * binaries the user may or may not have installed — when absent, the
 * dashboard falls back to the browser's Web Speech API. No bundled deps.
 */

export interface VoiceStatus {
  tts: { provider: string; available: boolean; detail: string };
  stt: { provider: string; available: boolean; detail: string };
}

function binaryExists(bin: string): boolean {
  if (!bin) return false;
  try {
    const res = spawnSync(bin, ['--help'], { timeout: 3000, stdio: 'ignore' });
    return res.error === undefined; // ENOENT etc. land in res.error
  } catch {
    return false;
  }
}

export function voiceStatus(cfg: JarvisConfig): VoiceStatus {
  const piperOk = cfg.voice.tts_provider === 'piper' && binaryExists(cfg.voice.piper_path);
  const whisperOk =
    cfg.voice.stt_provider === 'whisper' &&
    binaryExists(cfg.voice.whisper_path) &&
    cfg.voice.whisper_model !== '';
  return {
    tts: {
      provider: cfg.voice.tts_provider,
      available: piperOk,
      detail: piperOk ? `piper (${cfg.voice.piper_voice || 'default voice'})` : 'browser speechSynthesis',
    },
    stt: {
      provider: cfg.voice.stt_provider,
      available: whisperOk,
      detail: whisperOk ? `whisper.cpp (${path.basename(cfg.voice.whisper_model)})` : 'browser SpeechRecognition',
    },
  };
}

/** Wrap raw PCM16 mono bytes into a minimal WAV container. */
export function wavHeader(dataLength: number, sampleRate: number, channels = 1): Buffer {
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + dataLength, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16); // fmt chunk size
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * channels * 2, 28);
  header.writeUInt16LE(channels * 2, 32);
  header.writeUInt16LE(16, 34); // bits per sample
  header.write('data', 36);
  header.writeUInt32LE(dataLength, 40);
  return header;
}

const PIPER_SAMPLE_RATE = 22050;

/** Synthesize speech with Piper; throws when unavailable or it fails. */
export function piperTts(cfg: JarvisConfig, text: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    if (cfg.voice.tts_provider !== 'piper') return reject(new Error('piper TTS is not configured'));
    const args = ['--output-raw'];
    if (cfg.voice.piper_voice) args.push('--model', cfg.voice.piper_voice);
    const child = spawn(cfg.voice.piper_path, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    const chunks: Buffer[] = [];
    let stderr = '';
    child.stdout.on('data', (c: Buffer) => chunks.push(c));
    child.stderr.on('data', (c: Buffer) => (stderr += c.toString()));
    child.on('error', (err) => reject(new Error(`piper not available: ${err.message}`)));
    child.on('close', (code) => {
      if (code !== 0) {
        log.warn(`piper exited ${code}: ${stderr.slice(0, 300)}`);
        return reject(new Error(`piper exited with code ${code}`));
      }
      const raw = Buffer.concat(chunks);
      resolve(Buffer.concat([wavHeader(raw.length, PIPER_SAMPLE_RATE), raw]));
    });
    child.stdin.write(text);
    child.stdin.end();
  });
}

/** Transcribe a 16-bit mono WAV buffer with whisper.cpp; returns plain text. */
export function whisperStt(cfg: JarvisConfig, wav: Buffer): Promise<string> {
  return new Promise((resolve, reject) => {
    if (cfg.voice.stt_provider !== 'whisper') return reject(new Error('whisper STT is not configured'));
    const dir = mkdtempSync(path.join(os.tmpdir(), 'jarvis-stt-'));
    const file = path.join(dir, 'speech.wav');
    try {
      writeFileSync(file, wav);
    } catch (err) {
      return reject(new Error(`could not stage audio: ${String(err)}`));
    }
    const child = spawn(cfg.voice.whisper_path, ['-m', cfg.voice.whisper_model, '-f', file, '-nt'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (c: Buffer) => (stdout += c.toString()));
    child.stderr.on('data', (c: Buffer) => (stderr += c.toString()));
    child.on('error', (err) => {
      unlinkQuiet(file);
      reject(new Error(`whisper not available: ${err.message}`));
    });
    child.on('close', (code) => {
      unlinkQuiet(file);
      if (code !== 0) {
        log.warn(`whisper exited ${code}: ${stderr.slice(0, 300)}`);
        return reject(new Error(`whisper exited with code ${code}`));
      }
      resolve(stdout.replace(/\s+/g, ' ').trim());
    });
  });
}

function unlinkQuiet(file: string): void {
  try {
    unlinkSync(file);
  } catch {
    /* ignore */
  }
}
