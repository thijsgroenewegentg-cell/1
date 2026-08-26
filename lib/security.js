/**
 * SECURITY — rate limiting + auth-failure lockout. Tiny, in-memory,
 * good enough for a personal/LAN deployment.
 */
'use strict';

/** Sliding-window rate limiter per client IP. */
function rateLimit({ windowMs = 60000, max = 150 } = {}) {
  const hits = new Map(); // ip → [timestamps]
  return function limiter(req, res, next) {
    const ip = clientId(req);
    const now = Date.now();
    const list = (hits.get(ip) || []).filter((t) => now - t < windowMs);
    list.push(now);
    hits.set(ip, list);
    if (hits.size > 5000) hits.clear(); // paranoia cap
    if (list.length > max) {
      res.setHeader('Retry-After', Math.ceil(windowMs / 1000));
      return res.status(429).json({ error: 'rate limited — slow down' });
    }
    next();
  };
}

/** Progressive lockout after repeated failed token attempts. */
function authGuard({ maxFails = 5, lockMs = 5 * 60 * 1000 } = {}) {
  const fails = new Map(); // ip → {count, until}
  return {
    isLocked(req) {
      const f = fails.get(clientId(req));
      return !!(f && f.until > Date.now());
    },
    noteFailure(req) {
      const ip = clientId(req);
      const f = fails.get(ip) || { count: 0, until: 0 };
      f.count += 1;
      if (f.count >= maxFails) {
        f.until = Date.now() + lockMs;
        f.count = 0;
      }
      fails.set(ip, f);
    },
    noteSuccess(req) {
      fails.delete(clientId(req));
    },
  };
}

function clientId(req) {
  const fwd = req.headers && req.headers['x-forwarded-for'];
  if (typeof fwd === 'string' && fwd.trim()) return fwd.split(',')[0].trim();
  return (req.socket && req.socket.remoteAddress) || 'unknown';
}

module.exports = { rateLimit, authGuard };
