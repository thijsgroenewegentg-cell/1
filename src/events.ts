import { EventEmitter } from 'node:events';

/**
 * Shared event bus. Every module publishes here; the HTTP server relays
 * everything to the dashboard via Server-Sent Events.
 */
export const bus = new EventEmitter();
bus.setMaxListeners(100);

export interface JarvisEvent {
  ts: string;
  type: string;
  payload: unknown;
}

const ring: JarvisEvent[] = [];
const RING_MAX = 500;

export function publish(type: string, payload: unknown = {}): void {
  const evt: JarvisEvent = { ts: new Date().toISOString(), type, payload };
  ring.push(evt);
  if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX);
  bus.emit('event', evt);
  bus.emit(type, payload);
}

export function recentEvents(limit = 100): JarvisEvent[] {
  return ring.slice(-limit);
}
