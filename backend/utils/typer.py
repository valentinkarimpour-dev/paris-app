"""
Typage des galeries sans LLM :
  1. Tags OSM directs (gallery:type, art_type, subject:art)
  2. Mots-clés dans nom + description + subject
  3. Mots-clés dans le domaine du site web (dernier recours)
"""

from urllib.parse import urlparse

OSM_TYPE_MAP: dict[str, str] = {
    "photography":     "photographie",
    "photo":           "photographie",
    "sculpture":       "sculpture",
    "design":          "design",
    "contemporary":    "art_contemporain",
    "modern":          "art_contemporain",
    "painting":        "peinture",
    "print":           "estampe",
    "tribal":          "art_du_monde",
    "antique":         "antiquites",
    "illustration":    "illustration",
    "street_art":      "street_art",
    "graffiti":        "street_art",
    "fine_art":        "peinture",
    "decorative_art":  "design",
    "applied_art":     "design",
}

KEYWORD_TYPE_MAP: list[tuple[list[str], str]] = [
    (["photo", "photograph", "photographie", "argentique"],
     "photographie"),
    (["sculpture", "bronzes", "céramique", "ceramique", "terre cuite"],
     "sculpture"),
    (["design", "graphisme", "graphique", "affiche"],
     "design"),
    (["contemporain", "contemporary", "actuel", "moderne", "emergent", "émergent"],
     "art_contemporain"),
    (["peinture", "painting", "tableau", "huile", "aquarelle"],
     "peinture"),
    (["estampe", "gravure", "lithographie", "sérigraphie", "serigraphie"],
     "estampe"),
    (["afrique", "africain", "tribal", "oceanie", "océanie",
      "asie", "asiatique", "chine", "japon", "inde"],
     "art_du_monde"),
    (["antiquit", "ancien", "archéolog", "archeolog"],
     "antiquites"),
    (["illustration", "bande dessinee", "bd ", "manga"],
     "illustration"),
    (["street art", "urban art", "graffiti"],
     "street_art"),
]


def type_from_osm_tags(tags: dict) -> str:
    for field in ["gallery:type", "art_type", "subject:art", "tourism:type"]:
        val = tags.get(field, "").lower().strip()
        if val and val in OSM_TYPE_MAP:
            return OSM_TYPE_MAP[val]
    return "inconnu"


def type_from_keywords(text: str, website: str = "") -> str:
    low = text.lower()
    for keywords, gtype in KEYWORD_TYPE_MAP:
        if any(kw in low for kw in keywords):
            return gtype
    if website:
        domain = urlparse(website).netloc.lower()
        for keywords, gtype in KEYWORD_TYPE_MAP:
            if any(kw in domain for kw in keywords):
                return gtype
    return "inconnu"


def classify_gallery(tags: dict) -> tuple[str, str]:
    """Retourne (gallery_type, source) où source est 'osm' ou 'keywords'."""
    gtype = type_from_osm_tags(tags)
    if gtype != "inconnu":
        return gtype, "osm"
    text = " ".join(filter(None, [
        tags.get("name", ""),
        tags.get("description", ""),
        tags.get("subject", ""),
        tags.get("name:fr", ""),
    ]))
    website = tags.get("website", "") or tags.get("contact:website", "")
    gtype = type_from_keywords(text, website)
    return gtype, "keywords"
