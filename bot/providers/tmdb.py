"""TMDB provider (movies + TV). Free key: https://www.themoviedb.org/settings/api
Both the v3 "API Key" and the v4 "Read Access Token" work. Images need TMDB attribution."""
from __future__ import annotations

from .. import http
from ..models import Media, SearchHit

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"


def art_from(images: dict) -> dict:
    """TMDB /images payload -> ranked url lists {logo, poster, background} (same shape as fanart.tv results)."""
    def urls(items, size, textless_first=False, en_first=False):
        items = [i for i in (items or []) if i.get("file_path")]
        if textless_first:   # textless backdrops look best behind our own text
            items.sort(key=lambda i: (i.get("iso_639_1") is not None, -(i.get("vote_average") or 0)))
        elif en_first:       # logos: English first
            items.sort(key=lambda i: (i.get("iso_639_1") != "en", -(i.get("vote_average") or 0)))
        return [IMG + size + i["file_path"] for i in items]

    art = {"logo": urls(images.get("logos"), "w500", en_first=True)[:6],
           "poster": urls(images.get("posters"), "w780")[:6],
           "background": urls(images.get("backdrops"), "w1280", textless_first=True)[:6]}
    return {k: v for k, v in art.items() if v}


class TMDB:
    def __init__(self, key: str):
        self.key = key

    def _get(self, path: str, **params):
        headers = {}
        if self.key.startswith("eyJ"):  # v4 bearer token
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        return http.get_json(BASE + path, params=params, headers=headers)

    def search(self, query: str, kind: str | None = None) -> list[SearchHit]:
        """kind: 'movie' | 'tv' | None (both)."""
        if kind in ("movie", "tv"):
            data = self._get(f"/search/{kind}", query=query, include_adult="false")
            for r in data.get("results", []):
                r["media_type"] = kind
        else:
            data = self._get("/search/multi", query=query, include_adult="false")
        hits = []
        for r in data.get("results", []):
            k = r.get("media_type")
            if k not in ("movie", "tv"):
                continue
            date = r.get("release_date") or r.get("first_air_date") or ""
            hits.append(SearchHit("tmdb", k, r["id"], r.get("title") or r.get("name") or "?", date[:4]))
        return hits[:18]

    def images(self, kind: str, id_: int) -> dict:
        return art_from(self._get(f"/{kind}/{id_}/images", include_image_language="en,null"))

    def tvdb_id(self, tv_id: int) -> int:
        return int(self._get(f"/tv/{tv_id}/external_ids").get("tvdb_id") or 0)

    def match(self, titles: list[str], year: str, kind: str) -> int:
        """Best-effort TMDB id for a title from another service (used to reach fanart.tv for anime)."""
        norm = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
        want = {norm(t) for t in titles if t}
        for t in titles[:3]:
            try:
                res = self._get(f"/search/{kind}", query=t, include_adult="false").get("results", [])
            except Exception:
                continue
            for r in res[:6]:
                names = {norm(r.get(k) or "") for k in ("title", "name", "original_title", "original_name")}
                date = (r.get("release_date") or r.get("first_air_date") or "")[:4]
                if names & want and (not year or not date or abs(int(date) - int(year)) <= 1):
                    return r["id"]
        return 0

    def details(self, kind: str, id_: int) -> Media:
        d = self._get(f"/{kind}/{id_}", append_to_response="images", include_image_language="en,null")
        date = d.get("release_date") or d.get("first_air_date") or ""
        images = d.get("images", {})

        def urls(items, size, textless_first):
            items = list(items or [])
            if textless_first:  # textless backdrops look best behind our own text
                items.sort(key=lambda i: (i.get("iso_639_1") is not None, -(i.get("vote_average") or 0)))
            return [IMG + size + i["file_path"] for i in items if i.get("file_path")]

        backdrops = urls(images.get("backdrops"), "w1280", True)
        posters = urls(images.get("posters"), "w780", False)
        backdrop = backdrops[0] if backdrops else (IMG + "w1280" + d["backdrop_path"] if d.get("backdrop_path") else "")
        poster = IMG + "w780" + d["poster_path"] if d.get("poster_path") else (posters[0] if posters else "")

        if kind == "tv":
            episodes, unit = str(d.get("number_of_episodes") or ""), "Episodes"
            company = (d.get("networks") or d.get("production_companies") or [{}])[0].get("name", "")
            type_label = "TV SERIES"
        else:
            episodes, unit = str(d.get("runtime") or ""), "Min"
            company = (d.get("production_companies") or [{}])[0].get("name", "")
            type_label = "MOVIE"

        return Media(
            source="tmdb", kind=kind, id=id_,
            title=d.get("title") or d.get("name") or "?",
            year=date[:4], episodes=episodes, unit=unit,
            genres=[g["name"] for g in d.get("genres", [])],
            synopsis=d.get("overview", ""),
            poster=poster, backdrop=backdrop,
            extras=backdrops[1:4] + posters[:2], art=art_from(images),
            studio=company, status=(d.get("status") or "").title(),
            type_label=type_label,
            score=f"{d['vote_average']:.1f}" if d.get("vote_average") else "",
        )
