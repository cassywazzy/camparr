import logging
import time
import requests

log = logging.getLogger("camparr.lidarr")


class LidarrClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip("/")
        self.api = f"{self.url}/api/v1"
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = api_key

    def _get(self, path, params=None):
        resp = self.session.get(f"{self.api}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, json=None):
        resp = self.session.post(f"{self.api}{path}", json=json, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_wanted(self, page=1, page_size=50):
        return self._get("/wanted/missing", params={
            "page": page,
            "pageSize": page_size,
            "sortKey": "albums.title",
            "sortDirection": "ascending",
            "includeArtist": True,
        })

    def get_all_wanted(self):
        albums = []
        page = 1
        while True:
            data = self.get_wanted(page=page, page_size=50)
            albums.extend(data["records"])
            if page * 50 >= data["totalRecords"]:
                break
            page += 1
        return albums

    def get_queue_album_ids(self):
        data = self._get("/queue", params={
            "pageSize": 200,
            "sortKey": "albums.title",
            "sortDirection": "ascending",
        })
        return {r["albumId"] for r in data.get("records", []) if "albumId" in r}

    def get_artist_path(self, artist_id):
        try:
            data = self._get(f"/artist/{artist_id}")
            return data.get("path", "")
        except Exception as e:
            log.warning("Failed to get artist path for id %d: %s", artist_id, e)
            return ""

    def rescan_artist(self, artist_id):
        try:
            cmd = self._post("/command", json={
                "name": "RescanFolders",
                "filter": "known",
            })
            cmd_id = cmd["id"]
            log.info("Rescan command %d queued", cmd_id)
            for _ in range(60):
                time.sleep(5)
                status = self._get(f"/command/{cmd_id}")
                if status["status"] in ("completed", "failed"):
                    if status["status"] == "completed":
                        log.info("Rescan completed")
                        return True
                    log.warning("Rescan failed: %s", status.get("message", ""))
                    return False
            log.warning("Rescan timed out for command %d", cmd_id)
            return False
        except Exception as e:
            log.error("Failed to trigger rescan: %s", e)
            return False

    def test_connection(self):
        try:
            data = self._get("/system/status")
            log.info("Connected to Lidarr %s", data.get("version", "unknown"))
            return True
        except Exception as e:
            log.error("Lidarr connection failed: %s", e)
            return False
