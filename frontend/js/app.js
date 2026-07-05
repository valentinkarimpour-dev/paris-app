import {
  API_BASE, OVERPASS_CATS, BACKEND_CATS,
  CAT_COLORS, CAT_EMOJI, SOURCE_LABELS, ALL_CATS, _PARIS_POLY
} from './config.js';

import {
  getCatColor, getCatEmoji, getCatLabel,
  normalizeName, haversine, formatDist, toProper,
  formatSource, isNew, freshnessWidth
} from './utils.js';

import { state } from './state.js';
import {
  fetchSuggestions, fetchPOI,
  fetchBackendEvents, fetchMuseumExpos
} from './api.js';


// ══════════════════════════════════════════
// MAP INIT — CartoDB Voyager
// ══════════════════════════════════════════
const map = L.map('map', {
  center: [48.8566, 2.3522],
  zoom: 14,
  zoomControl: false
});

L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
  attribution: '© OpenStreetMap contributors © CARTO',
  subdomains: 'abcd',
  maxZoom: 19
}).addTo(map);

L.control.zoom({ position: 'bottomright' }).addTo(map);

// ══════════════════════════════════════════
// SEARCH BAR — api-adresse.data.gouv.fr
// ══════════════════════════════════════════
const addressInput = document.getElementById('address-input');
const suggestions  = document.getElementById('search-suggestions');
const searchClear  = document.getElementById('search-clear');
let searchDebounce = null;

addressInput.addEventListener('input', () => {
  const q = addressInput.value.trim();
  searchClear.classList.toggle('hidden', !q);
  clearTimeout(searchDebounce);
  if (q.length < 3) { suggestions.classList.add('hidden'); return; }
  searchDebounce = setTimeout(() => fetchSuggestions(q, renderSuggestions), 300);
});

searchClear.addEventListener('click', () => {
  addressInput.value = '';
  searchClear.classList.add('hidden');
  suggestions.classList.add('hidden');
  addressInput.focus();
});

document.addEventListener('click', e => {
  if (!e.target.closest('#search-bar')) suggestions.classList.add('hidden');
});


function renderSuggestions(features) {
  if (!features.length) { suggestions.classList.add('hidden'); return; }
  suggestions.innerHTML = features.map(f => {
    const props = f.properties;
    const label = props.name || props.label;
    const context = props.context || '';
    const [lng, lat] = f.geometry.coordinates;
    return `<li class="suggestion-item"
                data-lat="${lat}"
                data-lng="${lng}"
                data-label="${props.label}">
              <strong>${label}</strong>
              <span>${context}</span>
            </li>`;
  }).join('');
  suggestions.classList.remove('hidden');

  suggestions.querySelectorAll('.suggestion-item').forEach(item => {
    item.addEventListener('click', () => {
      const lat = parseFloat(item.dataset.lat);
      const lng = parseFloat(item.dataset.lng);
      addressInput.value = item.dataset.label;
      suggestions.classList.add('hidden');
      searchClear.classList.remove('hidden');
      map.setView([lat, lng], 16, { animate: true });
      placePin(lat, lng);
    });
  });
}



function getMuseumColor(normTitle) {
  const hasExpo = Object.entries(state.museumExposMap).some(([k]) => normalizeName(k) === normTitle);
  if (hasExpo) return '#4CAF50';
  if (state.museumEverParsedSet.has(normTitle)) return getCatColor('musee');
  return '#5C6470';
}


function getApiDays() {
  if (state.periodMode === 'recent') {
    const val  = parseInt(document.getElementById('period-days-val').value) || 30;
    const mult = parseInt(document.getElementById('period-days-unit').value) || 1;
    return Math.min(val * mult, 365);
  }
  return 365;
}

function applyPeriodFilter(events) {
  const d = new Date();
  const today = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;

  // Règle absolue tous modes : jamais afficher un event pas encore commencé
  events = events.filter(e => !e.date_debut || e.date_debut <= today);

  if (state.periodMode === 'nouveaux') {
    return events.filter(e => {
      if (!e.date_debut && !e.date_fin) return true;
      return e.date_debut === today;
    });
  }

  if (state.periodMode === 'current') {
    return events.filter(e => {
      if (!e.date_debut && !e.date_fin) return true;
      if (e.date_debut && e.date_debut > today) return false;
      if (e.date_fin && e.date_fin < today) return false;
      return true;
    });
  }

  if (state.periodMode === 'recent') {
    const daysVal = parseInt(document.getElementById('period-days-val').value) || 7;
    const unitVal = document.getElementById('period-days-unit').value || '1';
    const mult = unitVal === '1'  ? 1
               : unitVal === '7'  ? 7
               : 30; // month
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - daysVal * mult);
    const cutoffStr = `${cutoff.getFullYear()}-${String(cutoff.getMonth()+1).padStart(2,'0')}-${String(cutoff.getDate()).padStart(2,'0')}`;
    return events.filter(e => {
      if (!e.date_debut) return false;
      return e.date_debut >= cutoffStr;
    });
  }

  return events;
}

function updatePeriodBanner() {
  const banner = document.getElementById('period-info-banner');
  if (!banner) return;
  const d = new Date();
  const todayFr = `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}`;
  if (state.periodMode === 'nouveaux') {
    banner.textContent = `Événements ayant débuté aujourd'hui (${todayFr})`;
    banner.classList.add('visible');
  } else if (state.periodMode === 'recent') {
    const val  = document.getElementById('period-days-val').value  || '7';
    const unit = document.getElementById('period-days-unit').value || '1';
    const unitLabel = unit === '1'
      ? (val === '1' ? 'jour' : 'jours')
      : unit === '7'
        ? (val === '1' ? 'semaine' : 'semaines')
        : (val === '1' ? 'mois' : 'mois');
    banner.textContent = `Événements ayant débuté il y a moins de ${val} ${unitLabel}`;
    banner.classList.add('visible');
  } else if (state.periodMode === 'current') {
    banner.textContent = 'Événements actuellement en cours';
    banner.classList.add('visible');
  } else {
    banner.classList.remove('visible');
  }
}


// ══════════════════════════════════════════
// CUSTOM MARKER SVG (staggered bounce)
// ══════════════════════════════════════════
function makeMarkerIcon(color, cat, delay = 0, opacity = 0.95) {
  const emoji = getCatEmoji(cat);
  const svg = `
    <div style="animation: markerDrop 0.4s ease ${delay}ms both; opacity: ${opacity}">
      <svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
        <circle cx="18" cy="18" r="17" fill="${color}" opacity="0.95"/>
        <path d="M18 36 L18 44" stroke="${color}" stroke-width="2.5" stroke-linecap="round"/>
        <text x="18" y="23" text-anchor="middle" font-size="14">${emoji}</text>
      </svg>
    </div>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [36, 44],
    iconAnchor: [18, 44],
    popupAnchor: [0, -44]
  });
}

function makePinIcon() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
      <circle cx="14" cy="14" r="6" fill="rgb(0,246,111)"/>
      <circle cx="14" cy="14" r="11" fill="none" stroke="rgb(0,246,111)" stroke-width="2" opacity="0.5"/>
      <circle cx="14" cy="14" r="14" fill="none" stroke="rgb(0,246,111)" stroke-width="1" opacity="0.2"/>
    </svg>`;
  return L.divIcon({ html: svg, className: '', iconSize: [28,28], iconAnchor: [14,14] });
}

// ══════════════════════════════════════════
// SKELETON
// ══════════════════════════════════════════
function showSkeletons() {
  document.getElementById('events-list').innerHTML = Array(5).fill(`
    <div class="skeleton-card">
      <div class="sk sk-cat"></div>
      <div class="sk sk-title"></div>
      <div class="sk sk-meta"></div>
    </div>`).join('');
}

// ══════════════════════════════════════════
// CAT COUNTS
// ══════════════════════════════════════════
function updateCatCounts(allEvents) {
  const catSet = new Set();
  allEvents.forEach(e => {
    const cat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
    if (cat) catSet.add(cat);
  });
  state.currentMapCats = catSet;

  const mapCats = document.getElementById('map-cats');
  mapCats.innerHTML = '';
  const catsToShow = (state.activeCategories.size === 0
    ? ALL_CATS
    : ALL_CATS.filter(({ cat }) => state.activeCategories.has(cat))
  ).slice().sort((a, b) => (catSet.has(b.cat) ? 1 : 0) - (catSet.has(a.cat) ? 1 : 0));
  const MAX_CHIPS = 6;
  catsToShow.slice(0, MAX_CHIPS).forEach(({ cat, emoji, label }) => {
    const tag = document.createElement('button');
    tag.className = 'cat-btn' + (catSet.has(cat) ? ' active' : '');
    tag.dataset.cat = cat;
    tag.innerHTML = `${emoji} ${label}`;
    tag.addEventListener('click', () => _openCatPanel());
    mapCats.appendChild(tag);
  });
  if (catsToShow.length > MAX_CHIPS) {
    const more = document.createElement('button');
    more.className = 'cat-more-btn';
    more.textContent = `+${catsToShow.length - MAX_CHIPS}`;
    more.addEventListener('click', () => _openCatPanel());
    mapCats.appendChild(more);
  }
}


function isInsideParis(lat, lng) {
  let inside = false;
  for (let i = 0, j = _PARIS_POLY.length - 1; i < _PARIS_POLY.length; j = i++) {
    const [yi, xi] = _PARIS_POLY[i];
    const [yj, xj] = _PARIS_POLY[j];
    if (((yi > lat) !== (yj > lat)) &&
        (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

// ══════════════════════════════════════════
// PLACE PIN & SEARCH
// ══════════════════════════════════════════
function placePin(lat, lng) {
  document.getElementById('eiffel-btn').classList.remove('active');
  const _warning = document.getElementById('hors-paris-warning');
  if (!isInsideParis(lat, lng)) {
    _warning.classList.add('visible');
    setTimeout(() => _warning.classList.remove('visible'), 3000);
  } else {
    _warning.classList.remove('visible');
  }
  state.currentLat = lat;
  state.currentLng = lng;

  if (state.pinMarker) map.removeLayer(state.pinMarker);
  state.pinMarker = L.marker([lat, lng], { icon: makePinIcon(), draggable: true }).addTo(map);
  state.pinMarker.on('drag', e => {
    const p = e.target.getLatLng();
    state.currentLat = p.lat; state.currentLng = p.lng;
    updateCircle(p.lat, p.lng);
  });
  state.pinMarker.on('dragend', () => searchEvents());

  updateCircle(lat, lng);
  searchEvents();

  fetch(`${API_BASE}/museum-events/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lng, radius: state.currentRadius }),
  }).catch(() => {});
  setTimeout(() => refreshColors(), 10000);

  if (typeof openSidebarIfMobile === 'function') openSidebarIfMobile();
  if (window.innerWidth <= 768) {
    mapRadiusControl.classList.add('visible');
    mapSlider.value = state.currentRadius;
    mapLabel.textContent = state.currentRadius + 'm';
  }
}

function resetToBrowse() {
  if (state.pinMarker) { map.removeLayer(state.pinMarker); state.pinMarker = null; }
  if (state.radiusCircle) { map.removeLayer(state.radiusCircle); state.radiusCircle = null; }
  state.currentLat = null;
  state.currentLng = null;
  document.getElementById('eiffel-btn').classList.add('active');
  mapRadiusControl.classList.remove('visible');
  searchEventsBrowse();
}

function updateCircle(lat, lng) {
  if (state.radiusCircle) map.removeLayer(state.radiusCircle);
  state.radiusCircle = L.circle([lat, lng], {
    radius: state.currentRadius,
    color: 'rgb(0,246,111)',
    fillColor: 'rgb(0,246,111)',
    fillOpacity: 0.06,
    weight: 1.5,
    dashArray: '4 4'
  }).addTo(map);
}

// ══════════════════════════════════════════
// REFRESH COLORS
// ══════════════════════════════════════════
async function refreshColors() {
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
    renderMarkers(filtered.filter(e => e.lat && e.lng));
    renderEvents(filtered);
  } catch (e) {
    console.warn('[refreshColors]', e);
  }
}

// ══════════════════════════════════════════
// FADE OUT MARKERS
// ══════════════════════════════════════════
async function fadeOutMarkers() {
  if (!state.eventMarkers.length) return;
  state.eventMarkers.forEach(m => {
    if (m._icon) {
      m._icon.style.transition = 'opacity 0.2s';
      m._icon.style.opacity = '0';
    }
  });
  await new Promise(r => setTimeout(r, 200));
  state.eventMarkers.forEach(m => map.removeLayer(m));
  state.eventMarkers = [];
}

// ══════════════════════════════════════════
// SEARCH
// ══════════════════════════════════════════
async function searchEvents() {
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

  updateCatCounts(filtered);

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

  state.lastAllEvents = all;
  filtered.forEach((e, i) => { e._id = 'e' + i; });
  renderEvents(filtered);
  renderMarkers(filtered.filter(e => e.lat && e.lng));

  loading.classList.remove('visible');
  if (state.radiusCircle && state.radiusCircle._path) state.radiusCircle._path.classList.remove('pulsing');
}

async function searchEventsBrowse() {
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
    updateCatCounts(events);
    events.forEach((e, i) => { e._id = 'e' + i; });
    renderEvents(events);
    renderMarkers(events.filter(e => e.lat && e.lng));
  } catch (err) {
    console.warn('[searchEventsBrowse]', err);
  }
}

// ══════════════════════════════════════════
// RENDER EVENTS LIST
// ══════════════════════════════════════════
function renderEvents(events) {
  const list = document.getElementById('events-list');
  document.getElementById('count').textContent = events.length;

  if (!events.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <p>Aucun événement dans ce rayon.<br>Essaie d'élargir la zone ou de changer de catégorie.</p>
      </div>`;
    return;
  }

  list.innerHTML = events.map(e => {
    const expos     = e.cat === 'musee'
      ? (Object.entries(state.museumExposMap).find(([k]) => normalizeName(k) === normalizeName(e.titre)) || [])[1] || []
      : [];
    const expoBadge = expos.length
      ? `<span class="expo-badge">🖼 ${expos.length} expo${expos.length > 1 ? 's' : ''}</span>`
      : '';
    const catColor  = e.cat === 'musee' ? getMuseumColor(normalizeName(e.titre)) : getCatColor(e.cat);
    const today     = new Date();
    const todayMs   = today.setHours(0,0,0,0);
    const identified = new Date(e.identified_date || e.date || today);
    const ageDays   = Math.max(0, (Date.now() - identified) / 86400000);
    const freshPct  = Math.max(0, 100 - (ageDays / 30) * 100).toFixed(0);
    const showNew   = ageDays <= 7;

    let timingHtml = '';
    if (e.date) {
      const debut = new Date(e.date).setHours(0,0,0,0);
      const ouvertDepuis = Math.round((todayMs - debut) / 86400000);
      if (ouvertDepuis === 0)    timingHtml += '<span class="timing-open">Ouvre aujourd\'hui</span>';
      else if (ouvertDepuis > 0) timingHtml += `<span class="timing-open">Ouvert depuis ${ouvertDepuis}j</span>`;
      else                       timingHtml += `<span class="timing-soon">Dans ${Math.abs(ouvertDepuis)}j</span>`;
    }
    if (e.date_fin) {
      const fin = new Date(e.date_fin).setHours(0,0,0,0);
      const fermeIn = Math.round((fin - todayMs) / 86400000);
      if (fermeIn === 0)      timingHtml += '<span class="timing-closing">Ferme aujourd\'hui</span>';
      else if (fermeIn > 0)   timingHtml += `<span class="timing-closing">Ferme dans ${fermeIn}j</span>`;
    }
    const timingBlock = timingHtml ? `<div class="event-timing">${timingHtml}</div>` : '';

    return `
    <div class="event-card${e.outOfZone ? ' out-of-zone' : ''}" data-id="${e._id}" onclick="focusEvent('${e._id}', ${e.lat ?? 0}, ${e.lng ?? 0})">
      <div class="event-header">
        <div class="event-cat" style="color:${catColor}">${getCatEmoji(e.cat)} ${getCatLabel(e.cat)}</div>
        <div class="event-dist">${e.dist != null ? formatDist(e.dist) : '—'}</div>
      </div>
      <div class="event-title">${toProper(e.titre)}</div>
      <div class="event-address">${toProper(e.adresse) || '—'}</div>
      ${timingBlock}
      <div class="event-badges">
        ${e.source === 'OpenStreetMap' ? '<span class="badge-permanent">Permanent</span>' : (showNew ? '<span class="badge-new">NOUVEAU</span>' : '')}
        ${expoBadge}
      </div>
      <div class="freshness-bar" style="width:${freshPct}%"></div>
    </div>`;
  }).join('');
}

// ══════════════════════════════════════════
// RENDER MAP MARKERS (staggered bounce)
// ══════════════════════════════════════════
function renderMarkers(events) {
  state.eventMarkers.forEach(m => map.removeLayer(m));
  state.eventMarkers = [];

  events.forEach((e, i) => {
    const normTitle = normalizeName(e.titre);
    const expos     = e.cat === 'musee'
      ? (Object.entries(state.museumExposMap).find(([k]) => normalizeName(k) === normTitle) || [])[1] || []
      : [];

    const expoHtml = expos.length ? `
      <div class="popup-expos">
        <div class="popup-expo-label">En ce moment</div>
        ${expos.map(x => `
          <div class="popup-expo-item">
            ${x.url ? `<a href="${x.url}" target="_blank">${x.titre}</a>` : x.titre}
            ${x.date_fin ? `<span class="popup-expo-date">→ ${x.date_fin}</span>` : ''}
          </div>`).join('')}
      </div>` : '';

    const markerColor   = e.cat === 'musee' ? getMuseumColor(normTitle) : getCatColor(e.cat);
    const markerOpacity = e.outOfZone ? 0.3 : 0.95;
    const marker = L.marker([e.lat, e.lng], { icon: makeMarkerIcon(markerColor, e.cat, i * 60, markerOpacity) })
      .addTo(map);

    marker.bindPopup(`
      <div class="popup-cat" style="color:${markerColor}">${getCatEmoji(e.cat)} ${getCatLabel(e.cat)} · ${formatSource(e.source)}</div>
      <div class="popup-title">${toProper(e.titre)}</div>
      ${e.adresse ? `<div class="popup-date">${toProper(e.adresse)}</div>` : ''}
      ${e.dist != null ? `<div class="popup-date" style="margin-top:4px;color:var(--gold)">${formatDist(e.dist)}</div>` : ''}
      ${e.url ? `<a class="popup-link" href="${e.url}" target="_blank">Site web →</a>` : ''}
      ${expoHtml}
    `);

    marker.eventId = e._id;
    marker.on('click', () => highlightCard(e._id));
    state.eventMarkers.push(marker);
  });
}

// ══════════════════════════════════════════
// FOCUS / HIGHLIGHT
// ══════════════════════════════════════════
function focusEvent(id, lat, lng) {
  map.panTo([lat, lng], { animate: true, duration: 0.5 });
  const m = state.eventMarkers.find(m => m.eventId === id);
  if (m) m.openPopup();
  highlightCard(id);
}

function highlightCard(id) {
  document.querySelectorAll('.event-card').forEach(c => c.classList.remove('highlighted'));
  const card = document.querySelector(`.event-card[data-id="${id}"]`);
  if (card) {
    card.classList.add('highlighted');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

// ══════════════════════════════════════════
// SLIDER
// ══════════════════════════════════════════
const mapSlider = document.getElementById('map-radius-slider');
const mapLabel  = document.getElementById('map-radius-label');
const mapRadiusControl = document.getElementById('map-radius-control');

let sliderDebounce = null;
document.getElementById('radius-slider').addEventListener('input', e => {
  state.currentRadius = parseInt(e.target.value);
  document.getElementById('radius-val').textContent = state.currentRadius;
  mapSlider.value = state.currentRadius;
  mapLabel.textContent = state.currentRadius + 'm';
  if (state.currentLat) {
    updateCircle(state.currentLat, state.currentLng);
    if (window.innerWidth > 768) {
      clearTimeout(sliderDebounce);
      sliderDebounce = setTimeout(() => searchEvents(), 400);
    }
  }
});

// ── SLIDER CARTE (mobile) ──
mapSlider.addEventListener('input', e => {
  state.currentRadius = parseInt(e.target.value);
  mapLabel.textContent = state.currentRadius + 'm';
  document.getElementById('radius-slider').value = state.currentRadius;
  document.getElementById('radius-val').textContent = state.currentRadius;
  if (state.currentLat) {
    updateCircle(state.currentLat, state.currentLng);
    if (window.innerWidth > 768) {
      clearTimeout(sliderDebounce);
      sliderDebounce = setTimeout(() => searchEvents(), 400);
    }
  }
});

// ══════════════════════════════════════════
// CATEGORY FILTER PANEL
// ══════════════════════════════════════════

const chipsContainer = document.getElementById('cat-filter-chips');
ALL_CATS.forEach(({ cat, emoji, label }) => {
  const chip = document.createElement('button');
  chip.className = 'cat-filter-chip';
  chip.dataset.cat = cat;
  chip.innerHTML = `${emoji} ${label}`;
  chip.addEventListener('click', () => {
    chip.classList.toggle('selected');
    _syncToutState();
  });
  chipsContainer.appendChild(chip);
});

function _syncToutState() {
  const all   = document.querySelectorAll('.cat-filter-chip');
  const sel   = document.querySelectorAll('.cat-filter-chip.selected');
  document.getElementById('cat-filter-tout').classList.toggle('active', sel.length === all.length && all.length > 0);
}

function _applyCategories() {
  const selected = new Set(
    [...document.querySelectorAll('.cat-filter-chip.selected')].map(c => c.dataset.cat)
  );
  state.activeCategories = selected;
  document.getElementById('cat-filter-btn').classList.toggle('active', selected.size > 0);
  _closeCatPanel();
  if (state.currentLat !== null) searchEvents();
  else searchEventsBrowse();
}

const catPanel     = document.getElementById('cat-filter-panel');
const catFilterBtn = document.getElementById('cat-filter-btn');

function _openCatPanel() {
  if (state.activeCategories.size === 0) {
    document.querySelectorAll('.cat-filter-chip').forEach(chip => {
      chip.classList.toggle('selected', state.currentMapCats.has(chip.dataset.cat));
    });
    _syncToutState();
  }
  catPanel.classList.add('open');
  catFilterBtn.classList.add('active');
}
function _closeCatPanel() {
  catPanel.classList.remove('open');
  if (state.activeCategories.size === 0) catFilterBtn.classList.remove('active');
}

catFilterBtn.addEventListener('click', e => {
  e.stopPropagation();
  catPanel.classList.contains('open') ? _closeCatPanel() : _openCatPanel();
});

map.on('click', _closeCatPanel);
map.on('drag',  _closeCatPanel);
document.getElementById('cat-filter-apply').addEventListener('click', _applyCategories);

const toutBtn = document.getElementById('cat-filter-tout');
toutBtn.addEventListener('click', () => {
  const allChips = document.querySelectorAll('.cat-filter-chip');
  const allSelected = [...allChips].every(c => c.classList.contains('selected'));
  allChips.forEach(c => allSelected ? c.classList.remove('selected') : c.classList.add('selected'));
  _syncToutState();
});

catPanel.addEventListener('click', e => e.stopPropagation());

// ══════════════════════════════════════════
// PERIOD FILTER — dropdown popover
// ══════════════════════════════════════════
const periodPopover = document.getElementById('period-popover');
const periodLabel   = document.getElementById('period-label');
const periodBtn     = document.getElementById('period-btn');

periodBtn.addEventListener('click', e => {
  e.stopPropagation();
  const rect = periodBtn.getBoundingClientRect();
  periodPopover.style.top  = (rect.bottom + 6) + 'px';
  periodPopover.style.left = rect.left + 'px';
  periodPopover.classList.toggle('hidden');
});

document.addEventListener('click', e => {
  if (
    !e.target.closest('#period-popover') &&
    !e.target.closest('#period-btn')
  ) {
    periodPopover.classList.add('hidden');
  }
});

document.querySelectorAll('.period-option').forEach(opt => {
  opt.addEventListener('click', e => {
    e.stopPropagation();

    document.querySelectorAll('.period-option').forEach(o => o.classList.remove('active'));
    opt.classList.add('active');
    state.periodMode = opt.dataset.mode;
    const labels = { nouveaux: 'Ouverts aujourd\'hui', current: 'En cours', recent: 'Récents' };
    periodLabel.textContent = labels[state.periodMode];
    updatePeriodBanner();

    // Si le clic vient de l'input ou du select, garder le popover ouvert
    if (e.target.closest('.period-inline')) return;

    periodPopover.classList.add('hidden');
    if (window.innerWidth > 768) {
      if (state.currentLat !== null) searchEvents();
      else searchEventsBrowse();
    }
  });
});

document.getElementById('period-days-val').addEventListener('change', () => {
  state.periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (state.currentLat) searchEvents();
    else searchEventsBrowse();
  }
});
document.getElementById('period-days-unit').addEventListener('change', () => {
  state.periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (state.currentLat) searchEvents();
    else searchEventsBrowse();
  }
});

// ══════════════════════════════════════════
// TOGGLE PERMANENTS
// ══════════════════════════════════════════
document.getElementById('show-all-btn').addEventListener('click', () => {
  state.showPermanents = !state.showPermanents;
  document.getElementById('show-all-btn').classList.toggle('active', state.showPermanents);
  if (state.currentLat !== null) searchEvents();
  else searchEventsBrowse();
});

document.getElementById('apply-filters-btn').addEventListener('click', () => {
  if (state.currentLat !== null) searchEvents();
  else searchEventsBrowse();
  if (window.innerWidth <= 768) {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('visible');
  }
});

document.getElementById('eiffel-btn').addEventListener('click', () => {
  resetToBrowse();
});

map.on('click', e => {
  placePin(e.latlng.lat, e.latlng.lng);
});

document.getElementById('geolocate-btn').addEventListener('click', () => {
  const btn = document.getElementById('geolocate-btn');
  if (!navigator.geolocation) {
    alert('Géolocalisation non supportée par ce navigateur.');
    return;
  }
  btn.classList.add('loading');
  navigator.geolocation.getCurrentPosition(
    pos => {
      btn.classList.remove('loading');
      const { latitude: lat, longitude: lng } = pos.coords;
      map.setView([lat, lng], 16, { animate: true });
      placePin(lat, lng);
    },
    err => {
      btn.classList.remove('loading');
      alert('Impossible d\'obtenir votre position.');
      console.warn('Géolocalisation refusée :', err);
    },
    { timeout: 8000, maximumAge: 60000 }
  );
});
// SIDEBAR TOGGLE (mobile)
(function() {
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('sidebar-overlay');
  const toggleBtn = document.getElementById('sidebar-toggle');

  function isMobile() { return window.innerWidth <= 768; }

  function openSidebar() {
    if (window.innerWidth > 768) return;
    sidebar.classList.add('open');
    requestAnimationFrame(() => overlay.classList.add('visible'));
  }
  function closeSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('visible');
  }

  toggleBtn.addEventListener('click', () => {
    if (isMobile()) {
      sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
    } else {
      sidebar.classList.toggle('collapsed');
      setTimeout(() => map.invalidateSize(), 320);
    }
  });
  overlay.addEventListener('click', closeSidebar);

  window.openSidebarIfMobile = function() { if (isMobile()) openSidebar(); };
})();

// Chargement initial — tous les événements Nouveaux sur Paris
searchEventsBrowse();
updatePeriodBanner();

// Fonctions appelées depuis des onclick inline — doivent rester globales
window.focusEvent = focusEvent;
