/**
 * Mock voice endpoints for tests: whisper.cpp (STT), Piper (TTS),
 * ElevenLabs (voices + TTS + usage).
 */
'use strict';

const http = require('http');

function start(port, host = '127.0.0.1') {
  const seen = { whisper: [], piper: [], eleven: [] };
  const server = http.createServer((req, res) => {
    let body = [];
    req.on('data', (c) => body.push(c));
    req.on('end', () => {
      const buf = Buffer.concat(body);
      const text = buf.toString('utf8');

      if (req.url.startsWith('/v1/audio/transcriptions')) {
        seen.whisper.push({ bytes: buf.length, multipart: /multipart/.test(req.headers['content-type'] || ''), body: text.slice(0, 2000) });
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ text: 'goedemorgen ultron' }));
        return;
      }
      if (req.url === '/api/tts') {
        seen.piper.push(text.slice(0, 200));
        res.writeHead(200, { 'Content-Type': 'audio/wav' });
        res.end(Buffer.from('RIFF-FAKE-PIPER-WAV'));
        return;
      }
      if (req.url === '/v1/voices') {
        seen.eleven.push({ key: req.headers['xi-api-key'] });
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ voices: [{ voice_id: 'adam-1', name: 'Adam', category: 'premade' }] }));
        return;
      }
      if (req.url.startsWith('/v1/text-to-speech/')) {
        seen.eleven.push({ key: req.headers['xi-api-key'], voice: req.url.split('/')[3], body: text.slice(0, 200) });
        res.writeHead(200, { 'Content-Type': 'audio/mpeg' });
        res.end(Buffer.from('ID3-FAKE-ELEVEN-MP3'));
        return;
      }
      if (req.url === '/v1/user/subscription') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ character_count: 1234, character_limit: 10000, tier: 'free', next_character_count_reset_unix: 1893456000 }));
        return;
      }
      res.writeHead(404);
      res.end();
    });
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve({ server, seen })));
}

module.exports = { start };
