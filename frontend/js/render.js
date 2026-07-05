import { state } from './state.js';
import {
  getCatColor, getCatEmoji, getCatLabel,
  normalizeName, formatDist, toProper, getMuseumColor
} from './utils.js';

// ══════════════════════════════════════════
// RENDER EVENTS LIST
// ══════════════════════════════════════════
export function renderEvents(events) {
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
// ADDRESS SUGGESTIONS
// ══════════════════════════════════════════
export function renderSuggestions(features, onSelect) {
  const suggestions = document.getElementById('search-suggestions');
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
      onSelect(lat, lng, item.dataset.label);
    });
  });
}

// ══════════════════════════════════════════
// HIGHLIGHT
// ══════════════════════════════════════════
export function highlightCard(id) {
  document.querySelectorAll('.event-card').forEach(c => c.classList.remove('highlighted'));
  const card = document.querySelector(`.event-card[data-id="${id}"]`);
  if (card) {
    card.classList.add('highlighted');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}
