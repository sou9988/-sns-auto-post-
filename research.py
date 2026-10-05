"""話題のリサーチ：Googleニュース・Googleトレンドの配信（RSS・無料・キー不要）から今の話題を集める"""
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}


def google_news(query: str, n: int = 8, days: int = 7) -> list[str]:
    """Googleニュースで、直近の記事の見出しを集める"""
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d&hl=ja&gl=JP&ceid=JP:ja"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = ET.fromstring(r.content).findall("./channel/item")
    except Exception as e:
        print(f"（Googleニュースを取得できませんでした: {query} / {e}）")
        return []
    return [f"{it.findtext('title', '')}（{it.findtext('pubDate', '')[:16]}）" for it in items[:n]]


def google_trends(n: int = 15) -> list[str]:
    """Googleトレンド（日本）で、今日急上昇している検索ワードと関連ニュースの見出しを集める"""
    ns = {"ht": "https://trends.google.com/trending/rss"}
    try:
        r = requests.get("https://trends.google.com/trending/rss?geo=JP", headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = ET.fromstring(r.content).findall("./channel/item")
    except Exception as e:
        print(f"（Googleトレンドを取得できませんでした: {e}）")
        return []
    out = []
    for it in items[:n]:
        word = it.findtext("title", "")
        traffic = it.findtext("ht:approx_traffic", "", ns)
        news = [x.findtext("ht:news_item_title", "", ns) for x in it.findall("ht:news_item", ns)][:2]
        out.append(f"{word}（検索数 {traffic}）: " + " / ".join(t for t in news if t))
    return out


def niche_material(queries: list[str]) -> str:
    lines = []
    for q in queries:
        lines += [f"[{q}] {h}" for h in google_news(q, n=6)]
    return "\n".join(lines) or "（取得できませんでした）"


def trend_material() -> str:
    return "\n".join(google_trends()) or "（取得できませんでした）"
