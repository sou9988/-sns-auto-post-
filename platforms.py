"""X・Threads・Instagram への投稿"""
import os
import re
import time
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

import settings

THREADS_BASE = "https://graph.threads.net/v1.0"
IG_BASE = os.environ.get("IG_API_BASE", "https://graph.instagram.com/v23.0")


def _check(r: requests.Response, name: str) -> dict:
    if not r.ok:
        raise RuntimeError(f"{name} エラー {r.status_code}: {r.text[:500]}")
    return r.json()


# ---------------------------------------------------------------- X
def x_enabled() -> bool:
    return settings.X_ENABLED and all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"))


def x_length(text: str) -> int:
    """X の文字数カウント（日本語・絵文字は2、URLは23として数える）"""
    url_re = re.compile(r"https?://\S+")
    n = 23 * len(url_re.findall(text))
    for ch in url_re.sub("", text):
        cp = ord(ch)
        n += 1 if cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247 else 2
    return n


def x_fit(body: str, suffix: str = "") -> str:
    """280 に収まるよう本文を切り詰める"""
    while body and x_length(body + suffix) > 280:
        body = body[:-2] + "…"
    return body + suffix


def x_post(text: str, image: Path | None = None) -> str:
    auth = OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                  os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])
    payload: dict = {"text": text}
    if image:
        with open(image, "rb") as f:
            r = requests.post("https://api.x.com/2/media/upload", auth=auth, timeout=60,
                              files={"media": f}, data={"media_category": "tweet_image"})
        payload["media"] = {"media_ids": [_check(r, "X 画像アップロード")["data"]["id"]]}
    r = requests.post("https://api.x.com/2/tweets", auth=auth, json=payload, timeout=30)
    return _check(r, "X 投稿")["data"]["id"]


# ---------------------------------------------------------------- Threads / Instagram 共通
def _wait_container(base: str, cid: str, token: str, field: str, name: str) -> None:
    for _ in range(40):
        r = requests.get(f"{base}/{cid}", params={"fields": field, "access_token": token}, timeout=30)
        status = _check(r, f"{name} 状態確認").get(field)
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{name} の投稿準備に失敗しました: {r.text[:300]}")
        time.sleep(5)
    raise RuntimeError(f"{name} の投稿準備が時間内に終わりませんでした")


# ---------------------------------------------------------------- Threads
def threads_enabled() -> bool:
    return settings.THREADS_ENABLED and bool(os.environ.get("THREADS_ACCESS_TOKEN"))


def threads_post(text: str, image_url: str | None = None) -> str:
    token = os.environ["THREADS_ACCESS_TOKEN"]
    uid = os.environ.get("THREADS_USER_ID") or "me"
    data = {"media_type": "IMAGE" if image_url else "TEXT", "text": text, "access_token": token}
    if image_url:
        data["image_url"] = image_url
    cid = _check(requests.post(f"{THREADS_BASE}/{uid}/threads", data=data, timeout=60), "Threads 作成")["id"]
    _wait_container(THREADS_BASE, cid, token, "status", "Threads")
    r = requests.post(f"{THREADS_BASE}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=60)
    return _check(r, "Threads 公開")["id"]


def threads_reply(post_id: str, text: str) -> str:
    """自分の投稿にコメント（返信）を付ける。threads_manage_replies の権限が必要"""
    token = os.environ["THREADS_ACCESS_TOKEN"]
    uid = os.environ.get("THREADS_USER_ID") or "me"
    data = {"media_type": "TEXT", "text": text, "reply_to_id": post_id, "access_token": token}
    cid = _check(requests.post(f"{THREADS_BASE}/{uid}/threads", data=data, timeout=60), "Threads コメント作成")["id"]
    _wait_container(THREADS_BASE, cid, token, "status", "Threads コメント")
    r = requests.post(f"{THREADS_BASE}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=60)
    return _check(r, "Threads コメント公開")["id"]


# ---------------------------------------------------------------- Instagram
def ig_enabled() -> bool:
    return settings.INSTAGRAM_ENABLED and bool(os.environ.get("IG_ACCESS_TOKEN") and os.environ.get("IG_USER_ID"))


def ig_post(caption: str, image_url: str) -> str:
    token, uid = os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"]
    r = requests.post(f"{IG_BASE}/{uid}/media",
                      data={"image_url": image_url, "caption": caption, "access_token": token}, timeout=60)
    cid = _check(r, "Instagram 作成")["id"]
    _wait_container(IG_BASE, cid, token, "status_code", "Instagram")
    r = requests.post(f"{IG_BASE}/{uid}/media_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=60)
    return _check(r, "Instagram 公開")["id"]
