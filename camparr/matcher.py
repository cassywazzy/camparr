import re
import unicodedata
from rapidfuzz import fuzz


def normalize(s):
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def score_match(wanted_artist, wanted_album, result_artist, result_album):
    artist_score = fuzz.token_sort_ratio(
        normalize(wanted_artist), normalize(result_artist)
    )
    album_score = fuzz.token_sort_ratio(
        normalize(wanted_album), normalize(result_album)
    )
    return (artist_score * 0.4) + (album_score * 0.6)


def best_match(wanted_artist, wanted_album, results, threshold=80):
    best = None
    best_score = 0
    for r in results:
        s = score_match(wanted_artist, wanted_album, r["artist"], r["album"])
        if s > best_score:
            best_score = s
            best = r
    if best and best_score >= threshold:
        return best, best_score
    return None, best_score
