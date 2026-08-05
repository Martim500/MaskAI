# Masked Prompt Chat

Bedrock Guardrails でPIIをマスキングしてから、Amazon Bedrock経由のClaudeに渡すチャットアプリです。
会話・マスキングともにAWS（Amazon Bedrock）のみで完結し、Anthropic API（api.anthropic.com）は使用しません。

## 事前準備

### 1. IAMユーザー
このアプリ専用のIAMユーザー（本リポジトリでは `REDACTED_IAM_USER` を想定）を用意してください。
必要なIAM権限（最低限）:
- `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream`（Converse APIの権限もこれでカバーされる。`bedrock:Converse`は別途不要）
- `bedrock:ApplyGuardrail`

> MFA必須ポリシー（`BlockNonMFARequests`等）が付与されたメインユーザーとは別に、
> アプリ専用ユーザーを分離しておくと、常時起動するアプリからの利用がしやすくなります。

> **モデルIDについて**: オンデマンド呼び出しでは生のfoundation-model ID（例: `anthropic.claude-sonnet-5`）は使えず、
> 推論プロファイルID（例: `jp.anthropic.claude-opus-4-8`, `global.anthropic.claude-sonnet-5`）を指定する必要がある。
> `aws bedrock list-inference-profiles` で確認できる。本アプリの `app.py` は動作確認済みのプロファイルIDを設定済み。

### 2. Bedrock Guardrail の作成
以下のいずれかで作成する。

- **コンソール**: AWSコンソール → Bedrock → Guardrails → 作成
  - 「機密情報のフィルター」で検知したいPII種別（氏名、メールアドレス、電話番号、クレジットカード番号など）を選択
  - 動作を **「マスク（匿名化）」** に設定
- **スクリプト**: `bedrock:CreateGuardrail` 権限を持つ認証情報で
  ```bash
  python scripts/create_guardrail.py
  ```
  を実行すると、同じ設定（氏名・メール・電話番号・住所・クレジットカード番号をマスク）でGuardrailを自動作成する。
  ※ MaskAgentアプリ実行用のIAMユーザーには、この作成権限はあえて付与していない（最小権限のため）。

作成後、Guardrail ID と Version（未発行の場合は `DRAFT`）を控える。

### 3. モデルアクセス
Bedrock コンソール → モデルアクセス で、使用するClaudeモデル（Sonnet 5 / Opus 4.8 / Haiku 4.5）へのアクセスを有効化してください。

## セットアップ

```bash
pip install -r requirements.txt
```

### 設定値の指定方法

AWS認証情報・Guardrail ID/Versionは `.env` ファイル（または環境変数）からのみ読み込みます。
**画面（サイドバー）には表示・入力欄がありません。**

```bash
cp .env.example .env
```

`.env` の内容:

```
AWS_REGION=ap-northeast-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
GUARDRAIL_ID=
GUARDRAIL_VERSION=DRAFT
```

`.env` は `.gitignore` で除外されているため、誤ってコミットされることはありません。

## 起動

```bash
streamlit run app.py
```

`.streamlit/config.toml` により、サーバーは `127.0.0.1`（localhost）のみでLISTENします。
**同一PC内のブラウザからしかアクセスできず、LANや外部ネットワークからは接続できません。**

ブラウザが自動で開きます（開かない場合は `http://localhost:8501`）。

## 使い方
1. 左サイドバー上部の「＋ 新しいチャット」で会話セッションを作成・切り替えできる（Claudeライクな左ナビ構成）
2. 下部のチャット欄にメッセージを入力
3. マスキングが発生した場合は入力直後に「マスキング内容を確認」で元テキストとの差分が見られる
4. マスク後のテキストがBedrock Claudeに送信され、会話は履歴を保持したまま継続する
5. サイドバー下部の「⚙️ 設定」から、PIIマスキングのON/OFF切り替え・使用モデルの選択ができる
   （OFFにするとGuardrailsを通さず入力をそのままClaudeに送信するため、画面上部に警告が表示される）

## エラー時の挙動
- AWS認証情報（`.env`）が未設定の場合は、アプリ起動直後にエラーを表示して停止する
- マスキングON時にGuardrail IDが未設定の場合は、送信前にエラーメッセージを表示して処理を止める
- Bedrock Guardrails の呼び出し（`apply_guardrail`）が失敗した場合は最大3回まで自動リトライし、
  それでも失敗した場合はAWS Region / Guardrail ID / Guardrail Version やIAM権限を確認するよう促すエラーを表示する
- Bedrock Claude（Converse API）の呼び出しが失敗した場合も同様に自動リトライする
  （認証エラー・権限不足・不正リクエストなどはリトライせず即座にエラー表示）
- いずれの場合も例外を握りつぶさず、画面にエラー内容を表示する

## 補足
- マスキングは各ユーザー発言ごとに実行されます（Claudeの返信自体はマスキングしません）
- 会話（セッション）はブラウザのタブを閉じる・アプリを再起動すると失われます（永続化はしていません）
- AWSアクセスキーは `.env` のみで管理し、画面には一切表示されません

## docs/
社内の生成AI利用ポリシー（業務領域・ユースケースごとのデータ入力可否）を格納。
今後Guardrailsの拒否トピック（Denied Topics）設計の元ネタとして使用する。
