"""
プロンプトマスキングツール
- 入力したテキストのPIIをAmazon Bedrock Guardrailsでマスキングして表示するだけのツール。
- AI（Claude等）への送信は行わない。マスキング後のテキストは、他のAIチャット等に
  自分でコピーして使う想定。

起動方法:
    streamlit run app.py

AWS認証情報・Guardrail ID/Versionは .env / 環境変数からのみ読み込む
（画面上には表示・入力しない。.env.example 参照）。
"""

import os
import time

import boto3
import pandas as pd
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

# Guardrail設定パネルで切り替えられるPII種別（Bedrock Guardrailsが対応する全種別のうち、
# docs/業務領域・ユースケースごとのデータ入力可否.xlsx を踏まえて選んだもの）
AVAILABLE_PII_TYPES = {
    "NAME": "氏名",
    "EMAIL": "メールアドレス",
    "PHONE": "電話番号",
    "ADDRESS": "住所",
    "AGE": "年齢",
    "CREDIT_DEBIT_CARD_NUMBER": "クレジットカード番号",
    "PASSWORD": "パスワード",
    "USERNAME": "ユーザー名",
    "AWS_ACCESS_KEY": "AWSアクセスキー",
    "AWS_SECRET_KEY": "AWSシークレットキー",
    "IP_ADDRESS": "IPアドレス",
    "URL": "URL",
}

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
GUARDRAIL_ID = os.getenv("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.getenv("GUARDRAIL_VERSION", "DRAFT")

st.set_page_config(page_title="Prompt Masking Tool", layout="centered")

st.markdown(
    """
    <style>
    #MainMenu, header, footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)


class MaskingError(Exception):
    """Guardrailsによるマスキング処理が失敗したことを表す。"""


def bedrock_client(service_name: str):
    return boto3.client(
        service_name,
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
    )


def mask_text(text: str) -> tuple[str, bool]:
    """Bedrock GuardrailsでPIIをマスキングする。戻り値: (マスク後テキスト, マスクされたか)"""
    client = bedrock_client("bedrock-runtime")

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.apply_guardrail(
                guardrailIdentifier=GUARDRAIL_ID,
                guardrailVersion=GUARDRAIL_VERSION,
                source="INPUT",
                content=[{"text": {"text": text}}],
            )
            if response.get("action") == "GUARDRAIL_INTERVENED" and response.get(
                "outputs"
            ):
                masked = response["outputs"][0]["text"]
                return masked, masked != text
            return text, False
        except (ClientError, BotoCoreError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise MaskingError(str(last_error)) from last_error


def get_guardrail_details() -> dict:
    client = bedrock_client("bedrock")
    return client.get_guardrail(
        guardrailIdentifier=GUARDRAIL_ID, guardrailVersion=GUARDRAIL_VERSION
    )


def save_guardrail_config(
    selected_types: set[str], custom_regexes: list[dict], current_details: dict
) -> None:
    client = bedrock_client("bedrock")
    pii_cfg = [
        {
            "type": t,
            "action": "ANONYMIZE",
            "inputAction": "ANONYMIZE",
            "inputEnabled": True,
            "outputAction": "ANONYMIZE",
            "outputEnabled": True,
        }
        for t in selected_types
    ]
    regex_cfg = [
        {
            "name": r["name"],
            "description": r.get("description") or r["name"],
            "pattern": r["pattern"],
            "action": "ANONYMIZE",
            "inputAction": "ANONYMIZE",
            "inputEnabled": True,
            "outputAction": "ANONYMIZE",
            "outputEnabled": True,
        }
        for r in custom_regexes
        if r.get("name") and r.get("pattern")
    ]
    client.update_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        name=current_details["name"],
        description=current_details.get("description", ""),
        sensitiveInformationPolicyConfig={
            "piiEntitiesConfig": pii_cfg,
            "regexesConfig": regex_cfg,
        },
        blockedInputMessaging=current_details["blockedInputMessaging"],
        blockedOutputsMessaging=current_details["blockedOutputsMessaging"],
    )


# ── 起動時の必須設定チェック ──────────────────────────
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    st.error(
        "AWS認証情報が未設定です。.env の AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY を設定してください。"
    )
    st.stop()

st.title("Prompt Masking Tool")
st.caption(
    "入力したテキストのPIIをAmazon Bedrock Guardrailsでマスキングします。"
    "AIへの送信は行いません。マスキング後のテキストはコピーして他のAIチャット等にお使いください。"
)

if st.session_state.pop("guardrail_saved_flash", False):
    st.success("✅ Guardrail設定を更新しました")

# ── Guardrail設定パネル ──────────────────────────────
with st.expander("⚙️ Guardrail設定（マスキング対象の管理）"):
    if not GUARDRAIL_ID:
        st.error(".env の GUARDRAIL_ID が未設定です。")
    else:
        if "guardrail_snapshot" not in st.session_state:
            try:
                st.session_state.guardrail_snapshot = get_guardrail_details()
            except (ClientError, BotoCoreError) as exc:
                st.error(f"Guardrail設定の取得に失敗しました: {exc}")
                st.session_state.guardrail_snapshot = None

        if st.button("🔄 最新の設定を再取得"):
            try:
                st.session_state.guardrail_snapshot = get_guardrail_details()
            except (ClientError, BotoCoreError) as exc:
                st.error(f"Guardrail設定の取得に失敗しました: {exc}")

        details = st.session_state.guardrail_snapshot
        if details:
            current_types = {
                e["type"]
                for e in details.get("sensitiveInformationPolicy", {}).get(
                    "piiEntities", []
                )
            }
            selected: set[str] = set()
            cols = st.columns(2)
            for i, (type_key, label) in enumerate(AVAILABLE_PII_TYPES.items()):
                with cols[i % 2]:
                    checked = st.checkbox(
                        label, value=type_key in current_types, key=f"pii_{type_key}"
                    )
                    if checked:
                        selected.add(type_key)

            st.markdown("**カスタム正規表現（会社名など）**")
            st.caption(
                "name / pattern は必須。patternは正規表現として解釈されます"
                "（例: 会社名や略称を `|` で区切って複数指定）。"
            )
            current_regexes = details.get("sensitiveInformationPolicy", {}).get(
                "regexes", []
            )
            regex_df = (
                pd.DataFrame(
                    [
                        {
                            "name": r["name"],
                            "pattern": r["pattern"],
                            "description": r.get("description", ""),
                        }
                        for r in current_regexes
                    ]
                )
                if current_regexes
                else pd.DataFrame(columns=["name", "pattern", "description"])
            )
            edited_regex_df = st.data_editor(
                regex_df, num_rows="dynamic", use_container_width=True, key="regex_editor"
            )

            if st.button("この内容でGuardrailを保存", use_container_width=True):
                custom_regexes = edited_regex_df.fillna("").to_dict("records")
                try:
                    save_guardrail_config(selected, custom_regexes, details)
                    st.session_state.pop("guardrail_snapshot", None)
                    st.session_state["guardrail_saved_flash"] = True
                    st.rerun()
                except (ClientError, BotoCoreError) as exc:
                    st.error(f"Guardrail設定の更新に失敗しました: {exc}")

st.divider()

# ── マスキング本体 ────────────────────────────────────
text_input = st.text_area("マスキングしたいテキストを入力してください", height=200)

if st.button("マスキングする", type="primary", use_container_width=True):
    if not text_input.strip():
        st.warning("テキストを入力してください。")
    elif not GUARDRAIL_ID:
        st.error(".env の GUARDRAIL_ID が未設定です。")
    else:
        try:
            with st.spinner("マスキング中..."):
                masked_text, was_masked = mask_text(text_input)
        except MaskingError as exc:
            st.error(
                "Bedrock Guardrails の呼び出しに失敗しました。"
                "AWS Region / Guardrail ID / Guardrail Version やIAM権限（bedrock:ApplyGuardrail）"
                f"を確認してください。\n\n詳細: {exc}"
            )
        else:
            if was_masked:
                st.success("PIIを検知し、マスキングしました。")
            else:
                st.info("マスキング対象は検知されませんでした。")

            st.markdown("**マスキング後のテキスト**（右上のアイコンでコピーできます）")
            st.code(masked_text, language=None)

            if was_masked:
                with st.expander("元のテキストとの差分を確認"):
                    st.text(f"元のテキスト:\n{text_input}\n\n送信テキスト:\n{masked_text}")
