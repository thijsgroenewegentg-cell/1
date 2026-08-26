/**
 * WEATHER — via Open-Meteo. Free, no API key, no account.
 * Geocoding: https://geocoding-api.open-meteo.com
 * Forecast:  https://api.open-meteo.com
 */
'use strict';

const WMO = {
  0: 'clear sky', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast',
  45: 'fog', 48: 'depositing rime fog', 51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle',
  56: 'light freezing drizzle', 57: 'freezing drizzle', 61: 'light rain', 63: 'rain', 65: 'heavy rain',
  66: 'light freezing rain', 67: 'freezing rain', 71: 'light snow', 73: 'snow', 75: 'heavy snow',
  77: 'snow grains', 80: 'light showers', 81: 'showers', 82: 'violent showers',
  85: 'snow showers', 86: 'heavy snow showers', 95: 'thunderstorm', 96: 'thunderstorm with hail',
  99: 'severe thunderstorm with hail',
};

async function fetchJson(url, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) return { error: `HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    return { error: err.name === 'AbortError' ? 'timeout' : String(err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

async function geocode(name) {
  const data = await fetchJson(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(name)}&count=1&language=en&format=json`);
  if (data.error) return data;
  const hit = (data.results || [])[0];
  if (!hit) return { error: `unknown place "${name}"` };
  return { name: hit.name, country: hit.country || '', latitude: hit.latitude, longitude: hit.longitude };
}

/**
 * @param {object} args { location, days? }
 */
async function getWeather({ location, days = 1 }) {
  if (!location || !String(location).trim()) return { error: 'no location given' };
  const daysN = Math.min(Math.max(parseInt(days, 10) || 1, 1), 7);
  const geo = await geocode(String(location).trim());
  if (geo.error) return geo;

  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
    `&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max` +
    `&timezone=auto&forecast_days=${daysN}`;
  const data = await fetchJson(url);
  if (data.error) return data;

  const place = `${geo.name}${geo.country ? ', ' + geo.country : ''}`;
  const cur = data.current || {};
  const out = {
    location: place,
    current: {
      temperature_c: cur.temperature_2m,
      feels_like_c: cur.apparent_temperature,
      condition: WMO[cur.weather_code] || 'unknown',
      wind_kmh: cur.wind_speed_10m,
      humidity: cur.relative_humidity_2m,
    },
    daily: [],
  };
  const d = data.daily || {};
  for (let i = 0; i < (d.time || []).length; i++) {
    out.daily.push({
      date: d.time[i],
      high_c: d.temperature_2m_max ? d.temperature_2m_max[i] : null,
      low_c: d.temperature_2m_min ? d.temperature_2m_min[i] : null,
      condition: WMO[d.weather_code ? d.weather_code[i] : 0] || 'unknown',
      rain_chance: d.precipitation_probability_max ? d.precipitation_probability_max[i] : null,
    });
  }
  return out;
}

module.exports = { getWeather };
