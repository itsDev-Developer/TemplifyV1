from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchHit:
    source: str  # tmdb | anilist
    kind: str  # movie | tv | anime | manga
    id: int
    title: str
    year: str = ""


@dataclass
class Media:
    source: str
    kind: str  # movie | tv | anime | manga
    id: int
    title: str
    year: str = ""
    episodes: str = ""  # just the number, e.g. "59"
    unit: str = ""  # Episodes | Chapters | Min
    genres: list[str] = field(default_factory=list)
    synopsis: str = ""
    poster: str = ""  # portrait image URL
    backdrop: str = ""  # landscape image URL
    extras: list[str] = field(default_factory=list)  # more images (stills, characters)
    studio: str = ""
    status: str = ""
    type_label: str = ""  # TV SERIES | MOVIE | MANGA | MANHWA ...
    score: str = ""
    alt_titles: list[str] = field(default_factory=list)  # other names, used to match titles across services
    art: dict = field(default_factory=dict)  # fanart.tv: ranked url lists (logo, background, poster, thumb, banner, clearart, character)
