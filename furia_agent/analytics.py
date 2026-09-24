"""Métricas de desempenho calculadas a partir dos posts (sem LLM)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def parse_ts(ts: str) -> datetime:
    # A Graph API usa "2026-09-01T18:30:00+0000"
    ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts)


def post_format(post: dict[str, Any]) -> str:
    if post.get("media_product_type") == "REELS" or post.get("media_type") == "REELS":
        return "REELS"
    return post.get("media_type", "DESCONHECIDO")


def interactions(post: dict[str, Any]) -> int:
    ins = post.get("insights", {})
    if "total_interactions" in ins:
        return ins["total_interactions"]
    return (
        post.get("like_count", 0)
        + post.get("comments_count", 0)
        + ins.get("saved", 0)
        + ins.get("shares", 0)
    )


def engagement_rate(post: dict[str, Any], followers: int | None) -> float | None:
    """Interações / alcance; sem alcance, usa seguidores como denominador."""
    reach = post.get("insights", {}).get("reach")
    denom = reach or followers
    if not denom:
        return None
    return interactions(post) / denom


def enrich(posts: Iterable[dict[str, Any]], followers: int | None) -> list[dict[str, Any]]:
    out = []
    for p in posts:
        ts = parse_ts(p["timestamp"]).astimezone(TZ)
        caption = p.get("caption") or ""
        out.append(
            {
                "id": p.get("id"),
                "permalink": p.get("permalink"),
                "format": post_format(p),
                "timestamp": ts.isoformat(),
                "weekday": WEEKDAYS[ts.weekday()],
                "hour": ts.hour,
                "caption": caption,
                "caption_len": len(caption),
                "hashtags": [h.lower() for h in HASHTAG_RE.findall(caption)],
                "likes": p.get("like_count", 0),
                "comments": p.get("comments_count", 0),
                "reach": p.get("insights", {}).get("reach"),
                "views": p.get("insights", {}).get("views"),
                "saved": p.get("insights", {}).get("saved"),
                "shares": p.get("insights", {}).get("shares"),
                "interactions": interactions(p),
                "engagement_rate": engagement_rate(p, followers),
            }
        )
    return out


def filter_days(posts: list[dict[str, Any]], days: int | None, now: datetime | None = None) -> list[dict[str, Any]]:
    if not days:
        return posts
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    return [p for p in posts if datetime.fromisoformat(p["timestamp"]) >= cutoff]


def _group(posts: list[dict[str, Any]], key) -> dict[str, dict[str, Any]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for p in posts:
        k = key(p)
        for kk in k if isinstance(k, list) else [k]:
            groups[kk].append(p)
    result = {}
    for k, items in groups.items():
        rates = [p["engagement_rate"] for p in items if p["engagement_rate"] is not None]
        result[str(k)] = {
            "posts": len(items),
            "media_interacoes": round(mean(p["interactions"] for p in items), 1),
            "media_engajamento_pct": round(mean(rates) * 100, 2) if rates else None,
        }
    return dict(sorted(result.items(), key=lambda kv: -(kv[1]["media_engajamento_pct"] or 0)))


def _caption_bucket(p: dict[str, Any]) -> str:
    n = p["caption_len"]
    if n < 50:
        return "curta (<50)"
    if n < 150:
        return "média (50-150)"
    return "longa (150+)"


def _hour_bucket(p: dict[str, Any]) -> str:
    h = p["hour"]
    start = h - h % 3
    return f"{start:02d}h-{start + 3:02d}h"


def _slim(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "format": p["format"],
        "data": p["timestamp"][:16],
        "engajamento_pct": round(p["engagement_rate"] * 100, 2) if p["engagement_rate"] is not None else None,
        "interacoes": p["interactions"],
        "alcance": p["reach"],
        "legenda": p["caption"][:220],
        "link": p["permalink"],
    }


def performance_report(
    posts: list[dict[str, Any]], followers: int | None, days: int | None = 90, top_n: int = 5
) -> dict[str, Any]:
    enriched = filter_days(enrich(posts, followers), days)
    if not enriched:
        return {"erro": f"Nenhum post nos últimos {days} dias."}

    ranked = sorted(enriched, key=lambda p: p["engagement_rate"] or 0, reverse=True)
    rates = [p["engagement_rate"] for p in enriched if p["engagement_rate"] is not None]
    dates = sorted(datetime.fromisoformat(p["timestamp"]) for p in enriched)
    span_weeks = max((dates[-1] - dates[0]).days / 7, 1)
    hashtag_counts = Counter(h for p in enriched for h in p["hashtags"])
    hashtag_perf = _group([p for p in enriched if p["hashtags"]], lambda p: p["hashtags"])
    hashtag_perf = {h: v for h, v in hashtag_perf.items() if hashtag_counts[h] >= 2}

    return {
        "periodo_dias": days,
        "seguidores": followers,
        "total_posts": len(enriched),
        "posts_por_semana": round(len(enriched) / span_weeks, 1),
        "engajamento_medio_pct": round(mean(rates) * 100, 2) if rates else None,
        "engajamento_mediano_pct": round(median(rates) * 100, 2) if rates else None,
        "por_formato": _group(enriched, lambda p: p["format"]),
        "por_dia_da_semana": _group(enriched, lambda p: p["weekday"]),
        "por_faixa_horaria_brt": _group(enriched, _hour_bucket),
        "por_tamanho_legenda": _group(enriched, _caption_bucket),
        "hashtags_mais_usadas": hashtag_counts.most_common(15),
        "hashtags_por_desempenho": dict(list(hashtag_perf.items())[:10]),
        "top_posts": [_slim(p) for p in ranked[:top_n]],
        "piores_posts": [_slim(p) for p in ranked[-top_n:][::-1]],
    }


def list_posts(
    posts: list[dict[str, Any]],
    followers: int | None,
    sort_by: str = "recent",
    limit: int = 20,
    media_format: str | None = None,
    contains: str | None = None,
) -> list[dict[str, Any]]:
    enriched = enrich(posts, followers)
    if media_format:
        enriched = [p for p in enriched if p["format"] == media_format.upper()]
    if contains:
        needle = contains.lower()
        enriched = [p for p in enriched if needle in p["caption"].lower()]
    keys = {
        "recent": lambda p: p["timestamp"],
        "engagement": lambda p: p["engagement_rate"] or 0,
        "interactions": lambda p: p["interactions"],
        "reach": lambda p: p["reach"] or 0,
    }
    enriched.sort(key=keys.get(sort_by, keys["recent"]), reverse=True)
    return [_slim(p) for p in enriched[:limit]]
