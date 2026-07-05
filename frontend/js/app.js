import {
  API_BASE,
  CAT_COLORS, CAT_EMOJI, SOURCE_LABELS, ALL_CATS
} from './config.js';

import { state } from './state.js';
import { fetchSuggestions } from './api.js';
import {
  initMap, makeMarkerIcon, makePinIcon,
  updateCircle, isInsideParis
} from './map.js';
import { updatePeriodBanner } from './filters.js';
import { focusEvent, highlightCard } from './render.js';
import { searchEvents, searchEventsBrowse, refreshColors } from './search.js';

initMap();

// Fonction appelée depuis des onclick inline — doit rester globale
window.focusEvent = focusEvent;

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
      state.map.setView([lat, lng], 16, { animate: true });
      placePin(lat, lng);
    });
  });
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
  if (state.pinMarker) { state.map.removeLayer(state.pinMarker); state.pinMarker = null; }
  if (state.radiusCircle) { state.map.removeLayer(state.radiusCircle); state.radiusCircle = null; }
  state.currentLat = null;
  state.currentLng = null;
  document.getElementById('eiffel-btn').classList.add('active');
  mapRadiusControl.classList.remove('visible');
  searchEventsBrowse();
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
searchEventsBrowse();
updatePeriodBanner();
