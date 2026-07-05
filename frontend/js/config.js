export const API_BASE = 'http://145.241.168.3:8000';

export const OVERPASS_CATS = new Set(['cinema', 'musee']);
export const BACKEND_CATS  = new Set(['musique', 'exposition', 'vide-grenier', 'spectacle', 'atelier', 'restaurant', 'cafe', 'bar', 'brocante', 'sport', 'popup', 'boutique', 'rooftop', 'marche', 'loisirs', 'autre']);

export const CAT_COLORS = {
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
  loisirs:        '#4CAF50',
  autre:          '#888888',
};

export const CAT_EMOJI = {
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
  loisirs:        '🎡',
  autre:          '📌',
};

export const SOURCE_LABELS = {
  'lebonbon_food':    'LeBonbon',
  'lebonbon_drinks':  'LeBonbon',
  'lebonbon_news':    'LeBonbon',
  'lebonbon_healthy': 'LeBonbon',
  'lebonbon_loisirs': 'LeBonbon',
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

// Sources de scraping filtrables sur la carte.
// Les sources musées (parismusee_expos, museofile) et OpenStreetMap sont
// volontairement ignorées : elles restent toujours affichées, quel que soit
// le filtre. Quand une nouvelle source de scraping valide est ajoutée,
// il faut penser à l'ajouter ici pour qu'elle apparaisse dans le filtre.
export const SOURCE_FILTER_GROUPS = [
  { key: 'sortiraparis', label: 'Sortir à Paris',   sources: ['sortiraparis', 'sortiraparis_restaurant', 'sortiraparis_cafes', 'sortiraparis_expos', 'sortiraparis_popup'] },
  { key: 'lebonbon',     label: 'LeBonbon',          sources: ['lebonbon_food', 'lebonbon_drinks', 'lebonbon_news', 'lebonbon_healthy', 'lebonbon_loisirs'] },
  { key: 'parisbouge',   label: 'ParisBouge',        sources: ['parisbouge_bars', 'parisbouge_restos', 'parisbouge_expos', 'parisbouge_autre'] },
  { key: 'timeout',      label: 'Time Out Paris',    sources: ['timeout_paris'] },
  { key: 'newtable',     label: 'NewTable',          sources: ['newtable'] },
  { key: 'numero',       label: 'Numéro',            sources: ['numero_popup'] },
  { key: 'secrets',      label: 'Secrets of Paris',  sources: ['secrets_of_paris'] },
  { key: 'inpi',         label: 'INPI',              sources: ['inpi_food', 'inpi_drinks'] },
  { key: 'opendata',     label: 'Paris Opendata',    sources: ['paris_opendata'] },
];

// Groupes de sources exclus par défaut à l'ouverture du site — activables
// manuellement via le filtre source. INPI n'est pris en compte que si
// l'utilisateur clique explicitement dessus dans le filtre.
export const DEFAULT_EXCLUDED_SOURCE_GROUPS = new Set(['inpi']);

export const DEFAULT_SOURCE_GROUP_KEYS = new Set(
  SOURCE_FILTER_GROUPS.filter(g => !DEFAULT_EXCLUDED_SOURCE_GROUPS.has(g.key)).map(g => g.key)
);

// Vrai si la sélection de groupes ne constitue pas un vrai filtre : soit
// tout est sélectionné, soit c'est exactement la sélection par défaut
// (tout sauf INPI). Dans ces deux cas, l'UI ne doit rien signaler
// (ni chips sous la carte, ni bouton mis en évidence).
export function isBaselineSourceSelection(groupKeysSet) {
  if (groupKeysSet.size === SOURCE_FILTER_GROUPS.length) return true;
  if (groupKeysSet.size === DEFAULT_SOURCE_GROUP_KEYS.size &&
      [...groupKeysSet].every(k => DEFAULT_SOURCE_GROUP_KEYS.has(k))) return true;
  return false;
}

export const ALL_CATS = [
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
  { cat: 'loisirs',      emoji: '🎡', label: 'Loisirs' },
  { cat: 'autre',        emoji: '📌', label: 'Autre' },
];

export const _PARIS_POLY = [
  [48.9022, 2.3084],[48.8985, 2.3650],[48.8855, 2.4050],
  [48.8650, 2.4175],[48.8450, 2.4175],[48.8300, 2.3780],
  [48.8195, 2.3311],[48.8242, 2.2857],[48.8395, 2.2535],
  [48.8572, 2.2350],[48.8789, 2.2600],[48.9022, 2.3084],
];
