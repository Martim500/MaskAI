# Prompt Masking Tool 構成メモ

最終更新: 2026-08-06

## 1. 目的

社内で生成AI（ChatGPT等、社外のAIサービス含む）にプロンプトを入力する前に、
Amazon Bedrock GuardrailsでPII（氏名・メール・電話番号・住所・クレジットカード番号・
社名など）をマスキングし、マスキング後のテキストを表示するだけのシンプルなツール。
**AIとの会話機能は持たない。** マスキング後のテキストはユーザーが自分でコピーし、
利用したいAIサービスに貼り付けて使う。

> 経緯: 当初はBedrock Claudeとの会話機能・複数セッション管理・ユーザーログイン・
> DynamoDBでの永続化まで作り込んだが、要件を確認した結果「AIとの会話は不要、
> マスキング機能だけあればよい」と判明したため、それらを撤去しシンプルな構成に戻した。

## 2. 構成図

```mermaid
flowchart TD
    U[ブラウザ<br/>http://localhost:8501] -->|HTTP (127.0.0.1限定)| App[Streamlit アプリ app.py]
    App -->|apply_guardrail| GR[Bedrock Guardrails<br/>GUARDRAIL_ID（.envで指定）]
    App -->|get_guardrail/update_guardrail<br/>設定パネルから| GR

    subgraph AWS["AWSアカウント（docs/private-notes.md参照）"]
      GR
    end
```

構成はこれだけ。DB・認証基盤・常時稼働サーバー・ロードバランサーは無い。

## 3. コンポーネント

| コンポーネント | 役割 |
|---|---|
| Streamlitアプリ（`app.py`） | テキスト入力、マスキング実行・表示、Guardrail設定パネル（PII種別・カスタム正規表現の編集） |
| Bedrock Guardrails | PIIマスキング本体（`ApplyGuardrail`）。設定パネルからの変更は`UpdateGuardrail` |

## 4. 実行環境

各自のPCで `start.bat` を実行してローカル起動する運用。`127.0.0.1`限定でLISTENするため、
他のPCからはアクセスできない。全社で使う場合は、各自が自分のPCでこのツールを起動する形になる
（サーバーを1台立てて全員でアクセスする、という構成は現時点では想定していない）。

## 5. 参考: Bedrock Guardrailsのコスト

| 項目 | 単価 |
|---|---|
| PII/機密情報フィルター | $0.10 / 1,000 text units |
| Denied Topics・コンテンツフィルター（未使用） | $0.15 / 1,000 text units |

1 text unit = 最大1,000文字。会社名のような固有名詞は「機密情報フィルター」の標準PII種別には無いため、
カスタム正規表現（Guardrail設定パネルから追加可能）で個別に登録する必要がある。
