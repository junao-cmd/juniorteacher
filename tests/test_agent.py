from datetime import datetime, timezone
from pathlib import Path

from furia_agent import analytics
from furia_agent.instagram import JSONSource
from furia_agent.tools import Store, build_tools

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_posts.json"


def post(i, media_type="IMAGE", product="FEED", reach=1000, likes=50, caption="oi #DIADEFURIA", ts="2026-09-01T21:00:00+0000"):
    return {
        "id": str(i),
        "caption": caption,
        "media_type": media_type,
        "media_product_type": product,
        "timestamp": ts,
        "like_count": likes,
        "comments_count": 0,
        "insights": {"reach": reach},
    }


def test_parse_graph_timestamp():
    assert analytics.parse_ts("2026-09-01T21:00:00+0000") == datetime(2026, 9, 1, 21, tzinfo=timezone.utc)


def test_engagement_uses_reach_then_followers():
    assert analytics.engagement_rate(post(1, reach=1000, likes=50), 10_000) == 0.05
    p = post(2, likes=50)
    p["insights"] = {}
    assert analytics.engagement_rate(p, 10_000) == 0.005


def test_report_groups_by_format_and_timezone():
    posts = [
        post(1, "VIDEO", "REELS", likes=100),
        post(2, "IMAGE", likes=10),
        post(3, "CAROUSEL_ALBUM", likes=30, caption="#DIADEFURIA #cs2"),
    ]
    report = analytics.performance_report(posts, 5000, days=None)
    assert list(report["por_formato"]) == ["REELS", "CAROUSEL_ALBUM", "IMAGE"]
    # 21h UTC = 18h em Brasília
    assert "18h-21h" in report["por_faixa_horaria_brt"]
    assert report["top_posts"][0]["id"] == "1"
    assert ("diadefuria", 3) in report["hashtags_mais_usadas"]


def test_tools_run_on_sample(tmp_path):
    source = JSONSource(SAMPLE)
    store = Store(source, source.load(), output_dir=tmp_path)
    tools = {t.name: t for t in build_tools(store)}
    assert "furiagg_exemplo" in tools["get_profile"].call({})
    assert "por_formato" in tools["get_performance_report"].call({"days": 0})
    assert "sample_000" in tools["list_posts"].call({"sort_by": "recent", "limit": 3})
    assert "VAMO FURIA" in tools["get_post_comments"].call({"post_id": "sample_000"})
    msg = tools["save_content"].call({"filename": "Calendário Outubro!", "content": "# oi"})
    assert list(tmp_path.glob("*-calend-rio-outubro.md"))
    assert "Salvo em" in msg
