"""
マスキング付き Claude チャットアプリ（Amazon Bedrock版）
- PIIマスキング: Amazon Bedrock Guardrails (ApplyGuardrail API)
- 会話: Amazon Bedrock Converse API (Claude on Bedrock)
- セッション永続化: DynamoDB
- ユーザー識別: 簡易ログイン（社員名/IDの入力のみ、パスワード無し）

起動方法:
    streamlit run app.py

AWS認証情報・Guardrail ID/Versionは .env / 環境変数からのみ読み込む
（画面上には表示・入力しない。.env.example 参照）。
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key
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

# 管理者パネルで切り替えられるPII種別（Bedrock Guardrailsが対応する全種別のうち、
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
SESSIONS_TABLE_NAME = os.getenv("SESSIONS_TABLE_NAME", "mori-ddb-maskai-prod-sessions")
ADMIN_USERS = {u.strip() for u in os.getenv("ADMIN_USERS", "").split(",") if u.strip()}

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


def dynamodb_table():
    resource = boto3.resource(
        "dynamodb",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
    )
    return resource.Table(SESSIONS_TABLE_NAME)


def load_user_sessions(user_id: str) -> dict:
    """DynamoDBからそのユーザーの全セッションを読み込む。失敗時は空辞書を返し画面にエラー表示。"""
    try:
        resp = dynamodb_table().query(KeyConditionExpression=Key("user_id").eq(user_id))
    except (ClientError, BotoCoreError) as exc:
        st.error(f"セッション情報の読み込みに失敗しました: {exc}")
        return {}

    sessions = {}
    for item in resp.get("Items", []):
        sessions[item["session_id"]] = {
            "title": item["title"],
            "display_messages": json.loads(item["display_messages"]),
            "api_messages": json.loads(item["api_messages"]),
        }
    return sessions


def save_session(user_id: str, session_id: str, session: dict) -> None:
    try:
        dynamodb_table().put_item(
            Item={
                "user_id": user_id,
                "session_id": session_id,
                "title": session["title"],
                "display_messages": json.dumps(
                    session["display_messages"], ensure_ascii=False
                ),
                "api_messages": json.dumps(session["api_messages"], ensure_ascii=False),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except (ClientError, BotoCoreError) as exc:
        st.error(f"セッションの保存に失敗しました: {exc}")


def delete_session_record(user_id: str, session_id: str) -> None:
    try:
        dynamodb_table().delete_item(Key={"user_id": user_id, "session_id": session_id})
    except (ClientError, BotoCoreError) as exc:
        st.error(f"セッションの削除に失敗しました: {exc}")


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
                raise ChatError(
                    "モデルからテキスト応答が得られませんでした"
                    f"（stopReason={response.get('stopReason')}）。"
                    "出力上限に達した可能性があります。質問を短くするか、時間をおいて再度お試しください。"
                )
            return "\n".join(text_blocks)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
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


def get_guardrail_details() -> dict:
    client = bedrock_client("bedrock")
    return client.get_guardrail(
        guardrailIdentifier=GUARDRAIL_ID, guardrailVersion=GUARDRAIL_VERSION
    )


def save_pii_types(selected_types: set[str], current_details: dict) -> None:
    client = bedrock_client("bedrock")
    cfg = [
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
    client.update_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        name=current_details["name"],
        description=current_details.get("description", ""),
        sensitiveInformationPolicyConfig={"piiEntitiesConfig": cfg},
        blockedInputMessaging=current_details["blockedInputMessaging"],
        blockedOutputsMessaging=current_details["blockedOutputsMessaging"],
    )


# ── 起動時の必須設定チェック ──────────────────────────
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    st.error(
        "AWS認証情報が未設定です。.env の AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY を設定してください。"
    )
    st.stop()

# ── 簡易ログイン（社員名/IDのみ、パスワード無し） ──────
if "user_id" not in st.session_state:
    st.title("Masked Prompt Chat")
    st.caption("お名前または社員IDを入力してください")
    with st.form("login_form"):
        name_input = st.text_input("お名前 / 社員ID")
        submitted = st.form_submit_button("ログイン")
    if submitted:
        if name_input.strip():
            st.session_state.user_id = name_input.strip()
            st.rerun()
        else:
            st.warning("お名前または社員IDを入力してください。")
    st.stop()

user_id = st.session_state.user_id
is_admin = user_id in ADMIN_USERS

# ── セッション状態初期化（初回はDynamoDBから読み込み） ──
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
    with st.spinner("セッションを読み込み中..."):
        st.session_state.sessions = load_user_sessions(user_id)
    st.session_state.current_session_id = None
if "masking_enabled" not in st.session_state:
    st.session_state.masking_enabled = True
if "model_key" not in st.session_state:
    st.session_state.model_key = next(iter(MODEL_IDS))
if not st.session_state.sessions or st.session_state.current_session_id is None:
    if st.session_state.sessions:
        st.session_state.current_session_id = next(iter(st.session_state.sessions))
    else:
        new_session()

# ── サイドバー（Claude風: 新規チャット + セッション一覧 + 設定） ──
with st.sidebar:
    st.markdown(f"**Masked Prompt Chat**　`{user_id}`")

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
            delete_session_record(user_id, st.session_state.current_session_id)
            del st.session_state.sessions[st.session_state.current_session_id]
            st.session_state.current_session_id = None
            if not st.session_state.sessions:
                new_session()
            st.rerun()
        if st.button("すべてのチャットを削除", use_container_width=True):
            for sid in list(st.session_state.sessions.keys()):
                delete_session_record(user_id, sid)
            st.session_state.sessions = {}
            st.session_state.current_session_id = None
            new_session()
            st.rerun()

        if is_admin:
            st.divider()
            with st.expander("🛡️ Guardrail管理（管理者）"):
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
                                label,
                                value=type_key in current_types,
                                key=f"pii_{type_key}",
                            )
                            if checked:
                                selected.add(type_key)

                    if st.button("この内容でGuardrailを保存", use_container_width=True):
                        try:
                            save_pii_types(selected, details)
                            st.session_state.pop("guardrail_snapshot", None)
                            st.success("Guardrail設定を更新しました。")
                            st.rerun()
                        except (ClientError, BotoCoreError) as exc:
                            st.error(f"Guardrail設定の更新に失敗しました: {exc}")

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

    save_session(user_id, st.session_state.current_session_id, current)
