"""
MaskAgentのセッション永続化用 Bedrock AgentCore Memory を作成するワンショットスクリプト。
bedrock-agentcore:CreateMemory 権限を持つ認証情報で実行すること。

このスクリプトは「短期記憶（会話履歴の保存・取得）」のみのMemoryを作成する。
長期記憶（ユーザーの好み・要約の自動抽出）を後で追加したくなったら、
memoryStrategies（userPreferenceMemoryStrategy 等）と、それが使う
memoryExecutionRoleArn（IAMロール）を追加でセットアップする必要がある。

実行方法:
    python scripts/create_memory.py

環境変数（.env）:
    AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
"""

import os

import boto3
from dotenv import load_dotenv

load_dotenv()

MEMORY_NAME = "mori_memory_maskai_prod_sessions"
EVENT_EXPIRY_DAYS = 365  # 保存可能な最大値(365日)。短期記憶のみなので実質「消えない」運用にする。


def main() -> None:
    client = boto3.client(
        "bedrock-agentcore-control",
        region_name=os.getenv("AWS_REGION", "ap-northeast-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY") or None,
    )

    existing = client.list_memories().get("memories", [])
    for m in existing:
        if m.get("name") == MEMORY_NAME:
            print(f"Memory {MEMORY_NAME} は既に存在します: {m['id']}")
            return

    response = client.create_memory(
        name=MEMORY_NAME,
        description="MaskAgentチャットアプリのセッション（会話履歴）永続化用",
        eventExpiryDuration=EVENT_EXPIRY_DAYS,
    )

    memory_id = response["memory"]["id"]
    print("Memory作成完了:")
    print(f"  MEMORY_ID={memory_id}")
    print("上記を .env に設定してください。")


if __name__ == "__main__":
    main()
