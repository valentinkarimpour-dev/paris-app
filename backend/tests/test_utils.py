"""Tests unitaires pour backend/utils — sans réseau ni DB."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from utils.typer import type_from_keywords, type_from_osm_tags, classify_gallery
from utils.expo_parser import extract_expos_from_html


# ── typer.py ──────────────────────────────────────────────────────────────────

class TestTyper:
    def test_photo(self):
        assert type_from_keywords("Galerie Photo Bastille") == "photographie"

    def test_photographie_accent(self):
        assert type_from_keywords("Galerie de photographie contemporaine") == "photographie"

    def test_sculpture(self):
        assert type_from_keywords("Espace Sculpture du Marais") == "sculpture"

    def test_contemporain(self):
        assert type_from_keywords("Galerie d'art contemporain du 11e") == "art_contemporain"

    def test_peinture(self):
        assert type_from_keywords("Atelier peinture et aquarelle") == "peinture"

    def test_inconnu(self):
        assert type_from_keywords("Galerie XYZ") == "inconnu"

    def test_domain_fallback(self):
        assert type_from_keywords("Galerie XYZ", website="https://galeriephoto-paris.fr") == "photographie"

    def test_osm_tag_photography(self):
        tags = {"gallery:type": "photography", "name": "Galerie Z"}
        assert type_from_osm_tags(tags) == "photographie"

    def test_osm_tag_contemporary(self):
        tags = {"art_type": "contemporary", "name": "Espace X"}
        assert type_from_osm_tags(tags) == "art_contemporain"

    def test_osm_no_tag(self):
        tags = {"name": "Galerie sans tag"}
        assert type_from_osm_tags(tags) == "inconnu"

    def test_classify_osm_source(self):
        tags = {"gallery:type": "sculpture", "name": "X"}
        gtype, source = classify_gallery(tags)
        assert gtype == "sculpture"
        assert source == "osm"

    def test_classify_keywords_source(self):
        tags = {"name": "Espace Photo Paris"}
        gtype, source = classify_gallery(tags)
        assert gtype == "photographie"
        assert source == "keywords"

    def test_classify_inconnu(self):
        tags = {"name": "L'Espace"}
        gtype, _ = classify_gallery(tags)
        assert gtype == "inconnu"


# ── expo_parser.py ─────────────────────────────────────────────────────────────

# Simule aujourd'hui = 2026-05-11
_HTML_TIME = """
<html><body><main>
  <h2>Regards sur le Japon</h2>
  <p>du <time datetime="2026-04-15">15 avril 2026</time>
     au <time datetime="2026-07-20">20 juillet 2026</time></p>
</main></body></html>
"""

_HTML_PATTERN = """
<html><body><main>
  <p>Exposition : Regards sur le Japon, du 3 avril au 30 juin 2026</p>
</main></body></html>
"""

_HTML_EMPTY = """
<html><body><main>
  <p>Bienvenue dans notre galerie. Contactez-nous pour plus d'informations.</p>
</main></body></html>
"""

_HTML_UNTIL = """
<html><body><main>
  <h2>Corps et matières</h2>
  <p>Exposition jusqu'au 28 juin 2026</p>
</main></body></html>
"""

_HTML_FINISHED = """
<html><body><main>
  <p>Exposition : Lumières d'hiver, du 3 janvier au 15 février 2026</p>
</main></body></html>
"""


class TestExpoParser:
    def test_time_tag_extracts_dates(self):
        expos = extract_expos_from_html(_HTML_TIME, "https://example.com")
        assert len(expos) >= 1
        e = expos[0]
        assert "Japon" in e["titre"]
        assert e["date_debut"] == "2026-04-15"
        assert e["date_fin"] == "2026-07-20"
        assert e["confidence"] == "high"

    def test_pattern_match_extracts_title(self):
        expos = extract_expos_from_html(_HTML_PATTERN, "https://example.com")
        assert len(expos) >= 1
        assert "Japon" in expos[0]["titre"]
        assert expos[0]["date_fin"] is not None

    def test_empty_html_returns_empty(self):
        expos = extract_expos_from_html(_HTML_EMPTY, "https://example.com")
        assert expos == []

    def test_until_date(self):
        expos = extract_expos_from_html(_HTML_UNTIL, "https://example.com")
        # "jusqu'au 28 juin 2026" → date_fin extracted
        assert any(e["date_fin"] is not None for e in expos)

    def test_finished_expo_filtered_out(self):
        # Expo terminée en février 2026 — should be filtered (today = mai 2026)
        expos = extract_expos_from_html(_HTML_FINISHED, "https://example.com")
        assert expos == []
