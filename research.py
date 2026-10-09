"""話題のリサーチ：Googleニュース・Googleトレンドの配信（RSS・無料・キー不要）から今の話題を集める"""
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}


def google_news(query: str, n: int = 8, days: int = 7) -> list[dict]:
    """Googleニュースで、直近の記事を集める（見出し・メディア名・日付）"""
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d&hl=ja&gl=JP&ceid=JP:ja"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = ET.fromstring(r.content).findall("./channel/item")
    except Exception as e:
        print(f"（Googleニュースを取得できませんでした: {query} / {e}）")
        return []
    out = []
    for it in items[:n]:
        source = it.findtext("source", "")
        title = it.findtext("title", "")
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]  # 見出しの末尾についているメディア名を外す
        out.append({"title": title, "source": source, "date": it.findtext("pubDate", "")[:16], "query": query})
    return out


def news_items(queries: list[str], used_titles: set, days: int = 3) -> list[dict]:
    """テーマのニュースを集めて、まだ投稿していない記事だけを返す。少なければ期間を1週間に広げる"""
    for d in (days, 7):
        seen, items = set(), []
        for q in queries:
            for it in google_news(q, n=8, days=d):
                if it["title"] in seen or it["title"] in used_titles:
                    continue
                seen.add(it["title"])
                items.append(it)
        if len(items) >= 5:
            break
    return items[:30]


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


def trend_material() -> str:
    return "\n".join(google_trends()) or "（取得できませんでした）"
