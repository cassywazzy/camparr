import logging
import os
import shutil
import sys
import threading
import time
import urllib.request

from . import config, db, bandcamp, lidarr, matcher, web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("camparr")


def move_to_library(download_dir, rel_files, library_path, artist_name, album_title):
    dest = os.path.join(library_path, artist_name, album_title)
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for rel in rel_files:
        src = os.path.join(download_dir, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dest, os.path.basename(rel))
        shutil.move(src, dst)
        moved += 1
    log.info("Moved %d files to %s", moved, dest)
    src_dir = os.path.join(download_dir, os.path.dirname(rel_files[0])) if rel_files else ""
    if src_dir and os.path.isdir(src_dir) and not os.listdir(src_dir):
        os.rmdir(src_dir)
    return moved > 0


def poll_cycle(cfg, client):
    web.set_state(status="polling")
    rate_limit = cfg["bandcamp"]["rate_limit_seconds"]
    cooldown = cfg["bandcamp"]["search_cooldown_hours"]
    threshold = cfg["bandcamp"]["match_threshold"]
    fmt = cfg["bandcamp"]["format"]
    download_dir = cfg["downloads"]["path"]
    library_path = cfg["downloads"]["library_path"]

    results = {"wanted": 0, "searched": 0, "found": 0, "downloaded": 0, "imported": 0}

    try:
        wanted = client.get_all_wanted()
    except Exception as e:
        log.error("Failed to fetch wanted list: %s", e)
        web.set_state(status="error")
        return results

    queued = set()
    try:
        queued = client.get_queue_album_ids()
    except Exception as e:
        log.warning("Failed to fetch queue: %s", e)

    results["wanted"] = len(wanted)
    log.info("Found %d wanted albums (%d already in queue)", len(wanted), len(queued))

    needs_rescan = False

    for album in wanted:
        album_id = album["id"]
        artist_name = album.get("artist", {}).get("artistName", "Unknown")
        artist_id = album.get("artist", {}).get("id")
        album_title = album.get("title", "Unknown")

        if album_id in queued:
            continue

        if not db.should_search(album_id, cooldown):
            continue

        web.set_state(status="searching")
        results["searched"] += 1
        query = f"{artist_name} {album_title}"
        log.info("Searching Bandcamp for: %s", query)

        search_results = bandcamp.search_albums(query, rate_limit=rate_limit)
        if not search_results:
            db.record_search(album_id, artist_name, album_title, "not_found")
            continue

        match, score = matcher.best_match(artist_name, album_title, search_results, threshold)
        if not match:
            log.info("No match above threshold for %s (best: %.1f)", query, score)
            db.record_search(album_id, artist_name, album_title, "not_found")
            continue

        log.info("Match: %s - %s (%.1f%%) -> %s", match["artist"], match["album"], score, match["url"])

        free_info = bandcamp.check_free(match["url"], rate_limit=rate_limit)
        if not free_info:
            log.info("Not free/NYP: %s", match["url"])
            db.record_search(album_id, artist_name, album_title, "not_free", match["url"])
            continue

        results["found"] += 1
        db.record_search(album_id, artist_name, album_title, "found", match["url"])
        log.info("Free download available: %s (%s)", match["url"], free_info["type"])

        web.set_state(status="downloading")
        files, error = bandcamp.download(match["url"], download_dir, fmt)

        if files is None:
            db.record_download(album_id, artist_name, album_title, match["url"], fmt, "error", error=error)
            continue

        results["downloaded"] += 1
        db.record_download(album_id, artist_name, album_title, match["url"], fmt, "done", files=files)

        if library_path and files:
            lib_artist = artist_name
            if artist_id:
                artist_path = client.get_artist_path(artist_id)
                if artist_path:
                    lib_artist = os.path.basename(artist_path)
            if move_to_library(download_dir, files, library_path, lib_artist, album_title):
                needs_rescan = True

    if needs_rescan:
        log.info("Triggering Lidarr library rescan")
        if client.rescan_artist(None):
            results["imported"] = results["downloaded"]

    return results


def ping_healthcheck(url, suffix=""):
    if not url:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(url + suffix, method="POST"), timeout=10)
    except Exception as e:
        log.warning("Healthcheck ping failed: %s", e)


def polling_loop(cfg):
    client = lidarr.LidarrClient(cfg["lidarr"]["url"], cfg["lidarr"]["api_key"])
    interval = cfg["polling"]["interval_seconds"]
    hc_url = cfg["healthchecks"]["ping_url"].rstrip("/")

    if not client.test_connection():
        log.error("Cannot connect to Lidarr at %s — will retry", cfg["lidarr"]["url"])

    while True:
        try:
            ping_healthcheck(hc_url, "/start")
            web.set_state(last_poll=time.strftime("%Y-%m-%dT%H:%M:%S"))
            cycle_results = poll_cycle(cfg, client)
            web.set_state(
                status="idle",
                cycle_results=cycle_results,
                next_poll=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + interval)),
            )
            log.info(
                "Cycle complete — wanted:%d searched:%d found:%d downloaded:%d imported:%d — next poll in %ds",
                cycle_results["wanted"], cycle_results["searched"], cycle_results["found"],
                cycle_results["downloaded"], cycle_results["imported"], interval,
            )
            ping_healthcheck(hc_url)
        except Exception:
            log.exception("Error in polling cycle")
            web.set_state(status="error")
            ping_healthcheck(hc_url, "/fail")

        time.sleep(interval)


def main():
    cfg = config.load()
    db.init()

    if not cfg["lidarr"]["api_key"]:
        log.error("No Lidarr API key configured. Set lidarr.api_key in config.yml or LIDARR_API_KEY env var.")
        sys.exit(1)

    web.app.config["BANDCAMP_FORMAT"] = cfg["bandcamp"]["format"]
    web.app.config["DOWNLOAD_PATH"] = cfg["downloads"]["path"]

    poll_thread = threading.Thread(target=polling_loop, args=(cfg,), daemon=True)
    poll_thread.start()

    port = int(os.environ.get("PORT", 8585))
    log.info("Camparr starting on port %d", port)
    web.app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
