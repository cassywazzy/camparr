import json
import logging
import os
import re
import subprocess
import time

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("camparr.bandcamp")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def search_albums(query, rate_limit=2):
    results = []
    try:
        resp = requests.post(
            "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic",
            json={"search_text": query, "search_filter": "a", "full_page": True, "fan_id": None},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("Bandcamp search failed for %r: %s", query, e)
        time.sleep(rate_limit)
        return results

    for item in data.get("auto", {}).get("results", []):
        if item.get("type") != "a":
            continue
        results.append({
            "album": item.get("name", ""),
            "artist": item.get("band_name", ""),
            "url": item.get("item_url_path", ""),
            "art": item.get("img", ""),
        })

    time.sleep(rate_limit)
    log.info("Bandcamp search %r: %d results", query, len(results))
    return results


def check_free(album_url, rate_limit=2):
    try:
        resp = requests.get(
            album_url,
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        log.error("Failed to fetch %s: %s", album_url, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    tralbum_el = soup.find("script", attrs={"data-tralbum": True})
    if not tralbum_el:
        log.debug("No data-tralbum found on %s", album_url)
        time.sleep(rate_limit)
        return None

    try:
        tralbum = json.loads(tralbum_el["data-tralbum"])
    except (json.JSONDecodeError, KeyError):
        log.debug("Failed to parse data-tralbum on %s", album_url)
        time.sleep(rate_limit)
        return None

    if not tralbum.get("hasAudio"):
        time.sleep(rate_limit)
        return None

    free_page = tralbum.get("freeDownloadPage")
    if free_page:
        time.sleep(rate_limit)
        return {"url": album_url, "type": "free", "require_email": False}

    ld_el = soup.head.find("script", {"type": "application/ld+json"}, recursive=False) if soup.head else None
    if ld_el:
        try:
            ld = json.loads(ld_el.string)
            releases = ld.get("albumRelease", [])
            if not isinstance(releases, list):
                releases = [releases]
            for rel in releases:
                offers = rel.get("offers", {})
                if isinstance(offers, dict) and offers.get("price") == 0.0:
                    require_email = bool(tralbum.get("current", {}).get("require_email"))
                    time.sleep(rate_limit)
                    return {"url": album_url, "type": "name_your_price", "require_email": require_email}
        except (json.JSONDecodeError, TypeError):
            pass

    time.sleep(rate_limit)
    return None


def download(album_url, output_dir, fmt="FLAC"):
    os.makedirs(output_dir, exist_ok=True)
    before = set()
    for root, _, files in os.walk(output_dir):
        for f in files:
            before.add(os.path.join(root, f))

    cmd = ["bcdl-free", "--dir", output_dir, "--format", fmt, "--email", "auto", album_url]
    log.info("Downloading %s as %s", album_url, fmt)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        log.error("Download timed out for %s", album_url)
        return None, "Download timed out after 10 minutes"

    after = set()
    for root, _, files in os.walk(output_dir):
        for f in files:
            after.add(os.path.join(root, f))

    new_files = sorted(after - before)
    new_files = [f for f in new_files if not f.endswith(".zip")]

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        log.error("Download failed for %s: %s", album_url, error)
        return None, error

    if not new_files:
        log.warning("Download succeeded but no new files found for %s", album_url)
        return [], None

    rel_files = [os.path.relpath(f, output_dir) for f in new_files]
    log.info("Downloaded %d files for %s", len(rel_files), album_url)
    return rel_files, None
