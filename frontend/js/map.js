import { state } from './state.js';
import { _PARIS_POLY } from './config.js';
import {
  getCatColor, getCatEmoji, getCatLabel,
  normalizeName, formatDist, formatSource, toProper, getMuseumColor
} from './utils.js';
import { highlightCard } from './render.js';

// ══════════════════════════════════════════
// MAP INIT — CartoDB Voyager
// ══════════════════════════════════════════
export function initMap() {
  state.map = L.map('map', {
    center: [48.8566, 2.3522],
    zoom: 14,
    zoomControl: false
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap contributors © CARTO',
    subdomains: 'abcd',
    maxZoom: 19
  }).addTo(state.map);

  L.control.zoom({ position: 'bottomright' }).addTo(state.map);

  return state.map;
}

// ══════════════════════════════════════════
// CUSTOM MARKER SVG (staggered bounce)
// ══════════════════════════════════════════
export function makeMarkerIcon(color, cat, delay = 0, opacity = 0.95) {
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

export function makePinIcon() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
      <circle cx="14" cy="14" r="6" fill="rgb(0,246,111)"/>
      <circle cx="14" cy="14" r="11" fill="none" stroke="rgb(0,246,111)" stroke-width="2" opacity="0.5"/>
      <circle cx="14" cy="14" r="14" fill="none" stroke="rgb(0,246,111)" stroke-width="1" opacity="0.2"/>
    </svg>`;
  return L.divIcon({ html: svg, className: '', iconSize: [28,28], iconAnchor: [14,14] });
}

// ══════════════════════════════════════════
// PARIS POLYGON CHECK
// ══════════════════════════════════════════
export function isInsideParis(lat, lng) {
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
// RADIUS CIRCLE
// ══════════════════════════════════════════
export function updateCircle(lat, lng) {
  if (state.radiusCircle) state.map.removeLayer(state.radiusCircle);
  state.radiusCircle = L.circle([lat, lng], {
    radius: state.currentRadius,
    color: 'rgb(0,246,111)',
    fillColor: 'rgb(0,246,111)',
    fillOpacity: 0.06,
    weight: 1.5,
    dashArray: '4 4'
  }).addTo(state.map);
}

// ══════════════════════════════════════════
// FADE OUT MARKERS
// ══════════════════════════════════════════
export async function fadeOutMarkers() {
  if (!state.eventMarkers.length) return;
  state.eventMarkers.forEach(m => {
    if (m._icon) {
      m._icon.style.transition = 'opacity 0.2s';
      m._icon.style.opacity = '0';
    }
  });
  await new Promise(r => setTimeout(r, 200));
  state.eventMarkers.forEach(m => state.map.removeLayer(m));
  state.eventMarkers = [];
}

// ══════════════════════════════════════════
// RENDER MAP MARKERS (staggered bounce)
// ══════════════════════════════════════════
export function renderMarkers(events) {
  state.eventMarkers.forEach(m => state.map.removeLayer(m));
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
      .addTo(state.map);

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
