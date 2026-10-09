"""AI（Gemini または Claude）で投稿文を作る"""
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import research
import settings

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    return datetime.now(JST)


def _today_label() -> str:
    n = now_jst()
    return f"{n.year}年{n.month}月{n.day}日（{'月火水木金土日'[n.weekday()]}）{n.hour}時{n.minute:02d}分"


def _history_text(history: list[dict]) -> str:
    recent = history[-40:]
    if not recent:
        return "（まだ投稿はありません）"
    return "\n".join(f"- {h['date']} [{h['slot']}] {h['summary']}" for h in recent)


def _parse_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def ask_ai(prompt: str, use_search: bool = False) -> dict:
    """投稿案を JSON で書いてもらう。検索した記事の URL は "_sources" に入る"""
    if settings.TEXT_ENGINE == "claude":
        return ask_claude(prompt, use_search)
    return ask_gemini(prompt, use_search)


def gemini_request(models: list[str], body: dict) -> dict:
    """候補のモデルを順に試す。混雑時（429/5xx）は少し待って再挑戦し、
    それでもだめなモデルや廃止されたモデル（404）は次の候補に切り替える"""
    errors = []
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            r = requests.post(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=body, timeout=180)
            quota_over = r.status_code == 429 and "quota" in r.text.lower()  # 1日の上限：待っても回復しない
            if r.status_code in (429, 500, 503) and attempt == 0 and not quota_over:
                time.sleep(30)
                continue
            break
        if r.ok:
            print(f"（使用モデル: {model}）")
            return r.json()
        print(f"（{model} は使えませんでした: {r.status_code}）")
        errors.append(f"{model}: {r.status_code} {r.text[:300]}")
        if r.status_code not in (404, 429, 500, 503):
            break  # キーの間違いなど、モデルを変えても直らないエラー
    raise RuntimeError("Gemini エラー\n" + "\n".join(errors))


def ask_gemini(prompt: str, use_search: bool = False) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": settings.PERSONA}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if use_search:
        body["tools"] = [{"google_search": {}}]

    res = gemini_request(settings.GEMINI_TEXT_MODELS, body)
    cand = (res.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text:
        raise RuntimeError(f"Gemini が文章を返しませんでした（{cand.get('finishReason')}）")
    data = _parse_json(text)
    chunks = cand.get("groundingMetadata", {}).get("groundingChunks", [])
    data["_sources"] = [c["web"]["uri"] for c in chunks if c.get("web", {}).get("uri")]
    return data


def ask_claude(prompt: str, use_search: bool = False) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    kwargs = dict(
        model=settings.CLAUDE_MODEL,
        max_tokens=16000,
        system=settings.PERSONA,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if use_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}]

    messages = [{"role": "user", "content": prompt}]
    for _ in range(5):
        resp = client.beta.messages.create(messages=messages, **kwargs)
        if resp.stop_reason != "pause_turn":
            break
        # 検索が長引いて一時停止した場合は続きを頼む
        messages.append({"role": "assistant", "content": resp.content})

    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude が作成を断りました: {resp.stop_details}")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return {**_parse_json(text), "_sources": []}


def verified_url(url: str, sources: list[str]) -> str:
    """出典URLが本当に開けるか確かめる。だめなら検索結果の実URLを使う。どれもだめなら空"""
    for u in [url, *sources]:
        if not u:
            continue
        try:
            r = requests.get(u, timeout=15, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            if r.ok and "grounding-api-redirect" not in r.url:
                return r.url
        except requests.RequestException:
            pass
    return ""


JSON_RULE = """
最後に、次の形式の JSON だけを ```json ``` で囲んで出力してください。
"""


def news_prompt(history: list[dict]) -> str:
    part = "朝" if now_jst().hour < 12 else "夕方"
    return f"""現在は日本時間 {_today_label()} です。{part}のニュースネタ投稿を1つ作ってください。

手順:
1. web検索で、今日（直近24時間）の日本国内で話題のニュースを調べる
2. 明るめ・生活に身近・「へぇ」と思える話題を1つ選ぶ（悲惨な事件事故、政治的に対立する話題は避ける）
3. 実際に記事を読んで確認した事実だけで、自分の言葉で短くまとめる。記事の文章を丸写ししない
4. 最近の投稿と同じ話題は避ける

最近の投稿:
{_history_text(history)}
{JSON_RULE}
{{
  "summary": "投稿内容の一行要約（重複防止用）",
  "x_text": "X用の本文。全角100文字以内。URLは入れない",
  "long_text": "Threads用の本文。全角300文字以内。URLは入れない",
  "hashtags": ["ハッシュタグを1つ（#は付けない）"],
  "source_name": "出典メディア名",
  "source_url": "実際に読んだ記事のURL"
}}"""


def funny_prompt(history: list[dict]) -> str:
    return f"""現在は日本時間 {_today_label()} です。クスっと笑える投稿を1つ作ってください。

・日常の「あるある」、季節ネタ、ちょっとした発見など、誰も傷つかない笑い
・写真を1枚付けます。投稿に合う写真の内容も考えてください
・最近の投稿と似たネタは避ける

最近の投稿:
{_history_text(history)}
{JSON_RULE}
{{
  "summary": "投稿内容の一行要約（重複防止用）",
  "x_text": "X用の本文。全角110文字以内",
  "long_text": "Threads・Instagram用の本文。全角250文字以内",
  "hashtags": ["Instagram用ハッシュタグを3〜5個（#は付けない）"],
  "self_comment": "投稿のすぐ後に自分で付ける1件目のコメント。全角100文字以内。本文と重複しない補足（豆知識・ちょっとした本音・関連の小ネタ）＋本文とは違う角度の、答えやすい問いかけ。URLは入れない",
  "photo_query": "写真素材サイトで探すための英語の検索キーワード（1〜3語。例: sleepy cat, rainy window）",
  "image_prompt": "AIで写真を作る場合の内容を英語で具体的に。リアルな写真風。実在の人物・有名キャラクター・ブランドロゴ・文字は入れない"
}}"""


# ニュースを集める検索キーワード（増やしたい・減らしたいときはここを書き換え）
NICHE_QUERIES = ["ゴルフ", "男子ゴルフ", "女子ゴルフ", "ゴルフ 新製品", "キャンプ", "キャンプ 新商品", "アウトドア"]


def niche_prompt(history: list[dict], items: list[dict]) -> str:
    """キャンプ・ゴルフ・アウトドアのニュースを1つ選んで紹介する投稿"""
    listing = "\n".join(f"{i}. {it['title']}（{it['source']}／{it['date']}）" for i, it in enumerate(items))
    return f"""現在は日本時間 {_today_label()} です。
「{settings.NICHE}」がテーマのアカウントで、ニュースを紹介する投稿を1つ作ってください。

最新の {settings.NICHE} 関連ニュース（Googleニュースより。番号・見出し・メディア・日付）:
{listing}

手順:
1. 上のニュースから、いちばん多くの人が反応しそうなものを1つ選ぶ
   ・選び方の目安：有名選手・人気ブランド・新商品・大会結果・「へぇ」と思う話・みんなが意見を言いたくなる話
   ・事故・遭難・クマなどの被害は、注意を呼びかける形で事実だけを伝えるならよい（茶化さない・あおらない）
   ・訃報、政治、特定の人への批判、炎上中の話題は選ばない
   ・最近の投稿と同じニュースは選ばない
2. 見出しに書かれている事実だけを使う。見出しにない詳細・数字・コメントは作らない
3. 「ニュースの要点」→「ひとこと感想」→「みんなに聞く質問」の流れで、下の「伸びる書き方」に沿って書く

伸びる書き方:
{settings.BUZZ_RULES}

最近の投稿:
{_history_text(history)}
{JSON_RULE}
{{
  "pick": 選んだニュースの番号（数字）,
  "summary": "投稿内容の一行要約（重複防止用）",
  "x_text": "X用の本文。全角110文字以内",
  "long_text": "Threads・Instagram用の本文。全角250文字以内。最後は質問で終える",
  "hashtags": ["1つ目はThreads用のトピック（キャンプ か ゴルフ）。続けてInstagram用を合計5個まで（#は付けない）"],
  "self_comment": "投稿のすぐ後に自分で付ける1件目のコメント。全角100文字以内。本文と重複しない補足（豆知識・ちょっとした本音・関連の小ネタ）＋本文とは違う角度の、答えやすい問いかけ。URLは入れない",
  "photo_query": "写真素材サイトで探すための英語の検索キーワード（1〜3語。例: camping tent, golf course）"
}}"""


def trend_prompt(history: list[dict]) -> str:
    return f"""現在は日本時間 {_today_label()} です。
今日、日本でいちばん話題になっていることに乗っかった、雑談風の投稿を1つ作ってください。

今日、日本で急上昇している検索ワードと関連ニュース（Googleトレンドより）:
{research.trend_material()}

手順:
1. 上のトレンドの中から、明るく、誰でも会話に参加できる話題を1つ選ぶ
   （事件・事故・災害・訃報・政治・特定の人への批判・炎上中の話題は避ける）
2. {settings.NICHE}に自然につなげられるなら少しだけつなげる（無理につなげなくてよい）
3. 下の「伸びる書き方」に沿って書く。話題の事実は、上の見出しに書かれていることだけを使う

伸びる書き方:
{settings.BUZZ_RULES}

最近の投稿:
{_history_text(history)}
{JSON_RULE}
{{
  "summary": "投稿内容の一行要約（重複防止用）",
  "x_text": "X用の本文。全角110文字以内",
  "long_text": "Threads・Instagram用の本文。全角250文字以内。最後は質問で終える",
  "hashtags": ["1つ目はThreads用のトピック（話題を表す言葉）。続けてInstagram用を合計5個まで（#は付けない）"],
  "self_comment": "投稿のすぐ後に自分で付ける1件目のコメント。全角100文字以内。本文と重複しない補足（豆知識・ちょっとした本音・関連の小ネタ）＋本文とは違う角度の、答えやすい問いかけ。URLは入れない",
  "photo_query": "写真素材サイトで探すための英語の検索キーワード（1〜3語）"
}}"""


def stock_prompt(history: list[dict]) -> str:
    return f"""現在は日本時間 {_today_label()} です。今日の日本の株式市場まとめ投稿を作ってください。

手順:
1. web検索で、今日の東京市場の結果（日経平均・TOPIXの終値と前日比、大きく動いた業種や銘柄とその理由）を調べる
2. 今日が祝日などで東京市場が休場なら "skip": true にする
3. 数字は検索で確認できたものだけを書く。推測で数字を書かない

厳守:
・「買い」「売り」「おすすめ」「今が買い時」など、売買をすすめる表現は絶対に書かない
・今後の値動きを断定しない
{JSON_RULE}
{{
  "skip": false,
  "summary": "投稿内容の一行要約",
  "x_text": "X用の本文。全角100文字以内",
  "long_text": "Threads用の本文。全角300文字以内",
  "hashtags": ["ハッシュタグを1つ（#は付けない）"]
}}"""


def amazon_prompt(item: dict) -> str:
    return f"""Amazonで買える次の商品を紹介する投稿を作ってください。

商品データ:
- 商品名: {item['name']}
- 紹介者のメモ: {item['point'] or '（なし）'}

厳守:
・使ってよい事実は「商品名」と「紹介者のメモ」に書かれていることだけ。書かれていない機能・数値・評価・ランキングは作らない
・価格や「セール中」「最安」など、値段に関することは書かない
・誇張しすぎず、「こんな人に良さそう」という目線で親しみやすく
{JSON_RULE}
{{
  "summary": "投稿内容の一行要約",
  "x_text": "X用の本文。全角80文字以内。URLは入れない",
  "long_text": "Threads用の本文。全角250文字以内。URLは入れない",
  "ig_caption": "Instagram用の本文。全角500文字以内。おすすめポイント→こんな人に、の順で",
  "card_catch": "画像に大きく入れるキャッチコピー。全角16文字以内",
  "short_name": "検索しやすい短い商品名（全角20文字以内）",
  "hashtags": ["Instagram用ハッシュタグを3〜4個（#は付けない、PRは不要）"]
}}"""


def room_prompt(item: dict) -> str:
    return f"""楽天市場の次の商品を紹介する投稿を作ってください。

商品データ（これに書かれている事実だけを使い、書かれていない機能や数値は作らない）:
- 商品名: {item['name']}
- 価格: {item['price']:,}円（{item['date']}時点）
- ショップ: {item['shop']}
- ランキング: {item['rank']}位（{item['genre_label']}）
- 商品説明: {item['caption'][:1500]}

Instagram用の文章は、次の見本と同じ書き方（タイトル→デメリット→メリット→まとめ）にしてください:
{settings.ROOM_STYLE_EXAMPLE}
{JSON_RULE}
{{
  "summary": "投稿内容の一行要約",
  "x_text": "X用の本文。全角80文字以内。URLは入れない",
  "long_text": "Threads用の本文。全角250文字以内。URLは入れない",
  "ig_caption": "Instagram用の本文。全角600文字以内",
  "hashtags": ["Instagram用ハッシュタグを3〜4個（#は付けない、PRは不要）"]
}}"""
