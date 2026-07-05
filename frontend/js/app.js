import { API_BASE, ALL_CATS, SOURCE_FILTER_GROUPS, isBaselineSourceSelection } from './config.js';

import { state } from './state.js';
import { fetchSuggestions } from './api.js';
import { initMap, makePinIcon, updateCircle, isInsideParis } from './map.js';
import { updatePeriodBanner } from './filters.js';
import { highlightCard, renderSuggestions } from './render.js';
import { searchEvents, searchEventsBrowse, refreshColors } from './search.js';

// ═══════════════════════════════════════════════════════════
// app.js — Orchestrateur principal
// Contient : init, event listeners, UI helpers
// Logique métier → search.js | filters.js | render.js
// Cartographie  → map.js
// API           → api.js
// État          → state.js
// Constantes    → config.js | utils.js
// ═══════════════════════════════════════════════════════════

initMap();

// ══════════════════════════════════════════
// SELECT EVENT — sidebar card, marker, ou onclick inline
// ══════════════════════════════════════════
function selectEvent(eventId, { pan = true } = {}) {
  state.selectedEventId = eventId;
  highlightCard(eventId);

  const marker = state.eventMarkers.find(m => m.eventId === eventId);
  if (pan && marker) {
    state.map.panTo(marker.getLatLng(), { animate: true, duration: 0.5 });
  }
  if (marker) {
    marker.openPopup();
  }
}

const onMarkerClick = (id) => selectEvent(id, { pan: false });

// Fonctions appelées depuis des onclick inline — doivent rester globales
window.focusEvent = (id) => selectEvent(id, { pan: true });
window.selectEvent = selectEvent;

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
  searchDebounce = setTimeout(() => fetchSuggestions(q, features => renderSuggestions(features, selectAddressSuggestion)), 300);
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


function selectAddressSuggestion(lat, lng, label) {
  addressInput.value = label;
  suggestions.classList.add('hidden');
  searchClear.classList.remove('hidden');
  state.map.setView([lat, lng], 16, { animate: true });
  placePin(lat, lng);
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

  if (state.pinMarker) state.map.removeLayer(state.pinMarker);
  state.pinMarker = L.marker([lat, lng], { icon: makePinIcon(), draggable: true }).addTo(state.map);
  state.pinMarker.on('drag', e => {
    const p = e.target.getLatLng();
    state.currentLat = p.lat; state.currentLng = p.lng;
    updateCircle(p.lat, p.lng);
  });
  state.pinMarker.on('dragend', () => searchEvents(onMarkerClick));

  updateCircle(lat, lng);
  searchEvents(onMarkerClick);

  fetch(`${API_BASE}/museum-events/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lng, radius: state.currentRadius }),
  }).catch(() => {});
  setTimeout(() => refreshColors(onMarkerClick), 10000);

  if (typeof openSidebarIfMobile === 'function') openSidebarIfMobile();
  if (window.innerWidth <= 768) {
    mapRadiusControl.classList.add('visible');
    mapSlider.value = state.currentRadius;
    mapLabel.textContent = state.currentRadius + 'm';
  }
}

function resetToBrowse() {
  if (state.pinMarker) { state.map.removeLayer(state.pinMarker); state.pinMarker = null; }
  if (state.radiusCircle) { state.map.removeLayer(state.radiusCircle); state.radiusCircle = null; }
  state.currentLat = null;
  state.currentLng = null;
  document.getElementById('eiffel-btn').classList.add('active');
  mapRadiusControl.classList.remove('visible');
  searchEventsBrowse(onMarkerClick);
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
      sliderDebounce = setTimeout(() => searchEvents(onMarkerClick), 400);
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
      sliderDebounce = setTimeout(() => searchEvents(onMarkerClick), 400);
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
  if (state.currentLat !== null) searchEvents(onMarkerClick);
  else searchEventsBrowse(onMarkerClick);
}

const catPanel     = document.getElementById('cat-filter-panel');
const catFilterBtn = document.getElementById('cat-filter-btn');

function _openCatPanel() {
  _closeSourcePanel();
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

state.map.on('click', _closeCatPanel);
state.map.on('drag',  _closeCatPanel);
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
// SOURCE FILTER PANEL
// ══════════════════════════════════════════

const sourceChipsContainer = document.getElementById('source-filter-chips');
SOURCE_FILTER_GROUPS.forEach(({ key, label, sources }) => {
  const chip = document.createElement('button');
  chip.className = 'source-filter-chip' + (state.activeSourceGroups.has(key) ? ' selected' : '');
  chip.dataset.key = key;
  chip.dataset.sources = sources.join(',');
  chip.textContent = label;
  chip.addEventListener('click', () => {
    chip.classList.toggle('selected');
    _syncSourceToutState();
  });
  sourceChipsContainer.appendChild(chip);
});

function _syncSourceToutState() {
  const all = document.querySelectorAll('.source-filter-chip');
  const sel = document.querySelectorAll('.source-filter-chip.selected');
  document.getElementById('source-filter-tout').classList.toggle('active', sel.length === all.length && all.length > 0);
}

function _applySources() {
  const selectedChips = [...document.querySelectorAll('.source-filter-chip.selected')];
  state.activeSourceGroups = new Set(selectedChips.map(c => c.dataset.key));
  state.activeSources = new Set(selectedChips.flatMap(c => c.dataset.sources.split(',')));
  document.getElementById('source-filter-btn').classList.toggle('active', !isBaselineSourceSelection(state.activeSourceGroups));
  _closeSourcePanel();
  _renderSourceChips();
  if (state.currentLat !== null) searchEvents(onMarkerClick);
  else searchEventsBrowse(onMarkerClick);
}

const sourcePanel     = document.getElementById('source-filter-panel');
const sourceFilterBtn = document.getElementById('source-filter-btn');
const mapSourcesEl    = document.getElementById('map-sources');

function _openSourcePanel() {
  _closeCatPanel();
  sourcePanel.classList.add('open');
  sourceFilterBtn.classList.add('active');
}
function _closeSourcePanel() {
  sourcePanel.classList.remove('open');
  if (isBaselineSourceSelection(state.activeSourceGroups)) sourceFilterBtn.classList.remove('active');
}
function _toggleSourcePanel() {
  sourcePanel.classList.contains('open') ? _closeSourcePanel() : _openSourcePanel();
}

// Chips récapitulatifs sous la carte : masqués si la sélection ne constitue
// pas un vrai filtre (tout sélectionné, ou exactement le défaut sans INPI).
const MAX_SOURCE_CHIPS = 3;
function _renderSourceChips() {
  mapSourcesEl.innerHTML = '';
  const selected = state.activeSourceGroups;
  if (isBaselineSourceSelection(selected)) return;

  const selectedGroups = SOURCE_FILTER_GROUPS.filter(g => selected.has(g.key));
  selectedGroups.slice(0, MAX_SOURCE_CHIPS).forEach(({ label }) => {
    const tag = document.createElement('button');
    tag.className = 'cat-btn active';
    tag.textContent = label;
    tag.addEventListener('click', _toggleSourcePanel);
    mapSourcesEl.appendChild(tag);
  });
  if (selectedGroups.length > MAX_SOURCE_CHIPS) {
    const more = document.createElement('button');
    more.className = 'cat-more-btn';
    more.textContent = `+${selectedGroups.length - MAX_SOURCE_CHIPS}`;
    more.addEventListener('click', _toggleSourcePanel);
    mapSourcesEl.appendChild(more);
  }
}

sourceFilterBtn.addEventListener('click', e => {
  e.stopPropagation();
  _toggleSourcePanel();
});

state.map.on('click', _closeSourcePanel);
state.map.on('drag',  _closeSourcePanel);
document.getElementById('source-filter-apply').addEventListener('click', _applySources);

const sourceToutBtn = document.getElementById('source-filter-tout');
sourceToutBtn.addEventListener('click', () => {
  const allChips = document.querySelectorAll('.source-filter-chip');
  const allSelected = [...allChips].every(c => c.classList.contains('selected'));
  allChips.forEach(c => allSelected ? c.classList.remove('selected') : c.classList.add('selected'));
  _syncSourceToutState();
});

sourcePanel.addEventListener('click', e => e.stopPropagation());

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
      if (state.currentLat !== null) searchEvents(onMarkerClick);
      else searchEventsBrowse(onMarkerClick);
    }
  });
});

document.getElementById('period-days-val').addEventListener('change', () => {
  state.periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (state.currentLat) searchEvents(onMarkerClick);
    else searchEventsBrowse(onMarkerClick);
  }
});
document.getElementById('period-days-unit').addEventListener('change', () => {
  state.periodMode = 'recent';
  updatePeriodBanner();
  periodPopover.classList.add('hidden');
  if (window.innerWidth > 768) {
    if (state.currentLat) searchEvents(onMarkerClick);
    else searchEventsBrowse(onMarkerClick);
  }
});

// ══════════════════════════════════════════
// TOGGLE PERMANENTS
// ══════════════════════════════════════════
document.getElementById('show-all-btn').addEventListener('click', () => {
  state.showPermanents = !state.showPermanents;
  document.getElementById('show-all-btn').classList.toggle('active', state.showPermanents);
  if (state.currentLat !== null) searchEvents(onMarkerClick);
  else searchEventsBrowse(onMarkerClick);
});

document.getElementById('apply-filters-btn').addEventListener('click', () => {
  if (state.currentLat !== null) searchEvents(onMarkerClick);
  else searchEventsBrowse(onMarkerClick);
  if (window.innerWidth <= 768) {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('visible');
  }
});

document.getElementById('eiffel-btn').addEventListener('click', () => {
  resetToBrowse();
});

state.map.on('click', e => {
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
      state.map.setView([lat, lng], 16, { animate: true });
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
      setTimeout(() => state.map.invalidateSize(), 320);
    }
  });
  overlay.addEventListener('click', closeSidebar);

  window.openSidebarIfMobile = function() { if (isMobile()) openSidebar(); };
})();

// Chargement initial — tous les événements Nouveaux sur Paris
searchEventsBrowse(onMarkerClick);
updatePeriodBanner();
