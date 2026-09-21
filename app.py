"""
⚡ Asian Inference — Streamlit entry point.

Pages are thin: they collect input, call :mod:`core`, and render the result.
Every rule (quotas, pricing, ownership, token accounting) lives in the domain
layer so it holds no matter which surface triggers it.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import billing
import config
import core
import inference
import store
import supabase_backend
import supabase_memory
import ui
from config import (
    APP_ICON, APP_NAME, AUTH_COOKIE_NAME, AUTH_SESSION_DAYS, PLANS,
    TOKENS_PER_ROW, USING_DEFAULT_SECRET, display_limit, is_admin, plan_for,
)
from ui import esc

st.set_page_config(
    page_title=APP_NAME,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()
core.bootstrap()

SESSION_EMAIL = "user_email"
AUTH_COOKIE_SET_KEY = "_auth_cookie_to_set"
AUTH_COOKIE_CLEAR_KEY = "_auth_cookie_to_clear"
HERO_IMAGE_CANDIDATES = (
    Path("assets/home-hero.png"),
    Path("assets/home-hero.jpg"),
    Path("assets/home-hero.jpeg"),
)


# ─────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────
def _auth_cookie() -> str:
    try:
        cookies = st.context.cookies
        value = cookies.get(AUTH_COOKIE_NAME, "") if cookies else ""
    except Exception:
        value = ""
    return str(value or "").strip()



def _queue_auth_cookie(token: str) -> None:
    token = (token or "").strip()
    if token:
        st.session_state[AUTH_COOKIE_SET_KEY] = token



def _queue_auth_cookie_clear() -> None:
    st.session_state[AUTH_COOKIE_CLEAR_KEY] = True



def _render_auth_cookie_updates() -> None:
    token = st.session_state.pop(AUTH_COOKIE_SET_KEY, "")
    clear = bool(st.session_state.pop(AUTH_COOKIE_CLEAR_KEY, False))
    if not token and not clear:
        return
    max_age = max(1, int(AUTH_SESSION_DAYS)) * 24 * 60 * 60
    statements: list[str] = []
    if clear:
        statements.append(
            "for (const target of cookieTargets) {"
            "  target.cookie = `${cookieName}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; "
            "Max-Age=0; Path=/; SameSite=Lax${secure}`;"
            "}"
        )
    if token:
        statements.append(
            f"for (const target of cookieTargets) {{"
            f"  target.cookie = `${{cookieName}}=${{encodeURIComponent({json.dumps(token)})}}; "
            f"Max-Age={max_age}; Path=/; SameSite=Lax${{secure}}`;"
            f"}}"
        )
    script = "\n".join([
        "<script>",
        f"const cookieName = {json.dumps(AUTH_COOKIE_NAME)};",
        "const secure = window.location.protocol === 'https:' ? '; Secure' : '';",
        "const cookieTargets = [document];",
        "try { if (window.parent && window.parent.document) { cookieTargets.push(window.parent.document); } } catch (error) {}",
        *statements,
        "</script>",
    ])
    components.html(script, height=0, width=0)



def _restore_sign_in() -> bool:
    if st.session_state.get(SESSION_EMAIL):
        return True
    token = _auth_cookie()
    if not token:
        return False
    user = core.authenticate_persistent_session(token)
    if not user:
        _queue_auth_cookie_clear()
        return False
    st.session_state[SESSION_EMAIL] = user["email"]
    _queue_auth_cookie(token)
    return True



def _sign_out(message: str | None = None) -> None:
    core.revoke_persistent_session(_auth_cookie())
    st.session_state.clear()
    if message:
        st.session_state["auth_notice"] = message
    _queue_auth_cookie_clear()



def _build_zip_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()



def _home_hero_image() -> Path | None:
    for path in HERO_IMAGE_CANDIDATES:
        if path.exists():
            return path
    return None


def _render_announcement_banner() -> None:
    announcement = store.get_announcement()
    if not announcement or not announcement.get("active") or not announcement.get("message"):
        return
    author = announcement.get("author") or "Admin"
    message = esc(announcement.get("message", "")).replace("\n", "<br>")
    st.markdown(
        '<div class="admin-bar">'
        f'📣 Announcement · {esc(author)}<br>{message}'
        '</div>',
        unsafe_allow_html=True,
    )


def _limit_warning(user: dict, kind: str) -> None:
    plan = plan_for(user["plan"])
    st.markdown(
        f'<div class="warn">⚠️ You have used every {kind} slot '
        f'({plan[f"max_{kind}"]}) on the <b>{esc(plan["name"])}</b> plan. '
        "Delete one, or upgrade for more.</div>",
        unsafe_allow_html=True,
    )
    if st.button("⚡ See upgrade options", key=f"upsell_{kind}"):
        ui.go_to("⚡  Upgrade")
        st.rerun()


def _download_buttons(dataset_id: str, rows: list[dict], key_prefix: str = "") -> None:
    """CSV / JSON / JSONL download buttons for a set of rows."""
    if not rows:
        st.caption("This dataset has no rows to download.")
        return
    frame = pd.DataFrame(rows)
    prefix = key_prefix or dataset_id
    col1, col2, col3 = st.columns(3)
    counted = {"on_click": store.increment_dataset_downloads, "args": (dataset_id,)}
    with col1:
        st.download_button(
            "⬇ CSV", frame.to_csv(index=False), f"{dataset_id}.csv", "text/csv",
            key=f"csv_{prefix}", use_container_width=True, **counted,
        )
    with col2:
        st.download_button(
            "⬇ JSON", json.dumps(rows, indent=2, ensure_ascii=False),
            f"{dataset_id}.json", "application/json",
            key=f"json_{prefix}", use_container_width=True, **counted,
        )
    with col3:
        st.download_button(
            "⬇ JSONL", "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
            f"{dataset_id}.jsonl", "application/jsonl",
            key=f"jsonl_{prefix}", use_container_width=True, **counted,
        )


def _model_token(user: dict | None) -> str | None:
    return core.resolve_model_token(user or {}) if user else None


def _memory_enabled() -> bool:
    return supabase_memory.is_configured()


def _memory_status_text() -> str:
    if _memory_enabled():
        return "🧠 Saved memory is on"
    return "🧠 Saved memory is off"


def _tone(ok: bool, *, warn: bool = True) -> str:
    if ok:
        return "ok"
    return "warn" if warn else "off"


def _diagnostic_snapshot(user: dict) -> tuple[list[dict], list[dict]]:
    stats = core.usage(user)
    plan = stats["plan"]
    dataset_remaining = max(0, plan["max_datasets"] - stats["datasets"])
    model_remaining = max(0, plan["max_models"] - stats["models"])

    user_token = bool(_model_token(user))
    deployment_token = bool(config.MODEL_PROVIDER_TOKEN or config.HF_TOKEN)
    chat_ready = user_token or deployment_token
    storage_ok, storage_message = core.storage_status()
    memory_ok, memory_message = supabase_memory.memory_diagnostic()
    backend_ok, backend_message = supabase_backend.health_diagnostic()
    billing_ready = billing.stripe_available() or billing.traakteer_available()
    platform_key_ready = bool(user.get("platform_api_key"))
    secret_ready = not USING_DEFAULT_SECRET

    cards = [
        {
            "kicker": "Access",
            "title": "Chat & Generation",
            "state": "Live" if chat_ready else "Fallback",
            "tone": _tone(chat_ready, warn=False),
            "detail": (
                "Dataset generation and live chat inference are ready."
                if chat_ready else
                "The assistant stays available with built-in offline answers until a token is connected."
            ),
            "meta": (
                "Using your saved registry token first."
                if user_token else
                "Using the deployment model token."
                if deployment_token else
                "No model token detected."
            ),
        },
        {
            "kicker": "Storage",
            "title": "Managed Mirror",
            "state": "Connected" if storage_ok else "Local only",
            "tone": _tone(storage_ok, warn=False),
            "detail": storage_message,
            "meta": "Datasets still save locally even when the mirror is unavailable.",
        },
        {
            "kicker": "Memory",
            "title": "Persistent Chat",
            "state": "Connected" if memory_ok else "Session only",
            "tone": _tone(memory_ok, warn=False),
            "detail": memory_message,
            "meta": "Backed by Supabase when configured.",
        },
        {
            "kicker": "Backend",
            "title": "Supabase Mirror",
            "state": "Connected" if backend_ok else "Local only",
            "tone": _tone(backend_ok, warn=False),
            "detail": backend_message,
            "meta": "Critical app tables can be mirrored there for recovery.",
        },
        {
            "kicker": "Security",
            "title": "Workspace Access",
            "state": "Ready" if platform_key_ready else "Missing key",
            "tone": _tone(platform_key_ready),
            "detail": (
                "Your personal asi- key is generated and ready for scripts or Colab."
                if platform_key_ready else
                "Generate your asi- key in API Keys to call the platform from code."
            ),
            "meta": (
                "Deployment secret key is secure."
                if secret_ready else
                "Admin should replace the default deployment secret key."
            ),
        },
        {
            "kicker": "Billing",
            "title": "Upgrade Checkout",
            "state": "Enabled" if billing_ready else "Disabled",
            "tone": _tone(billing_ready, warn=False),
            "detail": (
                "At least one payment provider is configured."
                if billing_ready else
                "Paid plan checkout is disabled on this deployment right now."
            ),
            "meta": (
                "Stripe or Traakteer is available."
                if billing_ready else
                "Starter still works fully without billing."
            ),
        },
        {
            "kicker": "Capacity",
            "title": "Dataset Slots",
            "state": f"{dataset_remaining} left",
            "tone": "ok" if dataset_remaining > 0 else "warn",
            "detail": (
                f"You are using **{stats['datasets']}** of **{display_limit(plan['max_datasets'])}** dataset slots."
            ),
            "meta": f"Current plan: {plan['badge']} {plan['name']}",
        },
        {
            "kicker": "Capacity",
            "title": "Model Slots",
            "state": f"{model_remaining} left",
            "tone": "ok" if model_remaining > 0 else "warn",
            "detail": (
                f"You are using **{stats['models']}** of **{display_limit(plan['max_models'])}** model slots."
            ),
            "meta": f"Saved API keys: {stats['api_keys']} · Tokens: {stats['tokens']:,}",
        },
    ]

    rows = [
        {
            "label": "User registry token",
            "detail": (
                "A saved third-party token is available and will be preferred for model operations."
                if user_token else
                "No saved registry token found in your API Keys."
            ),
            "meta": "present" if user_token else "absent",
            "tone": _tone(user_token, warn=False),
        },
        {
            "label": "Deployment model token",
            "detail": (
                "The deployment has a managed token configured."
                if deployment_token else
                "No deployment model token is configured."
            ),
            "meta": "present" if deployment_token else "absent",
            "tone": _tone(deployment_token, warn=False),
        },
        {
            "label": "Supabase backend mirror",
            "detail": backend_message,
            "meta": "connected" if backend_ok else "inactive",
            "tone": _tone(backend_ok, warn=False),
        },
        {
            "label": "Public URL",
            "detail": f"Current app URL: `{config.PUBLIC_URL}`",
            "meta": "route",
            "tone": "off",
        },
        {
            "label": "Data directory",
            "detail": f"Local persistence path: `{config.DATA_DIR}`",
            "meta": "storage",
            "tone": "off",
        },
    ]
    return cards, rows


def _remember(email: str, message: dict) -> None:
    try:
        supabase_memory.append_message(
            email,
            message.get("role", ""),
            message.get("content", ""),
            message.get("offer"),
        )
    except Exception:
        pass


def _load_chat(user: dict) -> list[dict]:
    try:
        remembered = supabase_memory.load_chat_history(user["email"], limit=80)
    except Exception:
        remembered = []
    return remembered or [{"role": "bot", "content": _greeting(user)}]


def _clear_chat_memory(user: dict) -> None:
    try:
        supabase_memory.clear_chat_history(user["email"])
    except Exception:
        pass
    st.session_state["chat"] = [{"role": "bot", "content": _greeting(user)}]
    st.session_state["pending_dataset"] = None
    st.session_state["pending_notebook"] = None
    st.session_state["chat_pending"] = False
    st.rerun()


def _run_inference(repo: str, user: dict, output_key: str, prompt: str) -> None:
    """Shared 'try this model' handler with rate limiting and typed errors."""
    email = user["email"]
    if not core.rate_limit(email, "inference"):
        st.error("Rate limit reached — 5 inference calls per minute.")
        return
    try:
        with st.spinner("Running…"):
            output = inference.call_hf(repo, prompt, hf_token=_model_token(user))
    except inference.ModelLoadingError as exc:
        st.warning(str(exc))
    except inference.InferenceError as exc:
        st.error(str(exc))
    else:
        st.text_area("Output", output, height=140, key=output_key, disabled=True)


# ─────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────
def page_auth() -> None:
    _render_auth_cookie_updates()
    notice = st.session_state.pop("auth_notice", "")
    if notice:
        st.success(notice)
    st.markdown(
        '<div class="hero">'
        '<div class="badge">BETA · YOUR OWN AI PLATFORM</div>'
        f"<h1>{APP_ICON} {esc(APP_NAME)}</h1>"
        "<p>Build AI datasets with a chatbot · Fine-tune models · Share with the "
        "community.<br>Like a private AI hub — but yours. No separate registry account "
        "needed to get started.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    selected = st.session_state.get("selected_plan", "starter")
    st.markdown(
        f'<div class="note">Selected plan: <b>{esc(plan_for(selected)["name"])}</b>. '
        "You can change plans any time after signing up.</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1], gap="large")
    with left:
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])

        with tab_in:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="you@example.com")
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox(
                    "Keep me signed in on this device",
                    value=True,
                    help=f"Saves your login in this browser for up to {AUTH_SESSION_DAYS} days.",
                )
                submitted = st.form_submit_button("Sign in →", use_container_width=True, type="primary")
            if submitted:
                ok, message, user = core.login(email, password)
                if ok and user:
                    st.session_state[SESSION_EMAIL] = user["email"]
                    if remember_me:
                        token = core.create_persistent_session(user["email"])
                        if token:
                            _queue_auth_cookie(token)
                    else:
                        _queue_auth_cookie_clear()
                    st.rerun()
                else:
                    st.error(message)

        with tab_up:
            with st.form("register_form"):
                name = st.text_input("Full name")
                email = st.text_input("Email", placeholder="you@example.com", key="reg_email")
                password = st.text_input(
                    "Password", type="password",
                    help=f"At least {core.MIN_PASSWORD_LENGTH} characters", key="reg_pw",
                )
                confirm = st.text_input("Confirm password", type="password", key="reg_pw2")
                submitted = st.form_submit_button(
                    "Create free account →", use_container_width=True, type="primary"
                )
            if submitted:
                if password != confirm:
                    st.error("Passwords don't match.")
                else:
                    ok, message = core.register(email, password, name)
                    if ok:
                        st.success(f"✅ {message} Sign in using the tab above.")
                    else:
                        st.error(message)

    with right:
        st.markdown("### Plans")
        ui.plan_cards_auth()


# ─────────────────────────────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────────────────────────────
def page_home(user: dict) -> None:
    stats = core.usage(user)
    plan = stats["plan"]
    first_name = (user.get("name") or "there").split()[0]
    hero_image = _home_hero_image()

    if hero_image:
        left, right = st.columns([1.5, 1], gap="large")
        with left:
            ui.hero(
                f"Welcome back, {first_name} {plan['badge']}",
                "Your AI workspace — create, train and share",
                badge="AURA",
            )
        with right:
            st.image(str(hero_image), use_container_width=True)
    else:
        ui.hero(f"Welcome back, {first_name} {plan['badge']}",
                "Your AI workspace — create, train and share")

    quick1, quick2, quick3, quick4 = st.columns(4)
    with quick1:
        if st.button("🧪 Open Diagnostics", use_container_width=True):
            ui.go_to("🧪  Diagnostics")
            st.rerun()
    with quick2:
        if st.button("💬 Open Dataset Chat", use_container_width=True):
            ui.go_to("💬  Dataset Chat")
            st.rerun()
    with quick3:
        if st.button("🤖 Open My Models", use_container_width=True):
            ui.go_to("🤖  My Models")
            st.rerun()
    with quick4:
        if st.button("🛰️ Open Apps", use_container_width=True):
            ui.go_to("🛰️  Apps")
            st.rerun()

    columns = st.columns(4)
    tiles = [
        (stats["tokens"], "🪙 Tokens"),
        (stats["datasets"], "📦 Datasets"),
        (stats["models"], "🤖 Models"),
        (stats["api_keys"], "🔑 API Keys"),
    ]
    for column, (value, label) in zip(columns, tiles):
        column.markdown(ui.stat(value, label), unsafe_allow_html=True)

    ui.divider()
    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("**Recent datasets**")
        datasets = store.user_datasets(user["email"], with_rows=False)[:5]
        if not datasets:
            ui.note("No datasets yet — head to Dataset Chat to build one.")
        for dataset in datasets:
            ui.hub_card(dataset["name"], desc=dataset["description"],
                        stats=f"{dataset['row_count']:,} rows · {dataset['created'][:10]}",
                        is_public=dataset["public"], tags=dataset["tags"])

    with right:
        st.markdown("**Recent models**")
        models = store.user_models(user["email"])[:5]
        if not models:
            ui.note("No models yet — create one in My Models.")
        for model in models:
            ui.hub_card(model["name"], desc=model["description"],
                        stats=f"{model['base_model']} · {model['created'][:10]}",
                        is_public=model["public"], tags=model["tags"])

    ui.divider()
    st.markdown("**Plan usage**")
    usage_columns = st.columns(3)
    meters = [
        ("Datasets", stats["datasets"], stats["max_datasets"]),
        ("Models", stats["models"], stats["max_models"]),
        ("Tokens", stats["tokens"], stats["max_tokens"]),
    ]
    for column, (label, used, limit) in zip(usage_columns, meters):
        with column:
            st.markdown(f"{label}: **{used:,}** / {display_limit(limit)}")
            st.progress(min(used / max(limit, 1), 1.0))

    if user["plan"] == "starter":
        ui.note("Starter includes 2 datasets and 2 models. Pro gives you 6 of each, "
                "Elite is unlimited.")


# ─────────────────────────────────────────────────────────────────────
# DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────
def page_diagnostics(user: dict) -> None:
    ui.hero("🧪 Diagnostics", "Live health, access, memory and storage signals", badge="AURA")

    cards, rows = _diagnostic_snapshot(user)
    st.markdown(ui.diagnostic_grid(cards), unsafe_allow_html=True)

    pills = "".join([
        ui.status_pill("chat live" if cards[0]["tone"] == "ok" else "chat fallback", cards[0]["tone"]),
        ui.status_pill("storage mirror" if cards[1]["tone"] == "ok" else "local storage", cards[1]["tone"]),
        ui.status_pill("memory on" if cards[2]["tone"] == "ok" else "memory off", cards[2]["tone"]),
        ui.status_pill("backend mirror" if cards[3]["tone"] == "ok" else "backend local", cards[3]["tone"]),
        ui.status_pill("checkout on" if cards[5]["tone"] == "ok" else "checkout off", cards[5]["tone"]),
    ])
    st.markdown(f'<div class="aura-strip">{pills}</div>', unsafe_allow_html=True)

    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("### Current signals")
        st.markdown(ui.diagnostic_rows(rows), unsafe_allow_html=True)

        recent_datasets = store.user_datasets(user["email"], with_rows=False)[:5]
        st.markdown("### Dataset telemetry")
        if recent_datasets:
            dataset_frame = pd.DataFrame([
                {
                    "name": dataset["name"],
                    "rows": dataset["row_count"],
                    "visibility": "public" if dataset["public"] else "private",
                    "storage": dataset.get("storage_backend") or "local",
                    "updated": dataset["updated"][:19],
                }
                for dataset in recent_datasets
            ])
            st.dataframe(dataset_frame, use_container_width=True, hide_index=True)
        else:
            ui.note("No datasets yet — generate one in Dataset Chat to see storage telemetry.")

    with right:
        st.markdown("### Model telemetry")
        recent_models = store.user_models(user["email"])[:5]
        if recent_models:
            model_frame = pd.DataFrame([
                {
                    "name": model["name"],
                    "base": model["base_model"],
                    "target": model["hf_repo"] or "not set",
                    "visibility": "public" if model["public"] else "private",
                    "updated": model["updated"][:19],
                }
                for model in recent_models
            ])
            st.dataframe(model_frame, use_container_width=True, hide_index=True)
        else:
            ui.note("No models yet — create one in My Models to see output targets.")

        stats = core.usage(user)
        ui.card(
            "<div class=\"stat-lbl\">Workspace summary</div>"
            f"<div class=\"stat-num\">{stats['tokens']:,}</div>"
            "<div style=\"color:var(--txt2);font-size:.87rem;line-height:1.7;margin-top:.45rem\">"
            f"Datasets: <b>{stats['datasets']}</b><br>"
            f"Models: <b>{stats['models']}</b><br>"
            f"Stored keys: <b>{stats['api_keys']}</b>"
            "</div>",
            glow=True,
        )

        controls_col, refresh_col = st.columns(2)
        with controls_col:
            if st.button("🔑 Open API Keys", use_container_width=True):
                ui.go_to("🔑  API Keys")
                st.rerun()
        with refresh_col:
            if st.button("↻ Refresh", use_container_width=True):
                st.rerun()


# ─────────────────────────────────────────────────────────────────────
# DATASET CHAT
# ─────────────────────────────────────────────────────────────────────
CONVERSATION_STARTERS = [
    "What makes a good training dataset?",
    "Generate 50 customer reviews for a coffee shop",
    "How does LoRA fine-tuning actually work?",
    "Build 100 Q&A pairs about Python",
    "Make me a Colab notebook to train a sentiment model",
    "Make 40 spam vs not-spam examples",
]


def _greeting(user: dict) -> str:
    first_name = (user.get("name") or "there").split()[0]
    return (
        f"Hi {first_name} — I'm Asian.\n\n"
        "Ask me anything about machine learning, datasets or training. I can teach, "
        "help you make datasets, and prepare a Colab `.ipynb` notebook for model training.\n\n"
        f"You have **{user['tokens']:,} tokens** ({TOKENS_PER_ROW} per row)."
    )


def _provisional_offer(message: str) -> dict | None:
    """A dataset the assistant could build, so a later 'yes' has something to accept."""
    if not inference.looks_data_adjacent(message):
        return None
    return {
        "topic": message,
        "rows": inference.extract_row_count(message) or 20,
        "columns": inference.suggest_columns(message),
    }


def _queue_generation(user: dict, spec: dict) -> str:
    """Open the generation form for `spec` and return what the assistant says."""
    if core.at_limit(user, "datasets"):
        return (
            "I can help you design the dataset, but your dataset slots are full right now.\n\n"
            "Delete one from Dataset Hub or upgrade your plan, then I can generate it for you."
        )

    plan = plan_for(user["plan"])
    rows = max(1, min(int(spec.get("rows") or 20), plan["max_rows"]))
    columns = spec.get("columns") or ["input", "output"]
    topic = spec.get("topic", "")

    st.session_state["pending_dataset"] = {
        "topic": topic, "rows": rows, "columns": columns,
        "name": "My Dataset", "description": "", "tags": "",
    }
    capped = ""
    if (spec.get("rows") or 0) > plan["max_rows"]:
        capped = (f"\n\nI capped it at {plan['max_rows']:,} rows — that's the "
                  f"{plan['name']} plan limit.")
    return (
        f"On it — a **{rows}-row** dataset.\n\n"
        f"I'd use the columns `{', '.join(columns)}`. Adjust anything in the form "
        f"below, then hit **Generate dataset**.{capped}"
    )


def _default_notebook_dataset(user: dict) -> str:
    preferred = st.session_state.get("last_id")
    if preferred and store.get_dataset(preferred):
        return preferred
    datasets = store.user_datasets(user["email"], with_rows=False)
    return datasets[0]["id"] if datasets else ""


def _queue_notebook(user: dict, spec: dict) -> str:
    """Open the notebook builder and return what the assistant says."""
    if core.at_limit(user, "models"):
        return (
            "I can help you plan the training notebook, but your model slots are full right now.\n\n"
            "Delete one from My Models or upgrade your plan, then I can prepare the `.ipynb`."
        )

    dataset_id = _default_notebook_dataset(user)
    st.session_state["pending_notebook"] = {
        "name": spec.get("name") or "My Model",
        "description": "",
        "base_model": spec.get("base_model") or POPULAR_BASE_MODELS[0],
        "target_repo": "",
        "dataset_id": dataset_id,
        "epochs": 3,
        "learning_rate": "2e-4",
        "max_length": 512,
        "batch_size": 4,
        "tags": "",
        "public": False,
    }
    if dataset_id:
        return (
            "Absolutely — I opened the training notebook form below.\n\n"
            "Pick the dataset and base model you want, then press **Generate notebook** and I'll make the `.ipynb` for you."
        )
    return (
        "Absolutely — I opened the training notebook form below.\n\n"
        "You can still create the notebook now, but training works best once you've generated or selected a dataset."
    )


def _take_turn(user: dict) -> None:
    """Produce the assistant's reply to the last message.

    Runs while the thinking bubble is already on screen, so the wait for the
    model reads as the assistant composing rather than as the page hanging.
    """
    conversation = st.session_state["chat"]
    message = conversation[-1]["content"]
    history = conversation[:-1]

    dataset_intent = inference.detect_dataset_intent(message, history)
    notebook_intent = inference.detect_notebook_intent(message)
    if notebook_intent:
        reply, offer = _queue_notebook(user, notebook_intent), None
    elif dataset_intent:
        reply, offer = _queue_generation(user, dataset_intent), None
    else:
        reply = inference.chat_response(message, history, user_hf_token=_model_token(user))
        offer = _provisional_offer(message)
        if offer:
            reply += "\n\nWant me to build that? Just say the word."

    assistant_message = {"role": "bot", "content": reply, "offer": offer}
    conversation.append(assistant_message)
    _remember(user["email"], assistant_message)
    st.session_state["chat_pending"] = False
    st.rerun()


def _send(user: dict, message: str) -> None:
    """Record the person's message and hand the turn to the assistant."""
    user_message = {"role": "user", "content": message[:2000]}
    st.session_state["chat"].append(user_message)
    _remember(user["email"], user_message)
    st.session_state["chat_pending"] = True
    st.rerun()


def page_dataset_chat(user: dict) -> None:
    plan = plan_for(user["plan"])
    ui.hero("Dataset Chat", "Learn naturally — then let me build the dataset or notebook")

    if core.at_limit(user, "datasets"):
        _limit_warning(user, "datasets")
    if core.at_limit(user, "models"):
        _limit_warning(user, "models")

    if "chat" not in st.session_state:
        st.session_state["chat"] = _load_chat(user)
    st.session_state.setdefault("pending_dataset", None)
    st.session_state.setdefault("pending_notebook", None)
    st.session_state.setdefault("chat_pending", False)

    tools_col, status_col = st.columns([1, 1])
    with tools_col:
        if _memory_enabled() and st.button("🧹 Clear saved chat", use_container_width=True):
            _clear_chat_memory(user)
    with status_col:
        st.caption(_memory_status_text())

    pending = st.session_state["chat_pending"]
    st.markdown(
        ui.chat_transcript(st.session_state["chat"], user.get("name", ""), pending),
        unsafe_allow_html=True,
    )

    # Emitted after the transcript so the thinking bubble is painted first.
    if pending:
        _take_turn(user)
        return

    if st.session_state["pending_dataset"]:
        _render_generation_form(user, plan)
    if st.session_state["pending_notebook"]:
        _render_chat_notebook_form(user, plan)

    if st.session_state.get("last_rows"):
        with st.expander(f"⬇ Download — {st.session_state.get('last_name', 'last dataset')}"):
            st.dataframe(pd.DataFrame(st.session_state["last_rows"]),
                         use_container_width=True)
            _download_buttons(st.session_state.get("last_id", "dataset"),
                              st.session_state["last_rows"], key_prefix="last")

    if st.session_state.get("notebook_json"):
        _render_notebook_download()

    with st.form("chat_input", clear_on_submit=True):
        message_column, send_column = st.columns([6, 1])
        with message_column:
            message = st.text_input("Message", placeholder="Ask me anything…",
                                    label_visibility="collapsed")
        with send_column:
            send = st.form_submit_button("Send", use_container_width=True, type="primary")
    if send and message.strip():
        _send(user, message.strip())

    # Openers are only useful before the conversation has a direction.
    if len(st.session_state["chat"]) <= 1:
        st.markdown('<div class="small" style="margin-top:.4rem">Try one of these</div>',
                    unsafe_allow_html=True)
        left, right = st.columns(2)
        for index, prompt in enumerate(CONVERSATION_STARTERS):
            with left if index % 2 == 0 else right:
                if st.button(prompt, key=f"starter_{index}", use_container_width=True):
                    _send(user, prompt)


def _render_generation_form(user: dict, plan: dict) -> None:
    info = st.session_state["pending_dataset"]
    ui.divider()
    st.markdown("### ✦ Ready to generate")

    left, right = st.columns([2, 1])
    with left:
        with st.form("confirm_generation"):
            name = st.text_input("Dataset name", value=info["name"])
            description = st.text_area("Description", value=info["description"], height=70)
            columns_raw = st.text_input("Columns (comma-separated)",
                                        value=", ".join(info["columns"]))
            row_count = st.slider("Rows to generate", 1, plan["max_rows"],
                                  min(info["rows"], plan["max_rows"]))
            style = st.selectbox("Dataset style", [
                "Q&A pairs", "tabular", "instruction-response",
                "classification", "sentiment analysis", "custom",
            ])
            tags_raw = st.text_input("Tags", value=info["tags"], placeholder="nlp, english")
            public = st.checkbox("Share publicly on the Dataset Hub",
                                 disabled=not plan["share"], help="Pro and Elite only")
            generate_column, cancel_column = st.columns(2)
            with generate_column:
                generate = st.form_submit_button("✦ Generate dataset",
                                                 use_container_width=True,
                                                 type="primary")
            with cancel_column:
                cancel = st.form_submit_button("Cancel", use_container_width=True)

        if cancel:
            st.session_state["pending_dataset"] = None
            st.rerun()

        if generate:
            _generate_dataset(user, name, description, columns_raw, row_count,
                              style, tags_raw, public, info["topic"])

    with right:
        estimate = core.row_cost(info["rows"])
        st.markdown(
            '<div class="card">'
            '<div class="stat-lbl">Cost estimate</div>'
            f'<div class="stat-num" style="margin:.3rem 0 .1rem">{estimate:,}'
            '<span style="font-size:.9rem;font-weight:400;color:var(--txt3)"> tokens</span></div>'
            f'<div style="font-size:.8rem;color:var(--txt2)">{info["rows"]} rows × '
            f'{TOKENS_PER_ROW} tokens<br>Your balance: <b>{user["tokens"]:,}</b></div></div>',
            unsafe_allow_html=True,
        )


def _render_chat_notebook_form(user: dict, plan: dict) -> None:
    info = st.session_state["pending_notebook"]
    datasets = store.user_datasets(user["email"], with_rows=False)
    options = ["— none (zero-shot) —"] + [f"{d['name']} ({d['row_count']} rows)" for d in datasets]

    selected_option = options[0]
    for dataset, label in zip(datasets, options[1:]):
        if dataset["id"] == info.get("dataset_id"):
            selected_option = label
            break

    ui.divider()
    st.markdown("### ✦ Ready to prepare the notebook")
    left, right = st.columns([2, 1])

    with left:
        with st.form("chat_notebook_form"):
            name = st.text_input("Model name", value=info.get("name", "My Model"))
            description = st.text_area("Description", value=info.get("description", ""), height=70)
            base_model = st.text_input("Base model", value=info.get("base_model") or POPULAR_BASE_MODELS[0])
            target_repo = st.text_input(
                "Target model path (optional)",
                value=info.get("target_repo", ""),
                placeholder="your-name/my-model",
            )
            selection = st.selectbox(
                "Train on dataset",
                options,
                index=options.index(selected_option) if selected_option in options else 0,
            )

            with st.expander("⚙️ Training settings"):
                epochs = st.slider("Epochs", 1, 10, int(info.get("epochs") or 3), key="chat_epochs")
                learning_rate = st.select_slider(
                    "Learning rate", ["5e-5", "2e-4", "5e-4", "1e-3"],
                    value=str(info.get("learning_rate") or "2e-4"), key="chat_lr",
                )
                max_length = st.select_slider(
                    "Max sequence length", [128, 256, 512, 1024],
                    value=int(info.get("max_length") or 512), key="chat_max_length",
                )
                batch_size = st.select_slider(
                    "Batch size", [1, 2, 4, 8],
                    value=int(info.get("batch_size") or 4), key="chat_batch_size",
                )

            tags_raw = st.text_input("Tags", value=info.get("tags", ""), placeholder="nlp, tutorial")
            public = st.checkbox(
                "Share publicly on the Model Hub",
                value=bool(info.get("public")),
                disabled=not plan["share"],
                help="Pro and Elite only",
                key="chat_model_public",
            )
            create_col, cancel_col = st.columns(2)
            with create_col:
                generate = st.form_submit_button(
                    "✦ Generate notebook", use_container_width=True, type="primary"
                )
            with cancel_col:
                cancel = st.form_submit_button("Cancel", use_container_width=True)

        if cancel:
            st.session_state["pending_notebook"] = None
            st.rerun()

        if generate:
            _create_model(
                user, name, description, base_model, target_repo, selection, options,
                datasets, tags_raw, public, epochs, learning_rate, max_length,
                batch_size, from_chat=True,
            )

    with right:
        dataset_note = "Zero-shot" if selected_option == options[0] else selected_option
        st.markdown(
            '<div class="card">'
            '<div class="stat-lbl">Notebook plan</div>'
            f'<div style="font-weight:650;margin:.45rem 0;color:var(--txt)">{esc(dataset_note)}</div>'
            f'<div style="font-size:.82rem;color:var(--txt2)">Base model:<br><b>{esc(info.get("base_model") or POPULAR_BASE_MODELS[0])}</b></div>'
            '<div style="font-size:.8rem;color:var(--txt3);margin-top:.7rem">'
            'The generated file is a real `.ipynb` you can download and run in Colab.'
            '</div></div>',
            unsafe_allow_html=True,
        )



def _generate_dataset(user: dict, name: str, description: str, columns_raw: str,
                      row_count: int, style: str, tags_raw: str, public: bool,
                      topic: str) -> None:
    """Generate, charge and save — in that order, so failures never bill."""
    columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    cost = core.row_cost(row_count)

    if not columns:
        st.error("At least one column is required.")
        return
    if len(columns) > 12:
        st.error("Use 12 columns or fewer.")
        return
    if not core.rate_limit(user["email"], "generate"):
        st.error("Rate limit reached — 3 generations per minute.")
        return
    if user["tokens"] < cost:
        st.error(f"This needs {cost:,} tokens and you have {user['tokens']:,}.")
        return

    progress = st.progress(0.0, "Starting…")
    provider_token = _model_token(user)
    try:
        rows = inference.generate_rows(
            topic or name, columns, style, row_count,
            progress_cb=lambda done, total: progress.progress(
                done / total, f"Generated {done} of {total} rows…"),
            user_hf_token=provider_token,
        )
    except inference.ModelLoadingError as exc:
        st.warning(f"{exc} No tokens were used.")
        return
    except inference.InferenceError as exc:
        st.error(f"{exc} No tokens were used.")
        return
    finally:
        progress.empty()

    charged, balance = core.spend_tokens(user["email"], cost, "dataset_generation")
    if not charged:
        st.error("Your token balance changed while generating. Nothing was charged.")
        return

    try:
        with st.status("Saving…", expanded=False) as status:
            dataset_id = core.create_dataset(
                user["email"], name, description, rows, public, tags,
                provider_token=provider_token,
            )
            status.update(label="Dataset saved", state="complete")
    except (core.PlanLimitError, core.StorageUnavailableError, ValueError) as exc:
        core.refund_tokens(user["email"], cost, "refund:save_failed")
        st.error(f"{exc} Your {cost:,} tokens were refunded.")
        return

    st.session_state["pending_dataset"] = None
    st.session_state["last_rows"] = rows
    st.session_state["last_id"] = dataset_id
    st.session_state["last_name"] = name
    assistant_message = {
        "role": "bot",
        "content": (
            f"✅ Done — **{name}** with {len(rows)} rows is saved to your account.\n\n"
            f"That used {cost:,} tokens; you have {balance:,} left.\n\n"
            "Download it below, or find it in the Dataset Hub. If you want, I can also "
            "prepare a training `.ipynb` notebook for this dataset."
        ),
    }
    st.session_state["chat"].append(assistant_message)
    _remember(user["email"], assistant_message)
    st.rerun()


# ─────────────────────────────────────────────────────────────────────
# MY MODELS
# ─────────────────────────────────────────────────────────────────────
POPULAR_BASE_MODELS = [
    "Hwiiiiiiii/gemby.v1",
    "Hwiiiiiiii/gemby-plant",
    "Hwiiiiiiii/gemby-agent-3b",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "microsoft/phi-2",
    "google/flan-t5-base",
    "facebook/opt-1.3b",
    "EleutherAI/pythia-1b",
]


def page_my_models(user: dict) -> None:
    plan = plan_for(user["plan"])
    ui.hero("🤖 My Models", "Fine-tune on your data · Host · Share · Run inference")

    tab_new, tab_list = st.tabs(["Create & fine-tune", "My models"])
    with tab_new:
        if core.at_limit(user, "models"):
            _limit_warning(user, "models")
        else:
            _render_model_form(user, plan)
    with tab_list:
        _render_model_list(user, plan)


def _render_model_form(user: dict, plan: dict) -> None:
    left, right = st.columns([3, 2], gap="large")

    with right:
        st.markdown(
            '<div class="card"><div style="font-weight:600;margin-bottom:.6rem">How it works</div>'
            '<div style="font-size:.83rem;color:var(--txt2);line-height:1.85">'
            "1. Pick a base model from the registry<br>"
            "2. Choose one of your datasets to train on<br>"
            "3. Download the generated <b>Colab notebook</b><br>"
            "4. Open it in Google Colab → <b>T4 GPU (free)</b><br>"
            "5. Run all cells → weights push to your target path<br>"
            "6. Your model becomes available for inference"
            "</div></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="card"><div class="stat-lbl" style="margin-bottom:.5rem">'
            "Popular base models</div><div>"
            + "".join(ui.tag(m, accent=i == 0) for i, m in enumerate(POPULAR_BASE_MODELS))
            + "</div></div>",
            unsafe_allow_html=True,
        )

    with left:
        datasets = store.user_datasets(user["email"], with_rows=False)
        options = ["— none (zero-shot) —"] + [f"{d['name']} ({d['row_count']} rows)"
                                              for d in datasets]

        with st.form("new_model_form"):
            name = st.text_input("Model name", placeholder="My Coffee Classifier")
            description = st.text_area("Description", height=70)
            base_model = st.text_input("Base model", value=POPULAR_BASE_MODELS[0])
            target_repo = st.text_input(
                "Target model path (optional)",
                placeholder="your-name/my-coffee-classifier",
                help=(
                    "Leave blank to let the platform provision storage automatically. "
                    "Fill this in if you want the notebook to publish to your own namespace."
                ),
            )
            st.caption("Managed storage is automatic when the deployment or your saved "
                       "registry token allows it.")
            selection = st.selectbox("Train on dataset", options)

            with st.expander("⚙️ Training settings"):
                epochs = st.slider("Epochs", 1, 10, 3)
                learning_rate = st.select_slider(
                    "Learning rate", ["5e-5", "2e-4", "5e-4", "1e-3"], value="2e-4")
                max_length = st.select_slider(
                    "Max sequence length", [128, 256, 512, 1024], value=512)
                batch_size = st.select_slider("Batch size", [1, 2, 4, 8], value=4)

            tags_raw = st.text_input("Tags", placeholder="nlp, classifier, english")
            public = st.checkbox("Share publicly on the Model Hub",
                                 disabled=not plan["share"], help="Pro and Elite only")
            submitted = st.form_submit_button(
                "✦ Create model + generate Colab notebook", use_container_width=True,
                type="primary")

        if submitted:
            _create_model(user, name, description, base_model, target_repo, selection, options,
                          datasets, tags_raw, public, epochs, learning_rate,
                          max_length, batch_size)

    if st.session_state.get("notebook_json"):
        _render_notebook_download()


def _create_model(user: dict, name: str, description: str, base_model: str,
                  target_repo: str, selection: str, options: list[str],
                  datasets: list[dict], tags_raw: str, public: bool, epochs: int,
                  learning_rate: str, max_length: int, batch_size: int,
                  *, from_chat: bool = False) -> None:
    if not name.strip():
        st.error("Model name is required.")
        return
    if not base_model.strip():
        st.error("Base model is required.")
        return

    rows: list[dict] = []
    if selection != options[0]:
        index = options.index(selection) - 1
        full = store.get_dataset(datasets[index]["id"])
        rows = full["rows"] if full else []

    provider_token = _model_token(user)
    requested_repo = (target_repo or "").strip()
    output_repo = requested_repo or None
    if not output_repo:
        with st.spinner("Preparing managed model storage…"):
            output_repo = core.provision_model_repo(user["email"], name, provider_token)

    if not output_repo:
        output_repo = core.suggested_model_repo(user["email"], name, provider_token)
        st.info(
            "Managed storage could not be provisioned automatically, so the notebook will "
            f"target `{output_repo}`. Update it to a namespace you control before running "
            "if needed."
        )

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    try:
        core.create_model(user["email"], name, description, base_model,
                          output_repo, public, tags)
    except (core.PlanLimitError, ValueError) as exc:
        st.error(str(exc))
        return

    st.session_state["notebook_json"] = inference.generate_colab_notebook(
        name, base_model, output_repo, rows, epochs=epochs, lr=learning_rate,
        max_length=max_length, batch_size=batch_size,
    )
    st.session_state["notebook_name"] = name
    if from_chat:
        st.session_state["pending_notebook"] = None
        assistant_message = {
            "role": "bot",
            "content": (
                f"✅ Your training notebook for **{name}** is ready.\n\n"
                f"Base model: `{base_model}`\n"
                f"Target path: `{output_repo}`\n\n"
                "Download the `.ipynb` below and open it in Colab whenever you're ready."
            ),
        }
        st.session_state["chat"].append(assistant_message)
        _remember(user["email"], assistant_message)
    st.success(f"✅ **{name}** created. Download your Colab notebook below.")
    st.rerun()


def _render_notebook_download() -> None:
    ui.divider()
    st.markdown("### 🧪 Your Colab notebook is ready")
    st.markdown(
        '<div class="note"><b>Steps:</b> download the notebook → open '
        '<a href="https://colab.research.google.com" target="_blank" rel="noopener">'
        "colab.research.google.com</a> → Upload → Runtime → Change runtime type → "
        "<b>T4 GPU</b> → Run all. The notebook asks for your repository access token "
        "when it runs; it is never written into the file.</div>",
        unsafe_allow_html=True,
    )
    filename = (st.session_state.get("notebook_name") or "model").replace(" ", "_")
    left, right = st.columns(2)
    with left:
        st.download_button("⬇ Download notebook (.ipynb)",
                           st.session_state["notebook_json"],
                           file_name=f"train_{filename}.ipynb",
                           mime="application/json", use_container_width=True,
                           type="primary")
    with right:
        st.link_button("🔗 Open Google Colab", "https://colab.research.google.com",
                       use_container_width=True)


def _render_model_list(user: dict, plan: dict) -> None:
    models = store.user_models(user["email"])
    st.markdown(
        f'<div class="small">{len(models)} / {display_limit(plan["max_models"])} '
        "model slots used</div>",
        unsafe_allow_html=True,
    )
    if not models:
        ui.note("No models yet. Create one in the first tab.")
        return

    for model in models:
        ui.hub_card(
            model["name"], desc=model["description"],
            stats=f"Base: {model['base_model']} · platform-managed weights · "
                  f"{model['created'][:10]}",
            is_public=model["public"], tags=model["tags"],
        )
        with st.expander(f"▶ Inference & options — {model['name']}"):
            left, right = st.columns([3, 2])
            with left:
                prompt = st.text_area("Try a prompt", height=90, key=f"prompt_{model['id']}")
                if st.button("▶ Run inference", key=f"run_{model['id']}"):
                    _run_inference(
                        model["hf_repo"] or model["base_model"], user,
                        f"out_{model['id']}", prompt,
                    )
            with right:
                public = st.checkbox("Public", value=model["public"],
                                     key=f"public_{model['id']}",
                                     disabled=not plan["share"])
                if st.button("Save visibility", key=f"save_{model['id']}",
                             use_container_width=True):
                    ok, message = core.set_model_visibility(model["id"], user["email"], public)
                    st.toast(message, icon="✅" if ok else "⚠️")
                    st.rerun()
                if st.button("🗑 Delete model", key=f"delete_{model['id']}",
                             type="secondary", use_container_width=True):
                    ok, message = core.delete_model(model["id"], user["email"])
                    st.toast(message, icon="✅" if ok else "⚠️")
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────
# SPACE / APP
# ─────────────────────────────────────────────────────────────────────
def page_space_app(user: dict) -> None:
    gpu_target = inference.modal_gpu_for_plan(user.get("plan", "starter"))
    ui.hero(
        "🛰️ Apps",
        "Build app starters, export GitHub-ready bundles, and connect heavy workloads to Modal GPUs",
        badge="AURA",
    )
    ui.note(
        f"Current plan GPU target: {gpu_target}. Starter bundles target T4, Pro targets A10G, and Elite targets A100.",
        kind="ok",
    )

    datasets = store.user_datasets(user["email"], with_rows=False)
    models = store.user_models(user["email"])
    runtime_ids = list(inference.SPACE_APP_RUNTIMES)
    runtime_labels = {
        key: inference.SPACE_APP_RUNTIMES[key]["label"] for key in runtime_ids
    }
    dataset_options = ["— no sample dataset —"] + [
        f"{d['name']} ({d['row_count']} rows)" for d in datasets
    ]
    model_options = ["— no model reference —"] + [
        f"{m['name']} · {m['base_model']}" for m in models
    ]

    with st.form("space_app_form"):
        left, right = st.columns([2, 1], gap="large")
        with left:
            app_name = st.text_input("App name", value="My App")
            description = st.text_area(
                "Description",
                height=110,
                placeholder="Describe the app you want to build inside Asian Inference…",
            )
            runtime = st.selectbox(
                "Runtime template",
                runtime_ids,
                format_func=lambda value: runtime_labels[value],
            )
            github_repo = st.text_input(
                "GitHub repo (optional)",
                placeholder="your-name/your-app-repo",
            )
        with right:
            st.markdown("### Build profile")
            st.caption("License: Apache-2.0")
            dataset_label = st.selectbox("Sample dataset", dataset_options)
            model_label = st.selectbox("Model reference", model_options)
            st.text_input("Modal GPU target", value=gpu_target, disabled=True)
        submitted = st.form_submit_button(
            "🚀 Generate app bundle",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        sample_rows: list[dict] = []
        if dataset_label != dataset_options[0]:
            dataset_index = dataset_options.index(dataset_label) - 1
            full_dataset = store.get_dataset(datasets[dataset_index]["id"])
            sample_rows = (full_dataset or {}).get("rows") or []
        model_ref = "" if model_label == model_options[0] else model_label

        files = inference.build_space_app_files(
            app_name,
            description,
            runtime=runtime,
            sample_rows=sample_rows,
            model_label=model_ref,
            plan_id=user.get("plan", "starter"),
            github_repo=github_repo,
        )
        st.session_state["space_app_files"] = files
        st.session_state["space_app_zip"] = _build_zip_archive(files)
        st.session_state["space_app_name"] = (app_name or "my_app").strip() or "my_app"
        first_path = next(iter(files))
        st.session_state["space_app_root"] = "/".join(first_path.split("/")[:2])
        st.success("App bundle ready.")

    files = st.session_state.get("space_app_files") or {}
    if not files:
        return

    bundle_name = st.session_state.get("space_app_name", "my_app").replace(" ", "_").lower()
    bundle_root = st.session_state.get("space_app_root", "apps/app")
    zip_bytes = st.session_state.get("space_app_zip")

    if zip_bytes:
        st.download_button(
            "⬇ Download app bundle (.zip)",
            zip_bytes,
            file_name=f"{bundle_name}_apps_bundle.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

    tabs = st.tabs([
        "README", "App", "Modal worker", "GitHub Action", "Requirements",
        "GitHub setup", "License", "Sample data",
    ])
    with tabs[0]:
        st.code(files.get(f"{bundle_root}/README.md", ""), language="markdown")
    with tabs[1]:
        st.code(files.get(f"{bundle_root}/app.py", ""), language="python")
    with tabs[2]:
        st.code(files.get(f"{bundle_root}/modal_app.py", ""), language="python")
    with tabs[3]:
        st.code(files.get(f"{bundle_root}/.github/workflows/modal-deploy.yml", ""), language="yaml")
    with tabs[4]:
        st.code(files.get(f"{bundle_root}/requirements.txt", ""), language="text")
    with tabs[5]:
        st.code(files.get(f"{bundle_root}/github_setup.md", ""), language="markdown")
    with tabs[6]:
        st.code(files.get(f"{bundle_root}/LICENSE", ""), language="text")
    with tabs[7]:
        st.code(files.get(f"{bundle_root}/data/sample_rows.json", "[]"), language="json")


# ─────────────────────────────────────────────────────────────────────
# DATASET HUB
# ─────────────────────────────────────────────────────────────────────
def _matches(query: str, *fields: object) -> bool:
    if not query:
        return True
    needle = query.lower()
    return any(needle in str(field).lower() for field in fields)


def page_dataset_hub(user: dict) -> None:
    plan = plan_for(user["plan"])
    ui.hero("📦 Dataset Hub", "Browse · Download · Share community datasets")

    tab_public, tab_mine = st.tabs(["Community", "My datasets"])

    with tab_public:
        query = st.text_input("Search", placeholder="name, tag or description…",
                              key="hub_search", label_visibility="collapsed")
        datasets = [
            d for d in store.public_datasets(with_rows=False)
            if _matches(query, d["name"], d["description"], " ".join(d["tags"]))
        ]
        st.markdown(
            f'<div class="small">{len(datasets)} public '
            f'dataset{"" if len(datasets) == 1 else "s"}</div>',
            unsafe_allow_html=True,
        )
        if not datasets:
            ui.note("No public datasets yet — be the first to share one.")
        for dataset in datasets:
            ui.hub_card(
                dataset["name"], owner=dataset["owner"], desc=dataset["description"],
                tags=dataset["tags"], is_public=True,
                stats=f"{dataset['row_count']:,} rows · {dataset['created'][:10]} · "
                      f"⬇ {dataset['downloads']}",
            )
            with st.expander("Preview & download"):
                full = store.get_dataset(dataset["id"])
                rows = full["rows"] if full else []
                if rows:
                    st.dataframe(pd.DataFrame(rows).head(10), use_container_width=True)
                _download_buttons(dataset["id"], rows, key_prefix=f"pub_{dataset['id']}")

    with tab_mine:
        datasets = store.user_datasets(user["email"], with_rows=False)
        st.markdown(
            f'<div class="small">{len(datasets)} / '
            f'{display_limit(plan["max_datasets"])} dataset slots used</div>',
            unsafe_allow_html=True,
        )
        if not datasets:
            ui.note("No datasets yet. Go to Dataset Chat to build one.")
        for dataset in datasets:
            ui.hub_card(
                dataset["name"], desc=dataset["description"], tags=dataset["tags"],
                is_public=dataset["public"],
                stats=f"{dataset['row_count']:,} rows · {dataset['created'][:10]} · "
                      f"stored: {dataset['storage_backend']}",
            )
            with st.expander(f"Options — {dataset['name']}"):
                full = store.get_dataset(dataset["id"])
                rows = full["rows"] if full else []
                if rows:
                    st.dataframe(pd.DataFrame(rows).head(5), use_container_width=True)
                _download_buttons(dataset["id"], rows, key_prefix=f"own_{dataset['id']}")
                left, right = st.columns(2)
                with left:
                    public = st.checkbox("Share publicly", value=dataset["public"],
                                         key=f"ds_public_{dataset['id']}",
                                         disabled=not plan["share"],
                                         help="Pro and Elite only")
                    if st.button("Save", key=f"ds_save_{dataset['id']}",
                                 use_container_width=True):
                        ok, message = core.set_dataset_visibility(
                            dataset["id"], user["email"], public)
                        st.toast(message, icon="✅" if ok else "⚠️")
                        st.rerun()
                with right:
                    if st.button("🗑 Delete", key=f"ds_delete_{dataset['id']}",
                                 type="secondary", use_container_width=True):
                        ok, message = core.delete_dataset(dataset["id"], user["email"])
                        st.toast(message, icon="✅" if ok else "⚠️")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────
# MODEL HUB
# ─────────────────────────────────────────────────────────────────────
def page_model_hub(user: dict) -> None:
    ui.hero("🌐 Model Hub", "Browse · Try live inference · Discover community models")

    query = st.text_input("Search", placeholder="name, base model or tag…",
                          key="model_search", label_visibility="collapsed")
    models = [
        m for m in store.public_models()
        if _matches(query, m["name"], m["base_model"], m["description"], " ".join(m["tags"]))
    ]
    st.markdown(
        f'<div class="small">{len(models)} public '
        f'model{"" if len(models) == 1 else "s"}</div>',
        unsafe_allow_html=True,
    )
    if not models:
        ui.note("No public models yet.")

    for model in models:
        ui.hub_card(
            model["name"], owner=model["owner"], desc=model["description"],
            tags=model["tags"], is_public=True,
            stats=f"Base: {model['base_model']} · {model['created'][:10]}",
        )
        with st.expander(f"▶ Try inference — {model['name']}"):
            prompt = st.text_area("Prompt", height=80, key=f"hub_prompt_{model['id']}")
            if st.button("Run →", key=f"hub_run_{model['id']}"):
                _run_inference(
                    model["hf_repo"] or model["base_model"], user,
                    f"hub_out_{model['id']}", prompt,
                )


# ─────────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────────
def page_api_keys(user: dict) -> None:
    plan = plan_for(user["plan"])
    ui.hero("🔑 API Keys", "Your asi- key · use it from Colab, scripts or other apps")

    st.markdown(f"### Your {APP_NAME} API key")
    ui.note("This key authenticates as you. Anyone holding it can use your account, "
            "so keep it secret and rotate it if it leaks.")

    platform_key = user.get("platform_api_key")
    if not platform_key:
        if st.button("✦ Generate my asi- key", type="primary"):
            core.rotate_platform_key(user["email"])
            st.rerun()
    else:
        revealed = st.session_state.get("reveal_key", False)
        display = platform_key if revealed else core.mask_key(platform_key)
        st.markdown(f'<div class="key-box">🔑 {esc(display)}</div>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🙈 Hide" if revealed else "👁 Reveal", use_container_width=True):
                st.session_state["reveal_key"] = not revealed
                st.rerun()
        with col2:
            if st.button("🔄 Regenerate", type="secondary", use_container_width=True):
                core.rotate_platform_key(user["email"])
                st.session_state["reveal_key"] = False
                st.toast("A new key was generated. The old one no longer works.", icon="✅")
                st.rerun()
        with col3:
            st.download_button("⬇ Save as .txt", platform_key,
                               "asian_inference_key.txt", "text/plain",
                               use_container_width=True)

    ui.divider()
    st.markdown("### Use it from Google Colab")
    # Only inline the real key once the user has chosen to reveal it — otherwise
    # masking the key box above would be pointless with the key in plain sight.
    snippet_key = platform_key if st.session_state.get("reveal_key") else None
    st.code(_colab_snippet(snippet_key), language="python")
    if platform_key and not snippet_key:
        st.caption("Reveal your key above to have it filled into this template.")

    ui.divider()
    st.markdown("### Stored third-party keys")
    used = store.count_user_api_keys(user["email"])
    st.markdown(
        f'<div class="note"><b>{used}/{display_limit(plan["api_keys"])}</b> key slots '
        f'used on your {esc(plan["name"])} plan.</div>',
        unsafe_allow_html=True,
    )

    with st.form("add_api_key", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            label = st.text_input("Label", placeholder="My model registry token")
        with col2:
            value = st.text_input("Key value", type="password", placeholder="paste your access token")
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            add = st.form_submit_button("Add", use_container_width=True)
    if add:
        ok, message = core.add_api_key(user, label, value)
        (st.success if ok else st.error)(message)
        if ok:
            st.rerun()

    for entry in store.user_api_keys(user["email"]):
        ui.hub_card(
            entry["label"], is_public=False,
            stats=f"{core.mask_key(entry['key_value'])} · added {entry['created_at'][:10]}",
        )
        if st.button(f"Remove '{entry['label']}'", key=f"remove_key_{entry['label']}",
                     type="secondary"):
            core.remove_api_key(user, entry["label"])
            st.rerun()


def _colab_snippet(key: str | None) -> str:
    from config import PUBLIC_URL

    return f'''# ⚡ {APP_NAME} — Colab template
!pip install -q requests pandas

import requests
import pandas as pd

API_KEY  = "{key or 'asi-your-key-here'}"
BASE_URL = "{PUBLIC_URL}"


def generate_dataset(topic, rows, columns, style="Q&A pairs",
                     name="My Dataset", public=False):
    response = requests.post(
        f"{{BASE_URL}}/api/generate",
        headers={{"Authorization": f"Bearer {{API_KEY}}"}},
        json={{
            "topic": topic, "rows": rows, "columns": columns,
            "style": style, "name": name, "public": public,
        }},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


result = generate_dataset(
    topic="customer reviews for a coffee shop",
    rows=20,
    columns=["text", "rating", "sentiment"],
    style="sentiment analysis",
    name="Coffee Reviews",
)
display(pd.DataFrame(result.get("rows", [])))
'''


# ─────────────────────────────────────────────────────────────────────
# UPGRADE
# ─────────────────────────────────────────────────────────────────────
def page_upgrade(user: dict) -> None:
    ui.hero("⚡ Upgrade", "More tokens · more models · more datasets")
    current = user["plan"]

    columns = st.columns(3, gap="medium")
    for column, (plan_id, plan) in zip(columns, PLANS.items()):
        is_current = plan_id == current
        with column:
            st.markdown(
                ui.plan_card_html(plan, current=is_current, popular=plan_id == "pro"),
                unsafe_allow_html=True,
            )
            if is_current:
                st.button("✓ Current plan", key=f"plan_current_{plan_id}",
                          disabled=True, use_container_width=True)
            elif plan["price"] == 0:
                if st.button("Switch to Free", key=f"plan_free_{plan_id}",
                             type="secondary", use_container_width=True):
                    ok, message = billing.cancel_subscription(user["email"])
                    if not ok:
                        core.set_plan(user["email"], "starter")
                        message = "Your plan is now Starter."
                    st.toast(message, icon="✅")
                    st.rerun()
            else:
                url = billing.checkout_url(user["email"], plan_id)
                if url:
                    st.link_button(f"Upgrade to {plan['name']} →", url=url,
                                   use_container_width=True, type="primary")
                else:
                    st.button(f"Upgrade to {plan['name']}", key=f"plan_na_{plan_id}",
                              disabled=True, use_container_width=True,
                              help="Payments are not configured on this deployment.")

    ui.divider()
    st.markdown("### Full comparison")
    comparison = pd.DataFrame({
        "Feature": ["Tokens/month", "Max rows per dataset", "Datasets", "Models",
                    "Stored API keys", "Public sharing", "Priority queue", "Price"],
        **{
            f'{plan["badge"]} {plan["name"]}': [
                f'{plan["monthly_tokens"]:,}',
                f'{plan["max_rows"]:,}',
                display_limit(plan["max_datasets"]),
                display_limit(plan["max_models"]),
                display_limit(plan["api_keys"]),
                "✓" if plan["share"] else "✗",
                "✓" if plan["priority_queue"] else "✗",
                "Free" if plan["price"] == 0 else f'${plan["price"]}/mo',
            ]
            for plan in PLANS.values()
        },
    })
    st.dataframe(comparison.set_index("Feature"), use_container_width=True)

    if not (billing.stripe_available() or billing.traakteer_available()):
        ui.note("Payments are not configured on this deployment, so paid plans cannot "
                "be purchased yet. An administrator can enable Stripe or Traakteer.",
                kind="warn")


# ─────────────────────────────────────────────────────────────────────
# ACCOUNT
# ─────────────────────────────────────────────────────────────────────
def page_account(user: dict) -> None:
    plan = plan_for(user["plan"])
    ui.hero("⚙️ Account", "Profile · password · billing history")

    st.markdown(
        '<div class="card">'
        f'<div><b>{esc(user["name"] or "—")}</b></div>'
        f'<div class="small">{esc(user["email"])}</div>'
        f'<div style="margin-top:.6rem">{plan["badge"]} {esc(plan["name"])} · '
        f'🪙 {user["tokens"]:,} tokens · member since {user["created"][:10]}</div></div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("### Change password")
        with st.form("change_password", clear_on_submit=True):
            current = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Update password", use_container_width=True,
                                              type="primary")
        if submitted:
            if new != confirm:
                st.error("The new passwords don't match.")
            else:
                ok, message = core.change_password(user["email"], current, new)
                (st.success if ok else st.error)(message)

        st.markdown("### Session security")
        st.caption(f"Persistent sign-in lasts up to {AUTH_SESSION_DAYS} days on a browser that keeps cookies.")
        if st.button("🚪 Sign out from all devices", type="secondary", use_container_width=True):
            count = core.revoke_all_persistent_sessions(user["email"])
            _sign_out(f"Signed out from all devices. Closed {count} saved session(s).")
            st.rerun()

    with right:
        st.markdown("### Subscription")
        status = billing.subscription_status(user["email"])
        if status:
            st.markdown(
                f'<div class="card"><div class="small">Current plan</div>'
                f'<div style="font-weight:600;margin:.2rem 0 .6rem">'
                f'{esc(status["plan_name"])}</div>'
                f'<div class="small">Subscription: '
                f'{esc(status["stripe_subscription_id"] or "none on file")}</div></div>',
                unsafe_allow_html=True,
            )
        if user["plan"] != "starter":
            if st.button("Cancel subscription", type="secondary",
                         use_container_width=True):
                ok, message = billing.cancel_subscription(user["email"])
                st.toast(message, icon="✅" if ok else "⚠️")
                st.rerun()

    ui.divider()
    st.markdown("### Token history")
    history = store.token_history(user["email"], limit=50)
    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
    else:
        ui.note("No token activity yet.")

    events = billing.billing_history(user["email"], limit=25)
    if events:
        st.markdown("### Billing history")
        st.dataframe(
            pd.DataFrame([{"date": e["created_at"][:19], "event": e["event_type"]}
                          for e in events]),
            use_container_width=True, hide_index=True,
        )


# ─────────────────────────────────────────────────────────────────────
# SUPPORT
# ─────────────────────────────────────────────────────────────────────
FAQS = [
    ("How do tokens work?",
     f"Each generated dataset row costs {TOKENS_PER_ROW} tokens. Tokens are only "
     "charged after rows are generated successfully, and are refunded if saving "
     "fails. Allowances reset monthly and do not roll over."),
    ("How do I use my asi- key in Colab?",
     "Go to API Keys, generate your key, then copy the Colab template shown on that "
     "page and paste your key into it."),
    ("Why did generation fail?",
     "Usually the model is cold-starting on the free tier. Wait 20–30 seconds and try "
     "again — no tokens are charged for a failed generation."),
    ("How do I train my own model?",
     "My Models → Create & fine-tune. Fill in the form, download the Colab notebook, "
     "open it in Google Colab, pick the free T4 GPU and run all cells. The notebook "
     "asks for your repository access token at runtime."),
    ("Can other people see my datasets and models?",
     "Only if you mark them public. Starter is private-only; Pro and Elite can publish "
     "to the community Hub."),
    ("Where is my data stored?",
     "In the platform database. When offsite storage is configured, dataset rows are "
     "also mirrored to a private managed registry owned by the platform."),
]


def page_support(user: dict) -> None:
    ui.hero("💬 Support", "We reply within 24 hours on business days")

    tab_new, tab_mine, tab_faq = st.tabs(["Send a ticket", "My tickets", "FAQ"])

    with tab_new:
        with st.form("support_form", clear_on_submit=True):
            subject = st.selectbox("Topic", [
                "Billing or payment", "Tokens or plan issue",
                "Dataset generation error", "Model training / Colab issue",
                "API key issue", "Account access", "Feature request", "Other",
            ])
            message = st.text_area("Message", height=150,
                                   placeholder="Describe your issue in detail…")
            submitted = st.form_submit_button("Send message →", use_container_width=True,
                                              type="primary")
        if submitted:
            ok, result = core.submit_ticket(user, subject, message)
            if ok:
                st.success(f"✅ Ticket `{result}` submitted. We'll reply by email.")
            else:
                st.error(result)

    with tab_mine:
        tickets = store.user_tickets(user["email"])
        if not tickets:
            ui.note("You haven't opened any tickets yet.")
        for ticket in tickets:
            icon = "✅" if ticket["status"] == "closed" else "🟡"
            with st.expander(f"{icon} [{ticket['id']}] {ticket['subject']} · "
                             f"{ticket['created_at'][:10]}"):
                st.write(ticket["message"])
                if ticket["admin_reply"]:
                    st.info(f"Reply: {ticket['admin_reply']}")

    with tab_faq:
        for question, answer in FAQS:
            with st.expander(question):
                st.write(answer)


# ─────────────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────────────
def page_admin(admin: dict) -> None:
    st.markdown('<div class="admin-bar">👑 Admin Panel — full platform control</div>',
                unsafe_allow_html=True)

    if USING_DEFAULT_SECRET:
        ui.note("This deployment is using the default SECRET_KEY. Set a unique "
                "SECRET_KEY in Streamlit secrets.", kind="warn")
    connected, storage_message = core.storage_status()
    ui.note(storage_message, kind="ok" if connected else "warn")
    memory_ok, memory_message = supabase_memory.memory_diagnostic()
    ui.note(memory_message, kind="ok" if memory_ok else "warn")
    backend_ok, backend_message = supabase_backend.health_diagnostic()
    ui.note(backend_message, kind="ok" if backend_ok else "warn")

    users = store.list_users()
    datasets = store.all_datasets()
    models = store.all_models()

    tiles = [
        (len(users), "👤 Users"),
        (len(datasets), "📦 Datasets"),
        (len(models), "🤖 Models"),
        (store.count_open_tickets(), "🎫 Open tickets"),
        (sum(1 for u in users if u["flagged"]), "🚩 Flagged"),
    ]
    for column, (value, label) in zip(st.columns(5), tiles):
        column.markdown(ui.stat(value, label), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    tab_users, tab_datasets, tab_models, tab_tickets, tab_tokens, tab_diagnostics, tab_announcements = st.tabs(
        ["👤 Users", "📦 Datasets", "🤖 Models", "🎫 Tickets", "🪙 Tokens", "🧪 Diagnostics", "📣 Announcements"])

    with tab_users:
        query = st.text_input("Filter by email", key="admin_user_filter")
        shown = [u for u in users if not query or query.lower() in u["email"]]
        for user in shown:
            flag = " 🚩" if user["flagged"] else ""
            plan = plan_for(user["plan"])
            with st.expander(f"{user['email']} · {plan['badge']} {plan['name']} · "
                             f"🪙{user['tokens']:,}{flag}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    plan_ids = list(PLANS)
                    new_plan = st.selectbox(
                        "Plan", plan_ids, index=plan_ids.index(user["plan"])
                        if user["plan"] in plan_ids else 0,
                        key=f"admin_plan_{user['email']}")
                    if st.button("Apply plan", key=f"admin_apply_{user['email']}",
                                 use_container_width=True):
                        core.set_plan(user["email"], new_plan)
                        st.rerun()
                with col2:
                    if user["flagged"]:
                        if st.button("✅ Unflag", key=f"admin_unflag_{user['email']}",
                                     use_container_width=True):
                            store.update_user(user["email"], flagged=False, flag_reason="")
                            st.rerun()
                    else:
                        reason = st.text_input("Flag reason",
                                               key=f"admin_reason_{user['email']}")
                        if st.button("🚩 Flag & suspend",
                                     key=f"admin_flag_{user['email']}",
                                     use_container_width=True):
                            store.update_user(user["email"], flagged=True,
                                              flag_reason=reason or "Admin action")
                            st.rerun()
                with col3:
                    if user["email"] == admin["email"]:
                        st.caption("You cannot delete your own admin account.")
                    elif st.button("🗑 Delete account",
                                   key=f"admin_delete_{user['email']}",
                                   type="secondary", use_container_width=True):
                        store.delete_user(user["email"])
                        st.rerun()

                history = store.token_history(user["email"], limit=25)
                if history:
                    st.dataframe(pd.DataFrame(history), use_container_width=True,
                                 hide_index=True)

    with tab_datasets:
        for dataset in datasets:
            visibility = "🌐" if dataset["public"] else "🔒"
            with st.expander(f"{visibility} {dataset['name']} · {dataset['owner']} · "
                             f"{dataset['row_count']} rows"):
                public = st.checkbox("Public", value=dataset["public"],
                                     key=f"admin_ds_public_{dataset['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Save", key=f"admin_ds_save_{dataset['id']}",
                                 use_container_width=True):
                        core.set_dataset_visibility(dataset["id"], admin["email"], public)
                        st.rerun()
                with col2:
                    if st.button("🗑 Delete", key=f"admin_ds_delete_{dataset['id']}",
                                 type="secondary", use_container_width=True):
                        core.delete_dataset(dataset["id"], admin["email"])
                        st.rerun()

    with tab_models:
        for model in models:
            visibility = "🌐" if model["public"] else "🔒"
            with st.expander(f"{visibility} {model['name']} · {model['owner']} · "
                             f"{model['base_model']}"):
                public = st.checkbox("Public", value=model["public"],
                                     key=f"admin_md_public_{model['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Save", key=f"admin_md_save_{model['id']}",
                                 use_container_width=True):
                        core.set_model_visibility(model["id"], admin["email"], public)
                        st.rerun()
                with col2:
                    if st.button("🗑 Delete", key=f"admin_md_delete_{model['id']}",
                                 type="secondary", use_container_width=True):
                        core.delete_model(model["id"], admin["email"])
                        st.rerun()

    with tab_tickets:
        tickets = store.list_tickets()
        if not tickets:
            st.info("No tickets yet.")
        for ticket in tickets:
            icon = "✅" if ticket["status"] == "closed" else "🟡"
            with st.expander(f"{icon} [{ticket['id']}] {ticket['subject']} · "
                             f"{ticket['user_email']} · {ticket['created_at'][:10]}"):
                st.write(ticket["message"])
                if ticket["admin_reply"]:
                    st.info(f"Reply sent: {ticket['admin_reply']}")
                elif ticket["status"] == "open":
                    reply = st.text_area("Reply", key=f"admin_reply_{ticket['id']}")
                    if st.button("Close ticket", key=f"admin_close_{ticket['id']}"):
                        store.close_ticket(ticket["id"], reply)
                        st.rerun()

    with tab_tokens:
        ui.note("Every grant is logged. More than "
                f"{core.MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG} manual grants in an hour "
                "flags the account automatically.", kind="warn")
        with st.form("grant_tokens"):
            target = st.selectbox("User", [u["email"] for u in users])
            amount = st.number_input("Tokens to grant", 0, core.MAX_MANUAL_GRANT, 500)
            reason = st.text_input("Reason")
            if st.form_submit_button("Grant tokens", use_container_width=True,
                                     type="primary"):
                balance, flagged = core.grant_tokens(target, int(amount), reason)
                st.success(f"✅ Granted {amount:,} tokens to {target} "
                           f"(new balance {balance:,}).")
                if flagged:
                    st.warning("That account was flagged for unusual grant activity.")

        ui.divider()
        if st.button("🔄 Reset all accounts to their plan allowance", type="secondary"):
            count = core.reset_monthly_tokens()
            st.success(f"Reset token allowances for {count} account(s).")

    with tab_diagnostics:
        cards, rows = _diagnostic_snapshot(admin)
        st.markdown(ui.diagnostic_grid(cards), unsafe_allow_html=True)
        st.markdown(ui.diagnostic_rows(rows), unsafe_allow_html=True)
        st.markdown("### Platform totals")
        st.dataframe(pd.DataFrame([
            {"metric": "Users", "value": len(users)},
            {"metric": "Datasets", "value": len(datasets)},
            {"metric": "Models", "value": len(models)},
            {"metric": "Open tickets", "value": store.count_open_tickets()},
            {"metric": "Flagged users", "value": sum(1 for u in users if u["flagged"])},
        ]), use_container_width=True, hide_index=True)

    with tab_announcements:
        current = store.get_announcement() or {}
        if current.get("active") and current.get("message"):
            preview = esc(current.get("message", "")).replace("\n", "<br>")
            st.markdown(
                '<div class="admin-bar">'
                f'📣 Live announcement · {esc(current.get("author") or "Admin")}<br>{preview}'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            ui.note("No live announcement right now.")

        with st.form("admin_announcement_form"):
            message = st.text_area(
                "Announcement message",
                value=current.get("message", ""),
                height=120,
                placeholder="Tell everyone about maintenance, a new feature, or an important update…",
            )
            active = st.checkbox("Show this announcement to all signed-in users",
                                 value=bool(current.get("active")))
            col1, col2 = st.columns(2)
            with col1:
                publish = st.form_submit_button("📣 Save announcement", use_container_width=True,
                                                type="primary")
            with col2:
                clear = st.form_submit_button("Clear announcement", use_container_width=True)

        if publish:
            trimmed = (message or "").strip()[:2000]
            if not trimmed:
                st.error("Write an announcement first.")
            else:
                store.set_announcement(trimmed, admin["email"], active=active)
                st.success("Announcement updated.")
                st.rerun()

        if clear:
            store.clear_announcement()
            st.success("Announcement cleared.")
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────
ROUTES = {
    "🏠  Home": page_home,
    "💬  Dataset Chat": page_dataset_chat,
    "🤖  My Models": page_my_models,
    "🛰️  Apps": page_space_app,
    "📦  Dataset Hub": page_dataset_hub,
    "🌐  Model Hub": page_model_hub,
    "🧪  Diagnostics": page_diagnostics,
    "🔑  API Keys": page_api_keys,
    "⚡  Upgrade": page_upgrade,
    "⚙️  Account": page_account,
    "💬  Support": page_support,
}


def main() -> None:
    _restore_sign_in()
    email = st.session_state.get(SESSION_EMAIL)
    if not email:
        page_auth()
        return

    user = core.get_user(email)
    if user is None:
        # The account disappeared (deleted by an admin) — drop the stale session.
        _sign_out()
        st.rerun()
        return

    _render_auth_cookie_updates()

    if user["flagged"] and not is_admin(user["email"]):
        st.markdown(
            f'<div class="warn">🚫 Account suspended: '
            f'{esc(user["flag_reason"] or "contact support")}<br>'
            "Reach out to support to appeal.</div>",
            unsafe_allow_html=True,
        )
        if st.button("Sign out"):
            _sign_out()
            st.rerun()
        return

    page = ui.sidebar_nav(user)
    if st.session_state.pop(ui.SIGN_OUT_REQUEST_KEY, False):
        _sign_out()
        st.rerun()
        return
    _render_announcement_banner()
    if page == ui.ADMIN_PAGE:
        # Authorisation is re-derived from the account on every run, never from
        # a flag written into the session at sign-in.
        if is_admin(user["email"]):
            page_admin(user)
        else:
            st.error("You do not have access to that page.")
        return

    ROUTES.get(page, page_home)(user)


if __name__ == "__main__":
    main()
