import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from scrapers import ALL_SCRAPERS

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_scraper(scraper_cls):
    name = scraper_cls.name
    logger.info("[scheduler] Début scraping %s à %s", name, datetime.now().isoformat())
    try:
        inserted = scraper_cls().run()
        logger.info("[scheduler] %s terminé : %d events insérés", name, inserted)
    except Exception:
        logger.exception("[scheduler] %s a planté — scraper ignoré", name)


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Europe/Paris")

    for i, scraper_cls in enumerate(ALL_SCRAPERS):
        # Décalage de 5 min entre chaque scraper pour ne pas surcharger
        first_run = datetime.now() + timedelta(minutes=i * 5)
        _scheduler.add_job(
            _run_scraper,
            "interval",
            hours=24,
            args=[scraper_cls],
            next_run_time=first_run,
            id=f"scraper_{scraper_cls.name}",
            misfire_grace_time=3600,
        )
        logger.info("[scheduler] %s programmé (premier run dans %d min)", scraper_cls.name, i * 5)

    _scheduler.start()
    logger.info("[scheduler] Démarré — %d scrapers planifiés", len(ALL_SCRAPERS))


def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] Arrêté")
