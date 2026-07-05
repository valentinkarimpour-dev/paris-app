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
  searchDebounce = setTimeout(() => fetchSuggestions(q), 300);
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

async function fetchSuggestions(q) {
  try {
    const url = `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(q)}&limit=5&lat=48.8566&lon=2.3522`;
    const res = await fetch(url);
    const data = await res.json();
    renderSuggestions(data.features || []);
  } catch {
    suggestions.classList.add('hidden');
  }
}

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

// ══════════════════════════════════════════
// STATE
// ══════════════════════════════════════════
let pinMarker      = null;
let radiusCircle   = null;
let eventMarkers   = [];
let currentLat     = null;
let currentLng     = null;
let currentRadius  = 500;
let activeCategories = new Set();
let currentMapCats   = new Set();
let periodMode     = 'nouveaux';
let museumExposMap  = {};
let museumEverParsedSet = new Set();
let lastAllEvents   = [];
let showPermanents  = false;

// ══════════════════════════════════════════
// CAT CONFIG
// ══════════════════════════════════════════
const CAT_COLORS = {
  cinema:         '#E8503E',
  musee:          '#C9A84C',
  musique:        '#E8503E',
  exposition:     '#9B7EC8',
  spectacle:      '#D4825A',
  atelier:        '#5BAFBF',
  restaurant:     '#D4825A',
  cafe:           '#A0784A',
  bar:            '#C9784A',
  brocante:       '#7EB5A6',
  'vide-grenier': '#7EB5A6',
  sport:          '#4CAF50',
  popup:          '#E8A03E',
  boutique:       '#B07EC8',
  rooftop:        '#5BAFBF',
  marche:         '#7EB5A6',
  autre:          '#888888',
};

const CAT_EMOJI = {
  cinema:         '🎬',
  musee:          '🏛',
  musique:        '🎵',
  exposition:     '🖼',
  spectacle:      '🎭',
  atelier:        '🎨',
  restaurant:     '🍽',
  cafe:           '☕',
  bar:            '🍺',
  brocante:       '🪑',
  'vide-grenier': '🪑',
  sport:          '🏃',
  popup:          '🛍',
  boutique:       '🛍',
  rooftop:        '🌇',
  marche:         '🚶',
  autre:          '📌',
};

const API_BASE      = 'http://145.241.168.3:8000';
const OVERPASS_CATS = new Set(['cinema', 'musee']);
const BACKEND_CATS  = new Set(['musique', 'exposition', 'vide-grenier', 'spectacle', 'atelier', 'restaurant', 'cafe', 'bar', 'brocante', 'sport', 'popup', 'boutique', 'rooftop', 'marche', 'autre']);

function getCatColor(cat) {
  if (!cat) return '#888';
  if (cat.startsWith('autre')) return CAT_COLORS['autre'];
  return CAT_COLORS[cat] || '#888';
}

function getCatEmoji(cat) {
  if (!cat) return '📌';
  if (cat.startsWith('autre')) return CAT_EMOJI['autre'];
  return CAT_EMOJI[cat] || '📌';
}

function getCatLabel(cat) {
  if (!cat) return 'AUTRE';
  if (cat.startsWith('autre')) return 'AUTRE';
  return cat.toUpperCase();
}

function getMuseumColor(normTitle) {
  const hasExpo = Object.entries(museumExposMap).some(([k]) => normalizeName(k) === normTitle);
  if (hasExpo) return '#4CAF50';
  if (museumEverParsedSet.has(normTitle)) return getCatColor('musee');
  return '#5C6470';
}

// ══════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════
function normalizeName(s) {
  return s.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180) * Math.cos(lat2*Math.PI/180) * Math.sin(dLng/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function formatDist(m) {
  return m < 1000 ? `${Math.round(m)}m` : `${(m/1000).toFixed(1)}km`;
}

function toProper(str) {
  if (!str) return '';
  return str
    .toLowerCase()
    .replace(/(?:^|\s|[-''])\S/g, c => c.toUpperCase());
}

const SOURCE_LABELS = {
  'lebonbon_food':    'LeBonbon',
  'lebonbon_drinks':  'LeBonbon',
  'lebonbon_news':    'LeBonbon',
  'lebonbon_healthy': 'LeBonbon',
  'sortiraparis':     'Sortir à Paris',
  'sortiraparis_restaurant': 'SortirAParis Restos',
  'sortiraparis_cafes':      'SortirAParis Cafés',
  'sortiraparis_expos':      'SortirAParis Expos',
  'sortiraparis_popup':      'SortirAParis Popup',
  'timeout_paris':    'Time Out Paris',
  'paris_opendata':   'Paris Opendata',
  'paris_fr':         'Paris.fr',
  'parisbouge_bars':  'ParisBouge',
  'parisbouge_restos':'ParisBouge',
  'parisbouge_expos': 'ParisBouge',
  'newtable':         'NewTable',
  'inpi_food':        'INPI',
  'inpi_drinks':      'INPI',
  'numero_popup':     'Numéro',
  'secrets_of_paris': 'Secrets of Paris',
  'parismusee_expos': 'Paris Musées',
  'OpenStreetMap':    'OpenStreetMap',
};

function formatSource(source) {
  if (!source) return '';
  return SOURCE_LABELS[source] || source;
}

function getApiDays() {
  if (periodMode === 'recent') {
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

  if (periodMode === 'nouveaux') {
    return events.filter(e => {
      if (!e.date_debut && !e.date_fin) return true;
      return e.date_debut === today;
    });
  }

  if (periodMode === 'current') {
    return events.filter(e => {
      if (!e.date_debut && !e.date_fin) return true;
      if (e.date_debut && e.date_debut > today) return false;
      if (e.date_fin && e.date_fin < today) return false;
      return true;
    });
  }

  if (periodMode === 'recent') {
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
  if (periodMode === 'nouveaux') {
    banner.textContent = `Événements ayant débuté aujourd'hui (${todayFr})`;
    banner.classList.add('visible');
  } else if (periodMode === 'recent') {
    const val  = document.getElementById('period-days-val').value  || '7';
    const unit = document.getElementById('period-days-unit').value || '1';
    const unitLabel = unit === '1'
      ? (val === '1' ? 'jour' : 'jours')
      : unit === '7'
        ? (val === '1' ? 'semaine' : 'semaines')
        : (val === '1' ? 'mois' : 'mois');
    banner.textContent = `Événements ayant débuté il y a moins de ${val} ${unitLabel}`;
    banner.classList.add('visible');
  } else if (periodMode === 'current') {
    banner.textContent = 'Événements actuellement en cours';
    banner.classList.add('visible');
  } else {
    banner.classList.remove('visible');
  }
}

function isNew(identifiedDate) {
  if (!identifiedDate) return false;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  return new Date(identifiedDate) >= cutoff;
}

function freshnessWidth(identifiedDate) {
  if (!identifiedDate) return 0;
  const days = (Date.now() - new Date(identifiedDate)) / (1000 * 60 * 60 * 24);
  return Math.max(0, Math.round(100 - (days / 30) * 100));
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
  currentMapCats = catSet;

  const mapCats = document.getElementById('map-cats');
  mapCats.innerHTML = '';
  const catsToShow = (activeCategories.size === 0
    ? ALL_CATS
    : ALL_CATS.filter(({ cat }) => activeCategories.has(cat))
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

const _PARIS_POLY = [
  [48.9022, 2.3084],[48.8985, 2.3650],[48.8855, 2.4050],
  [48.8650, 2.4175],[48.8450, 2.4175],[48.8300, 2.3780],
  [48.8195, 2.3311],[48.8242, 2.2857],[48.8395, 2.2535],
  [48.8572, 2.2350],[48.8789, 2.2600],[48.9022, 2.3084],
];

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
  currentLat = lat;
  currentLng = lng;

  if (pinMarker) map.removeLayer(pinMarker);
  pinMarker = L.marker([lat, lng], { icon: makePinIcon(), draggable: true }).addTo(map);
  pinMarker.on('drag', e => {
    const p = e.target.getLatLng();
    currentLat = p.lat; currentLng = p.lng;
    updateCircle(p.lat, p.lng);
  });
  pinMarker.on('dragend', () => searchEvents());

  updateCircle(lat, lng);
  searchEvents();

  fetch(`${API_BASE}/museum-events/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lng, radius: currentRadius }),
  }).catch(() => {});
  setTimeout(() => refreshColors(), 10000);

  if (typeof openSidebarIfMobile === 'function') openSidebarIfMobile();
  if (window.innerWidth <= 768) {
    mapRadiusControl.classList.add('visible');
    mapSlider.value = currentRadius;
    mapLabel.textContent = currentRadius + 'm';
  }
}

function resetToBrowse() {
  if (pinMarker) { map.removeLayer(pinMarker); pinMarker = null; }
  if (radiusCircle) { map.removeLayer(radiusCircle); radiusCircle = null; }
  currentLat = null;
  currentLng = null;
  document.getElementById('eiffel-btn').classList.add('active');
  mapRadiusControl.classList.remove('visible');
  searchEventsBrowse();
}

function updateCircle(lat, lng) {
  if (radiusCircle) map.removeLayer(radiusCircle);
  radiusCircle = L.circle([lat, lng], {
    radius: currentRadius,
    color: 'rgb(0,246,111)',
    fillColor: 'rgb(0,246,111)',
    fillOpacity: 0.06,
    weight: 1.5,
    dashArray: '4 4'
  }).addTo(map);
}

// ══════════════════════════════════════════
// OVERPASS
// ══════════════════════════════════════════
async function fetchPOI(lat, lng, radius) {
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

// ══════════════════════════════════════════
// BACKEND EVENTS
// ══════════════════════════════════════════
async function fetchBackendEvents(lat, lng, radius) {
  const params = new URLSearchParams({ lat, lng, radius, days: getApiDays() });
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

// ══════════════════════════════════════════
// MUSEUM EXPOS
// ══════════════════════════════════════════
async function fetchMuseumExpos(lat, lng, radius) {
  const params = new URLSearchParams({ lat, lng, radius });
  const resp = await fetch(`${API_BASE}/museum-events?${params}`);
  if (!resp.ok) throw new Error(`Backend museum-events HTTP ${resp.status}`);
  const data = await resp.json();
  museumEverParsedSet = new Set((data.museums_ever_parsed || []).map(n => normalizeName(n)));
  return data.museums_with_recent_expos || {};
}

// ══════════════════════════════════════════
// REFRESH COLORS
// ══════════════════════════════════════════
async function refreshColors() {
  if (currentLat === null || !lastAllEvents.length) return;
  try {
    const prevMuseumParsed = [...museumEverParsedSet].sort().join(',');
    const prevMuseumExpos  = JSON.stringify(museumExposMap);
    const [newMuseumExpos] = await Promise.all([
      fetchMuseumExpos(currentLat, currentLng, currentRadius),
    ]);
    const changed =
      JSON.stringify(newMuseumExpos) !== prevMuseumExpos ||
      [...museumEverParsedSet].sort().join(',') !== prevMuseumParsed;
    if (!changed) return;
    museumExposMap = newMuseumExpos;
    const filtered = activeCategories.size === 0
      ? lastAllEvents
      : lastAllEvents.filter(e => {
          const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
          return activeCategories.has(eCat);
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
  if (!eventMarkers.length) return;
  eventMarkers.forEach(m => {
    if (m._icon) {
      m._icon.style.transition = 'opacity 0.2s';
      m._icon.style.opacity = '0';
    }
  });
  await new Promise(r => setTimeout(r, 200));
  eventMarkers.forEach(m => map.removeLayer(m));
  eventMarkers = [];
}

// ══════════════════════════════════════════
// SEARCH
// ══════════════════════════════════════════
async function searchEvents() {
  if (currentLat === null) return;

  const loading = document.getElementById('loading');
  const warning = document.getElementById('backend-warning');
  const isFirst = lastAllEvents.length === 0;

  if (isFirst) {
    loading.classList.add('visible');
  } else {
    showSkeletons();
  }

  if (radiusCircle && radiusCircle._path) radiusCircle._path.classList.add('pulsing');
  await fadeOutMarkers();

  const fetchOverpass = activeCategories.size === 0 || [...activeCategories].some(c => OVERPASS_CATS.has(c));
  const fetchBackend  = activeCategories.size === 0 || [...activeCategories].some(c => BACKEND_CATS.has(c) || c.startsWith('autre'));
  const fetchMusee    = activeCategories.size === 0 || activeCategories.has('musee');

  const [overpassResult, backendResult, museeResult] = await Promise.allSettled([
    fetchOverpass ? fetchPOI(currentLat, currentLng, currentRadius) : Promise.resolve([]),
    fetchBackend  ? fetchBackendEvents(currentLat, currentLng, currentRadius) : Promise.resolve([]),
    fetchMusee    ? fetchMuseumExpos(currentLat, currentLng, currentRadius) : Promise.resolve({}),
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

  museumExposMap = {};
  if (museeResult.status === 'fulfilled') museumExposMap = museeResult.value;
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
  const showingPermanents = showPermanents;
  if (!showingPermanents) {
    for (let i = all.length - 1; i >= 0; i--) {
      if (all[i].source === 'OpenStreetMap') all.splice(i, 1);
    }
  }

  // Filtre catégorie
  let filtered = activeCategories.size === 0
    ? all
    : all.filter(e => {
        const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
        return activeCategories.has(eCat);
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

  lastAllEvents = all;
  filtered.forEach((e, i) => { e._id = 'e' + i; });
  renderEvents(filtered);
  renderMarkers(filtered.filter(e => e.lat && e.lng));

  loading.classList.remove('visible');
  if (radiusCircle && radiusCircle._path) radiusCircle._path.classList.remove('pulsing');
}

async function searchEventsBrowse() {
  showSkeletons();
  await fadeOutMarkers();
  const PARIS_LAT = 48.8566, PARIS_LNG = 2.3522;
  try {
    const showingPermanents = showPermanents;

    const params = new URLSearchParams({
      lat: PARIS_LAT, lng: PARIS_LNG, radius: 5000, days: getApiDays()
    });
    if (activeCategories.size === 1) params.set('cat', [...activeCategories][0]);

    const fetchOverpass = showingPermanents
      && (activeCategories.size === 0 || [...activeCategories].some(c => OVERPASS_CATS.has(c)));

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
    if (activeCategories.size > 1) {
      events = events.filter(e => {
        const eCat = (e.cat || '').startsWith('autre') ? 'autre' : e.cat;
        return activeCategories.has(eCat);
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
      ? (Object.entries(museumExposMap).find(([k]) => normalizeName(k) === normalizeName(e.titre)) || [])[1] || []
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
  eventMarkers.forEach(m => map.removeLayer(m));
  eventMarkers = [];

  events.forEach((e, i) => {
    const normTitle = normalizeName(e.titre);
    const expos     = e.cat === 'musee'
      ? (Object.entries(museumExposMap).find(([k]) => normalizeName(k) === normTitle) || [])[1] || []
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
    eventMarkers.push(marker);
  });
}

// ══════════════════════════════════════════
// FOCUS / HIGHLIGHT
// ══════════════════════════════════════════
function focusEvent(id, lat, lng) {
  map.panTo([lat, lng], { animate: true, duration: 0.5 });
  const m = eventMarkers.find(m => m.eventId === id);
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
  currentRadius = parseInt(e.target.value);
  document.getElementById('radius-val').textContent = currentRadius;
  mapSlider.value = currentRadius;
  mapLabel.textContent = currentRadius + 'm';
  if (currentLat) {
    updateCircle(currentLat, currentLng);
    if (window.innerWidth > 768) {
      clearTimeout(sliderDebounce);
      sliderDebounce = setTimeout(() => searchEvents(), 400);
    }
  }
});

// ── SLIDER CARTE (mobile) ──
mapSlider.addEventListener('input', e => {
  currentRadius = parseInt(e.target.value);
  mapLabel.textContent = currentRadius + 'm';
  document.getElementById('radius-slider').value = currentRadius;
  document.getElementById('radius-val').textContent = currentRadius;
  if (currentLat) {
    updateCircle(currentLat, currentLng);
    if (window.innerWidth > 768) {
      clearTimeout(sliderDebounce);
      sliderDebounce = setTimeout(() => searchEvents(), 400);
    }
  }
});

// ══════════════════════════════════════════
// CATEGORY FILTER PANEL
// ══════════════════════════════════════════
const ALL_CATS = [
  { cat: 'musique',      emoji: '🎵', label: 'Musique' },
  { cat: 'exposition',   emoji: '🖼', label: 'Expo' },
  { cat: 'restaurant',   emoji: '🍽', label: 'Restaurant' },
  { cat: 'bar',          emoji: '🍺', label: 'Bar' },
  { cat: 'cafe',         emoji: '☕', label: 'Café' },
  { cat: 'rooftop',      emoji: '🌇', label: 'Rooftop' },
  { cat: 'popup',        emoji: '🛍', label: 'Pop-up' },
  { cat: 'boutique',     emoji: '🏪', label: 'Boutique' },
  { cat: 'wellness',     emoji: '🧘', label: 'Wellness' },
  { cat: 'spectacle',    emoji: '🎭', label: 'Spectacle' },
  { cat: 'cinema',       emoji: '🎬', label: 'Cinéma' },
  { cat: 'musee',        emoji: '🏛', label: 'Musée' },
  { cat: 'marche',       emoji: '🛒', label: 'Marché' },
  { cat: 'brocante',     emoji: '🪑', label: 'Brocante' },
  { cat: 'vide-grenier', emoji: '🪑', label: 'Vide-grenier' },
  { cat: 'sport',        emoji: '🏃', label: 'Sport' },
  { cat: 'atelier',      emoji: '🎨', label: 'Atelier' },
  { cat: 'autre',        emoji: '📌', label: 'Autre' },
];

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
  activeCategories = selected;
  document.getElementById('cat-filter-btn').classList.toggle('active', selected.size > 0);
  _closeCatPanel();
  if (currentLat !== null) searchEvents();
  else searchEventsBrowse();
}

const catPanel     = document.getElementById('cat-filter-panel');
const catFilterBtn = document.getElementById('cat-filter-btn');

function _openCatPanel() {
  if (activeCategories.size === 0) {
    document.querySelectorAll('.cat-filter-chip').forEach(chip => {
      chip.classList.toggle('selected', currentMapCats.has(chip.dataset.cat));
    });
    _syncToutState();
  }
  catPanel.classList.add('open');
  catFilterBtn.classList.add('active');
}
function _closeCatPanel() {
  catPanel.classList.remove('open');
  if (activeCategories.size === 0) catFilterBtn.classList.remove('active');
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
    periodMode = opt.dataset.mode;
    const labels = { nouveaux: 'Ouverts aujourd\'hui', current: 'En cours', recent: 'Récents' };
    periodLabel.textContent = labels[periodMode];
    updatePeriodBanner();

    // Si le clic vient de l'input ou du select, garder le popover ouvert
    if (e.target.closest('.period-inline')) return;

    periodPopover.classList.add('hidden');
    if (window.innerWidth > 768) {
      if (currentLat !== null) searchEvents();
      else searchEventsBrowse();
    }
  });
});

document.getElementById('period-days-val').addEventListener('change', () => {
  periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (currentLat) searchEvents();
    else searchEventsBrowse();
  }
});
document.getElementById('period-days-unit').addEventListener('change', () => {
  periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (currentLat) searchEvents();
    else searchEventsBrowse();
  }
});

// ══════════════════════════════════════════
// TOGGLE PERMANENTS
// ══════════════════════════════════════════
document.getElementById('show-all-btn').addEventListener('click', () => {
  showPermanents = !showPermanents;
  document.getElementById('show-all-btn').classList.toggle('active', showPermanents);
  if (currentLat !== null) searchEvents();
  else searchEventsBrowse();
});

document.getElementById('apply-filters-btn').addEventListener('click', () => {
  if (currentLat !== null) searchEvents();
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
