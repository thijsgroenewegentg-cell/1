/**
 * MAPS — the open map of the world, via OpenStreetMap.
 * Geocoding (Nominatim) · routing (OSRM) · POI search (Overpass).
 * Free, keyless, accountless. (Endpoints overridable for tests.)
 */
'use strict';

const NOMINATIM = process.env.ULTRON_NOMINATIM || 'https://nominatim.openstreetmap.org';
const OSRM = process.env.ULTRON_OSRM || 'https://router.project-osrm.org';
const OVERPASS = process.env.ULTRON_OVERPASS || 'https://overpass-api.de/api/interpreter';

const UA = 'Ultron/1.0 (local AI agent; personal use)';

async function getJson(url, timeoutMs = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': UA, Accept: 'application/json' },
    });
    if (!res.ok) return { error: `HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    return { error: err.name === 'AbortError' ? 'timeout' : String(err.message || err).slice(0, 120) };
  } finally {
    clearTimeout(timer);
  }
}

/** Search a place by name → [{name, lat, lon}]. */
async function geocode(query) {
  const q = String(query || '').trim().slice(0, 200);
  if (!q) return { error: 'no query' };
  const data = await getJson(`${NOMINATIM}/search?q=${encodeURIComponent(q)}&format=json&limit=3&accept-language=nl,en`);
  if (data.error) return data;
  const results = (Array.isArray(data) ? data : []).map((r) => ({
    name: r.display_name,
    lat: Number(r.lat),
    lon: Number(r.lon),
    type: r.type || '',
  }));
  if (results.length === 0) return { error: `nothing found for "${q}"` };
  return { results };
}

async function resolvePoint(place) {
  // Accepts "lat,lon" directly or a place name.
  const s = String(place || '').trim();
  const m = s.match(/^(-?\d{1,3}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)$/);
  if (m) return { lat: Number(m[1]), lon: Number(m[2]) };
  const geo = await geocode(s);
  if (geo.error) return geo;
  return { lat: geo.results[0].lat, lon: geo.results[0].lon, name: geo.results[0].name };
}

const MODES = { driving: 'driving', car: 'driving', auto: 'driving', cycling: 'bike', bike: 'bike', fiets: 'bike', foot: 'foot', walking: 'foot', lopen: 'foot' };

const MANEUVER = {
  depart: 'Head out', arrive: 'Arrive', turn: 'Turn', 'new name': 'Continue',
  merge: 'Merge', 'on ramp': 'Take the ramp', 'off ramp': 'Take the exit',
  'fork': 'Keep', 'end of road': 'At the end of the road', continue: 'Continue',
  roundabout: 'At the roundabout', 'exit roundabout': 'Exit the roundabout',
  'rotary': 'At the roundabout', depart_: 'Head out',
};

function fmtKm(m) { return (m / 1000).toFixed(1) + ' km'; }
function fmtMin(s) { return Math.max(1, Math.round(s / 60)) + ' min'; }

/** Directions between two places. */
async function route({ from, to, mode }) {
  const m = MODES[String(mode || 'driving').toLowerCase()] || 'driving';
  const a = await resolvePoint(from);
  if (a.error) return { error: `from: ${a.error}` };
  const b = await resolvePoint(to);
  if (b.error) return { error: `to: ${b.error}` };

  const url = `${OSRM}/route/v1/${m}/${a.lon},${a.lat};${b.lon},${b.lat}?overview=false&steps=true`;
  const data = await getJson(url);
  if (data.error) return data;
  if (data.code !== 'Ok' || !data.routes || !data.routes[0]) {
    return { error: `no route found (${data.code || 'unknown'})` };
  }
  const r = data.routes[0];
  const steps = [];
  for (const leg of r.legs || []) {
    for (const st of (leg.steps || []).slice(0, 20)) {
      const verb = MANEUVER[st.maneuver && st.maneuver.type] || 'Go';
      const dir = st.maneuver && st.maneuver.modifier ? ' ' + st.maneuver.modifier : '';
      const road = st.name ? ` onto ${st.name}` : '';
      steps.push(`${verb}${dir}${road} (${fmtKm(st.distance)})`.replace(/\s+/g, ' ').trim());
    }
  }
  return {
    from: a.name || from,
    to: b.name || to,
    mode: m,
    distance: fmtKm(r.distance),
    duration: fmtMin(r.duration),
    steps: steps.slice(0, 14),
    map: `https://www.openstreetmap.org/directions?engine=fossgis_osrm_${m}&route=${a.lat}%2C${a.lon}%3B${b.lat}%2C${b.lon}`,
  };
}

const CATEGORIES = {
  cafe: 'amenity=cafe', cafeteria: 'amenity=cafe', koffie: 'amenity=cafe',
  restaurant: 'amenity=restaurant', eetcafe: 'amenity=restaurant',
  bar: 'amenity=bar', pub: 'amenity=bar',
  fuel: 'amenity=fuel', benzine: 'amenity=fuel', tankstation: 'amenity=fuel',
  supermarket: 'shop=supermarket', supermarkt: 'shop=supermarket',
  bakery: 'shop=bakery', bakker: 'shop=bakery', bakkerij: 'shop=bakery',
  pharmacy: 'amenity=pharmacy', apotheek: 'amenity=pharmacy',
  hospital: 'amenity=hospital', ziekenhuis: 'amenity=hospital',
  doctor: 'amenity=doctors', dokter: 'amenity=doctors',
  bank: 'amenity=bank', atm: 'amenity=atm', geldautomaat: 'amenity=atm',
  parking: 'amenity=parking', parkeer: 'amenity=parking',
  school: 'amenity=school', school: 'amenity=school',
  police: 'amenity=police', politie: 'amenity=police',
  post: 'amenity=post_office', postkantoor: 'amenity=post_office',
  hotel: 'tourism=hotel', camping: 'tourism=camp_site',
  park: 'leisure=park', speeltuin: 'leisure=playground',
  bicycle: 'shop=bicycle', fietsenmaker: 'shop=bicycle',
};

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Find nearby points of interest. */
async function nearby({ what, place, radius_m }) {
  const q = String(what || '').trim().toLowerCase();
  if (!q) return { error: 'what are we looking for?' };
  const center = await resolvePoint(place);
  if (center.error) return { error: `place: ${center.error}` };
  const radius = Math.min(Math.max(parseInt(radius_m, 10) || 1500, 100), 10000);

  const cat = CATEGORIES[q];
  const filter = cat
    ? `node(around:${radius},${center.lat},${center.lon})[${cat}];`
    : `node(around:${radius},${center.lat},${center.lon})[name~"${q.replace(/[^a-z0-9 ]/gi, '')}",i];`;
  const query = `[out:json][timeout:10];(${filter});out 20;`;

  const data = await getJson(`${OVERPASS}?data=${encodeURIComponent(query)}`);
  if (data.error) return data;
  const elements = (data.elements || []).filter((e) => e.lat && (e.tags || {}).name);
  const results = elements
    .map((e) => ({
      name: e.tags.name,
      kind: e.tags.amenity || e.tags.shop || e.tags.tourism || e.tags.leisure || '',
      distance_km: Number(haversineKm(center.lat, center.lon, e.lat, e.lon).toFixed(2)),
      lat: e.lat,
      lon: e.lon,
    }))
    .sort((x, y) => x.distance_km - y.distance_km)
    .slice(0, 8);
  if (results.length === 0) return { error: `no ${q} found within ${radius} m — try a bigger radius` };
  return {
    center: center.name || place,
    radius_m: radius,
    results,
    map: `https://www.openstreetmap.org/#map=16/${center.lat}/${center.lon}`,
  };
}

module.exports = { geocode, route, nearby };
