"""
マスキング付き Claude チャットアプリ（Amazon Bedrock版）
- PIIマスキング: Amazon Bedrock Guardrails (ApplyGuardrail API)
- 会話: Amazon Bedrock Converse API (Claude on Bedrock)

起動方法:
    streamlit run app.py

AWS認証情報・Guardrail ID/Versionは .env / 環境変数からのみ読み込む
（画面上には表示・入力しない。.env.example 参照）。
"""

import os
import time
import uuid

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

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
GUARDRAIL_ID = os.getenv("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.getenv("GUARDRAIL_VERSION", "DRAFT")

st.set_page_config(page_title="Masked Prompt Chat", layout="wide")

st.markdown(
    """
    <style>
    #MainMenu, header, footer {visibility: hidden;}
    section[data-testid="stSidebar"] { width: 260px !important; }
    section[data-testid="stSidebar"] button {
        text-align: left;
        justify-content: flex-start;
    }
    .block-container { max-width: 780px; padding-top: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


class MaskingError(Exception):
    """Guardrailsによるマスキング処理が失敗したことを表す。"""


class ChatError(Exception):
    """Bedrock Claudeの呼び出しが失敗したことを表す。"""


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


def call_claude(messages: list[dict], model_key: str) -> str:
    """Bedrock Converse APIでClaudeを呼び出し、応答テキストを返す。失敗時はリトライする。"""
    client = bedrock_client("bedrock-runtime")
    model_id = MODEL_IDS[model_key]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens": 4000},
            )
            content_blocks = response["output"]["message"]["content"]
            text_blocks = [block["text"] for block in content_blocks if "text" in block]
            if not text_blocks:
                # 思考(reasoning)だけでmax_tokensに達した場合など、テキスト応答が無いケース
                raise ChatError(
                    "モデルからテキスト応答が得られませんでした"
                    f"（stopReason={response.get('stopReason')}）。"
                    "出力上限に達した可能性があります。質問を短くするか、時間をおいて再度お試しください。"
                )
            return "\n".join(text_blocks)
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


# ── セッション状態初期化 ──────────────────────────────
def new_session() -> str:
    session_id = str(uuid.uuid4())
    st.session_state.sessions[session_id] = {
        "title": "新しいチャット",
        "display_messages": [],
        "api_messages": [],
    }
    st.session_state.current_session_id = session_id
    return session_id


if "sessions" not in st.session_state:
    st.session_state.sessions = {}
    st.session_state.current_session_id = None
if "masking_enabled" not in st.session_state:
    st.session_state.masking_enabled = True
if "model_key" not in st.session_state:
    st.session_state.model_key = next(iter(MODEL_IDS))
if not st.session_state.sessions:
    new_session()

# ── 起動時の必須設定チェック ──────────────────────────
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    st.error(
        "AWS認証情報が未設定です。.env の AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY を設定してください。"
    )
    st.stop()

# ── サイドバー（Claude風: 新規チャット + セッション一覧 + 設定） ──
with st.sidebar:
    st.markdown("**Masked Prompt Chat**")

    if st.button("＋ 新しいチャット", use_container_width=True):
        new_session()
        st.rerun()

    st.divider()

    for sid, sess in list(st.session_state.sessions.items()):
        is_current = sid == st.session_state.current_session_id
        label = ("💬 " if is_current else "　") + sess["title"]
        if st.button(label, key=f"session_btn_{sid}", use_container_width=True):
            st.session_state.current_session_id = sid
            st.rerun()

    st.divider()

    with st.popover("⚙️ 設定", use_container_width=True):
        st.session_state.masking_enabled = st.toggle(
            "PIIマスキングを有効にする",
            value=st.session_state.masking_enabled,
            help="OFFにするとBedrock Guardrailsを通さず、入力をそのままClaudeに送信します。",
        )
        st.session_state.model_key = st.selectbox(
            "モデル",
            list(MODEL_IDS.keys()),
            index=list(MODEL_IDS.keys()).index(st.session_state.model_key),
        )
        st.caption(
            f"Guardrail ID: {GUARDRAIL_ID or '未設定'} / Version: {GUARDRAIL_VERSION}"
        )

        st.divider()
        if st.button("このチャットを削除", use_container_width=True):
            del st.session_state.sessions[st.session_state.current_session_id]
            if not st.session_state.sessions:
                new_session()
            else:
                st.session_state.current_session_id = next(
                    iter(st.session_state.sessions)
                )
            st.rerun()
        if st.button("すべてのチャットを削除", use_container_width=True):
            st.session_state.sessions = {}
            new_session()
            st.rerun()

# ── メイン画面 ────────────────────────────────────────
current = st.session_state.sessions[st.session_state.current_session_id]

if not st.session_state.masking_enabled:
    st.caption("⚠ マスキングOFF: 入力はそのままBedrock Claudeに送信されます")

for msg in current["display_messages"]:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("masked_note"):
            with st.expander("マスキング内容を確認"):
                st.text(msg["masked_note"])

user_input = st.chat_input("メッセージを入力...")

if user_input:
    if st.session_state.masking_enabled and not GUARDRAIL_ID:
        st.error(".env の GUARDRAIL_ID が未設定です。")
        st.stop()

    with st.chat_message("user"):
        st.write(user_input)

    # ① マスキング（OFFの場合はそのまま使う）
    masked_text, was_masked = user_input, False
    if st.session_state.masking_enabled:
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

    current["display_messages"].append(
        {"role": "user", "content": user_input, "masked_note": masked_note}
    )
    if current["title"] == "新しいチャット":
        current["title"] = user_input[:20] + ("…" if len(user_input) > 20 else "")

    # ② マスク後テキストで会話継続（履歴にはマスク後のものを積む）
    current["api_messages"].append({"role": "user", "content": [{"text": masked_text}]})

    with st.chat_message("assistant"):
        try:
            with st.spinner("Claudeが応答中..."):
                reply = call_claude(current["api_messages"], st.session_state.model_key)
            st.write(reply)
        except ChatError as exc:
            st.error(
                "Bedrock Claude の呼び出しに失敗しました。"
                "AWS認証情報・IAM権限・モデルアクセス設定を確認してください。"
                f"\n\n詳細: {exc}"
            )
            current["api_messages"].pop()  # 失敗したユーザー発言を履歴から取り消す
            st.stop()

    current["api_messages"].append({"role": "assistant", "content": [{"text": reply}]})
    current["display_messages"].append({"role": "assistant", "content": reply})
