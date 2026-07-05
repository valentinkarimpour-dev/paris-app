// frontend/js/search.js
import { state } from './state.js';
import { API_BASE, OVERPASS_CATS, BACKEND_CATS } from './config.js';
import {
  getApiDays, applyPeriodFilter,
  updateCatCounts, showSkeletons
} from './filters.js';
import { fetchPOI, fetchBackendEvents, fetchMuseumExpos } from './api.js';
import { fadeOutMarkers, renderMarkers } from './map.js';
import { renderEvents } from './render.js';

// Proxy local — évite un import depuis app.js (orchestrateur, pas un module de logique)
function openCatPanel() {
  const p = document.getElementById('cat-filter-panel');
  const b = document.getElementById('cat-filter-btn');
  if (!p) return;
  if (p.classList.contains('open')) {
    p.classList.remove('open');
    if (state.activeCategories.size === 0 && b) b.classList.remove('active');
  } else {
    p.classList.add('open');
    if (b) b.classList.add('active');
  }
}

// ══════════════════════════════════════════
// REFRESH COLORS
// ══════════════════════════════════════════
export async function refreshColors(onMarkerClick) {
  if (state.currentLat === null || !state.lastAllEvents.length) return;
  try {
    const prevMuseumParsed = [...state.museumEverParsedSet].sort().join(',');
    const prevMuseumExpos  = JSON.stringify(state.museumExposMap);
    const [newMuseumExpos] = await Promise.all([
      fetchMuseumExpos(state.currentLat, state.currentLng, state.currentRadius),
    ]);
    const changed =
      JSON.stringify(newMuseumExpos) !== prevMuseumExpos ||
      [...state.museumEverParsedSet].sort().join(',') !== prevMuseumParsed;
    if (!changed) return;
    state.museumExposMap = newMuseumExpos;
    const filtered = state.activeCategories.size === 0
      ? state.lastAllEvents
      : state.lastAllEvents.filter(e => {
          const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
          return state.activeCategories.has(eCat);
        });
    filtered.forEach((e, i) => { e._id = 'e' + i; });
    renderMarkers(filtered.filter(e => e.lat && e.lng), onMarkerClick);
    renderEvents(filtered);
  } catch (e) {
    console.warn('[refreshColors]', e);
  }
}

// ══════════════════════════════════════════
// SEARCH
// ══════════════════════════════════════════
export async function searchEvents(onMarkerClick) {
  if (state.currentLat === null) return;

  const loading = document.getElementById('loading');
  const warning = document.getElementById('backend-warning');
  const isFirst = state.lastAllEvents.length === 0;

  if (isFirst) {
    loading.classList.add('visible');
  } else {
    showSkeletons();
  }

  if (state.radiusCircle && state.radiusCircle._path) state.radiusCircle._path.classList.add('pulsing');
  await fadeOutMarkers();

  const fetchOverpass = state.activeCategories.size === 0 || [...state.activeCategories].some(c => OVERPASS_CATS.has(c));
  const fetchBackend  = state.activeCategories.size === 0 || [...state.activeCategories].some(c => BACKEND_CATS.has(c) || c.startsWith('autre'));
  const fetchMusee    = state.activeCategories.size === 0 || state.activeCategories.has('musee');

  const [overpassResult, backendResult, museeResult] = await Promise.allSettled([
    fetchOverpass ? fetchPOI(state.currentLat, state.currentLng, state.currentRadius) : Promise.resolve([]),
    fetchBackend  ? fetchBackendEvents(state.currentLat, state.currentLng, state.currentRadius, getApiDays()) : Promise.resolve([]),
    fetchMusee    ? fetchMuseumExpos(state.currentLat, state.currentLng, state.currentRadius) : Promise.resolve({}),
  ]);

  let pois = overpassResult.status === 'fulfilled' ? overpassResult.value : [];
  if (overpassResult.status !== 'fulfilled') console.warn('Overpass indisponible:', overpassResult.reason);

  let beEvents = [];
  if (backendResult.status === 'fulfilled') {
    beEvents = backendResult.value;
    warning.style.display = 'none';
  } else {
    console.warn('Backend indisponible:', backendResult.reason);
    warning.style.display = 'block';
  }

  state.museumExposMap = {};
  if (museeResult.status === 'fulfilled') state.museumExposMap = museeResult.value;
  else console.warn('Museum expos indisponible:', museeResult.reason);

  // Merge + déduplication
  const PERM_CATS = new Set(['restaurant','bar','cafe','boutique','wellness','rooftop','musee']);
  const seen = new Set();
  const all  = [];
  for (const e of [...pois, ...beEvents]) {
    const locKey = `${Math.round((e.lat??0)*10000)}|${Math.round((e.lng??0)*10000)}`;
    const key = PERM_CATS.has(e.cat)
      ? `${e.cat}|${locKey}`
      : `${(e.titre||'').toLowerCase().slice(0,30)}|${locKey}`;
    if (seen.has(key)) continue;
    seen.add(key);
    all.push(e);
  }

  // ── Filtre permanents (musées, cinémas OSM) ──
  const showingPermanents = state.showPermanents;
  if (!showingPermanents) {
    for (let i = all.length - 1; i >= 0; i--) {
      if (all[i].source === 'OpenStreetMap') all.splice(i, 1);
    }
  }

  // Filtre catégorie
  let filtered = state.activeCategories.size === 0
    ? all
    : all.filter(e => {
        const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
        return state.activeCategories.has(eCat);
      });

  // Filtre période (frontend)
  filtered = applyPeriodFilter(filtered);

  updateCatCounts(filtered, openCatPanel);

  filtered.sort((a, b) => {
    const aDebut = a.date_debut || null;
    const bDebut = b.date_debut || null;
    if (aDebut !== bDebut) {
      if (!aDebut) return 1;
      if (!bDebut) return -1;
      return aDebut > bDebut ? -1 : 1;
    }
    const aFin = a.date_fin || null;
    const bFin = b.date_fin || null;
    if (aFin !== bFin) {
      if (!aFin) return 1;
      if (!bFin) return -1;
      return aFin < bFin ? -1 : 1;
    }
    return (a.dist ?? Infinity) - (b.dist ?? Infinity);
  });

  state.events         = all;
  state.filteredEvents = filtered;

  state.lastAllEvents = all;
  filtered.forEach((e, i) => { e._id = 'e' + i; });
  renderEvents(filtered);
  renderMarkers(filtered.filter(e => e.lat && e.lng), onMarkerClick);

  loading.classList.remove('visible');
  if (state.radiusCircle && state.radiusCircle._path) state.radiusCircle._path.classList.remove('pulsing');
}

export async function searchEventsBrowse(onMarkerClick) {
  showSkeletons();
  await fadeOutMarkers();
  const PARIS_LAT = 48.8566, PARIS_LNG = 2.3522;
  try {
    const showingPermanents = state.showPermanents;

    const params = new URLSearchParams({
      lat: PARIS_LAT, lng: PARIS_LNG, radius: 5000, days: getApiDays()
    });
    if (state.activeCategories.size === 1) params.set('cat', [...state.activeCategories][0]);

    const fetchOverpass = showingPermanents
      && (state.activeCategories.size === 0 || [...state.activeCategories].some(c => OVERPASS_CATS.has(c)));

    const [resp, poisResult] = await Promise.all([
      fetch(`${API_BASE}/events?${params}`),
      fetchOverpass ? fetchPOI(PARIS_LAT, PARIS_LNG, 5000) : Promise.resolve([]),
    ]);

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    let beEvents = data.events.map(e => ({
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
      dist:            null,
    }));

    const pois = Array.isArray(poisResult) ? poisResult : [];
    const seen = new Set();
    let events = [];
    for (const e of [...pois, ...beEvents]) {
      const key = `${(e.titre||'').toLowerCase().slice(0,30)}|${Math.round((e.lat??0)*10000)}|${Math.round((e.lng??0)*10000)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      events.push(e);
    }

    const all = events;

    events = applyPeriodFilter(events);
    if (state.activeCategories.size > 1) {
      events = events.filter(e => {
        const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
        return state.activeCategories.has(eCat);
      });
    }
    if (!showingPermanents) {
      events = events.filter(e => e.source !== 'OpenStreetMap');
    }
    events.sort((a, b) => {
      const aDebut = a.date_debut || null;
      const bDebut = b.date_debut || null;
      if (aDebut !== bDebut) {
        if (!aDebut) return 1;
        if (!bDebut) return -1;
        return aDebut > bDebut ? -1 : 1;
      }
      const aFin = a.date_fin || null;
      const bFin = b.date_fin || null;
      if (aFin !== bFin) {
        if (!aFin) return 1;
        if (!bFin) return -1;
        return aFin < bFin ? -1 : 1;
      }
      return (a.dist ?? Infinity) - (b.dist ?? Infinity);
    });

    state.events         = all;
    state.filteredEvents = events;

    updateCatCounts(events, openCatPanel);
    events.forEach((e, i) => { e._id = 'e' + i; });
    renderEvents(events);
    renderMarkers(events.filter(e => e.lat && e.lng), onMarkerClick);
  } catch (err) {
    console.warn('[searchEventsBrowse]', err);
  }
}
