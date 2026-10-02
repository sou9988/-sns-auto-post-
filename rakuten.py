"""楽天ランキングから紹介する商品を選ぶ"""
import os
import random

import requests

import settings
from content import now_jst

API_URL = os.environ.get(
    "RAKUTEN_API_URL",
    "https://app.rakuten.co.jp/services/api/IchibaItem/Ranking/20220601",
)


def _fetch_ranking(genre_id: int) -> list[dict]:
    params = {
        "applicationId": os.environ["RAKUTEN_APP_ID"],
        "formatVersion": 2,
    }
    if genre_id:
        params["genreId"] = genre_id
    if os.environ.get("RAKUTEN_AFFILIATE_ID"):
        params["affiliateId"] = os.environ["RAKUTEN_AFFILIATE_ID"]
    if os.environ.get("RAKUTEN_ACCESS_KEY"):
        params["accessKey"] = os.environ["RAKUTEN_ACCESS_KEY"]
    r = requests.get(API_URL, params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"楽天API エラー {r.status_code}: {r.text[:300]}")
    data = r.json()
    items = data.get("Items", [])
    # formatVersion=1 の形 {"Item": {...}} にも対応
    items = [i.get("Item", i) for i in items]
    title = data.get("title", "楽天ランキング")
    for i in items:
        i["_genre_label"] = title
    return items


def _image_url(item: dict) -> str:
    urls = item.get("mediumImageUrls") or []
    url = urls[0] if urls else ""
    if isinstance(url, dict):
        url = url.get("imageUrl", "")
    # 128x128 の小さい画像を大きいサイズに差し替える
    return url.split("?")[0] + "?_ex=700x700" if url else ""


def pick_item(history: list[dict]) -> dict:
    posted = {h.get("item_code") for h in history if h.get("item_code")}
    genres = settings.RAKUTEN_GENRE_IDS[:]
    random.shuffle(genres)
    for genre_id in genres + [0]:
        for item in _fetch_ranking(genre_id):
            if item["itemCode"] in posted or not _image_url(item):
                continue
            n = now_jst()
            return {
                "code": item["itemCode"],
                "name": item["itemName"],
                "price": int(item["itemPrice"]),
                "shop": item["shopName"],
                "rank": item.get("rank", "-"),
                "genre_label": item["_genre_label"],
                "caption": item.get("itemCaption", ""),
                "url": item.get("affiliateUrl") or item["itemUrl"],
                "image_url": _image_url(item),
                "date": f"{n.year}年{n.month}月{n.day}日",
            }
    raise RuntimeError("紹介できる新しい商品が見つかりませんでした")
