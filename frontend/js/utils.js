import { CAT_COLORS, CAT_EMOJI, SOURCE_LABELS } from './config.js';

export function getCatColor(cat) {
  if (!cat) return '#888';
  if (cat.startsWith('autre')) return CAT_COLORS['autre'];
  return CAT_COLORS[cat] || '#888';
}

export function getCatEmoji(cat) {
  if (!cat) return '📌';
  if (cat.startsWith('autre')) return CAT_EMOJI['autre'];
  return CAT_EMOJI[cat] || '📌';
}

export function getCatLabel(cat) {
  if (!cat) return 'AUTRE';
  if (cat.startsWith('autre')) return 'AUTRE';
  return cat.toUpperCase();
}

export function normalizeName(s) {
  return s.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180) * Math.cos(lat2*Math.PI/180) * Math.sin(dLng/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

export function formatDist(m) {
  return m < 1000 ? `${Math.round(m)}m` : `${(m/1000).toFixed(1)}km`;
}

export function toProper(str) {
  if (!str) return '';
  return str
    .toLowerCase()
    .replace(/(?:^|\s|[-''])\S/g, c => c.toUpperCase());
}

export function formatSource(source) {
  if (!source) return '';
  return SOURCE_LABELS[source] || source;
}

export function isNew(identifiedDate) {
  if (!identifiedDate) return false;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  return new Date(identifiedDate) >= cutoff;
}

export function freshnessWidth(identifiedDate) {
  if (!identifiedDate) return 0;
  const days = (Date.now() - new Date(identifiedDate)) / (1000 * 60 * 60 * 24);
  return Math.max(0, Math.round(100 - (days / 30) * 100));
}
