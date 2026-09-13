"""
⚡ Asian Inference Platform — app.py
Streamlit Cloud entry point
"""
import json, uuid, re
import pandas as pd
import streamlit as st
from datetime import datetime

import core, ui, inference
from hf_storage import make_model_repo
from core import (
    PLANS, ADMIN_EMAIL,
    load_db, save_db,
    register, login, get_user, save_user,
    safe_add_tokens, deduct_tokens, rate_limit,
    save_dataset, get_public_datasets, get_user_datasets,
    save_model, get_public_models, get_user_models,
    generate_api_key, revoke_api_key,
)

st.set_page_config(
    page_title="Asian Inference",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _over_limit(user, kind):
    if user["email"] == ADMIN_EMAIL:
        return False
    return len(user.get(kind, [])) >= PLANS[user["plan"]][f"max_{kind}"]

def _limit_warn(user, kind):
    plan  = PLANS[user["plan"]]
    limit = plan[f"max_{kind}"]
    st.markdown(f'<div class="warn">⚠️ You\'ve hit your {kind} limit ({limit}) on the '
                f'<b>{plan["name"]}</b> plan. Upgrade to create more.</div>',
                unsafe_allow_html=True)
    if st.button("⚡ Upgrade now", key=f"ulim_{kind}"):
        st.session_state["_page"] = "⚡  Upgrade"
        st.rerun()

def _ds_downloads(ds):
    df = pd.DataFrame(ds["rows"])
    did = ds["id"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("⬇ CSV", df.to_csv(index=False),
            f"{did}.csv", "text/csv", key=f"csv_{did}", use_container_width=True)
    with c2:
        st.download_button("⬇ JSON", json.dumps(ds["rows"], indent=2),
            f"{did}.json", "application/json", key=f"json_{did}", use_container_width=True)
    with c3:
        st.download_button("⬇ JSONL",
            "\n".join(json.dumps(r) for r in ds["rows"]),
            f"{did}.jsonl", "application/json", key=f"jl_{did}", use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────
def page_auth():
    st.markdown("""
<div class="hero">
  <div class="badge">BETA · YOUR OWN AI PLATFORM</div>
  <h1>⚡ Asian Inference</h1>
  <p>Build AI datasets with a chatbot · Fine-tune models · Share with the community<br>
     Like HuggingFace — but yours. No HF account needed to use it.</p>
</div>""", unsafe_allow_html=True)

    col_l, col_r = st.columns([1, 1], gap="large")
    with col_l:
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="you@example.com")
                pw    = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in →", use_container_width=True):
                    ok, msg, user = login(email, pw)
                    if ok:
                        st.session_state["ue"] = user["email"]
                        st.session_state["ia"] = user["email"] == ADMIN_EMAIL
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_up:
            with st.form("reg_form"):
                name  = st.text_input("Full name")
                email = st.text_input("Email", placeholder="you@example.com")
                pw    = st.text_input("Password", type="password", help="Min 8 characters")
                pw2   = st.text_input("Confirm password", type="password")
                if st.form_submit_button("Create free account →", use_container_width=True):
                    if pw != pw2:
                        st.error("Passwords don't match.")
                    else:
                        ok, msg = register(email, pw, name)
                        st.success("✅ " + msg + "  Sign in above.") if ok else st.error(msg)

    with col_r:
        st.markdown("### Plans")
        ui.plan_cards_auth()

# ─────────────────────────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────────────────────────
def page_home(user):
    plan = PLANS[user["plan"]]
    name = (user.get("name","") or "there").split()[0]
    ui.hero(f"Welcome back, {name} {plan['badge']}",
            "Your AI workspace — create, train, and share")

    c1, c2, c3, c4 = st.columns(4)
    for col, num, lbl in [
        (c1, user.get("tokens",0),           "🪙 Tokens"),
        (c2, len(user.get("datasets",[])),    "📦 Datasets"),
        (c3, len(user.get("models",[])),      "🤖 Models"),
        (c4, len(user.get("api_keys",{})),    "🔑 API Keys"),
    ]:
        col.markdown(f"""
<div class="card" style="text-align:center;padding:1.3rem">
  <div class="stat-num">{num:,}</div>
  <div class="stat-lbl">{lbl}</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    cl, cr = st.columns(2, gap="large")

    with cl:
        st.markdown("**Recent datasets**")
        my_ds = get_user_datasets(user["email"])
        if not my_ds:
            st.markdown('<div class="note">No datasets yet — go to Dataset Chat to make one.</div>',
                        unsafe_allow_html=True)
        for ds in reversed(my_ds[-5:]):
            vis = "🌐" if ds.get("public") else "🔒"
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {ds["name"]}</h4>
  <div class="meta">{len(ds["rows"])} rows · {ds["created"][:10]}</div>
</div>""", unsafe_allow_html=True)

    with cr:
        st.markdown("**Recent models**")
        my_md = get_user_models(user["email"])
        if not my_md:
            st.markdown('<div class="note">No models yet — go to My Models to create one.</div>',
                        unsafe_allow_html=True)
        for md in reversed(my_md[-5:]):
            vis = "🌐" if md.get("public") else "🔒"
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {md["name"]}</h4>
  <div class="meta">{md["base_model"]} · {md["created"][:10]}</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("**Plan usage**")
    c1, c2, c3 = st.columns(3)
    ds_lim = plan["max_datasets"]; ds_ct = len(user.get("datasets",[]))
    md_lim = plan["max_models"];   md_ct = len(user.get("models",[]))
    tk_lim = plan["monthly_tokens"]; tk_ct = user.get("tokens",0)
    with c1:
        st.markdown(f"Datasets: **{ds_ct}** / {ds_lim}")
        st.progress(min(ds_ct/max(ds_lim,1), 1.0))
    with c2:
        st.markdown(f"Models: **{md_ct}** / {md_lim}")
        st.progress(min(md_ct/max(md_lim,1), 1.0))
    with c3:
        st.markdown(f"Tokens: **{tk_ct:,}** / {tk_lim:,}")
        st.progress(min(tk_ct/max(tk_lim,1), 1.0))

    if user["plan"] == "starter":
        st.markdown('<div class="note" style="margin-top:.6rem">'
                    '✦ On Starter you get 2 datasets + 2 models. '
                    'Upgrade to Pro for 6 each, or Elite for unlimited.</div>',
                    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# DATASET CHAT
# ─────────────────────────────────────────────────────────────────
def page_dataset_chat(user):
    plan = PLANS[user["plan"]]
    ui.hero("💬 Dataset Chat",
            "Just describe what you want — the AI builds your dataset like a conversation")

    if _over_limit(user, "datasets"):
        _limit_warn(user, "datasets")
        return

    if "chat" not in st.session_state:
        first_name = (user.get("name","") or "there").split()[0]
        st.session_state["chat"] = [{
            "role": "bot",
            "content": (
                f"👋 Hi {first_name}! I'm your dataset assistant.\n\n"
                "Tell me what kind of dataset you need. For example:\n"
                "- *50 rows of customer reviews for a coffee shop*\n"
                "- *Q&A pairs about Python programming*\n"
                "- *Sentiment dataset about movie reviews*\n\n"
                f"You have **{user['tokens']:,} tokens** left (10 tokens per row)."
            )
        }]
    if "pending_ds" not in st.session_state:
        st.session_state["pending_ds"] = None

    # ── Render chat bubbles ──
    chat_html = '<div class="chat-wrap">'
    for msg in st.session_state["chat"]:
        sender  = "You" if msg["role"] == "user" else "⚡ Asian AI"
        content = msg["content"].replace("\n","<br>")
        bclass  = "user" if msg["role"] == "user" else "bot"
        chat_html += f'<div class="bubble {bclass}"><div class="sender">{sender}</div>{content}</div>'
    chat_html += "</div>"
    st.markdown(chat_html, unsafe_allow_html=True)

    # ── Pending dataset form ──
    if st.session_state["pending_ds"]:
        info = st.session_state["pending_ds"]
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.markdown("### ✦ Ready to generate")

        col_l, col_r = st.columns([2,1])
        with col_l:
            with st.form("confirm_gen"):
                ds_name  = st.text_input("Dataset name", value=info.get("name","My Dataset"))
                ds_desc  = st.text_area("Description", value=info.get("desc",""), height=60)
                cols_raw = st.text_input("Columns (comma-separated)",
                                         value=", ".join(info.get("columns",["input","output"])))
                num_rows = st.slider("Rows to generate", 1, plan["max_rows"],
                                     min(info.get("rows",10), plan["max_rows"]))
                style    = st.selectbox("Dataset style", [
                    "Q&A pairs","tabular","instruction-response",
                    "classification","sentiment analysis","custom"])
                tags_raw = st.text_input("Tags", value=info.get("tags",""),
                                         placeholder="nlp, english")
                public   = st.checkbox("Share publicly on Dataset Hub",
                                       disabled=not plan["share"],
                                       help="Pro / Elite only")
                c1b, c2b = st.columns(2)
                with c1b: go     = st.form_submit_button("✦ Generate dataset", use_container_width=True)
                with c2b: cancel = st.form_submit_button("Cancel",            use_container_width=True)

            if cancel:
                st.session_state["pending_ds"] = None
                st.rerun()

            if go:
                columns = [c.strip() for c in cols_raw.split(",") if c.strip()]
                tags    = [t.strip() for t in tags_raw.split(",") if t.strip()]
                cost    = num_rows * 10
                topic   = info.get("topic", ds_name)

                if not columns:
                    st.error("At least one column required.")
                elif not rate_limit(user["email"], "generate", 3):
                    st.error("Rate limit: max 3 generations/minute.")
                elif user["tokens"] < cost:
                    st.error(f"Need {cost:,} tokens, you have {user['tokens']:,}.")
                else:
                    prog = st.progress(0, "Starting…")
                    def cb(i, n): prog.progress((i+1)/n, f"Row {i+1} of {n}…")
                    rows = inference.generate_rows(topic, columns, style, num_rows, cb)
                    prog.empty()

                    if deduct_tokens(user, cost):
                        did = save_dataset(user["email"], ds_name, ds_desc,
                                           rows, public, tags)
                        save_user(user)
                        st.session_state["pending_ds"]   = None
                        st.session_state["last_ds"]      = rows
                        st.session_state["last_ds_id"]   = did
                        st.session_state["last_ds_name"] = ds_name
                        st.session_state["chat"].append({
                            "role": "bot",
                            "content": (
                                f"✅ Done! **{ds_name}** with {num_rows} rows saved to your account.\n\n"
                                f"Used {cost:,} tokens — {user['tokens']:,} left.\n\n"
                                "Download it below, or find it in the Dataset Hub."
                            )
                        })
                        st.rerun()

        with col_r:
            cost_est = info.get("rows",10) * 10
            st.markdown(f"""
<div class="card">
  <div style="font-size:.72rem;color:var(--txt3);text-transform:uppercase;letter-spacing:.06em">Cost estimate</div>
  <div style="font-size:1.8rem;font-weight:700;color:var(--txt);margin:.3rem 0 .1rem">
    {cost_est:,}
    <span style="font-size:.95rem;font-weight:400;color:var(--txt3)">tokens</span>
  </div>
  <div style="font-size:.8rem;color:var(--txt2)">
    {info.get("rows",10)} rows × 10 tokens<br>
    Your balance: <b>{user["tokens"]:,}</b>
  </div>
</div>""", unsafe_allow_html=True)

    # ── Last generated preview ──
    if st.session_state.get("last_ds"):
        with st.expander(f"⬇ Download — {st.session_state.get('last_ds_name','Last dataset')}",
                         expanded=False):
            st.dataframe(pd.DataFrame(st.session_state["last_ds"]), use_container_width=True)
            _ds_downloads({"id": st.session_state.get("last_ds_id","out"),
                           "rows": st.session_state["last_ds"]})

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # ── Message input ──
    with st.form("chat_input", clear_on_submit=True):
        ci, cb2 = st.columns([5,1])
        with ci:
            msg = st.text_input("Message", placeholder="Describe your dataset…",
                                label_visibility="collapsed")
        with cb2:
            send = st.form_submit_button("Send →", use_container_width=True)

    if send and msg.strip():
        user_msg = msg.strip()
        st.session_state["chat"].append({"role":"user","content":user_msg})

        # Detect row count in message
        m_rows = re.search(r'\b(\d+)\s*(rows?|samples?|examples?|entries)\b', user_msg, re.I)
        row_count = int(m_rows.group(1)) if m_rows else None
        has_info  = len(user_msg) > 12

        if row_count and has_info:
            row_count = min(row_count, plan["max_rows"])
            # Guess columns from keywords
            cols = ["input","output"]
            low  = user_msg.lower()
            if any(w in low for w in ["review","sentiment","opinion","feeling"]):
                cols = ["text","sentiment","score"]
            elif any(w in low for w in ["q&a","question","answer","faq"]):
                cols = ["question","answer"]
            elif any(w in low for w in ["instruct","command","task","assistant"]):
                cols = ["instruction","response"]
            elif any(w in low for w in ["classif","label","categor","class"]):
                cols = ["text","label","confidence"]
            elif any(w in low for w in ["summar","article","document"]):
                cols = ["document","summary"]

            st.session_state["pending_ds"] = {
                "topic":user_msg,"rows":row_count,
                "columns":cols,"name":"My Dataset","desc":"","tags":"",
            }
            bot_reply = (
                f"Got it! I'll build a **{row_count}-row** dataset about:\n\n"
                f"*{user_msg[:100]}*\n\n"
                f"Suggested columns: `{', '.join(cols)}`\n\n"
                "Review the settings below and hit **Generate dataset** when ready."
            )
        else:
            # No row count — chat normally
            bot_reply = inference.chat_response(
                user_msg, st.session_state["chat"][:-1])
            # Nudge user if they have a topic but no row count
            if has_info and "row" not in bot_reply.lower():
                bot_reply += "\n\n*Tip: tell me how many rows you want, e.g. \"50 rows\"*"

        st.session_state["chat"].append({"role":"bot","content":bot_reply})
        st.rerun()

    # ── Quick start buttons ──
    st.markdown("**Quick start:**")
    prompts = [
        "50 rows of customer reviews for a coffee shop",
        "100 Q&A pairs about Python programming",
        "30 rows sentiment dataset about social media posts",
        "20 instruction-response pairs for a cooking assistant",
        "40 rows product descriptions for an electronics store",
        "60 classification examples of spam vs not-spam emails",
    ]
    c1, c2 = st.columns(2)
    for i, p in enumerate(prompts):
        with (c1 if i%2==0 else c2):
            if st.button(f"💡 {p}", key=f"qp_{i}", use_container_width=True):
                m2 = re.search(r'\b(\d+)\b', p)
                rc = int(m2.group(1)) if m2 else 20
                low = p.lower()
                if "review" in low or "sentiment" in low: cg = ["text","sentiment","score"]
                elif "q&a" in low or "question" in low:   cg = ["question","answer"]
                elif "instruct" in low:                    cg = ["instruction","response","category"]
                elif "classif" in low or "spam" in low:   cg = ["text","label"]
                elif "product" in low or "description" in low: cg = ["name","description","price","category"]
                else:                                      cg = ["input","output"]
                st.session_state["chat"].append({"role":"user","content":p})
                st.session_state["pending_ds"] = {
                    "topic":p,"rows":rc,"columns":cg,
                    "name":"My Dataset","desc":"","tags":"",
                }
                st.session_state["chat"].append({
                    "role":"bot",
                    "content": (
                        f"Got it! Building a **{rc}-row** dataset:\n\n*{p}*\n\n"
                        f"Suggested columns: `{', '.join(cg)}`\n\n"
                        "Review the form below and hit **Generate dataset**."
                    )
                })
                st.rerun()

# ─────────────────────────────────────────────────────────────────
# MY MODELS
# ─────────────────────────────────────────────────────────────────
def page_my_models(user):
    plan = PLANS[user["plan"]]
    ui.hero("🤖 My Models", "Fine-tune on your data · Host · Share · Run inference")

    if _over_limit(user, "models"):
        _limit_warn(user, "models")
        return

    tab_new, tab_list = st.tabs(["Create & fine-tune", "My models"])

    with tab_new:
        col_l, col_r = st.columns([3,2], gap="large")

        with col_r:
            st.markdown("""
<div class="card">
  <div style="font-weight:600;color:var(--txt);margin-bottom:.6rem">How it works</div>
  <div style="font-size:.83rem;color:var(--txt2);line-height:1.8">
    1. Pick a base model from HuggingFace<br>
    2. Choose one of your datasets to train on<br>
    3. Download the auto-generated <b>Colab notebook</b><br>
    4. Open in Google Colab → <b>T4 GPU (free)</b><br>
    5. Run all cells → model pushes to HuggingFace<br>
    6. Paste HF repo here → model lives on Asian Inference
  </div>
</div>
<div class="card" style="margin-top:.7rem">
  <div style="font-size:.73rem;color:var(--txt3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:.5rem">Popular base models</div>
  <div>
    <span class="tag acc">Hwiiiiiiii/gemby-agent-3b</span>
    <span class="tag">TinyLlama/TinyLlama-1.1B</span>
    <span class="tag">microsoft/phi-2</span>
    <span class="tag">google/flan-t5-base</span>
    <span class="tag">facebook/opt-1.3b</span>
    <span class="tag">EleutherAI/pythia-1b</span>
  </div>
</div>""", unsafe_allow_html=True)

        with col_l:
            with st.form("new_model_form"):
                mname    = st.text_input("Model name", placeholder="My Coffee Classifier")
                mdesc    = st.text_area("Description", height=65)
                base     = st.text_input("Base model",
                                         value="Hwiiiiiiii/gemby-agent-3b")
                st.caption("Your trained weights are stored securely by the platform. You do not need to manage a storage repository or token.")

                my_ds   = get_user_datasets(user["email"])
                ds_opts = ["— none (zero-shot) —"] + [d["name"] for d in my_ds]
                ds_sel  = st.selectbox("Train on dataset", ds_opts)

                with st.expander("⚙️ Training settings"):
                    epochs = st.slider("Epochs", 1, 10, 3)
                    lr     = st.select_slider("Learning rate",
                                              ["5e-5","2e-4","5e-4","1e-3"], value="2e-4")
                    mlen   = st.select_slider("Max sequence length",
                                              [128,256,512,1024], value=512)
                    batch  = st.select_slider("Batch size", [1,2,4,8], value=4)

                tags_raw = st.text_input("Tags", placeholder="nlp, classifier, english")
                public   = st.checkbox("Share publicly on Model Hub",
                                       disabled=not plan["share"],
                                       help="Pro / Elite only")
                submitted = st.form_submit_button(
                    "✦ Create model + generate Colab notebook",
                    use_container_width=True)

            if submitted:
                if not mname:    st.error("Model name required."); st.stop()
                if not base:     st.error("Base model required."); st.stop()
                out_repo = make_model_repo(user["email"])
                if not out_repo:
                    st.error("Model storage is not available yet. Please contact support or try again later."); st.stop()

                chosen_rows = []
                if ds_sel != "— none (zero-shot) —":
                    for d in my_ds:
                        if d["name"] == ds_sel:
                            chosen_rows = d["rows"]; break

                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                nb   = inference.generate_colab_notebook(
                    mname, base, out_repo, chosen_rows,
                    "", epochs, lr, mlen, batch)

                mid = save_model(user["email"], mname, mdesc, base, out_repo, public, tags)
                save_user(user)
                st.session_state["nb_json"] = nb
                st.session_state["nb_name"] = mname
                st.success(f"✅ **{mname}** created! Download your Colab notebook below.")
                st.rerun()

        if st.session_state.get("nb_json"):
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown("### 🧪 Your Colab notebook is ready")
            st.markdown("""
<div class="note">
  <b>Steps:</b>  Download the notebook →
  open <a href="https://colab.research.google.com" target="_blank" style="color:#7dd3fc">colab.research.google.com</a>
  → Upload → Runtime → Change runtime type → <b>T4 GPU</b> → Run All.<br>
  Model trains and is saved automatically by the platform. 100% free GPU!
</div>""", unsafe_allow_html=True)
            nb_name = st.session_state.get("nb_name","model").replace(" ","_")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇ Download Colab notebook (.ipynb)",
                    st.session_state["nb_json"],
                    file_name=f"train_{nb_name}.ipynb",
                    mime="application/json", use_container_width=True)
            with c2:
                st.link_button("🔗 Open Google Colab",
                               "https://colab.research.google.com",
                               use_container_width=True)

    with tab_list:
        my_md = get_user_models(user["email"])
        st.markdown(f'<div style="color:var(--txt3);font-size:.78rem;margin-bottom:.8rem">'
                    f'{len(my_md)} / {plan["max_models"]} model slots used</div>',
                    unsafe_allow_html=True)
        if not my_md:
            st.markdown('<div class="note">No models yet. Create one above.</div>',
                        unsafe_allow_html=True)

        for md in reversed(my_md):
            vis   = "🌐" if md.get("public") else "🔒"
            thtml = ui.tags_html(md.get("tags",[]), accent=True)
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {md["name"]}</h4>
  <div class="desc">{md.get("description","")}</div>
  <div class="meta">
    Base: <code style="color:var(--acc2);font-size:.76rem">{md["base_model"]}</code> ·
    Platform-managed weights ·
    {md["created"][:10]}
  </div>
  <div style="margin-top:.35rem">{thtml}</div>
</div>""", unsafe_allow_html=True)

            with st.expander(f"▶ Inference & options — {md['name']}"):
                c1, c2 = st.columns([3,2])
                with c1:
                    prompt  = st.text_area("Try a prompt", height=90, key=f"pr_{md['id']}")
                    if st.button("▶ Run inference", key=f"run_{md['id']}"):
                        if not rate_limit(user["email"], "inf", 5):
                            st.error("Rate limit: 5 calls/minute.")
                        else:
                            with st.spinner("Running…"):
                                out = inference.call_hf(
                                    md["hf_repo"], prompt)
                            if out == "__MODEL_LOADING__":
                                st.warning("Model warming up — try again in 20 seconds.")
                            elif out.startswith("["):
                                st.error(out)
                            else:
                                st.text_area("Output", out, height=110,
                                             key=f"op_{md['id']}")
                with c2:
                    db  = load_db()
                    new_pub = st.checkbox("Public", value=md.get("public"),
                                          key=f"mpub_{md['id']}",
                                          disabled=not plan["share"])
                    if st.button("Save visibility", key=f"msv_{md['id']}",
                                 use_container_width=True):
                        db["models"][md["id"]]["public"] = new_pub
                        save_db(db); st.rerun()
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("🗑 Delete model", key=f"mdel_{md['id']}",
                                 type="secondary", use_container_width=True):
                        del db["models"][md["id"]]
                        db["users"][user["email"]]["models"].remove(md["id"])
                        save_db(db); st.rerun()

# ─────────────────────────────────────────────────────────────────
# DATASET HUB
# ─────────────────────────────────────────────────────────────────
def page_dataset_hub(user):
    plan = PLANS[user["plan"]]
    ui.hero("📦 Dataset Hub", "Browse · Download · Share community datasets")

    tab_pub, tab_mine = st.tabs(["Community", "My datasets"])

    with tab_pub:
        search = st.text_input("🔍 Search", placeholder="name, tag, description…",
                                key="dh_s", label_visibility="collapsed")
        all_ds = get_public_datasets()
        shown  = [d for d in all_ds if not search
                  or any(search.lower() in str(v).lower()
                         for v in [d["name"], d.get("description","")]
                         + d.get("tags",[]))]
        st.markdown(f'<div style="color:var(--txt3);font-size:.78rem;margin:.2rem 0 .9rem">'
                    f'{len(shown)} public dataset{"s" if len(shown)!=1 else ""}</div>',
                    unsafe_allow_html=True)
        if not shown:
            st.markdown('<div class="note">No public datasets yet — be first to share one!</div>',
                        unsafe_allow_html=True)
        for ds in shown:
            thtml = ui.tags_html(ds.get("tags",[]))
            st.markdown(f"""
<div class="hub-card">
  <h4>🌐 {ds["name"]}
    <span style="color:var(--txt3);font-weight:400;font-size:.75rem"> by {ds["owner"]}</span>
  </h4>
  <div class="desc">{ds.get("description","No description")}</div>
  <div class="meta">{len(ds["rows"])} rows · {ds["created"][:10]} · ⬇ {ds.get("downloads",0)}</div>
  <div style="margin-top:.3rem">{thtml}</div>
</div>""", unsafe_allow_html=True)
            with st.expander("Preview & download"):
                st.dataframe(pd.DataFrame(ds["rows"]).head(10), use_container_width=True)
                _ds_downloads(ds)

    with tab_mine:
        my_ds = get_user_datasets(user["email"])
        st.markdown(f'<div style="color:var(--txt3);font-size:.78rem;margin:.2rem 0 .9rem">'
                    f'{len(my_ds)} / {plan["max_datasets"]} slots used</div>',
                    unsafe_allow_html=True)
        if not my_ds:
            st.markdown('<div class="note">No datasets yet. Go to Dataset Chat to make one.</div>',
                        unsafe_allow_html=True)
        for ds in reversed(my_ds):
            vis   = "🌐 Public" if ds.get("public") else "🔒 Private"
            thtml = ui.tags_html(ds.get("tags",[]))
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} — {ds["name"]}</h4>
  <div class="desc">{ds.get("description","")}</div>
  <div class="meta">{len(ds["rows"])} rows · {ds["created"][:10]}</div>
  <div style="margin-top:.3rem">{thtml}</div>
</div>""", unsafe_allow_html=True)
            with st.expander("Options"):
                st.dataframe(pd.DataFrame(ds["rows"]).head(5), use_container_width=True)
                _ds_downloads(ds)
                c1, c2 = st.columns(2)
                with c1:
                    new_pub = st.checkbox("Share publicly", value=ds.get("public"),
                                          key=f"dpub_{ds['id']}",
                                          disabled=not plan["share"],
                                          help="Pro / Elite only")
                    if st.button("Save", key=f"dsav_{ds['id']}"):
                        db = load_db()
                        db["datasets"][ds["id"]]["public"] = new_pub
                        save_db(db); st.rerun()
                with c2:
                    if st.button("🗑 Delete", key=f"ddel_{ds['id']}",
                                 type="secondary", use_container_width=True):
                        db = load_db()
                        del db["datasets"][ds["id"]]
                        db["users"][user["email"]]["datasets"].remove(ds["id"])
                        save_db(db); st.rerun()

# ─────────────────────────────────────────────────────────────────
# MODEL HUB
# ─────────────────────────────────────────────────────────────────
def page_model_hub(user):
    ui.hero("🌐 Model Hub", "Browse · Try live inference · Download community models")

    search = st.text_input("🔍 Search", placeholder="name, base model, tag…",
                            key="mh_s", label_visibility="collapsed")
    all_md = get_public_models()
    shown  = [m for m in all_md if not search
              or any(search.lower() in str(v).lower()
                     for v in [m["name"], m.get("base_model",""), m.get("description","")]
                     + m.get("tags",[]))]
    st.markdown(f'<div style="color:var(--txt3);font-size:.78rem;margin:.2rem 0 .9rem">'
                f'{len(shown)} public model{"s" if len(shown)!=1 else ""}</div>',
                unsafe_allow_html=True)
    if not shown:
        st.markdown('<div class="note">No public models yet.</div>', unsafe_allow_html=True)

    for m in shown:
        thtml  = ui.tags_html(m.get("tags",[]))
        st.markdown(f"""
<div class="hub-card">
  <h4>🌐 {m["name"]}
    <span style="color:var(--txt3);font-weight:400;font-size:.75rem"> by {m["owner"]}</span>
  </h4>
  <div class="desc">{m.get("description","No description")}</div>
  <div class="meta">
    Base: <code style="color:var(--acc2);font-size:.76rem">{m["base_model"]}</code> ·
    Platform-managed weights ·
    {m["created"][:10]}
  </div>
  <div style="margin-top:.35rem">{thtml}</div>
</div>""", unsafe_allow_html=True)
        with st.expander(f"▶ Try inference — {m['name']}"):
            prompt  = st.text_area("Prompt", height=80, key=f"mhp_{m['id']}")
            if st.button("Run →", key=f"mhr_{m['id']}"):
                if not rate_limit(user["email"], "inf", 5):
                    st.error("Rate limit: 5 calls/minute.")
                else:
                    with st.spinner("Running…"):
                        out = inference.call_hf(m["hf_repo"], prompt)
                    if out == "__MODEL_LOADING__":
                        st.warning("Model warming up — wait 20s and retry.")
                    else:
                        st.text_area("Output", out, height=100, key=f"mho_{m['id']}")

# ─────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────
def page_api_keys(user):
    plan = PLANS[user["plan"]]
    ui.hero("🔑 API Keys", "Your asi- key · Use in Colab · Saves results to your account")

    # ── Platform key ──
    st.markdown("### Your Asian Inference API key")
    st.markdown("""
<div class="note">
  This is your personal <code>asi-</code> key. Use it anywhere — Google Colab, Python scripts,
  other apps — to authenticate as <b>you</b> and save datasets or run models directly
  into your Asian Inference account.
</div>""", unsafe_allow_html=True)

    pkey = user.get("platform_api_key")
    if not pkey:
        if st.button("✦ Generate my asi- key", use_container_width=False):
            user["platform_api_key"] = "asi-" + uuid.uuid4().hex
            save_user(user)
            st.rerun()
    else:
        st.markdown(f'<div class="key-box">🔑 {pkey}</div>', unsafe_allow_html=True)
        st.caption("Keep this secret — anyone with this key can act as you on the platform.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Regenerate key", type="secondary"):
                user["platform_api_key"] = "asi-" + uuid.uuid4().hex
                save_user(user); st.rerun()
        with c2:
            st.download_button("⬇ Save key as .txt", pkey,
                "asian_inference_key.txt", "text/plain")

    # ── Colab template ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("### Use in Google Colab")

    key_display = pkey or "asi-your-key-here"
    st.code(f'''# ⚡ Asian Inference — Colab template
# Paste your asi- key below and run this cell

!pip install -q requests pandas

import requests, json
import pandas as pd

API_KEY  = "{key_display}"
BASE_URL = "https://asian-inference.streamlit.app"   # your deployed URL

# ── Generate a dataset ──────────────────────────────────────────
def generate_dataset(topic, rows, columns, style="Q&A pairs",
                     name="My Dataset", public=False):
    r = requests.post(
        f"{{BASE_URL}}/api/generate",
        headers={{"Authorization": f"Bearer {{API_KEY}}"}},
        json={{
            "topic":   topic,
            "rows":    rows,
            "columns": columns,
            "style":   style,
            "name":    name,
            "public":  public,
        }},
        timeout=120
    )
    return r.json()

# Example
result = generate_dataset(
    topic   = "customer reviews for a coffee shop",
    rows    = 20,
    columns = ["text", "rating", "sentiment"],
    style   = "sentiment analysis",
    name    = "Coffee Reviews Dataset",
)

print(f"Dataset ID : {{result.get('dataset_id')}}")
print(f"Rows       : {{len(result.get('rows', []))}}")
print(f"Tokens left: {{result.get('tokens_left')}}")

# Show as DataFrame
df = pd.DataFrame(result.get("rows", []))
display(df)

# ── Run inference on a model ────────────────────────────────────
def run_model(model_id, prompt):
    r = requests.post(
        f"{{BASE_URL}}/api/inference",
        headers={{"Authorization": f"Bearer {{API_KEY}}"}},
        json={{"model_id": model_id, "prompt": prompt}},
        timeout=60
    )
    return r.json()
''', language="python")

    # ── External keys ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("### External API keys")

    used = len(user.get("api_keys",{}))
    max_k = plan["api_keys"]
    st.markdown(f'<div class="note"><b>{used}/{max_k}</b> key slots used on your '
                f'{plan["name"]} plan.</div>', unsafe_allow_html=True)

    with st.form("add_ext_key"):
        c1, c2, c3 = st.columns([2,3,1])
        with c1: label = st.text_input("Label", placeholder="External service key")
        with c2: kval  = st.text_input("Key value", type="password", placeholder="hf_xxxx…")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            add = st.form_submit_button("Add", use_container_width=True)
        if add:
            if not label: st.error("Label required.")
            elif not kval: st.error("Key value required.")
            elif used >= max_k: st.error(f"Limit reached ({max_k}). Upgrade for more.")
            elif label in user.get("api_keys",{}): st.error("Label already used.")
            else:
                user.setdefault("api_keys",{})[label] = {
                    "key": kval, "created": datetime.utcnow().isoformat(), "uses": 0}
                save_user(user); st.rerun()

    for label, info in user.get("api_keys",{}).items():
        k = info["key"]
        masked = k[:8] + "••••••••" + k[-4:]
        st.markdown(f"""
<div class="hub-card">
  <h4>🔑 {label}</h4>
  <div class="meta">
    <code style="color:var(--acc2)">{masked}</code> · added {info["created"][:10]}
  </div>
</div>""", unsafe_allow_html=True)
        if st.button(f"Remove '{label}'", key=f"rk_{label}", type="secondary"):
            revoke_api_key(user, label); st.rerun()

# ─────────────────────────────────────────────────────────────────
# UPGRADE  (working buttons)
# ─────────────────────────────────────────────────────────────────
def page_upgrade(user):
    ui.hero("⚡ Upgrade", "More tokens · More models · More datasets")

    current = user["plan"]

    # ── Plan cards ──
    c1, c2, c3 = st.columns(3, gap="medium")
    for col, (pid, p) in zip([c1,c2,c3], PLANS.items()):
        is_cur  = pid == current
        popular = pid == "pro"
        price   = "Free" if p["price"]==0 else f"${p['price']}/mo"
        feats   = [
            (f"{p['monthly_tokens']:,} tokens/month",          True),
            (f"Up to {p['max_rows']:,} rows per dataset",      True),
            (f"{p['max_datasets']} datasets · {p['max_models']} models", True),
            ("Public sharing on Hub",                          p["share"]),
            (f"{p['api_keys']} API key{'s' if p['api_keys']!=1 else ''}", True),
            ("Priority generation queue",                      p["price"] >= 29.99),
        ]
        fhtml = "".join(
            f'<div style="display:flex;gap:.5rem;align-items:flex-start;margin:.4rem 0;'
            f'font-size:.82rem;color:{"var(--txt2)" if ok else "var(--txt3)"}">'
            f'<span style="color:{"var(--grn)" if ok else "var(--txt3)"}">{"✓" if ok else "✗"}</span>'
            f'{feat}</div>'
            for feat, ok in feats
        )
        pop_badge = ('<div style="position:absolute;top:0;right:0;background:var(--acc);'
                     'color:#fff;font-size:.6rem;font-weight:700;letter-spacing:.08em;'
                     'padding:.22rem .7rem;border-radius:0 18px 0 12px">POPULAR</div>'
                     if popular else "")
        cur_note  = ('<div style="color:var(--grn);font-size:.76rem;margin:.3rem 0 .6rem">'
                     '✓ Your current plan</div>' if is_cur else "")

        with col:
            st.markdown(f"""
<div class="plan-card {'current' if is_cur else ''}"
     style="position:relative;min-height:340px">
  {pop_badge}
  <div style="font-size:1.6rem;margin-bottom:.5rem">{p["badge"]}</div>
  <div style="font-size:1rem;font-weight:600;color:var(--txt)">{p["name"]}</div>
  {cur_note}
  <div style="font-size:1.85rem;font-weight:700;color:var(--txt);line-height:1.15;
       margin-bottom:.2rem">{price}</div>
  <div style="font-size:.73rem;color:var(--txt3);margin-bottom:1rem">
    {"via Traakteer · cancel anytime" if p["price"]>0 else "forever free · no card needed"}
  </div>
  {fhtml}
  <div style="height:1.2rem"></div>
</div>""", unsafe_allow_html=True)

            # Working buttons rendered by Streamlit (not inside HTML)
            if is_cur:
                st.button("✓ Current plan", key=f"btn_cur_{pid}",
                          disabled=True, use_container_width=True)
            elif p["price"] == 0:
                if st.button("Switch to Free", key=f"btn_free_{pid}",
                             type="secondary", use_container_width=True):
                    db = load_db()
                    db["users"][user["email"]]["plan"] = "starter"
                    save_db(db); st.rerun()
            else:
                checkout = (f"https://pay.traakteer.com/checkout"
                            f"?plan={p['traakteer_id']}"
                            f"&customer_email={user['email']}")
                st.link_button(f"Upgrade to {p['name']} →",
                               url=checkout, use_container_width=True)

    # ── Table ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("### Full plan comparison")
    df = pd.DataFrame({
        "Feature":            ["Tokens/month","Max rows","Datasets","Models",
                               "API keys","Public sharing","Priority queue","Price"],
        "🆓 Starter":        ["500","50","2","2","1","✗","✗","Free"],
        "⚡ Pro":            ["15,000","2,000","6","6","5","✓","✗","$9.99/mo"],
        "👑 Elite":          ["Unlimited","50,000","Unlimited","Unlimited",
                               "Unlimited","✓","✓","$29.99/mo"],
    })
    st.dataframe(df.set_index("Feature"), use_container_width=True)
    st.markdown("""
<div class="note" style="margin-top:.8rem">
  Payments processed by <b>Traakteer</b>. After payment, your plan upgrades
  automatically via a signed webhook — no waiting, no manual steps.
</div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# SUPPORT
# ─────────────────────────────────────────────────────────────────
def page_support(user):
    ui.hero("💬 Support", "We reply within 24 hours on business days")

    tab_t, tab_faq = st.tabs(["Send a ticket", "FAQ"])

    with tab_t:
        with st.form("support_form"):
            subject = st.selectbox("Topic", [
                "Billing / Traakteer payment",
                "Tokens or plan issue",
                "Dataset generation error",
                "Model training / Colab issue",
                "API key issue",
                "Account access",
                "Feature request",
                "Other",
            ])
            message = st.text_area("Message", height=140,
                                   placeholder="Describe your issue in detail…")
            if st.form_submit_button("Send message →", use_container_width=True):
                if not message.strip():
                    st.error("Please write a message.")
                else:
                    db = load_db()
                    db.setdefault("support_tickets",[]).append({
                        "id":      str(uuid.uuid4())[:8],
                        "user":    user["email"],
                        "subject": subject,
                        "message": message,
                        "ts":      datetime.utcnow().isoformat(),
                        "status":  "open",
                        "admin_reply": "",
                    })
                    save_db(db)
                    st.success("✅ Ticket submitted! We'll reply to your email soon.")

    with tab_faq:
        faqs = [
            ("How do tokens work?",
             "Each dataset row costs 10 tokens. Tokens reset monthly on your billing date. "
             "Unused tokens don't roll over."),
            ("How do I use my asi- key in Colab?",
             "Go to API Keys → generate your key → copy the Colab template shown there. "
             "Paste your key into the template and run the cell. Datasets save directly "
             "to your account."),
            ("Why did generation fail or return sample data?",
             "The HuggingFace model may be cold-starting (free tier spins down). "
             "Wait 20–30 seconds and try again. Tokens are only deducted on success."),
            ("How does Traakteer billing work?",
             "Click Upgrade → redirected to Traakteer secure checkout → pay → "
             "a signed webhook upgrades your account instantly (usually under 5 seconds)."),
            ("How do I train my own model?",
             "Go to My Models → Create & fine-tune. Fill in the form, download the Colab "
             "notebook, open in Google Colab, select T4 GPU (free tier), Run All. "
             "Done — your model is live on HuggingFace and Asian Inference."),
            ("Can other people see my datasets/models?",
             "Only if you toggle them to Public. Starter plan is private-only. "
             "Pro and Elite can share to the public Hub."),
        ]
        for q, a in faqs:
            with st.expander(q):
                st.write(a)

# ─────────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────────
def page_admin():
    st.markdown('<div class="admin-bar">👑 Admin Panel — full platform control</div>',
                unsafe_allow_html=True)

    db      = load_db()
    users   = list(db["users"].values())
    datasets= list(db["datasets"].values())
    models  = list(db["models"].values())
    tickets = db.get("support_tickets",[])

    c1,c2,c3,c4,c5 = st.columns(5)
    for col, n, l in [
        (c1, len(users),   "👤 Users"),
        (c2, len(datasets),"📦 Datasets"),
        (c3, len(models),  "🤖 Models"),
        (c4, sum(1 for t in tickets if t.get("status")=="open"), "🎫 Tickets"),
        (c5, sum(1 for u in users if u.get("flagged")), "🚩 Flagged"),
    ]:
        col.markdown(f"""
<div class="card" style="text-align:center;padding:1rem">
  <div class="stat-num">{n}</div>
  <div class="stat-lbl">{l}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    t1,t2,t3,t4,t5 = st.tabs(
        ["👤 Users","📦 Datasets","🤖 Models","🎫 Tickets","🪙 Tokens"])

    with t1:
        srch = st.text_input("Filter email", key="a_us")
        shown = [u for u in users if srch.lower() in u["email"]] if srch else users
        for u in shown:
            flg = " 🚩" if u.get("flagged") else ""
            with st.expander(f"{u['email']}  ·  {PLANS[u['plan']]['badge']} {u['plan']}  ·  🪙{u['tokens']:,}{flg}"):
                c1,c2,c3 = st.columns(3)
                with c1:
                    np = st.selectbox("Plan", list(PLANS.keys()),
                        index=list(PLANS.keys()).index(u["plan"]), key=f"apl_{u['email']}")
                    if st.button("Apply plan", key=f"aap_{u['email']}", use_container_width=True):
                        u["plan"]=np; save_user(u); st.rerun()
                with c2:
                    if u.get("flagged"):
                        if st.button("✅ Unflag", key=f"auf_{u['email']}", use_container_width=True):
                            u["flagged"]=False; u["flag_reason"]=""; save_user(u); st.rerun()
                    else:
                        fr = st.text_input("Flag reason", key=f"afr_{u['email']}")
                        if st.button("🚩 Flag & suspend", key=f"afg_{u['email']}", use_container_width=True):
                            u["flagged"]=True; u["flag_reason"]=fr or "Admin action"; save_user(u); st.rerun()
                with c3:
                    if st.button("🗑 Delete account", key=f"adl_{u['email']}",
                                 type="secondary", use_container_width=True):
                        del db["users"][u["email"]]; save_db(db); st.rerun()
                if u.get("token_log"):
                    with st.expander("Token log"):
                        st.dataframe(pd.DataFrame(u["token_log"]), use_container_width=True)

    with t2:
        for ds in datasets:
            vis = "🌐" if ds.get("public") else "🔒"
            with st.expander(f"{vis} {ds['name']}  ·  {ds['owner']}  ·  {len(ds['rows'])} rows"):
                st.dataframe(pd.DataFrame(ds["rows"]).head(5), use_container_width=True)
                c1,c2 = st.columns(2)
                with c1:
                    pub = st.checkbox("Public", value=ds.get("public"), key=f"adpub_{ds['id']}")
                    if st.button("Save", key=f"adsv_{ds['id']}"):
                        db["datasets"][ds["id"]]["public"]=pub; save_db(db); st.rerun()
                with c2:
                    if st.button("🗑 Delete", key=f"addd_{ds['id']}", type="secondary"):
                        del db["datasets"][ds["id"]]; save_db(db); st.rerun()

    with t3:
        for md in models:
            vis = "🌐" if md.get("public") else "🔒"
            with st.expander(f"{vis} {md['name']}  ·  {md['owner']}  ·  {md['base_model']}"):
                c1,c2 = st.columns(2)
                with c1:
                    pub = st.checkbox("Public", value=md.get("public"), key=f"admpub_{md['id']}")
                    if st.button("Save", key=f"admsv_{md['id']}"):
                        db["models"][md["id"]]["public"]=pub; save_db(db); st.rerun()
                with c2:
                    if st.button("🗑 Delete", key=f"admd_{md['id']}", type="secondary"):
                        del db["models"][md["id"]]; save_db(db); st.rerun()

    with t4:
        if not tickets:
            st.info("No tickets yet.")
        for t in reversed(tickets):
            icon = "✅" if t["status"]=="closed" else "🟡"
            with st.expander(f"{icon} [{t['id']}] {t['subject']}  ·  {t['user']}  ·  {t['ts'][:10]}"):
                st.write(t["message"])
                if t.get("admin_reply"):
                    st.info(f"Your reply: {t['admin_reply']}")
                if t["status"]=="open":
                    rep = st.text_area("Reply", key=f"arep_{t['id']}")
                    if st.button("Close ticket", key=f"acls_{t['id']}"):
                        for tk in db["support_tickets"]:
                            if tk["id"]==t["id"]:
                                tk["status"]="closed"; tk["admin_reply"]=rep
                        save_db(db); st.rerun()

    with t5:
        st.markdown('<div class="warn">All token grants logged. '
                    'Suspicious activity auto-flags accounts.</div>', unsafe_allow_html=True)
        with st.form("tok_grant"):
            tgt = st.selectbox("User", [u["email"] for u in users])
            amt = st.number_input("Tokens to grant", 0, 100_000, 500)
            rsn = st.text_input("Reason")
            if st.form_submit_button("Grant tokens", use_container_width=True):
                u = get_user(tgt)
                if u:
                    safe_add_tokens(u, int(amt), f"manual:{rsn}")
                    save_user(u)
                    st.success(f"✅ Granted {amt:,} to {tgt}.")
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        if st.button("🔄 Reset ALL tokens to plan limits", type="secondary"):
            for email, u in db["users"].items():
                u["tokens"] = PLANS[u["plan"]]["monthly_tokens"]
            save_db(db)
            st.success("All tokens reset.")

# ─────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────
def main():
    if "ue" not in st.session_state:
        page_auth(); return

    user = get_user(st.session_state["ue"])
    if not user:
        st.session_state.clear(); st.rerun()

    if user.get("flagged") and user["email"] != ADMIN_EMAIL:
        st.markdown(f'<div class="warn">🚫 Account suspended: {user.get("flag_reason","")}<br>'
                    'Contact support to appeal.</div>', unsafe_allow_html=True)
        if st.button("Sign out"): st.session_state.clear(); st.rerun()
        return

    page = ui.sidebar_nav(user)
    if st.session_state.get("_page"):
        page = st.session_state.pop("_page")

    if   "Home"         in page: page_home(user)
    elif "Dataset Chat" in page: page_dataset_chat(user)
    elif "My Models"    in page: page_my_models(user)
    elif "Dataset Hub"  in page: page_dataset_hub(user)
    elif "Model Hub"    in page: page_model_hub(user)
    elif "API Keys"     in page: page_api_keys(user)
    elif "Upgrade"      in page: page_upgrade(user)
    elif "Support"      in page: page_support(user)
    elif "Admin"        in page and st.session_state.get("ia"): page_admin()

if __name__ == "__main__":
    main()
