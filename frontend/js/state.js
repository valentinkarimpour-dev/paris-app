import { SOURCE_FILTER_GROUPS, DEFAULT_SOURCE_GROUP_KEYS } from './config.js';

// Sources actives par défaut : tous les groupes sauf ceux explicitement
// exclus (INPI) tant que l'utilisateur n'a rien choisi dans le filtre.
const _defaultSourceGroups = SOURCE_FILTER_GROUPS.filter(g => DEFAULT_SOURCE_GROUP_KEYS.has(g.key));

export const state = {
  map:                 null,
  pinMarker:           null,
  radiusCircle:        null,
  eventMarkers:        [],
  currentLat:          null,
  currentLng:          null,
  currentRadius:       500,
  activeCategories:    new Set(),
  currentMapCats:      new Set(),
  activeSources:       new Set(_defaultSourceGroups.flatMap(g => g.sources)),
  activeSourceGroups:  new Set(_defaultSourceGroups.map(g => g.key)),
  periodMode:          'nouveaux',
  museumExposMap:      {},
  museumEverParsedSet: new Set(),
  lastAllEvents:       [],
  showPermanents:      false,
  selectedEventId:     null,
  events:              [],   // tous les events fetched (avant filtrage)
  filteredEvents:      [],   // events après applyPeriodFilter et filtre catégories
};
