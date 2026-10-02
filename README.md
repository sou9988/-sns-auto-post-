# SNS自動投稿 セットアップ手順

X・Threads・Instagram に、毎日自動で投稿するしくみです。GitHub Actions（無料）で動くので、パソコンの電源を切っていても投稿されます。

## 毎日の投稿

| 時刻 | 内容 | X | Threads | Instagram |
|---|---|---|---|---|
| 7:30 | ニュースネタ | ✅ | ✅ | − |
| 12:00 | クスっと笑えるネタ＋写真 | ✅ | ✅ | ✅ |
| 15:30 | 株式市場まとめ（平日のみ・休場日は投稿なし） | ✅ | ✅ | − |
| 18:00 | ニュースネタ | ✅ | ✅ | − |
| 20:00 | 楽天ROOM商品紹介（#PR付き） | ✅ | ✅ | ✅ |
| 21:30 | クスっと笑えるネタ＋写真 | ✅ | ✅ | ✅ |

キーが設定されていないSNSは自動でスキップされるので、準備できたSNSから順に始められます。

---

## 手順1　GitHub にファイルを置く

1. https://github.com でアカウントを作成
2. 右上の「＋」→「New repository」
   - Repository name: `sns-auto-post`
   - **Public** を選ぶ（Instagram・Threads が写真を読み込むために必要。キーは手順3の Secrets に入れるので公開されません）
3. 作ったリポジトリで「uploading an existing file」をクリックし、このフォルダの中身（`.github` フォルダも含めて）をすべてドラッグして「Commit changes」

## 手順2　各サービスのキーを取得する

### Claude（文章を作る）
1. https://console.anthropic.com にログイン → 「Billing」でクレジットを購入（$10〜で十分）
2. 「API Keys」→「Create Key」→ 表示されたキーをメモ → **ANTHROPIC_API_KEY**

### Gemini（写真を作る）
1. https://aistudio.google.com にGoogleアカウントでログイン
2. 「Get API key」→「APIキーを作成」→ **GEMINI_API_KEY**
3. 画像生成は有料枠の場合があるので、エラーが出たら課金設定（Billing）を有効にしてください

### 楽天（商品を選ぶ）
1. https://webservice.rakuten.co.jp →「アプリID発行」→ **RAKUTEN_APP_ID**
   - アクセスキーも表示された場合は → **RAKUTEN_ACCESS_KEY**
2. 同じページの「アフィリエイトID」→ **RAKUTEN_AFFILIATE_ID**（これで紹介料が入ります）

### X
1. https://developer.x.com に投稿したいアカウントでログインし、開発者登録
2. アプリの「User authentication settings」→ App permissions を **Read and write** にして保存
3. 「Keys and tokens」で次の4つを発行（**権限を変えた後に**発行すること）
   - API Key → **X_API_KEY** / API Key Secret → **X_API_SECRET**
   - Access Token → **X_ACCESS_TOKEN** / Access Token Secret → **X_ACCESS_TOKEN_SECRET**
4. 無料プランは月の投稿数に上限があります（このしくみは月に約180件投稿します）。登録時に上限を確認してください

### Threads
1. https://developers.facebook.com →「マイアプリ」→「アプリを作成」
2. ユースケースで「Threads APIにアクセス」を選ぶ
3. 権限 `threads_basic` と `threads_content_publish` を追加
4. 「役割」→ Threadsテスターに自分のThreadsアカウントを追加し、Threadsアプリ側で招待を承認
5. 「ユーザートークン生成ツール」で長期トークンを発行 → **THREADS_ACCESS_TOKEN**

### Instagram
1. Instagramアプリでアカウントを「プロアカウント（ビジネス or クリエイター）」に切り替え
2. 上と同じ Meta のアプリに、ユースケース「Instagram APIでメッセージとコンテンツを管理」を追加
3. 権限 `instagram_business_basic` と `instagram_business_content_publish` を追加
4. 「Instagramビジネスログインを使ったAPI設定」で自分のアカウントを追加し、トークンを生成 → **IG_ACCESS_TOKEN**
5. **IG_USER_ID** は手順4の「接続テスト」で表示されます

### GitHub（トークンの自動延長用）
Threads・Instagram のトークンは60日で切れるので、自動で延長するために使います。
1. GitHub 右上のアイコン →「Settings」→「Developer settings」→「Personal access tokens」→「Fine-grained tokens」→「Generate new token」
2. Repository access: `sns-auto-post` のみ / Permissions: **Secrets** を Read and write
3. 有効期限は最長に設定 → **GH_PAT**

## 手順3　キーを GitHub に登録する

リポジトリの「Settings」→「Secrets and variables」→「Actions」→「New repository secret」で、手順2の太字の名前とキーを1つずつ登録します。

## 手順4　テストする

リポジトリの「Actions」タブ →「SNS自動投稿」→「Run workflow」

1. **接続テスト**：種類 `check` を選んで実行 → ログに各SNSのアカウント名が出ればOK（Instagram の `user_id` を IG_USER_ID に登録）
2. **内容テスト**：種類 `funny`、テストモードにチェックを入れたまま実行 → ログに投稿文が表示されます。写真は実行結果ページ下部の「test-image」からダウンロードできます
3. **本番テスト**：テストモードのチェックを外して実行 → 実際に投稿されます
4. `news` `stock` `room` も同じように確認

ここまで問題なければ、あとは毎日自動で投稿されます。

---

## 困ったとき

- **投稿に失敗した**：GitHub から失敗通知メールが届きます。Actions タブのログに理由が出ています
- **口調やネタの方向性を変えたい**：`settings.py` の `PERSONA` を書き換えます
- **時刻を変えたい**：`.github/workflows/post.yml` の `cron`（UTC表記・日本時間−9時間）を変えます
- **一時停止したい**：Actions タブ →「SNS自動投稿」→ 右上「…」→「Disable workflow」
