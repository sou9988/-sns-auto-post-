"""投稿用の写真を作る・ネット上に置く"""
import base64
import os
import random
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
    from content import gemini_request
    body = {
        "contents": [{"parts": [{"text": prompt + " Square composition. No text, no letters, no watermark."}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}},
    }
    res = gemini_request(settings.GEMINI_IMAGE_MODELS, body)
    for cand in res.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data:
                return _save_square_jpeg(base64.b64decode(data["data"]), path, pad=False)
    raise RuntimeError(f"画像が返ってきませんでした: {str(res)[:300]}")


def from_url(url: str, path: Path, pad: bool = True) -> Path:
    """写真をダウンロードして正方形にする（商品写真は余白付き、それ以外は切り抜き）"""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return _save_square_jpeg(r.content, path, pad=pad)


def _search_pixabay(q: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/", timeout=30, params={
        "key": os.environ["PIXABAY_API_KEY"], "q": q, "image_type": "photo",
        "safesearch": "true", "per_page": 20, "lang": "en"})
    if not r.ok:
        raise RuntimeError(f"Pixabay エラー {r.status_code}: {r.text[:300]}")
    return [{"id": f"pixabay-{h['id']}", "url": h["largeImageURL"], "credit": f"Photo: {h['user']} / Pixabay"}
            for h in r.json().get("hits", [])]


def _search_pexels(q: str) -> list[dict]:
    r = requests.get("https://api.pexels.com/v1/search", timeout=30,
                     headers={"Authorization": os.environ["PEXELS_API_KEY"]},
                     params={"query": q, "per_page": 20, "orientation": "square"})
    if not r.ok:
        raise RuntimeError(f"Pexels エラー {r.status_code}: {r.text[:300]}")
    return [{"id": f"pexels-{p['id']}", "url": p["src"]["large2x"], "credit": f"Photo: {p['photographer']} / Pexels"}
            for p in r.json().get("photos", [])]


def stock_photo(query: str, path: Path, used_ids: set) -> tuple[Path, str, str]:
    """無料の写真素材サイトから写真を探す。戻り値: (保存先, クレジット表記, 写真ID)"""
    search = _search_pexels if settings.FUNNY_IMAGE_SOURCE == "pexels" else _search_pixabay
    words = query.split()
    # 見つからなければキーワードを短くして探し直す
    for q in dict.fromkeys([query, " ".join(words[:2]), words[0] if words else "funny"]):
        photos = [p for p in search(q) if p["id"] not in used_ids]
        if photos:
            p = random.choice(photos[:8])
            from_url(p["url"], path, pad=False)
            return path, p["credit"], p["id"]
    raise RuntimeError(f"「{query}」に合う写真が見つかりませんでした")


FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # GitHub Actions（post.yml でインストール）
    "C:/Windows/Fonts/meiryob.ttc",                          # Windows
]


def _font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise RuntimeError("日本語フォントが見つかりません")


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + [cur] if cur else lines


def product_card(catch: str, name: str, path: Path) -> Path:
    """商品紹介用の画像カード（キャッチコピー＋商品名）を作る"""
    from PIL import ImageDraw
    img = Image.new("RGB", (SIZE, SIZE), "#1B2433")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 70, SIZE - 70, SIZE - 70), radius=40, fill="#FFFFFF")

    f_tag, f_catch, f_name = _font(40), _font(84), _font(44)
    d.rounded_rectangle((130, 140, 400, 210), radius=35, fill="#FF9900")
    d.text((265, 175), "おすすめ", font=f_tag, fill="#FFFFFF", anchor="mm")

    y = 290
    for line in _wrap(d, catch, f_catch, SIZE - 260)[:3]:
        d.text((130, y), line, font=f_catch, fill="#1B2433")
        y += 110
    y += 30
    for line in _wrap(d, name, f_name, SIZE - 260)[:3]:
        d.text((130, y), line, font=f_name, fill="#4B5563")
        y += 64

    d.text((130, SIZE - 170), "Amazonで「商品名」を検索", font=f_tag, fill="#9CA3AF")
    d.text((SIZE - 130, SIZE - 170), "#PR", font=f_tag, fill="#9CA3AF", anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=92)
    return path


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
