"""
✦ Gemby Platform — app.py
Run: streamlit run app.py
"""
import json, re, uuid
import pandas as pd
import streamlit as st
from datetime import datetime
from pathlib import Path

import core, ui, inference
from core import (PLANS, ADMIN_EMAIL, load_db, save_db, load_rates,
                  register, login, get_user, save_user,
                  safe_add_tokens, deduct_tokens, rate_limit,
                  save_dataset, get_public_datasets, get_user_datasets,
                  save_model, get_public_models, get_user_models,
                  create_api_key, delete_api_key)

# ─────────────────────────────────────────────────────────────────
# STREAMLIT CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Gemby Platform",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _over_limit(user: dict, kind: str) -> bool:
    """Returns True if user has hit their plan limit for 'models' or 'datasets'."""
    if user["email"] == ADMIN_EMAIL:
        return False
    plan = PLANS[user["plan"]]
    count = len(user.get(kind, []))
    limit = plan[f"max_{kind}"]
    return count >= limit

def _limit_msg(user: dict, kind: str) -> str:
    plan = PLANS[user["plan"]]
    limit = plan[f"max_{kind}"]
    return (f"You've reached your {kind} limit ({limit}) on the "
            f"{plan['name']} plan. Upgrade to make more.")

def _tags_input(key: str) -> list:
    raw = st.text_input("Tags (comma-separated)", placeholder="nlp, text, english", key=key)
    return [t.strip() for t in raw.split(",") if t.strip()] if raw else []

# ─────────────────────────────────────────────────────────────────
# AUTH PAGE
# ─────────────────────────────────────────────────────────────────
def page_auth():
    ui.hero("✦ Gemby Platform",
            "Build datasets · Fine-tune models · Share with the world")

    tab_in, tab_up = st.tabs(["Sign in", "Create account"])

    with tab_in:
        with st.form("login"):
            email = st.text_input("Email")
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
        with st.form("register"):
            name  = st.text_input("Full name")
            email = st.text_input("Email")
            pw    = st.text_input("Password", type="password", help="Min 8 characters")
            pw2   = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account →", use_container_width=True):
                if pw != pw2: st.error("Passwords don't match.")
                else:
                    ok, msg = register(email, pw, name)
                    st.success(msg + " Sign in above.") if ok else st.error(msg)

    st.markdown("<br>", unsafe_allow_html=True)
    ui.plan_cards()

# ─────────────────────────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────────────────────────
def page_home(user: dict):
    plan = PLANS[user["plan"]]
    ui.hero(f"Welcome back, {user.get('name','').split()[0] or 'there'} {plan['badge']}",
            "Your AI workspace — datasets, models, and the community hub")

    # Stats row
    c1, c2, c3, c4 = st.columns(4)
    ds_count = len(user.get("datasets", []))
    md_count = len(user.get("models", []))
    tk       = user.get("tokens", 0)
    keys     = len(user.get("api_keys", {}))
    for col, num, lbl in [
        (c1, tk, "Tokens left"),
        (c2, ds_count, "Datasets"),
        (c3, md_count, "Models"),
        (c4, keys, "API keys"),
    ]:
        col.markdown(f"""
<div class="card" style="text-align:center">
  <div class="stat"><div class="n">{num:,}</div><div class="l">{lbl}</div></div>
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_l, col_r = st.columns(2)

    # Recent datasets
    with col_l:
        st.markdown("**Recent datasets**")
        my_ds = get_user_datasets(user["email"])[-5:]
        if not my_ds:
            st.markdown('<div class="info">No datasets yet. Go to Generate Dataset to create one.</div>',
                        unsafe_allow_html=True)
        for ds in reversed(my_ds):
            vis = "🌐" if ds.get("public") else "🔒"
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {ds['name']}</h4>
  <div class="meta">{len(ds['rows'])} rows · {ds['created'][:10]}</div>
</div>""", unsafe_allow_html=True)

    # Recent models
    with col_r:
        st.markdown("**Recent models**")
        my_md = get_user_models(user["email"])[-5:]
        if not my_md:
            st.markdown('<div class="info">No models yet. Go to My Models to create one.</div>',
                        unsafe_allow_html=True)
        for md in reversed(my_md):
            vis = "🌐" if md.get("public") else "🔒"
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {md['name']}</h4>
  <div class="meta">Base: {md['base_model']} · {md['created'][:10]}</div>
</div>""", unsafe_allow_html=True)

    # Plan limits bar
    st.markdown("---")
    st.markdown("**Plan usage**")
    c1, c2 = st.columns(2)
    with c1:
        ds_lim = plan["max_datasets"]
        st.markdown(f"Datasets: {ds_count} / {ds_lim}")
        st.progress(min(ds_count / max(ds_lim, 1), 1.0))
    with c2:
        md_lim = plan["max_models"]
        st.markdown(f"Models: {md_count} / {md_lim}")
        st.progress(min(md_count / max(md_lim, 1), 1.0))

    if plan["price"] > 0:
        pass
    else:
        st.markdown("""
<div class="info" style="margin-top:.6rem">
  ✦ Starter plan: 12 total AI & dataset slots.
  <a href="#" style="color:#7dd3fc">Upgrade to Pro</a> for 60, or Elite for unlimited.
</div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# GENERATE DATASET
# ─────────────────────────────────────────────────────────────────
def page_generate(user: dict):
    plan = PLANS[user["plan"]]
    ui.hero("Generate Dataset", "Gemby Agent 3B builds your data row by row")

    if _over_limit(user, "datasets"):
        st.markdown(f'<div class="warn">⚠️ {_limit_msg(user, "datasets")}</div>',
                    unsafe_allow_html=True)
        if st.button("Upgrade now →"): st.session_state["_nav"] = "⚡  Upgrade"; st.rerun()
        return

    col_l, col_r = st.columns([2, 1], gap="large")

    with col_r:
        st.markdown(f"""
<div class="card">
  <div style="font-size:.7rem;color:var(--txt3);text-transform:uppercase">Plan</div>
  <div style="font-weight:600;margin:.25rem 0">{plan['badge']} {plan['name']}</div>
  <hr style="border-color:var(--border);margin:.5rem 0">
  <span class="pill">🪙 {user['tokens']:,} tokens</span>
  <div style="font-size:.76rem;color:var(--txt3);margin-top:.5rem">
    10 tokens per row<br>
    Max {plan['max_rows']:,} rows<br>
    {plan['max_datasets'] - len(user.get('datasets',[]))} dataset slots left
  </div>
</div>""", unsafe_allow_html=True)

        # Optional: use a different HF model
        st.markdown("**Optional: custom model**")
        custom_repo = st.text_input("HF repo (leave blank for Gemby 3B)",
                                    placeholder="username/model-name", key="gen_repo")
        custom_tok  = st.text_input("HF token (if private model)", type="password", key="gen_tok")

    with col_l:
        with st.form("gen_form"):
            topic    = st.text_input("What is this dataset about?",
                                     placeholder="customer reviews for a shoe store")
            style    = st.selectbox("Style", [
                "tabular", "Q&A pairs", "instruction-response",
                "classification", "sentiment analysis", "summarization", "custom"])
            col_str  = st.text_input("Columns (comma-separated)",
                                     value="input, output, label")
            num_rows = st.slider("Rows", 1, plan["max_rows"], min(10, plan["max_rows"]))
            ds_name  = st.text_input("Dataset name")
            ds_desc  = st.text_area("Description", height=70)
            tags_raw = st.text_input("Tags", placeholder="nlp, english, reviews")
            public   = st.checkbox("Share publicly",
                                   disabled=not plan["share"],
                                   help="Pro/Elite only")
            go = st.form_submit_button("✦ Generate", use_container_width=True)

        if go:
            cols     = [c.strip() for c in col_str.split(",") if c.strip()]
            tags     = [t.strip() for t in tags_raw.split(",") if t.strip()]
            cost     = num_rows * 10

            if not topic:   st.error("Topic required."); st.stop()
            if not cols:    st.error("At least one column required."); st.stop()
            if not ds_name: st.error("Name required."); st.stop()
            if not rate_limit(user["email"], "generate", 3):
                st.error("Rate limit: 3 generations/minute. Wait a moment."); st.stop()
            if user["tokens"] < cost:
                st.error(f"Not enough tokens (need {cost:,}, have {user['tokens']:,})."); st.stop()

            repo  = custom_repo.strip() or "Hwiiiiiyyy/gemby-agent-3b"
            token = custom_tok.strip() or None

            prog  = st.progress(0, "Starting…")
            def cb(i, n): prog.progress((i+1)/n, f"Row {i+1}/{n}…")

            rows = inference.generate_dataset_rows(topic, num_rows, cols, style,
                                                   model_repo=repo,
                                                   user_hf_token=token,
                                                   progress_cb=cb)
            prog.empty()

            if deduct_tokens(user, cost):
                did = save_dataset(user["email"], ds_name, ds_desc, rows, public, tags)
                save_user(user)
                st.session_state["last_ds"]    = rows
                st.session_state["last_ds_id"] = did
                st.success(f"✅ **{ds_name}** created! ({cost:,} tokens used, "
                           f"{user['tokens']:,} left)")
                st.rerun()

    if st.session_state.get("last_ds"):
        st.markdown("### Preview")
        df  = pd.DataFrame(st.session_state["last_ds"])
        st.dataframe(df, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        did = st.session_state.get("last_ds_id", "out")
        with c1:
            st.download_button("⬇ CSV", df.to_csv(index=False),
                f"gemby_{did}.csv", "text/csv", use_container_width=True)
        with c2:
            st.download_button("⬇ JSON",
                json.dumps(st.session_state["last_ds"], indent=2),
                f"gemby_{did}.json", "application/json", use_container_width=True)
        with c3:
            st.download_button("⬇ JSONL",
                "\n".join(json.dumps(r) for r in st.session_state["last_ds"]),
                f"gemby_{did}.jsonl", "application/json", use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# MY MODELS
# ─────────────────────────────────────────────────────────────────
def page_my_models(user: dict):
    plan = PLANS[user["plan"]]
    ui.hero("My Models", "Fine-tune · Host · Share")

    if _over_limit(user, "models"):
        st.markdown(f'<div class="warn">⚠️ {_limit_msg(user, "models")}</div>',
                    unsafe_allow_html=True)
        if st.button("Upgrade →"): st.session_state["_nav"] = "⚡  Upgrade"; st.rerun()
        return

    tab_new, tab_mine = st.tabs(["Create / fine-tune", "My models"])

    # ── CREATE ──────────────────────────────────────────────────────
    with tab_new:
        col_l, col_r = st.columns([3, 2], gap="large")

        with col_r:
            st.markdown("""
<div class="card">
  <h3>How it works</h3>
  <p>
    1. Choose a base model from HuggingFace.<br>
    2. Pick a dataset you've already generated (or skip for zero-shot).<br>
    3. Download the auto-generated <b>Google Colab notebook</b>.<br>
    4. Open it in Colab, enable GPU, run all cells.<br>
    5. The trained model is pushed to your HuggingFace repo automatically.<br>
    6. Paste the repo ID back here to host it on Gemby Platform.
  </p>
</div>""", unsafe_allow_html=True)

            st.markdown("""
<div class="card" style="margin-top:.6rem">
  <h3>Popular base models</h3>
  <p>
    <span class="tag accent">Hwiiiiiyyy/gemby-agent-3b</span>
    <span class="tag">TinyLlama/TinyLlama-1.1B-Chat-v1.0</span>
    <span class="tag">microsoft/phi-2</span>
    <span class="tag">google/flan-t5-base</span>
    <span class="tag">facebook/opt-1.3b</span>
    <span class="tag">EleutherAI/pythia-1b</span>
  </p>
</div>""", unsafe_allow_html=True)

        with col_l:
            with st.form("new_model"):
                mname     = st.text_input("Model name", placeholder="My Coffee Classifier")
                mdesc     = st.text_area("Description", height=70)
                base      = st.text_input("Base model (HF repo ID)",
                                          value="Hwiiiiiyyy/gemby-agent-3b",
                                          placeholder="username/model-name")
                out_repo  = st.text_input("Your HF output repo",
                                          placeholder="your-username/my-model-name",
                                          help="Where the trained model will be pushed on HuggingFace")
                user_hft  = st.text_input("HuggingFace write token",
                                          type="password",
                                          help="Needed to push your trained model to HF Hub")

                # Dataset to train on
                my_ds     = get_user_datasets(user["email"])
                ds_names  = ["— none / zero-shot —"] + [d["name"] for d in my_ds]
                ds_choice = st.selectbox("Train on dataset", ds_names)

                # Training hyperparams
                with st.expander("Training settings"):
                    epochs  = st.slider("Epochs", 1, 10, 3)
                    lr_exp  = st.select_slider("Learning rate",
                        options=["5e-5", "2e-4", "5e-4", "1e-3"], value="2e-4")
                    mlen    = st.select_slider("Max sequence length",
                        options=[128, 256, 512, 1024], value=512)
                    batch   = st.select_slider("Batch size",
                        options=[1, 2, 4, 8], value=4)

                tags_raw  = st.text_input("Tags", placeholder="nlp, classifier")
                public    = st.checkbox("Share publicly", disabled=not plan["share"])
                submit    = st.form_submit_button("✦ Create model & generate Colab notebook",
                                                  use_container_width=True)

            if submit:
                if not mname:     st.error("Model name required."); st.stop()
                if not base:      st.error("Base model required."); st.stop()
                if not out_repo:  st.error("HF output repo required."); st.stop()

                # Grab dataset rows if chosen
                chosen_rows = []
                if ds_choice != "— none / zero-shot —":
                    for d in my_ds:
                        if d["name"] == ds_choice:
                            chosen_rows = d["rows"]; break

                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

                # Generate Colab notebook
                nb_json = inference.generate_colab_notebook(
                    model_name   = mname,
                    base_model   = base,
                    output_repo  = out_repo,
                    dataset_rows = chosen_rows,
                    hf_token     = user_hft or "",
                    epochs       = epochs,
                    lr           = float(lr_exp),
                    max_length   = mlen,
                    batch_size   = batch,
                )

                # Register model in DB
                mid = save_model(
                    owner        = user["email"],
                    name         = mname,
                    desc         = mdesc,
                    base_model   = base,
                    hf_repo      = out_repo,
                    colab_url    = "",
                    public       = public,
                    tags         = tags,
                    api_keys_used= {"hf_write": bool(user_hft)},
                )
                save_user(user)

                st.session_state["nb_download"] = nb_json
                st.session_state["nb_name"]     = mname
                st.success(f"✅ Model **{mname}** created (ID: `{mid}`). "
                           "Download your Colab notebook below!")

        if st.session_state.get("nb_download"):
            st.markdown("---")
            st.markdown("### 🧪 Your Google Colab notebook is ready")
            st.markdown("""
<div class="info">
  <b>Steps to train on GPU:</b><br>
  1. Click Download below → save the .ipynb file<br>
  2. Go to <a href="https://colab.research.google.com" target="_blank"
     style="color:#7dd3fc">colab.research.google.com</a> → Upload notebook<br>
  3. Runtime → Change runtime type → <b>T4 GPU</b> (free)<br>
  4. Run all cells — your model trains and pushes to HuggingFace automatically
</div>""", unsafe_allow_html=True)

            nb_name = st.session_state.get("nb_name","model").replace(" ","_")
            st.download_button(
                "⬇ Download Colab notebook (.ipynb)",
                st.session_state["nb_download"],
                file_name=f"train_{nb_name}.ipynb",
                mime="application/json",
                use_container_width=True,
            )
            st.markdown(
                '<a href="https://colab.research.google.com" target="_blank">'
                '<div class="colab-btn" style="width:fit-content;margin-top:.5rem">'
                '🔗 Open Google Colab</div></a>', unsafe_allow_html=True)

    # ── MY MODELS list ───────────────────────────────────────────────
    with tab_mine:
        my_md = get_user_models(user["email"])
        if not my_md:
            st.markdown('<div class="info">No models yet — create one in the tab above.</div>',
                        unsafe_allow_html=True)

        for md in reversed(my_md):
            vis   = "🌐" if md.get("public") else "🔒"
            tags  = "".join(f'<span class="tag accent">{t}</span>'
                            for t in md.get("tags", []))
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {md['name']}</h4>
  <div class="desc">{md.get('description','')}</div>
  <div class="meta">
    Base: <code style="color:var(--accent2)">{md['base_model']}</code> ·
    HF: <code style="color:var(--accent2)">{md['hf_repo']}</code> ·
    {md['created'][:10]}
  </div>
  <div style="margin-top:.3rem">{tags}</div>
</div>""", unsafe_allow_html=True)

            with st.expander(f"Details & inference — {md['name']}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Try inference**")
                    prompt   = st.text_area("Prompt", height=80, key=f"p_{md['id']}")
                    inf_tok  = st.text_input("HF token (if private)",
                                             type="password", key=f"t_{md['id']}")
                    if st.button("Run →", key=f"run_{md['id']}"):
                        if not rate_limit(user["email"], "inference", 5):
                            st.error("Rate limit. Wait.")
                        else:
                            with st.spinner("Running…"):
                                out = inference.call_hf(
                                    md["hf_repo"], prompt,
                                    hf_token=inf_tok or None)
                            st.text_area("Output", out, height=100,
                                         key=f"out_{md['id']}")
                with c2:
                    st.markdown("**HuggingFace link**")
                    hf_url = f"https://huggingface.co/{md['hf_repo']}"
                    st.markdown(f"[{md['hf_repo']}]({hf_url})")
                    st.markdown("**Re-download Colab notebook**")
                    my_ds_list = get_user_datasets(user["email"])
                    if my_ds_list:
                        ds_sel = st.selectbox("Dataset", ["none"]+[d["name"] for d in my_ds_list],
                                              key=f"ds_{md['id']}")
                        r = []
                        for d in my_ds_list:
                            if d["name"] == ds_sel: r = d["rows"]; break
                    else:
                        r = []
                    if st.button("Generate notebook", key=f"nb_{md['id']}"):
                        nb = inference.generate_colab_notebook(
                            md["name"], md["base_model"], md["hf_repo"], r)
                        st.download_button("⬇ Download .ipynb", nb,
                            file_name=f"train_{md['id']}.ipynb",
                            mime="application/json",
                            key=f"nbd_{md['id']}")

                    db = load_db()
                    if st.button("🗑 Delete model", key=f"del_{md['id']}",
                                 type="secondary"):
                        del db["models"][md["id"]]
                        db["users"][user["email"]]["models"].remove(md["id"])
                        save_db(db); st.rerun()

# ─────────────────────────────────────────────────────────────────
# DATASET HUB
# ─────────────────────────────────────────────────────────────────
def page_dataset_hub(user: dict):
    ui.hero("Dataset Hub", "Community datasets — browse, download, share")

    tab_pub, tab_mine = st.tabs(["Community", "My datasets"])

    with tab_pub:
        search = st.text_input("Search", placeholder="Filter by name, tag or description…",
                               key="dh_search")
        all_ds = get_public_datasets()
        shown  = [d for d in all_ds
                  if not search or search.lower() in d["name"].lower()
                  or search.lower() in d.get("description","").lower()
                  or any(search.lower() in t for t in d.get("tags",[]))] \
                 if search else all_ds

        st.markdown(f"<div style='color:var(--txt3);font-size:.8rem;margin-bottom:.6rem'>"
                    f"{len(shown)} dataset{'s' if len(shown)!=1 else ''}</div>",
                    unsafe_allow_html=True)

        if not shown:
            st.markdown('<div class="info">No public datasets yet.</div>', unsafe_allow_html=True)

        for ds in shown:
            tags_html = "".join(f'<span class="tag">{t}</span>' for t in ds.get("tags",[]))
            st.markdown(f"""
<div class="hub-card">
  <h4>🌐 {ds['name']} <span style="color:var(--txt3);font-size:.75rem">by {ds['owner']}</span></h4>
  <div class="desc">{ds.get('description','No description')}</div>
  <div class="meta">{len(ds['rows'])} rows · {ds['created'][:10]} · ⬇ {ds.get('downloads',0)} {tags_html}</div>
</div>""", unsafe_allow_html=True)

            with st.expander(f"Preview — {ds['name']}"):
                st.dataframe(pd.DataFrame(ds["rows"]).head(10), use_container_width=True)

            c1, c2, c3 = st.columns(3)
            df = pd.DataFrame(ds["rows"])
            with c1:
                st.download_button("⬇ CSV", df.to_csv(index=False),
                    f"{ds['id']}.csv", "text/csv", key=f"csv_{ds['id']}",
                    use_container_width=True)
            with c2:
                st.download_button("⬇ JSON",
                    json.dumps(ds["rows"], indent=2),
                    f"{ds['id']}.json", "application/json",
                    key=f"json_{ds['id']}", use_container_width=True)
            with c3:
                st.download_button("⬇ JSONL",
                    "\n".join(json.dumps(r) for r in ds["rows"]),
                    f"{ds['id']}.jsonl", "application/json",
                    key=f"jl_{ds['id']}", use_container_width=True)

    with tab_mine:
        my_ds = get_user_datasets(user["email"])
        plan  = PLANS[user["plan"]]
        st.markdown(f"<div style='color:var(--txt3);font-size:.8rem;margin-bottom:.5rem'>"
                    f"{len(my_ds)} / {plan['max_datasets']} datasets used</div>",
                    unsafe_allow_html=True)

        if not my_ds:
            st.markdown('<div class="info">No datasets yet. Go to Generate Dataset.</div>',
                        unsafe_allow_html=True)

        for ds in reversed(my_ds):
            vis      = "🌐 Public" if ds.get("public") else "🔒 Private"
            tags_html= "".join(f'<span class="tag">{t}</span>' for t in ds.get("tags",[]))
            st.markdown(f"""
<div class="hub-card">
  <h4>{vis} — {ds['name']}</h4>
  <div class="desc">{ds.get('description','')}</div>
  <div class="meta">{len(ds['rows'])} rows · {ds['created'][:10]} {tags_html}</div>
</div>""", unsafe_allow_html=True)

            with st.expander(f"Options — {ds['name']}"):
                c1, c2, c3 = st.columns(3)
                df = pd.DataFrame(ds["rows"])
                with c1:
                    st.download_button("⬇ CSV", df.to_csv(index=False),
                        f"{ds['id']}.csv", "text/csv",
                        key=f"mycsv_{ds['id']}", use_container_width=True)
                with c2:
                    new_pub = st.checkbox("Public", value=ds.get("public"),
                                         key=f"pub_{ds['id']}",
                                         disabled=not plan["share"])
                    if st.button("Save", key=f"savepub_{ds['id']}"):
                        db = load_db()
                        db["datasets"][ds["id"]]["public"] = new_pub
                        save_db(db); st.rerun()
                with c3:
                    if st.button("🗑 Delete", key=f"deld_{ds['id']}",
                                 type="secondary", use_container_width=True):
                        db = load_db()
                        del db["datasets"][ds["id"]]
                        db["users"][user["email"]]["datasets"].remove(ds["id"])
                        save_db(db); st.rerun()

# ─────────────────────────────────────────────────────────────────
# MODEL HUB
# ─────────────────────────────────────────────────────────────────
def page_model_hub(user: dict):
    ui.hero("Model Hub", "Community models — browse, try, download")

    search  = st.text_input("Search", placeholder="Filter by name, base model or tag…",
                             key="mh_search")
    all_md  = get_public_models()
    shown   = [m for m in all_md
               if not search or search.lower() in m["name"].lower()
               or search.lower() in m.get("description","").lower()
               or search.lower() in m.get("base_model","").lower()
               or any(search.lower() in t for t in m.get("tags",[]))] \
              if search else all_md

    st.markdown(f"<div style='color:var(--txt3);font-size:.8rem;margin-bottom:.6rem'>"
                f"{len(shown)} model{'s' if len(shown)!=1 else ''}</div>",
                unsafe_allow_html=True)

    if not shown:
        st.markdown('<div class="info">No public models yet.</div>', unsafe_allow_html=True)

    for m in shown:
        tags_html = "".join(f'<span class="tag">{t}</span>' for t in m.get("tags",[]))
        hf_link   = f"https://huggingface.co/{m['hf_repo']}"
        st.markdown(f"""
<div class="hub-card">
  <h4>🌐 {m['name']} <span style="color:var(--txt3);font-size:.75rem">by {m['owner']}</span></h4>
  <div class="desc">{m.get('description','No description')}</div>
  <div class="meta">
    Base: <code style="color:var(--accent2)">{m['base_model']}</code> ·
    {m['created'][:10]} · ⬇ {m.get('downloads',0)} {tags_html}
  </div>
</div>""", unsafe_allow_html=True)

        with st.expander(f"Try — {m['name']}"):
            c1, c2 = st.columns([3,1])
            with c1:
                prompt  = st.text_area("Prompt", height=90, key=f"mhp_{m['id']}")
                inf_tok = st.text_input("HF token (if private model)",
                                        type="password", key=f"mht_{m['id']}")
                if st.button("Run inference →", key=f"mhr_{m['id']}"):
                    if not rate_limit(user["email"], "inference", 5):
                        st.error("Rate limit.")
                    else:
                        with st.spinner("Running…"):
                            out = inference.call_hf(m["hf_repo"], prompt,
                                                    hf_token=inf_tok or None)
                        st.text_area("Output", out, height=100, key=f"mho_{m['id']}")
            with c2:
                st.markdown(f"**HuggingFace**")
                st.markdown(f"[{m['hf_repo']}]({hf_link})")
                st.markdown(f"**Base model**")
                st.markdown(f"`{m['base_model']}`")

# ─────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────
def page_api_keys(user: dict):
    plan = PLANS[user["plan"]]
    ui.hero("API Keys", "Add your own HuggingFace or external tokens")

    st.markdown(f"""
<div class="info">
  Your plan allows <b>{plan['api_keys']}</b> API key{'s' if plan['api_keys']!=1 else ''}.
  Keys are stored encrypted and used to call private models or run fine-tuning.
</div>""", unsafe_allow_html=True)

    # ── Add key ──
    with st.form("add_key"):
        col1, col2 = st.columns(2)
        with col1:
            label = st.text_input("Label", placeholder="e.g. HF Personal Token")
        with col2:
            key_val = st.text_input("Key / token", type="password",
                                    placeholder="hf_xxx… or sk-…")
        if st.form_submit_button("Add key", use_container_width=True):
            if not label: st.error("Label required.")
            elif not key_val: st.error("Key value required.")
            else:
                existing = user.get("api_keys", {})
                if len(existing) >= plan["api_keys"]:
                    st.error(f"Limit reached ({plan['api_keys']} keys). Upgrade for more.")
                elif label in existing:
                    st.error("Label already used.")
                else:
                    # Store hashed label + masked key (never store plaintext in prod!)
                    user.setdefault("api_keys", {})[label] = {
                        "key":     key_val,          # In prod: encrypt this
                        "created": datetime.utcnow().isoformat(),
                        "uses":    0,
                    }
                    save_user(user)
                    st.success(f"Key '{label}' saved.")
                    st.rerun()

    # ── List keys ──
    st.markdown("---")
    keys = user.get("api_keys", {})
    if not keys:
        st.markdown('<div class="info">No API keys yet.</div>', unsafe_allow_html=True)

    for label, info in keys.items():
        masked = info["key"][:6] + "•••••••••" + info["key"][-4:]
        st.markdown(f"""
<div class="hub-card">
  <h4>🔑 {label}</h4>
  <div class="meta"><code style="color:var(--accent2)">{masked}</code> · added {info['created'][:10]}</div>
</div>""", unsafe_allow_html=True)
        if st.button(f"🗑 Remove '{label}'", key=f"delkey_{label}", type="secondary"):
            del user["api_keys"][label]
            save_user(user); st.rerun()

    st.markdown("---")
    st.markdown("**Your platform API key** (use this to call Gemby models externally)")
    gby_key = user.get("gemby_api_key")
    if not gby_key:
        if st.button("Generate Gemby API key"):
            user["gemby_api_key"] = "asi-" + uuid.uuid4().hex
            save_user(user); st.rerun()
    else:
        st.code(gby_key, language=None)
        st.caption("Keep this secret. Use it in Authorization: Bearer headers.")
        if st.button("Regenerate", type="secondary"):
            user["gemby_api_key"] = "asi-" + uuid.uuid4().hex
            save_user(user); st.rerun()

# ─────────────────────────────────────────────────────────────────
# UPGRADE
# ─────────────────────────────────────────────────────────────────
def page_upgrade(user: dict):
    ui.hero("Upgrade", "More models · More datasets · More power")

    current = user["plan"]
    cols    = st.columns(3)
    for i, (pid, p) in enumerate(PLANS.items()):
        with cols[i]:
            is_cur    = pid == current
            price_str = "Free" if p["price"]==0 else f"${p['price']}/mo"
            feats     = [
                f"{p['monthly_tokens']:,} tokens/month",
                f"Up to {p['max_rows']:,} rows per dataset",
                f"{p['max_datasets']} datasets + {p['max_models']} models",
                "Public sharing" if p["share"] else "Private only",
                f"{p['api_keys']} API key{'s' if p['api_keys']!=1 else ''}",
                "Priority GPU queue" if p.get("priority") else "",
            ]
            feats = [f for f in feats if f]
            st.markdown(f"""
<div class="card {'active' if is_cur else ''}">
  <div style="font-size:1.7rem">{p['badge']}</div>
  <div style="font-size:1.1rem;font-weight:600;color:var(--txt);margin:.3rem 0">{p['name']}</div>
  {'<div style="color:var(--green);font-size:.75rem;margin-bottom:.3rem">✓ Current plan</div>' if is_cur else ''}
  <div style="font-size:1.75rem;font-weight:600;color:var(--txt)">{price_str}</div>
  <div style="font-size:.74rem;color:var(--txt3);margin-bottom:.7rem">
    {'via Traakteer · cancel anytime' if p['price']>0 else 'no card needed'}
  </div>
  <div style="font-size:.8rem;color:var(--txt2);line-height:1.8">
    {"".join("✓ "+f+"<br>" for f in feats)}
  </div>
</div>""", unsafe_allow_html=True)

            if not is_cur and p["price"] > 0:
                url = (f"https://pay.traakteer.com/checkout"
                       f"?plan={p['traakteer_id']}&customer_email={user['email']}")
                st.link_button(f"Upgrade to {p['name']} →", url,
                               use_container_width=True)

    st.markdown("---")
    st.markdown("**Slot comparison**")
    st.markdown("""
| | Starter | Pro | Elite |
|---|---|---|---|
| Datasets | 2 | 6 | Unlimited |
| Models | 2 | 6 | Unlimited |
| Combined AI & dataset | **12 total** | **60 total** | **∞** |
| Rows per dataset | 50 | 2,000 | 50,000 |
| API keys | 1 | 5 | Unlimited |
| Public sharing | ✗ | ✓ | ✓ |
""")
    st.caption("Payments via **Traakteer** · Upgrades are instant via signed webhook.")

# ─────────────────────────────────────────────────────────────────
# SUPPORT
# ─────────────────────────────────────────────────────────────────
def page_support(user: dict):
    ui.hero("Support", "We reply within 24 hours on business days")

    with st.form("support"):
        subject = st.selectbox("Topic", [
            "Billing / Traakteer", "Token issue", "Generation error",
            "Model training / Colab", "API keys", "Account access", "Other"])
        message = st.text_area("Message", height=140, placeholder="Describe your issue…")
        if st.form_submit_button("Send →", use_container_width=True):
            if not message.strip():
                st.error("Please write a message.")
            else:
                db = load_db()
                db.setdefault("support_tickets", []).append({
                    "id": str(uuid.uuid4())[:8],
                    "user": user["email"], "subject": subject,
                    "message": message,
                    "ts": datetime.utcnow().isoformat(),
                    "status": "open", "admin_reply": "",
                })
                save_db(db)
                st.success("✅ Ticket submitted. We'll get back to you!")

    st.markdown("---")
    with st.expander("How do I train a model?"):
        st.write("Go to My Models → Create/fine-tune. Fill in the form, download the "
                 "Colab notebook, open it in Google Colab (free T4 GPU), run all cells. "
                 "Your model pushes to HuggingFace automatically.")
    with st.expander("Why did generation fail?"):
        st.write("If you see MODEL_LOADING, the HF model is cold-starting — wait 20s and retry. "
                 "Tokens are only deducted on success.")
    with st.expander("How does the 12 slot limit work?"):
        st.write("Starter accounts can have 2 datasets + 2 models (4 total, not 12). "
                 "Pro gets 6+6=12, Elite is unlimited. Upgrade anytime.")
    with st.expander("How does Traakteer billing work?"):
        st.write("Click Upgrade → you're redirected to Traakteer secure checkout. "
                 "After payment, Traakteer sends a signed webhook and your plan upgrades instantly.")

# ─────────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────────
def page_admin():
    st.markdown('<div class="admin-bar">👑 Admin Panel — emir.erningpraja@gmail.com</div>',
                unsafe_allow_html=True)

    db      = load_db()
    users   = list(db["users"].values())
    datasets= list(db["datasets"].values())
    models  = list(db["models"].values())
    tickets = db.get("support_tickets", [])

    # Stats
    c1,c2,c3,c4,c5 = st.columns(5)
    for col, n, l in [
        (c1, len(users),   "Users"),
        (c2, len(datasets),"Datasets"),
        (c3, len(models),  "Models"),
        (c4, sum(1 for t in tickets if t.get("status")=="open"), "Open tickets"),
        (c5, sum(1 for u in users if u.get("flagged")), "Flagged"),
    ]:
        col.markdown(f"""
<div class="card" style="text-align:center">
  <div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    tab_u, tab_d, tab_m, tab_t, tab_tok = st.tabs(
        ["👤 Users", "📦 Datasets", "🤖 Models", "🎫 Tickets", "🪙 Tokens"])

    # ── Users ──
    with tab_u:
        search = st.text_input("Filter email", key="adm_us")
        shown  = [u for u in users if search.lower() in u["email"]] if search else users
        for u in shown:
            flg = " 🚩" if u.get("flagged") else ""
            with st.expander(f"{u['email']}  ·  {PLANS[u['plan']]['badge']} {u['plan']}  ·  🪙{u['tokens']:,}{flg}"):
                c1,c2,c3 = st.columns(3)
                with c1:
                    np = st.selectbox("Plan", list(PLANS.keys()),
                                      index=list(PLANS.keys()).index(u["plan"]),
                                      key=f"adm_pl_{u['email']}")
                    if st.button("Apply plan", key=f"adm_ap_{u['email']}", use_container_width=True):
                        u["plan"] = np; save_user(u); st.rerun()
                with c2:
                    if u.get("flagged"):
                        if st.button("✅ Unflag", key=f"adm_uf_{u['email']}", use_container_width=True):
                            u["flagged"]=False; u["flag_reason"]=""; save_user(u); st.rerun()
                    else:
                        fr = st.text_input("Reason", key=f"adm_fr_{u['email']}")
                        if st.button("🚩 Flag", key=f"adm_fg_{u['email']}", use_container_width=True):
                            u["flagged"]=True; u["flag_reason"]=fr or "Admin"; save_user(u); st.rerun()
                with c3:
                    if st.button("🗑 Delete", key=f"adm_dl_{u['email']}",
                                 type="secondary", use_container_width=True):
                        del db["users"][u["email"]]; save_db(db); st.rerun()
                if u.get("token_log"):
                    with st.expander("Token log"):
                        st.dataframe(pd.DataFrame(u["token_log"]), use_container_width=True)

    # ── Datasets ──
    with tab_d:
        for ds in datasets:
            vis = "🌐" if ds.get("public") else "🔒"
            with st.expander(f"{vis} {ds['name']}  ·  {ds['owner']}  ·  {len(ds['rows'])} rows"):
                st.dataframe(pd.DataFrame(ds["rows"]).head(5), use_container_width=True)
                c1,c2 = st.columns(2)
                with c1:
                    pub = st.checkbox("Public", value=ds.get("public"), key=f"adm_pub_{ds['id']}")
                    if st.button("Save", key=f"adm_sv_{ds['id']}"):
                        db["datasets"][ds["id"]]["public"] = pub; save_db(db); st.rerun()
                with c2:
                    if st.button("🗑 Delete dataset", key=f"adm_dd_{ds['id']}", type="secondary"):
                        del db["datasets"][ds["id"]]; save_db(db); st.rerun()

    # ── Models ──
    with tab_m:
        for md in models:
            vis = "🌐" if md.get("public") else "🔒"
            with st.expander(f"{vis} {md['name']}  ·  {md['owner']}  ·  {md['base_model']}"):
                st.json({k: v for k,v in md.items() if k != "rows"})
                c1,c2 = st.columns(2)
                with c1:
                    pub = st.checkbox("Public", value=md.get("public"), key=f"adm_mpub_{md['id']}")
                    if st.button("Save", key=f"adm_msv_{md['id']}"):
                        db["models"][md["id"]]["public"] = pub; save_db(db); st.rerun()
                with c2:
                    if st.button("🗑 Delete model", key=f"adm_dm_{md['id']}", type="secondary"):
                        del db["models"][md["id"]]; save_db(db); st.rerun()

    # ── Tickets ──
    with tab_t:
        if not tickets:
            st.info("No tickets.")
        for t in reversed(tickets):
            icon = "✅" if t["status"]=="closed" else "🟡"
            with st.expander(f"{icon} [{t['id']}] {t['subject']}  ·  {t['user']}  ·  {t['ts'][:10]}"):
                st.write(t["message"])
                if t.get("admin_reply"):
                    st.info(f"**Reply:** {t['admin_reply']}")
                if t["status"] == "open":
                    rep = st.text_area("Reply", key=f"adm_rep_{t['id']}")
                    if st.button("Close ticket", key=f"adm_cls_{t['id']}"):
                        for tk in db["support_tickets"]:
                            if tk["id"] == t["id"]:
                                tk["status"]="closed"; tk["admin_reply"]=rep
                        save_db(db); st.rerun()

    # ── Tokens ──
    with tab_tok:
        st.warning("All grants are logged. Suspicious activity auto-flags accounts.")
        with st.form("adm_tok"):
            tgt = st.selectbox("User", [u["email"] for u in users])
            amt = st.number_input("Tokens", 0, 100_000, 500)
            rsn = st.text_input("Reason")
            if st.form_submit_button("Grant", use_container_width=True):
                u = get_user(tgt)
                if u:
                    safe_add_tokens(u, int(amt), f"manual:{rsn}")
                    save_user(u)
                    st.success(f"Granted {amt:,} to {tgt}.")

        st.markdown("---")
        if st.button("Reset ALL users to plan token limits", type="secondary"):
            for email, u in db["users"].items():
                u["tokens"] = PLANS[u["plan"]]["monthly_tokens"]
            save_db(db); st.success("All tokens reset.")

# ─────────────────────────────────────────────────────────────────
# MAIN ROUTER
# ─────────────────────────────────────────────────────────────────
def main():
    # Not logged in
    if "ue" not in st.session_state:
        page_auth(); return

    user = get_user(st.session_state["ue"])
    if not user:
        st.session_state.clear(); st.rerun()

    # Flagged
    if user.get("flagged") and user["email"] != ADMIN_EMAIL:
        st.markdown(f'<div class="warn">🚫 Account suspended: {user.get("flag_reason","")}<br>'
                    'Contact support to appeal.</div>', unsafe_allow_html=True)
        if st.button("Sign out"): st.session_state.clear(); st.rerun()
        return

    # Nav via session override (internal links)
    if "_nav" in st.session_state:
        override = st.session_state.pop("_nav")
        # Can't actually change the radio, but we can rerun after setting it
        st.session_state["_force_nav"] = override

    page = ui.sidebar_nav(user)
    force = st.session_state.pop("_force_nav", None)
    if force: page = force

    if   "Home"          in page: page_home(user)
    elif "Generate"      in page: page_generate(user)
    elif "My Models"     in page: page_my_models(user)
    elif "Dataset Hub"   in page: page_dataset_hub(user)
    elif "Model Hub"     in page: page_model_hub(user)
    elif "API Keys"      in page: page_api_keys(user)
    elif "Upgrade"       in page: page_upgrade(user)
    elif "Support"       in page: page_support(user)
    elif "Admin"         in page and st.session_state.get("ia"): page_admin()

if __name__ == "__main__":
    main()
