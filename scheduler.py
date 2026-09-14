import logging
import os
import threading

from pipeline.ingest import run_ingest_cycle

logger = logging.getLogger("news_research_tool.scheduler")

DEFAULT_INTERVAL_MINUTES = 15

_thread = None
_stop_event = threading.Event()
_lock = threading.Lock()


def _interval_seconds():
    try:
        minutes = float(os.getenv("NEWS_FETCH_INTERVAL", DEFAULT_INTERVAL_MINUTES))
    except ValueError:
        minutes = DEFAULT_INTERVAL_MINUTES
    return max(minutes, 1) * 60


def _run_loop(queries, category, country, language):
    logger.info("scheduler: background ingestion loop started (interval=%ss)", _interval_seconds())
    while not _stop_event.is_set():
        try:
            result = run_ingest_cycle(queries=queries, category=category, country=country, language=language)
            logger.info("scheduler: ingest cycle complete: %s", result)
        except Exception:
            # A bad cycle must not kill the loop -- it retries next interval.
            logger.exception("scheduler: ingest cycle failed")
        _stop_event.wait(_interval_seconds())
    logger.info("scheduler: background ingestion loop stopped")


def start_background_ingestion(queries=None, category=None, country=None, language="en"):
    """Idempotent -- safe to call on every Streamlit script rerun.

    Guarded with a module-level lock/flag rather than st.session_state on
    purpose: session_state is per-browser-tab, so guarding with it would
    start one thread per open tab. Module globals persist across Streamlit
    reruns within the same server process (Python doesn't re-import an
    already-imported module), so this reliably starts exactly one shared
    background thread per running server, no matter how many tabs are open.
    """
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop_event.clear()
        _thread = threading.Thread(
            target=_run_loop,
            args=(queries, category, country, language),
            daemon=True,
            name="news-ingestion-scheduler",
        )
        _thread.start()
        return True


def is_running():
    return _thread is not None and _thread.is_alive()
