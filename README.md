# Prompt Masking Tool

入力したテキストのPIIを Amazon Bedrock Guardrails でマスキングして表示するだけのツールです。
**AI（Claude等）への送信は行いません。** マスキング後のテキストは、ご自身で他のAIチャット等にコピーしてお使いください。

## 事前準備

### 1. IAMユーザー
このアプリ専用のIAMユーザー（本リポジトリでは `REDACTED_IAM_USER` を想定）を用意してください。
必要なIAM権限（最低限）:
- `bedrock:ApplyGuardrail`（マスキング処理そのもの）
- `bedrock:GetGuardrail` / `bedrock:UpdateGuardrail`（画面上のGuardrail設定パネルから対象PII・カスタム正規表現を編集する場合）

> MFA必須ポリシー（`BlockNonMFARequests`等）が付与されたメインユーザーとは別に、
> アプリ専用ユーザーを分離しておくと運用しやすくなります。

### 2. Bedrock Guardrail の作成
以下のいずれかで作成する。

- **コンソール**: AWSコンソール → Bedrock → Guardrails → 作成
  - 「機密情報のフィルター」で検知したいPII種別（氏名、メールアドレス、電話番号、クレジットカード番号など）を選択
  - 動作を **「マスク（匿名化）」** に設定
- **スクリプト**: `bedrock:CreateGuardrail` 権限を持つ認証情報で
  ```bash
  python scripts/create_guardrail.py
  ```
  を実行すると、同じ設定（氏名・メール・電話番号・住所・クレジットカード番号・年齢をマスク）でGuardrailを自動作成する。
  ※ アプリ実行用のIAMユーザーには、この作成権限はあえて付与していない（最小権限のため）。

作成後、Guardrail ID と Version（未発行の場合は `DRAFT`）を控える。

## セットアップ

```bash
pip install -r requirements.txt
```

### 設定値の指定方法

AWS認証情報・Guardrail ID/Versionは `.env` ファイル（または環境変数）からのみ読み込みます。
**画面には表示・入力欄がありません。**

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

## 起動・停止

`start.bat` をダブルクリックすると起動します（内部で `streamlit run app.py` を実行しているだけ）。
コマンド操作は不要です。

- 起動: `start.bat` をダブルクリック
- 停止: 起動時に開いたウィンドウで `Ctrl+C`、またはウィンドウを閉じる。閉じ忘れた場合は `stop.bat` をダブルクリックすれば該当プロセスのみ停止する
- ブラウザが自動で開きます（開かない場合は `http://localhost:8501` を開く）

コマンドラインから直接起動したい場合:
```bash
streamlit run app.py
```

`.streamlit/config.toml` により、サーバーは `127.0.0.1`（localhost）のみでLISTENします。
**同一PC内のブラウザからしかアクセスできず、LANや外部ネットワークからは接続できません。**
（「サーバーを立ててIPを公開する」ようなものではなく、このPC専用の入り口が開くだけです）

## 使い方
1. テキスト入力欄にマスキングしたい文章を貼り付ける
2. 「マスキングする」ボタンを押す
3. マスキング後のテキストが表示される（右上のアイコンでコピーできる）。マスキングが発生した場合は「元のテキストとの差分を確認」で内容を確認できる
4. コピーしたテキストは、ご自身で他のAIチャット等に貼り付けて使う

### Guardrail設定（マスキング対象の管理）
画面上部の「⚙️ Guardrail設定」を開くと、
- マスキング対象のPII種別（氏名・メール・電話番号・住所・年齢・クレジットカード番号など）のON/OFF
- カスタム正規表現（会社名など、任意の文字列パターン）の追加・編集・削除

ができます。保存すると、その場でAWS側のGuardrail設定に反映されます（ログイン等は無く、この画面を開ける人なら誰でも変更できます）。

## エラー時の挙動
- AWS認証情報（`.env`）が未設定の場合は、アプリ起動直後にエラーを表示して停止する
- Guardrail IDが未設定の場合は、マスキング実行前にエラーメッセージを表示する
- Bedrock Guardrails の呼び出し（`apply_guardrail`）が失敗した場合は最大3回まで自動リトライし、
  それでも失敗した場合はAWS Region / Guardrail ID / Guardrail Version やIAM権限を確認するよう促すエラーを表示する
- いずれの場合も例外を握りつぶさず、画面にエラー内容を表示する

## 補足
- 入力したテキストや会話履歴は保存されません（ページを再読み込みすると消えます）
- AWSアクセスキーは `.env` のみで管理し、画面には一切表示されません

## docs/
- `architecture.md`: 構成メモ
- `業務領域・ユースケースごとのデータ入力可否.xlsx` / `MaskAI要件.png`: 社内の生成AI利用ポリシー資料（参考情報として保管）
