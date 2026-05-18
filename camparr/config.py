import os
import yaml

DEFAULTS = {
    "lidarr": {
        "url": "http://lidarr:8686",
        "api_key": "",
    },
    "bandcamp": {
        "format": "FLAC",
        "search_cooldown_hours": 168,
        "match_threshold": 80,
        "rate_limit_seconds": 2,
    },
    "downloads": {
        "path": "/downloads",
        "library_path": "",
    },
    "polling": {
        "interval_seconds": 300,
    },
    "healthchecks": {
        "ping_url": "",
    },
}


def _deep_merge(base, override):
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load(path=None):
    if path is None:
        path = os.environ.get("CAMPARR_CONFIG", "/config/config.yml")
    cfg = DEFAULTS.copy()
    if os.path.isfile(path):
        with open(path) as f:
            user = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user)
    api_key_env = os.environ.get("LIDARR_API_KEY")
    if api_key_env:
        cfg["lidarr"]["api_key"] = api_key_env
    url_env = os.environ.get("LIDARR_URL")
    if url_env:
        cfg["lidarr"]["url"] = url_env
    return cfg
