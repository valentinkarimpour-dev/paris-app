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
  activeSources:       new Set(),
  activeSourceGroups:  new Set(),
  periodMode:          'nouveaux',
  museumExposMap:      {},
  museumEverParsedSet: new Set(),
  lastAllEvents:       [],
  showPermanents:      false,
  selectedEventId:     null,
  events:              [],   // tous les events fetched (avant filtrage)
  filteredEvents:      [],   // events après applyPeriodFilter et filtre catégories
};
