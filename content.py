"""Claude で投稿文を作る"""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

import settings

JST = ZoneInfo("Asia/Tokyo")
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}

client = anthropic.Anthropic()


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


def ask_claude(prompt: str, use_search: bool = False) -> dict:
    """Claude に投稿案を JSON で書いてもらう"""
    kwargs = dict(
        model=settings.CLAUDE_MODEL,
        max_tokens=16000,
        system=settings.PERSONA,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if use_search:
        kwargs["tools"] = [WEB_SEARCH]

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
    return _parse_json(text)


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
  "image_prompt": "写真の内容を英語で具体的に。リアルな写真風。実在の人物・有名キャラクター・ブランドロゴ・文字は入れない"
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
