"""Amazon アソシエイト：商品リスト（amazon_items.txt）から紹介する商品を選ぶ"""
import re
from pathlib import Path

import settings

ITEMS_FILE = Path("amazon_items.txt")


def load_items() -> list[dict]:
    items = []
    if not ITEMS_FILE.exists():
        return items
    for line in ITEMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        m = re.search(r"(?:/dp/|/gp/product/|^)([A-Z0-9]{10})(?:[/?]|$)", parts[0])
        if not m:
            print(f"ASINが読み取れない行をとばしました: {line[:60]}")
            continue
        items.append({
            "code": m.group(1),
            "name": parts[1],
            "point": parts[2] if len(parts) > 2 else "",
        })
    return items


def pick_item(history: list[dict]) -> dict | None:
    """まだ紹介していない商品を上から選ぶ。全部紹介済みなら、いちばん前に紹介したものを選ぶ"""
    items = load_items()
    if not items:
        return None
    last_posted = {}
    for i, h in enumerate(history):
        if h.get("item_code"):
            last_posted[h["item_code"]] = i
    item = min(items, key=lambda it: last_posted.get(it["code"], -1))
    item["url"] = f"https://www.amazon.co.jp/dp/{item['code']}?tag={settings.AMAZON_TAG}"
    return item
