# 内部用メモ（テンプレート）

このファイルをコピーして `docs/private-notes.md` を作成し、実際の値を記入してください。
`private-notes.md` は `.gitignore` で除外されているため、Gitにはコミットされません。

```bash
cp docs/private-notes.example.md docs/private-notes.md
```

## AWSアカウント情報

| 項目 | 値 |
|---|---|
| AWSアカウントID | （記入） |
| リージョン | ap-northeast-1 |

## IAM

| 項目 | 値 |
|---|---|
| アプリ専用IAMユーザー | （記入） |
| アタッチしているカスタムポリシー | （記入） |

## Bedrock Guardrail

| 項目 | 値 |
|---|---|
| Guardrail ID | （記入。`.env` の `GUARDRAIL_ID` と同じ） |
| Guardrail Version | （記入。`.env` の `GUARDRAIL_VERSION` と同じ） |

## GitHub（このリポジトリをフォーク・複製して使う場合）

| 項目 | 値 |
|---|---|
| リポジトリ | （記入） |
| Personal Access Token | ここには書かず、別途安全な場所（パスワードマネージャー等）で管理してください |
