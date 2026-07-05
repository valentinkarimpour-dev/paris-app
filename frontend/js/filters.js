// frontend/js/filters.js
import { state } from './state.js';
import { ALL_CATS } from './config.js';

export function getApiDays() {
  if (state.periodMode === 'recent') {
    const val  = parseInt(document.getElementById('period-days-val').value) || 30;
    const mult = parseInt(document.getElementById('period-days-unit').value) || 1;
    return Math.min(val * mult, 365);
  }
  return 365;
}

export function applyPeriodFilter(events) {
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

export function updatePeriodBanner() {
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
    banner.textContent = `Événements ayant débuté il y a moins de ${val} ${unitLabel}`;
    banner.classList.add('visible');
  } else if (state.periodMode === 'current') {
    banner.textContent = 'Événements actuellement en cours';
    banner.classList.add('visible');
  } else {
    banner.classList.remove('visible');
  }
}

// ══════════════════════════════════════════
// SKELETON
// ══════════════════════════════════════════
export function showSkeletons() {
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
export function updateCatCounts(allEvents, onChipClick) {
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
    tag.addEventListener('click', () => onChipClick());
    mapCats.appendChild(tag);
  });
  if (catsToShow.length > MAX_CHIPS) {
    const more = document.createElement('button');
    more.className = 'cat-more-btn';
    more.textContent = `+${catsToShow.length - MAX_CHIPS}`;
    more.addEventListener('click', () => onChipClick());
    mapCats.appendChild(more);
  }
}
