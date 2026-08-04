"""
マスキング付き Claude チャットアプリ（Amazon Bedrock版）
- PIIマスキング: Amazon Bedrock Guardrails (ApplyGuardrail API)
- 会話: Amazon Bedrock Converse API (Claude on Bedrock)

起動方法:
    streamlit run app.py

設定値は環境変数 / .env からも読み込めます（.env.example 参照）。
サイドバー入力は環境変数の値を上書きするために使えます。
"""

import os
import time

import boto3
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

MODEL_IDS = {
    # オンデマンド呼び出しには推論プロファイルIDが必要（生のfoundation-model IDは不可）。
    # sonnet-5はjp.リージョンプロファイルが無いためglobal.を使用。
    "claude-sonnet-5": "global.anthropic.claude-sonnet-5",
    "claude-opus-4-8": "jp.anthropic.claude-opus-4-8",
    "claude-haiku-4-5-20251001": "jp.anthropic.claude-haiku-4-5-20251001-v1:0",
}

st.set_page_config(page_title="Masked Prompt Chat", layout="wide")

# ── サイドバー設定 ────────────────────────────────────
with st.sidebar:
    st.header("設定")

    st.subheader("AWS / Bedrock")
    aws_region = st.text_input(
        "AWS Region", value=os.getenv("AWS_REGION", "ap-northeast-1")
    )
    aws_access_key_id = st.text_input(
        "AWS Access Key ID", value=os.getenv("AWS_ACCESS_KEY_ID", "")
    )
    aws_secret_access_key = st.text_input(
        "AWS Secret Access Key",
        value=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        type="password",
    )

    st.divider()

    st.subheader("Bedrock Guardrails")
    guardrail_id = st.text_input("Guardrail ID", value=os.getenv("GUARDRAIL_ID", ""))
    guardrail_version = st.text_input(
        "Guardrail Version", value=os.getenv("GUARDRAIL_VERSION", "DRAFT")
    )

    st.divider()

    st.subheader("Claude モデル")
    model = st.selectbox("Model", list(MODEL_IDS.keys()), index=0)

    st.divider()
    if st.button("会話をリセット"):
        st.session_state.clear()
        st.rerun()

st.title("Masked Prompt Chat")
st.caption("入力はBedrock Guardrailsでマスキングされた上でBedrock Claudeに送信されます")

# ── セッション状態初期化 ──────────────────────────────
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []  # 画面表示用（マスク前後含む）
if "api_messages" not in st.session_state:
    st.session_state.api_messages = []  # Bedrock Converseに渡す実際の履歴


def bedrock_client(service_name: str):
    """AWS認証情報を明示的に指定してBedrockクライアントを作る。"""
    return boto3.client(
        service_name,
        region_name=aws_region,
        aws_access_key_id=aws_access_key_id or None,
        aws_secret_access_key=aws_secret_access_key or None,
    )


class MaskingError(Exception):
    """Guardrailsによるマスキング処理が失敗したことを表す。"""


class ChatError(Exception):
    """Bedrock Claudeの呼び出しが失敗したことを表す。"""


def mask_text(text: str) -> tuple[str, bool]:
    """Bedrock GuardrailsでPIIをマスキングする。戻り値: (マスク後テキスト, マスクされたか)"""
    client = bedrock_client("bedrock-runtime")

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.apply_guardrail(
                guardrailIdentifier=guardrail_id,
                guardrailVersion=guardrail_version,
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


def call_claude(messages: list[dict]) -> str:
    """Bedrock Converse APIでClaudeを呼び出し、応答テキストを返す。失敗時はリトライする。"""
    client = bedrock_client("bedrock-runtime")
    model_id = MODEL_IDS[model]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens": 2000},
            )
            return response["output"]["message"]["content"][0]["text"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            # 認証・権限・入力不正はリトライしても解決しないため即座に失敗させる
            if error_code in (
                "AccessDeniedException",
                "UnrecognizedClientException",
                "ValidationException",
            ):
                raise ChatError(str(exc)) from exc
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        except BotoCoreError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise ChatError(str(last_error)) from last_error


# ── 過去メッセージの再表示 ────────────────────────────
for msg in st.session_state.display_messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("masked_note"):
            with st.expander("マスキング内容を確認"):
                st.text(msg["masked_note"])

# ── 入力欄 ────────────────────────────────────────────
user_input = st.chat_input("メッセージを入力...")

if user_input:
    if not guardrail_id:
        st.error(
            "Guardrail ID が未設定です。サイドバーで入力するか、.env の GUARDRAIL_ID を設定してください。"
        )
        st.stop()
    if not aws_access_key_id or not aws_secret_access_key:
        st.error(
            "AWS Access Key ID / Secret Access Key が未設定です。"
            "サイドバーで入力するか、.env に設定してください。"
        )
        st.stop()

    with st.chat_message("user"):
        st.write(user_input)

    # ① マスキング
    try:
        with st.spinner("マスキング中..."):
            masked_text, was_masked = mask_text(user_input)
    except MaskingError as exc:
        st.error(
            "Bedrock Guardrails の呼び出しに失敗しました。"
            "AWS Region / Guardrail ID / Guardrail Version やIAM権限（bedrock:ApplyGuardrail）"
            f"を確認してください。\n\n詳細: {exc}"
        )
        st.stop()

    masked_note = None
    if was_masked:
        masked_note = f"元のテキスト:\n{user_input}\n\n送信テキスト:\n{masked_text}"
        with st.expander("マスキング内容を確認", expanded=True):
            st.text(masked_note)

    st.session_state.display_messages.append(
        {"role": "user", "content": user_input, "masked_note": masked_note}
    )

    # ② マスク後テキストで会話継続（履歴にはマスク後のものを積む）
    st.session_state.api_messages.append(
        {"role": "user", "content": [{"text": masked_text}]}
    )

    with st.chat_message("assistant"):
        try:
            with st.spinner("Claudeが応答中..."):
                reply = call_claude(st.session_state.api_messages)
            st.write(reply)
        except ChatError as exc:
            st.error(
                "Bedrock Claude の呼び出しに失敗しました。"
                "AWS認証情報・IAM権限（bedrock:Converse）・モデルアクセス設定を確認してください。"
                f"\n\n詳細: {exc}"
            )
            st.session_state.api_messages.pop()  # 失敗したユーザー発言を履歴から取り消す
            st.stop()

    st.session_state.api_messages.append(
        {"role": "assistant", "content": [{"text": reply}]}
    )
    st.session_state.display_messages.append({"role": "assistant", "content": reply})
