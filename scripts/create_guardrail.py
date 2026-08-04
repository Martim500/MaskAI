"""
MaskAgent用のBedrock Guardrailを作成するワンショットスクリプト。
bedrock:CreateGuardrail権限を持つ認証情報で実行すること
（REDACTED_IAM_USERには意図的にこの権限を付与していないため、
ryuta.moriのMFA済みセッション、またはコンソール操作が必要）。

実行方法:
    python scripts/create_guardrail.py

環境変数（.env）:
    AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN(任意)
"""

import os

import boto3
from dotenv import load_dotenv

load_dotenv()

GUARDRAIL_NAME = "mori-guardrail-maskagent-prod"

PII_ENTITY_TYPES = [
    "NAME",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "CREDIT_DEBIT_CARD_NUMBER",
]


def main() -> None:
    client = boto3.client(
        "bedrock",
        region_name=os.getenv("AWS_REGION", "ap-northeast-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY") or None,
        aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
    )

    response = client.create_guardrail(
        name=GUARDRAIL_NAME,
        description="MaskAgentチャットアプリ用: 入力中のPIIをマスキングする",
        sensitiveInformationPolicy={
            "piiEntitiesConfig": [
                {"type": t, "action": "ANONYMIZE"} for t in PII_ENTITY_TYPES
            ]
        },
        blockedInputMessaging="このメッセージには送信できない内容が含まれています。",
        blockedOutputsMessaging="この回答は表示できません。",
    )

    guardrail_id = response["guardrailId"]
    guardrail_version = response["version"]

    print("Guardrail作成完了:")
    print(f"  GUARDRAIL_ID={guardrail_id}")
    print(f"  GUARDRAIL_VERSION={guardrail_version}")
    print("上記を .env に設定してください。")


if __name__ == "__main__":
    main()
