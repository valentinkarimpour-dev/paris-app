import { API_BASE } from './config.js';
import { haversine, normalizeName } from './utils.js';
import { state } from './state.js';

export async function fetchSuggestions(q, onResults) {
  try {
    const url = `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(q)}&limit=5&lat=48.8566&lon=2.3522`;
    const res = await fetch(url);
    const data = await res.json();
    onResults(data.features || []);
  } catch {
    onResults([]);
  }
}

export async function fetchPOI(lat, lng, radius) {
  const r = radius, la = lat, ln = lng;
  const query = `
    [out:json][timeout:25];
    (
      node["amenity"="cinema"](around:${r},${la},${ln});
      node["tourism"="museum"](around:${r},${la},${ln});
      way["amenity"="cinema"](around:${r},${la},${ln});
      way["tourism"="museum"](around:${r},${la},${ln});
    );
    out center;
  `.trim();

  const resp = await fetch('https://overpass-api.de/api/interpreter', { method: 'POST', body: query });
  if (!resp.ok) throw new Error(`Overpass HTTP ${resp.status}`);
  const data = await resp.json();

  return data.elements.map(el => {
    const tags   = el.tags || {};
    const poiLat = el.lat ?? el.center?.lat;
    const poiLng = el.lon ?? el.center?.lon;
    let cat;
    if (tags.amenity === 'cinema')      cat = 'cinema';
    else if (tags.tourism === 'museum') cat = 'musee';
    else                                cat = 'autre';

    const adresseParts = [tags['addr:housenumber'], tags['addr:street']].filter(Boolean);
    const adresse = adresseParts.length ? adresseParts.join(' ') : (tags['addr:city'] || '');
    let prix = '';
    if (tags.fee === 'no') prix = 'Gratuit'; else if (tags.fee === 'yes') prix = 'Payant';
    const dist = (poiLat && poiLng) ? Math.round(haversine(lat, lng, poiLat, poiLng)) : null;

    return {
      id:              'osm_' + el.id,
      titre:           tags['name:fr'] || tags.name || 'Sans nom',
      cat,
      adresse,
      lat:             poiLat,
      lng:             poiLng,
      prix,
      url:             tags.website || tags['contact:website'] || '',
      source:          'OpenStreetMap',
      date:            '',
      date_debut:      '',
      date_fin:        '',
      identified_date: '',
      dist,
    };
  }).filter(e => e.lat && e.lng);
}

export async function fetchBackendEvents(lat, lng, radius, days) {
  const params = new URLSearchParams({ lat, lng, radius, days });
  const resp = await fetch(`${API_BASE}/events?${params}`);
  if (!resp.ok) throw new Error(`Backend HTTP ${resp.status}`);
  const data = await resp.json();
  return data.events.map(e => ({
    id:              'be_' + e.id,
    titre:           e.titre,
    cat:             e.categorie || 'autre',
    adresse:         e.adresse || '',
    lat:             e.lat,
    lng:             e.lng,
    prix:            e.prix || '',
    url:             e.url || '',
    source:          e.source,
    date:            e.date_debut || '',
    date_debut:      e.date_debut || '',
    date_fin:        e.date_fin   || '',
    identified_date: e.identified_date || e.date_debut || '',
    dist:            e.dist_m,
  }));
}

export async function fetchMuseumExpos(lat, lng, radius) {
  const params = new URLSearchParams({ lat, lng, radius });
  const resp = await fetch(`${API_BASE}/museum-events?${params}`);
  if (!resp.ok) throw new Error(`Backend museum-events HTTP ${resp.status}`);
  const data = await resp.json();
  state.museumEverParsedSet = new Set((data.museums_ever_parsed || []).map(n => normalizeName(n)));
  return data.museums_with_recent_expos || {};
}
