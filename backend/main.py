"""
Flâneur Backend — FastAPI
GET /events?lat=&lng=&radius=&days=&cat=
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

import db
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Scheduler interne désactivé — orchestration déléguée à n8n
    # start_scheduler()
    yield
    # stop_scheduler()


app = FastAPI(title="Flâneur API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

FRONTEND = Path(__file__).parent.parent / "frontend" / "paris-explorer.html"


@app.get("/")
def serve_frontend():
    if FRONTEND.exists():
        return FileResponse(FRONTEND)
    return {"status": "frontend not found", "path": str(FRONTEND)}


@app.get("/events")
def get_events(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(500, ge=100, le=5000),
    days: int = Query(30, ge=1, le=365),
    cat: Optional[str] = Query(None),
):
    events = db.get_events_in_radius(lat, lng, radius, days=days, cat=cat or None)
    return {"count": len(events), "events": events}



class GalleryScrapeRequest(BaseModel):
    lat: float
    lng: float
    radius: int = 2000


@app.post("/gallery-data/scrape")
def trigger_gallery_scrape(req: GalleryScrapeRequest, background_tasks: BackgroundTasks):
    from scrapers.galleries import GalleriesScraper
    scraper = GalleriesScraper()
    background_tasks.add_task(scraper.run, req.lat, req.lng, req.radius)
    return {"status": "scraping_started"}


@app.get("/gallery-data")
def get_gallery_data(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(2000, ge=100, le=10000),
    days: int = Query(30, ge=1, le=365),
):
    expos       = db.get_recent_gallery_expos(lat=lat, lng=lng, radius_m=radius, days=days)
    ever_parsed = db.get_galleries_ever_parsed()
    return {
        "galleries_with_recent_expos": expos,
        "galleries_ever_parsed":       ever_parsed,
    }


@app.post("/scrapers/run-all")
def trigger_all_scrapers(background_tasks: BackgroundTasks):
    from datetime import datetime
    from scrapers import ALL_SCRAPERS
    run_id = datetime.now().isoformat(timespec="seconds")
    runnable = ALL_SCRAPERS
    for scraper_cls in runnable:
        background_tasks.add_task(scraper_cls().run, run_id)
    names = [s.name for s in runnable]
    logger.info("[n8n] run-all déclenché run_id=%s : %s", run_id, names)
    return {"status": "started", "run_id": run_id, "scrapers": names}


@app.post("/scrapers/run-monthly")
def trigger_monthly_scrapers(background_tasks: BackgroundTasks):
    from datetime import datetime
    from scrapers import MONTHLY_SCRAPERS
    run_id = datetime.now().isoformat(timespec="seconds")
    for scraper_cls in MONTHLY_SCRAPERS:
        background_tasks.add_task(scraper_cls().run, run_id)
    names = [s.name for s in MONTHLY_SCRAPERS]
    logger.info("[n8n] run-monthly déclenché run_id=%s : %s", run_id, names)
    return {"status": "started", "run_id": run_id, "scrapers": names}


@app.get("/scrapers/last-run")
def last_run_summary():
    return db.get_last_run_summary()


@app.post("/scrapers/run/{name}")
def trigger_scraper(name: str, background_tasks: BackgroundTasks):
    from scrapers import ALL_SCRAPERS
    scraper_cls = next((s for s in ALL_SCRAPERS if s.name == name), None)
    if not scraper_cls:
        return {"error": f"scraper '{name}' inconnu", "available": [s.name for s in ALL_SCRAPERS]}
    background_tasks.add_task(scraper_cls().run)
    logger.info("[n8n] scraper '%s' déclenché", name)
    return {"status": "started", "scraper": name}


@app.get("/scrapers")
def list_scrapers():
    from scrapers import ALL_SCRAPERS
    return {"scrapers": [s.name for s in ALL_SCRAPERS]}


@app.get("/stats")
def stats():
    with db._conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM master_events").fetchone()[0]
        with_coords = conn.execute("SELECT COUNT(*) FROM master_events WHERE lat IS NOT NULL").fetchone()[0]
        by_cat = conn.execute("SELECT categorie, COUNT(*) n FROM master_events GROUP BY categorie").fetchall()
        by_src = conn.execute("SELECT source, COUNT(*) n FROM master_events GROUP BY source").fetchall()
    return {
        "total": total,
        "with_coords": with_coords,
        "by_category": {r[0]: r[1] for r in by_cat},
        "by_source": {r[0]: r[1] for r in by_src},
    }
