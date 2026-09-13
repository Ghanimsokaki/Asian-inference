"""ui.py — shared styles, components, sidebar"""
import streamlit as st
from core import PLANS, ADMIN_EMAIL

# ── Palette & tokens ────────────────────────────────────────────────
# Deep indigo-slate base, violet accent, amber highlight for Elite
# Deliberately avoids the generic near-black + acid-green or cream + terracotta defaults

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:        #080810;
  --surface:   #0e0e1c;
  --surface2:  #141428;
  --border:    #1f1f38;
  --border2:   #2a2a50;
  --txt:       #dde1f0;
  --txt2:      #6b7194;
  --txt3:      #3d4166;
  --accent:    #6d5dfc;
  --accent2:   #9b8dff;
  --amber:     #f59e0b;
  --green:     #34d399;
  --red:       #f87171;
  --radius:    10px;
  --radius-lg: 16px;
}

html, body, [class*="css"] {
  font-family: 'Inter', sans-serif;
  background: var(--bg) !important;
  color: var(--txt);
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: #060612 !important;
  border-right: 1px solid var(--border);
}

/* Inputs */
input, textarea, select,
.stTextInput input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"] {
  background: var(--surface2) !important;
  border: 1px solid var(--border2) !important;
  color: var(--txt) !important;
  border-radius: var(--radius) !important;
}

/* Forms */
div[data-testid="stForm"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
}

/* Buttons */
.stButton > button {
  background: var(--accent) !important;
  color: #fff !important;
  border: none !important;
  border-radius: var(--radius) !important;
  font-weight: 500;
  transition: opacity .15s;
}
.stButton > button:hover { opacity: .85; }
.stButton > button[kind="secondary"] {
  background: var(--surface2) !important;
  border: 1px solid var(--border2) !important;
  color: var(--txt2) !important;
}

/* Tabs */
button[data-baseweb="tab"] {
  background: transparent !important;
  border-bottom: 2px solid transparent !important;
  color: var(--txt2) !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  border-bottom-color: var(--accent) !important;
  color: var(--txt) !important;
}

/* Metrics */
div[data-testid="metric-container"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: .8rem 1rem;
}

/* Progress */
div[data-testid="stProgressBar"] > div > div {
  background: var(--accent) !important;
}

/* ── Custom components ── */
.hero {
  background: linear-gradient(135deg, #0c0c24 0%, #101030 60%, #0a0a20 100%);
  border: 1px solid var(--border2);
  border-radius: var(--radius-lg);
  padding: 2.4rem 2.8rem 2rem;
  margin-bottom: 1.6rem;
  text-align: center;
}
.hero h1 {
  font-size: 2.1rem;
  font-weight: 600;
  letter-spacing: -.03em;
  background: linear-gradient(110deg, #a5b4fc 0%, #818cf8 40%, #c4b5fd 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0 0 .45rem;
}
.hero p { color: var(--txt2); font-size: .92rem; margin: 0; }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.2rem 1.4rem;
  margin-bottom: .75rem;
  transition: border-color .18s;
}
.card:hover { border-color: var(--border2); }
.card.active { border-color: var(--accent); background: #100e28; }

.card h3 { margin: 0 0 .2rem; font-size: 1rem; font-weight: 600; color: var(--txt); }
.card p  { margin: 0; font-size: .8rem; color: var(--txt2); line-height: 1.5; }

.tag {
  display: inline-block;
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: 999px;
  padding: .15rem .7rem;
  font-size: .72rem;
  color: var(--txt2);
  margin: .15rem .1rem;
}
.tag.accent { background: #1a1548; border-color: #3d35a0; color: var(--accent2); }

.pill {
  display: inline-block;
  background: #0e0e2a;
  border: 1px solid var(--border2);
  border-radius: 999px;
  padding: .2rem .85rem;
  font-size: .78rem;
  color: var(--txt2);
  font-family: 'JetBrains Mono', monospace;
}

.stat { text-align: center; }
.stat .n { font-size: 1.8rem; font-weight: 600; color: var(--txt); }
.stat .l { font-size: .75rem; color: var(--txt3); margin-top: .1rem; }

.warn  { background:#1c0a0a; border:1px solid #5b1c1c; border-radius:var(--radius);
         padding:.6rem 1rem; color:#fca5a5; font-size:.82rem; margin-bottom:.8rem; }
.info  { background:#0a1020; border:1px solid #1e3048; border-radius:var(--radius);
         padding:.6rem 1rem; color:#7dd3fc; font-size:.82rem; margin-bottom:.8rem; }
.ok    { background:#0a1a10; border:1px solid #1a4830; border-radius:var(--radius);
         padding:.6rem 1rem; color:#6ee7b7; font-size:.82rem; margin-bottom:.8rem; }

.admin-bar {
  background: linear-gradient(90deg,#2d1a7022,var(--bg) 80%);
  border-left: 3px solid var(--accent);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: .45rem 1rem;
  color: var(--accent2);
  font-size: .8rem;
  margin-bottom: 1rem;
}

/* Model / dataset hub cards */
.hub-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.1rem 1.3rem;
  margin-bottom: .6rem;
  display: flex;
  flex-direction: column;
  gap: .35rem;
}
.hub-card h4 { margin: 0; font-size: .97rem; font-weight: 600; color: var(--txt); }
.hub-card .meta { font-size: .76rem; color: var(--txt3); }
.hub-card .desc { font-size: .82rem; color: var(--txt2); }

.colab-btn {
  display: inline-flex; align-items: center; gap: .4rem;
  background: #f9ab00; color: #000;
  border-radius: var(--radius); padding: .35rem .9rem;
  font-size: .82rem; font-weight: 600;
  text-decoration: none;
}
</style>
"""

def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)

def hero(title: str, sub: str = ""):
    st.markdown(f"""
<div class="hero">
  <h1>{title}</h1>
  {'<p>' + sub + '</p>' if sub else ''}
</div>""", unsafe_allow_html=True)

def hub_card(name, owner, desc, tags, stats, is_public, extra_html=""):
    vis  = "🌐" if is_public else "🔒"
    tags_html = "".join(f'<span class="tag accent">{t}</span>' for t in (tags or []))
    st.markdown(f"""
<div class="hub-card">
  <h4>{vis} {name}</h4>
  <div class="desc">{desc or 'No description'}</div>
  <div class="meta">{stats} {tags_html}</div>
  {extra_html}
</div>""", unsafe_allow_html=True)

def plan_cards():
    cols = st.columns(3)
    for i, (pid, p) in enumerate(PLANS.items()):
        with cols[i]:
            price = "Free" if p["price"] == 0 else f"${p['price']}/mo"
            feats = [
                f"{p['monthly_tokens']:,} tokens/month",
                f"{p['max_rows']:,} max rows",
                f"{p['max_datasets']} datasets + {p['max_models']} models",
                "Public sharing" if p["share"] else "Private only",
                f"{p['api_keys']} API key{'s' if p['api_keys']!=1 else ''}",
            ]
            st.markdown(f"""
<div class="card {'active' if i==1 else ''}">
  <div style="font-size:1.6rem">{p['badge']}</div>
  <div style="font-size:1.05rem;font-weight:600;color:var(--txt);margin:.3rem 0">{p['name']}</div>
  <div style="font-size:1.7rem;font-weight:600;color:var(--txt)">{price}</div>
  <div style="font-size:.75rem;color:var(--txt3);margin-bottom:.7rem">
    {'via Traakteer · cancel anytime' if p['price']>0 else 'no card needed'}
  </div>
  <div style="font-size:.8rem;color:var(--txt2);line-height:1.8">
    {"".join("✓ "+f+"<br>" for f in feats)}
  </div>
</div>""", unsafe_allow_html=True)

def sidebar_nav(user: dict) -> str:
    plan = PLANS[user["plan"]]
    with st.sidebar:
        st.markdown(f"""
<div class="card" style="margin-bottom:1rem">
  <div style="font-size:.7rem;color:var(--txt3);text-transform:uppercase;letter-spacing:.06em">Account</div>
  <div style="font-weight:600;color:var(--txt);margin:.25rem 0 .1rem">{user.get('name') or user['email']}</div>
  <div style="font-size:.75rem;color:var(--txt3)">{user['email']}</div>
  <div style="margin-top:.6rem">
    <span class="pill">🪙 {user['tokens']:,}</span>
    <span style="color:var(--txt3);font-size:.74rem;margin-left:.4rem">{plan['badge']} {plan['name']}</span>
  </div>
</div>""", unsafe_allow_html=True)

        pages = [
            "🏠  Home",
            "⚙️  Generate Dataset",
            "🤖  My Models",
            "📦  Dataset Hub",
            "🌐  Model Hub",
            "🔑  API Keys",
            "⚡  Upgrade",
            "💬  Support",
        ]
        if user["email"] == ADMIN_EMAIL:
            pages.append("👑  Admin")

        choice = st.radio("", pages, label_visibility="collapsed")
        st.markdown("---")
        if st.button("Sign out", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
    return choice
