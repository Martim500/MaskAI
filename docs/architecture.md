# MaskAgent（Masked Prompt Chat）構成案

最終更新: 2026-08-05

## 1. 目的

Bedrock Guardrailsで入力中のPIIをマスキングした上で、Amazon Bedrock経由のClaudeと会話できる社内向けチャットアプリ。
将来的には `docs/業務領域・ユースケースごとのデータ入力可否.xlsx` に基づき、PIIマスキングだけでなく
「未公開決算情報」「契約書」等の業務データ分類ごとの入力可否判定（Denied Topics）も組み込む想定。

## 2. 全体構成図

```mermaid
flowchart TD
    U[社員のブラウザ<br/>簡易ログイン: 社員名/ID入力のみ] -->|HTTPS| ALB[Application Load Balancer<br/>社内ネットワークからのみアクセス可]

    ALB --> FG[ECS Fargate サービス<br/>Streamlitコンテナ (app.py)<br/>タスク数: 1〜（負荷に応じて増減可）]

    FG -->|apply_guardrail| GR[Bedrock Guardrails<br/>REDACTED_GUARDRAIL_ID]
    FG -->|converse| Claude[Bedrock Claude<br/>推論プロファイル<br/>sonnet-5 / opus-4.8 / haiku-4.5]
    FG -->|put/get/query/delete Item| DDB[(DynamoDB<br/>mori-ddb-maskai-prod-sessions<br/>PK:user_id SK:session_id)]

    Admin[管理者ユーザー] -->|Guardrail管理パネル| FG
    FG -->|get_guardrail/update_guardrail| GR

    FG -.IAMロール(タスクロール)で認証.-> IAMRole[ECSタスクロール<br/>静的アクセスキー不要]

    subgraph AWS["AWSアカウント REDACTED_ACCOUNT_ID (ap-northeast-1)"]
      ALB
      FG
      GR
      Claude
      DDB
      IAMRole
    end
```

## 3. コンポーネント

| コンポーネント | 役割 | 備考 |
|---|---|---|
| ALB | HTTPS終端、社内ネットワークからのアクセスのみ許可 | 現状は未構築（開発中は`127.0.0.1`限定で動作確認） |
| ECS Fargate（Streamlitコンテナ） | アプリ本体。ログイン、チャットUI、マスキング制御、セッション管理、管理者向けGuardrail編集 | `app.py` 1本構成 |
| Bedrock Guardrails | PIIマスキング（`ApplyGuardrail`）、管理者パネルからの設定変更（`UpdateGuardrail`） | Guardrail ID: `REDACTED_GUARDRAIL_ID` |
| Bedrock Claude（Converse API） | 会話生成。sonnet-5 / opus-4.8 / haiku-4.5 を選択可 | オンデマンド呼び出しには推論プロファイルIDが必要 |
| DynamoDB | セッション（会話履歴）の永続化 | テーブル: `mori-ddb-maskai-prod-sessions`、PK=`user_id`, SK=`session_id` |
| ECSタスクロール | Fargateタスクに付与するIAMロール。静的アクセスキー(.env)を廃止し、これに置き換える予定 | 本番デプロイ時に対応 |

## 4. 主な設計判断とその理由

### 4-1. セッション永続化: DynamoDB を採用（AgentCore Memoryは見送り）
- AgentCore Memoryは短期記憶だけの利用でも `$0.25 / 1,000イベント` かかるのに対し、DynamoDBは`$1.25 / 100万書込`とほぼ無視できるコスト。同一想定負荷（月3万件程度のやり取り）で比較すると **DynamoDBの方が約100倍以上安い**。
- AgentCore Memoryの強み（長期記憶＝ユーザーの好み等の自動抽出）は今回使わない方針のため、コスト差だけが残る形になり見送った。
- 将来「過去の会話から好みを学習して活かす」機能が必要になった時点で、AgentCore Memoryへの移行を再検討する。

### 4-2. デプロイ基盤: Fargateを採用（EC2は見送り）
- Streamlit自体はコンテナを必須としないが、運用面（OSパッチ不要、`docker push`だけで再デプロイ、後からのスケールが容易）でFargateが優位。
- セッション状態をDynamoDBに外出ししたことで、Streamlitプロセスがステートレスに近くなり、複数タスクへの水平スケールが安全にできるようになった（以前の「メモリ内セッション」設計のままだと、複数台に増やした際にユーザーがどのタスクに繋がるかで会話が消える問題があった）。
- 50人程度の同時利用であればタスク1つでも足りる可能性が高いが、Fargateなら負荷増加時にタスク数を増やすだけで対応できる。

### 4-3. Streamlitを継続利用
- 現状の実装（マスキング制御、セッション管理、管理者パネル等）を作り直すコストが大きいため、フロントエンド/バックエンドを分離した別構成への刷新は今回のスコープ外とした。

### 4-4. マスキングON/OFF・モデル選択・Guardrail管理はUIから操作可能
- 設定パネル（⚙️）にPIIマスキングのトグル、モデル選択を配置。
- Guardrailの検知対象PII種別の追加・削除は管理者限定（`ADMIN_USERS`環境変数で判定）。現状は管理者のみ。将来的には「部署リーダーは追加のみ可、削除は管理者のみ」という権限分離を検討。

## 5. 未対応・今後の検討事項

| 項目 | 現状 | 課題 |
|---|---|---|
| 認証 | 社員名/IDを入力するだけ（パスワード無し） | なりすまし防止にならない。社内SSO連携を将来検討 |
| Denied Topics（業務データ分類のNG判定） | 未実装。PII 5〜6種のマスキングのみ | `docs/業務領域・ユースケースごとのデータ入力可否.xlsx` を元に、未公開決算情報・契約書・APIキー等の意味的な検知をどう実装するか要設計 |
| AWS認証情報 | `.env`に静的アクセスキー（`REDACTED_IAM_USER`） | 本番デプロイ時にECSタスクロールへ移行し、静的キーを廃止する |
| 監査ログ | Guardrailsが何を検知・マスクしたかの記録なし | 社内ポリシー運用ツールとして必要になる可能性が高い |
| ネットワーク公開範囲 | `127.0.0.1`限定（開発中） | ALB経由での社内公開に切り替える際、アクセス制御（VPC内限定 or 認証必須）を設計する |
| HTTPS | 未対応（HTTPのみ） | ALB + ACM証明書での終端が必要 |

## 6. 参考: これまでのコスト調査結果

| 項目 | 単価 |
|---|---|
| Bedrock Guardrails（PII/機密情報フィルター） | $0.10 / 1,000 text units |
| Bedrock Guardrails（Denied Topics・コンテンツフィルター） | $0.15 / 1,000 text units |
| DynamoDB（オンデマンド） | 書込 $1.25 / 100万件、読込 $0.25 / 100万件 |
| AgentCore Memory（短期記憶） | $0.25 / 1,000イベント |
| AgentCore Memory（長期記憶） | 保存 $0.75 / 1,000レコード/月、検索 $0.50 / 1,000件 |

1 text unit = 最大1,000文字。会社名の網羅的マスキングはBedrock Guardrails標準機能では不可（個別登録が必要）。
