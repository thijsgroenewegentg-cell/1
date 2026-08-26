/**
 * Mock Telegram Bot API for tests.
 * Script: first getUpdates returns a pairing message from chat 12345;
 * after the pairing sendMessage is seen, the next getUpdates returns a
 * real question from the same chat. sendMessage records everything.
 */
'use strict';

const http = require('http');

function start(port, host = '127.0.0.1') {
  const sent = [];
  let stage = 0; // 0 = pair message pending, 1 = question pending, 2 = done
  const server = http.createServer((req, res) => {
    let body = [];
    req.on('data', (c) => body.push(c));
    req.on('end', () => {
      const text = Buffer.concat(body).toString('utf8');
      const isToken = /\/botTESTTOKEN\//.test(req.url);

      if (!isToken) { res.writeHead(404); res.end(); return; }

      if (req.url.includes('/getUpdates')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        let updates = [];
        if (stage === 0) {
          updates = [{ update_id: 1, message: { chat: { id: 12345 }, text: 'hallo ultron' } }];
          stage = 1;
        } else if (stage === 2) {
          updates = [{ update_id: 2, message: { chat: { id: 12345 }, text: 'wat is twee plus twee' } }];
          stage = 3;
        } else if (stage === 4) {
          updates = [{ update_id: 3, message: { chat: { id: 12345 }, voice: { file_id: 'VOICETEST', duration: 2 } } }];
          stage = 5;
        }
        res.end(JSON.stringify({ ok: true, result: updates }));
        return;
      }
      if (req.url.includes('/getFile')) {
        const p = JSON.parse(text);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, result: { file_id: p.file_id, file_path: 'voice/note.oga' } }));
        return;
      }
      if (req.url.includes('/file/botTESTTOKEN/voice/note.oga')) {
        res.writeHead(200, { 'Content-Type': 'audio/ogg' });
        res.end(Buffer.from('FAKE-OGG-OPUS-AUDIO-BYTES'));
        return;
      }
      if (req.url.includes('/sendMessage')) {
        const p = JSON.parse(text);
        sent.push({ chat_id: p.chat_id, text: String(p.text || '') });
        if (stage === 1 && /Pairing complete/.test(p.text || '')) stage = 2;
        if (stage === 3 && /model=/.test(p.text || '')) stage = 4;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, result: { message_id: sent.length } }));
        return;
      }
      res.writeHead(404);
      res.end();
    });
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve({ server, sent, getStage: () => stage })));
}

module.exports = { start };
