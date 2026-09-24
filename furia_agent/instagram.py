"""Coleta de dados do Instagram.

Duas fontes:
- GraphAPISource: Instagram Graph API (conta Business/Creator).
- JSONSource: arquivo JSON local (exportação, cache ou dados de exemplo).

As duas devolvem o mesmo formato: {"profile": {...}, "posts": [...]}.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

MEDIA_FIELDS = ",".join(
    [
        "id",
        "caption",
        "media_type",
        "media_product_type",
        "permalink",
        "timestamp",
        "like_count",
        "comments_count",
    ]
)
PROFILE_FIELDS = "username,name,biography,followers_count,follows_count,media_count"

# Métricas de insights por post. Nem toda métrica existe para todo formato;
# pedimos o conjunto e, se a API recusar, tentamos uma a uma.
INSIGHT_METRICS = ["reach", "views", "saved", "shares", "total_interactions"]


class InstagramError(RuntimeError):
    pass


@dataclass
class GraphAPISource:
    access_token: str
    user_id: str
    version: str = "v23.0"
    timeout: float = 30.0

    @property
    def base(self) -> str:
        return f"https://graph.facebook.com/{self.version}"

    def _get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}/{path_or_url}"
        params = dict(params or {})
        if "access_token=" not in url:
            params["access_token"] = self.access_token
        resp = requests.get(url, params=params, timeout=self.timeout)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {})
            raise InstagramError(f"Graph API {resp.status_code}: {err.get('message', resp.text)}")
        return data

    def fetch_profile(self) -> dict[str, Any]:
        return self._get(self.user_id, {"fields": PROFILE_FIELDS})

    def fetch_posts(self, limit: int = 100) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        data = self._get(f"{self.user_id}/media", {"fields": MEDIA_FIELDS, "limit": min(limit, 50)})
        while True:
            posts.extend(data.get("data", []))
            next_url = data.get("paging", {}).get("next")
            if len(posts) >= limit or not next_url:
                break
            data = self._get(next_url)
        return posts[:limit]

    def fetch_insights(self, media_id: str) -> dict[str, int]:
        def parse(payload: dict[str, Any]) -> dict[str, int]:
            out = {}
            for item in payload.get("data", []):
                values = item.get("values") or [{}]
                value = item.get("total_value", {}).get("value", values[0].get("value"))
                if isinstance(value, (int, float)):
                    out[item["name"]] = int(value)
            return out

        try:
            return parse(self._get(f"{media_id}/insights", {"metric": ",".join(INSIGHT_METRICS)}))
        except InstagramError:
            out: dict[str, int] = {}
            for metric in INSIGHT_METRICS:
                try:
                    out.update(parse(self._get(f"{media_id}/insights", {"metric": metric})))
                except InstagramError:
                    continue
            return out

    def fetch_comments(self, media_id: str, limit: int = 50) -> list[dict[str, Any]]:
        data = self._get(
            f"{media_id}/comments", {"fields": "text,timestamp,like_count", "limit": min(limit, 50)}
        )
        return data.get("data", [])[:limit]

    def load(self, limit: int = 100, with_insights: bool = True) -> dict[str, Any]:
        profile = self.fetch_profile()
        posts = self.fetch_posts(limit)
        if with_insights:
            for post in posts:
                post["insights"] = self.fetch_insights(post["id"])
                time.sleep(0.05)  # gentileza com o rate limit
        return {
            "profile": profile,
            "posts": posts,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "graph_api",
        }


@dataclass
class JSONSource:
    path: Path

    def load(self, **_: Any) -> dict[str, Any]:
        data = json.loads(Path(self.path).read_text(encoding="utf-8"))
        if isinstance(data, list):  # lista pura de posts
            data = {"profile": {}, "posts": data}
        data.setdefault("profile", {})
        data.setdefault("posts", [])
        data.setdefault("source", str(self.path))
        return data

    def fetch_comments(self, media_id: str, limit: int = 50) -> list[dict[str, Any]]:
        for post in self.load()["posts"]:
            if post.get("id") == media_id:
                return post.get("comments", [])[:limit]
        return []


def save_cache(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
