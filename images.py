"""投稿用の写真を作る・ネット上に置く"""
import base64
import os
import subprocess
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

import settings

IMAGE_DIR = Path("images")
SIZE = 1080


def _save_square_jpeg(raw: bytes, path: Path, pad: bool) -> Path:
    """1080x1080 の JPEG にする（Instagram は JPEG のみ対応）"""
    img = Image.open(BytesIO(raw)).convert("RGB")
    if pad:
        # 商品写真: 白い正方形の中央に配置
        img.thumbnail((int(SIZE * 0.9), int(SIZE * 0.9)))
        canvas = Image.new("RGB", (SIZE, SIZE), "white")
        canvas.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2))
        img = canvas
    else:
        # 生成写真: 中央を正方形に切り抜き
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((SIZE, SIZE))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=90)
    return path


def generate(prompt: str, path: Path) -> Path:
    """Gemini で写真を生成する"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt + " Square composition. No text, no letters, no watermark."}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}},
    }
    r = requests.post(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=body, timeout=180)
    if not r.ok:
        raise RuntimeError(f"Gemini 画像生成エラー {r.status_code}: {r.text[:300]}")
    for cand in r.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data:
                return _save_square_jpeg(base64.b64decode(data["data"]), path, pad=False)
    raise RuntimeError(f"画像が返ってきませんでした: {r.text[:300]}")


def from_url(url: str, path: Path) -> Path:
    """商品写真をダウンロードする"""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return _save_square_jpeg(r.content, path, pad=True)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def git_push(message: str) -> None:
    _git("commit", "-m", message)
    for _ in range(3):
        try:
            _git("push")
            return
        except subprocess.CalledProcessError:
            _git("pull", "--rebase")
    _git("push")


def publish(path: Path) -> str | None:
    """写真を GitHub に置いて、SNS から読める URL を返す"""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    _git("add", str(path))
    git_push(f"投稿画像 {path.name}")
    sha = _git("rev-parse", "HEAD")
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path.as_posix()}"
    for _ in range(30):
        if requests.head(url, timeout=10).status_code == 200:
            return url
        time.sleep(3)
    raise RuntimeError(f"画像の公開URLにアクセスできません: {url}")


def cleanup_old() -> None:
    """古い投稿画像を削除する（SNS側には残ります）"""
    # ファイル名の先頭が日付（YYYYMMDD）なので、それで古さを判断する
    limit = (datetime.now() - timedelta(days=settings.IMAGE_KEEP_DAYS)).strftime("%Y%m%d")
    for p in IMAGE_DIR.glob("*.jpg"):
        if p.name[:8] < limit:
            _git("rm", "-q", str(p))
