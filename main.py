"""SNS 自動投稿

使い方: python main.py <news|funny|stock|room|check>
  環境変数 DRY_RUN=1 のときは投稿せず、作った内容を表示するだけ
"""
import json
import os
import sys
import traceback
from pathlib import Path

import content
import images
import platforms
import settings

HISTORY = Path("data/history.json")


def load_history() -> list[dict]:
    return json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []


def tags(words: list[str], n: int) -> str:
    return " ".join("#" + w.lstrip("#").replace(" ", "") for w in words[:n])


# ---------------------------------------------------------------- 投稿を組み立てる
def build(slot: str, history: list[dict]) -> dict | None:
    """各 SNS 向けの文章と写真を用意する。投稿しない日は None"""
    stamp = content.now_jst().strftime("%Y%m%d-%H%M")
    post: dict = {"slot": slot, "image": None}

    if slot == "news":
        d = content.ask_ai(content.news_prompt(history), use_search=True)
        url = content.verified_url(d.get("source_url", ""), d["_sources"])
        source = f"出典：{d['source_name']}" + (f"\n{url}" if url else "")
        post["x"] = platforms.x_fit(d["x_text"], f"\n{url or '出典：' + d['source_name']}")
        post["threads"] = f"{d['long_text']}\n\n{source}\n{tags(d['hashtags'], 1)}"

    elif slot == "funny":
        d = content.ask_ai(content.funny_prompt(history))
        path, credit = images.IMAGE_DIR / f"{stamp}-funny.jpg", ""
        try:
            if settings.FUNNY_IMAGE_SOURCE == "gemini":
                post["image"] = images.generate(d["image_prompt"], path)
            else:
                used = {h["photo_id"] for h in history if h.get("photo_id")}
                post["image"], credit, post["photo_id"] = images.stock_photo(d["photo_query"], path, used)
        except Exception as e:
            # 写真が用意できなくても、X・Threads には文章だけで投稿する（Instagram はスキップ）
            print(f"写真を用意できませんでした。文章だけで投稿します: {str(e)[:200]}")
        post["x"] = platforms.x_fit(d["x_text"])
        post["threads"] = f"{d['long_text']}\n{tags(d['hashtags'], 1)}"
        post["instagram"] = f"{d['long_text']}\n\n{tags(d['hashtags'], 5)}" + (f"\n\n{credit}" if credit else "")

    elif slot == "stock":
        d = content.ask_ai(content.stock_prompt(history), use_search=True)
        if d.get("skip"):
            return None
        post["x"] = platforms.x_fit(d["x_text"], f"\n{settings.STOCK_DISCLAIMER}")
        post["threads"] = f"{d['long_text']}\n\n{settings.STOCK_DISCLAIMER}\n{tags(d['hashtags'], 1)}"

    elif slot == "room":
        if not os.environ.get("RAKUTEN_APP_ID"):
            print("楽天のキーが未設定なので、楽天ROOMの投稿はスキップします")
            return None
        import rakuten
        item = rakuten.pick_item(history)
        d = content.ask_ai(content.room_prompt(item))
        post["item_code"] = item["code"]
        post["image"] = images.from_url(item["image_url"], images.IMAGE_DIR / f"{stamp}-room.jpg")
        room = f"\n楽天ROOMでも紹介中 {settings.ROOM_URL}" if settings.ROOM_URL else ""
        post["x"] = platforms.x_fit("【PR】" + d["x_text"], f"\n{item['url']}\n#PR")
        post["threads"] = f"【PR】{d['long_text']}\n\n{item['url']}{room}\n#PR"
        post["instagram"] = (f"【PR】\n{d['ig_caption']}\n\n商品はプロフィールのリンク（楽天ROOM）から見られます"
                             f"\n\n#PR {tags(d['hashtags'], 4)}")

    else:
        raise SystemExit(f"不明な投稿の種類です: {slot}")

    post["summary"] = d["summary"]
    return post


# ---------------------------------------------------------------- 投稿する
def publish(post: dict) -> dict[str, str]:
    image_url = images.publish(post["image"]) if post["image"] else None
    jobs = {
        "X": (platforms.x_enabled, lambda: platforms.x_post(post["x"], post["image"])),
        "Threads": (platforms.threads_enabled, lambda: platforms.threads_post(post["threads"], image_url)),
    }
    if post.get("instagram") and image_url:
        jobs["Instagram"] = (platforms.ig_enabled, lambda: platforms.ig_post(post["instagram"], image_url))

    results = {}
    for name, (enabled, run) in jobs.items():
        if not enabled():
            results[name] = "スキップ（キー未設定）"
            continue
        try:
            results[name] = f"成功 id={run()}"
        except Exception as e:
            traceback.print_exc()
            results[name] = f"失敗: {e}"
    return results


def check() -> None:
    """各サービスにつながるか確認する（投稿はしない）"""
    import requests
    if platforms.threads_enabled():
        r = requests.get(f"{platforms.THREADS_BASE}/me",
                         params={"fields": "id,username", "access_token": os.environ["THREADS_ACCESS_TOKEN"]})
        print("Threads:", r.status_code, r.text)
    if os.environ.get("IG_ACCESS_TOKEN"):
        r = requests.get(f"{platforms.IG_BASE}/me",
                         params={"fields": "user_id,username", "access_token": os.environ["IG_ACCESS_TOKEN"]})
        print("Instagram:", r.status_code, r.text, "← user_id を IG_USER_ID に設定してください")
    if platforms.x_enabled():
        from requests_oauthlib import OAuth1
        auth = OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                      os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])
        r = requests.get("https://api.x.com/2/users/me", auth=auth)
        print("X:", r.status_code, r.text)


def main() -> None:
    slot = sys.argv[1] if len(sys.argv) > 1 else "funny"
    if slot == "check":
        return check()

    dry_run = os.environ.get("DRY_RUN") == "1"
    if not dry_run and not (platforms.x_enabled() or platforms.threads_enabled() or platforms.ig_enabled()):
        print("投稿できるSNSがまだありません（キー未設定、または settings.py で停止中）")
        return
    history = load_history()
    post = build(slot, history)
    if post is None:
        print("今回は投稿しません（休場日・キー未設定など）")
        return

    print("=" * 60)
    for key in ("x", "threads", "instagram"):
        if post.get(key):
            extra = f"（{platforms.x_length(post[key])}/280）" if key == "x" else ""
            print(f"■ {key}{extra}\n{post[key]}\n")
    print("■ 写真:", post["image"] or "なし")
    print("=" * 60)

    if dry_run:
        print("テストモードなので投稿しません")
        return

    results = publish(post)
    for name, res in results.items():
        print(f"{name}: {res}")

    history.append({
        "date": content.now_jst().strftime("%Y-%m-%d %H:%M"),
        "slot": slot,
        "summary": post["summary"],
        **({"item_code": post["item_code"]} if post.get("item_code") else {}),
        **({"photo_id": post["photo_id"]} if post.get("photo_id") else {}),
    })
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(history[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    if os.environ.get("GITHUB_REPOSITORY"):
        images.cleanup_old()
        images._git("add", str(HISTORY))
        images.git_push(f"投稿履歴 {slot}")

    if any(r.startswith("失敗") for r in results.values()):
        sys.exit(1)  # GitHub からエラー通知メールが届く


if __name__ == "__main__":
    main()
