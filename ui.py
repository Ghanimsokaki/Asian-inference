"""ui.py — CSS, sidebar, shared components for Asian Inference"""
import streamlit as st
from core import PLANS, ADMIN_EMAIL, APP_NAME

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;1,14..32,400&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:       #06060f;
  --s1:       #0c0c1e;
  --s2:       #111128;
  --s3:       #181838;
  --b1:       #1c1c40;
  --b2:       #252558;
  --txt:      #e2e4f0;
  --txt2:     #7880a4;
  --txt3:     #3d4270;
  --acc:      #5b6ef5;
  --acc2:     #818cf8;
  --acc3:     #c7d2fe;
  --grn:      #34d399;
  --red:      #f87171;
  --amb:      #fbbf24;
  --r:        12px;
  --r2:       18px;
}

*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: var(--bg) !important; color: var(--txt); }

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background: #040410 !important; border-right: 1px solid var(--b1); }
section[data-testid="stSidebar"] .stRadio label { color: var(--txt2) !important; font-size: .88rem; padding: .35rem .5rem; border-radius: 8px; transition: background .15s; }
section[data-testid="stSidebar"] .stRadio label:hover { background: var(--s2) !important; color: var(--txt) !important; }

/* ── Inputs ── */
input, textarea, .stTextInput input, .stTextArea textarea {
  background: var(--s2) !important;
  border: 1px solid var(--b1) !important;
  color: var(--txt) !important;
  border-radius: var(--r) !important;
  font-family: 'Inter', sans-serif !important;
}
input:focus, textarea:focus { border-color: var(--acc) !important; box-shadow: 0 0 0 3px #5b6ef520 !important; }
.stSelectbox > div > div { background: var(--s2) !important; border: 1px solid var(--b1) !important; border-radius: var(--r) !important; }

/* ── Forms ── */
div[data-testid="stForm"] { background: var(--s1); border: 1px solid var(--b1); border-radius: var(--r2); padding: 1.6rem; }

/* ── Buttons ── */
.stButton > button {
  background: var(--acc) !important;
  color: #fff !important;
  border: none !important;
  border-radius: var(--r) !important;
  font-weight: 500 !important;
  font-size: .88rem !important;
  padding: .5rem 1.2rem !important;
  transition: all .15s !important;
  letter-spacing: .01em;
}
.stButton > button:hover { background: #6b7ff7 !important; transform: translateY(-1px); box-shadow: 0 4px 20px #5b6ef540; }
.stButton > button:active { transform: translateY(0); }
.stButton > button[kind="secondary"] {
  background: var(--s2) !important;
  border: 1px solid var(--b2) !important;
  color: var(--txt2) !important;
}
.stButton > button[kind="secondary"]:hover { background: var(--s3) !important; color: var(--txt) !important; }
.stLinkButton > a {
  background: var(--acc) !important;
  color: #fff !important;
  border-radius: var(--r) !important;
  font-weight: 500 !important;
  border: none !important;
  text-decoration: none !important;
  transition: all .15s !important;
}
.stLinkButton > a:hover { background: #6b7ff7 !important; transform: translateY(-1px); }

/* ── Tabs ── */
div[data-baseweb="tab-list"] { background: transparent !important; border-bottom: 1px solid var(--b1) !important; gap: .25rem; }
button[data-baseweb="tab"] { background: transparent !important; border: none !important; color: var(--txt2) !important; font-size: .88rem !important; padding: .6rem 1rem !important; border-radius: var(--r) var(--r) 0 0 !important; }
button[data-baseweb="tab"]:hover { background: var(--s2) !important; color: var(--txt) !important; }
button[data-baseweb="tab"][aria-selected="true"] { background: var(--s2) !important; color: var(--acc2) !important; border-bottom: 2px solid var(--acc) !important; font-weight: 500 !important; }

/* ── Expander ── */
details { background: var(--s1) !important; border: 1px solid var(--b1) !important; border-radius: var(--r) !important; }
summary { color: var(--txt2) !important; font-size: .88rem !important; }

/* ── Metrics ── */
div[data-testid="metric-container"] { background: var(--s1); border: 1px solid var(--b1); border-radius: var(--r); padding: .9rem 1.1rem; }
div[data-testid="metric-container"] label { color: var(--txt3) !important; font-size: .75rem !important; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: var(--txt) !important; font-weight: 600; }

/* ── Progress ── */
div[data-testid="stProgressBar"] > div { background: var(--b1) !important; border-radius: 999px !important; }
div[data-testid="stProgressBar"] > div > div { background: linear-gradient(90deg, var(--acc), var(--acc2)) !important; border-radius: 999px !important; }

/* ── Slider ── */
div[data-testid="stSlider"] div[role="slider"] { background: var(--acc) !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--b2); border-radius: 999px; }

/* ── Custom components ── */
.hero {
  background: linear-gradient(135deg, #0a0a22 0%, #0d0d2e 50%, #080820 100%);
  border: 1px solid var(--b2);
  border-radius: var(--r2);
  padding: 2.6rem 3rem 2.2rem;
  margin-bottom: 1.8rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: '';
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% 0%, #5b6ef512 0%, transparent 70%);
  pointer-events: none;
}
.hero h1 {
  font-size: 2.2rem; font-weight: 600; letter-spacing: -.04em;
  background: linear-gradient(120deg, #a5b4fc 0%, #818cf8 40%, #e0e7ff 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin: 0 0 .5rem; line-height: 1.2;
}
.hero p { color: var(--txt2); font-size: .92rem; margin: 0; line-height: 1.6; }
.hero .badge { display: inline-block; background: #1a1a40; border: 1px solid var(--b2);
  border-radius: 999px; padding: .2rem .9rem; font-size: .75rem; color: var(--acc2);
  margin-bottom: .8rem; letter-spacing: .05em; text-transform: uppercase; }

.card {
  background: var(--s1); border: 1px solid var(--b1);
  border-radius: var(--r2); padding: 1.3rem 1.5rem;
  margin-bottom: .7rem; transition: border-color .18s, box-shadow .18s;
}
.card:hover { border-color: var(--b2); }
.card.glow { border-color: var(--acc); box-shadow: 0 0 0 1px #5b6ef520, 0 4px 30px #5b6ef512; }

.plan-card {
  background: var(--s1); border: 1px solid var(--b1);
  border-radius: var(--r2); padding: 1.6rem 1.4rem;
  height: 100%; transition: all .2s; position: relative; overflow: hidden;
}
.plan-card:hover { border-color: var(--b2); transform: translateY(-2px); box-shadow: 0 8px 40px #00000040; }
.plan-card.current { border-color: var(--acc); box-shadow: 0 0 0 1px #5b6ef530; }
.plan-card.popular::before {
  content: 'MOST POPULAR';
  position: absolute; top: 0; right: 0;
  background: var(--acc); color: #fff;
  font-size: .65rem; font-weight: 600; letter-spacing: .08em;
  padding: .25rem .7rem; border-radius: 0 var(--r2) 0 var(--r);
}

.hub-card {
  background: var(--s1); border: 1px solid var(--b1);
  border-radius: var(--r2); padding: 1.2rem 1.4rem;
  margin-bottom: .6rem; transition: border-color .18s;
}
.hub-card:hover { border-color: var(--b2); }
.hub-card h4 { margin: 0 0 .3rem; font-size: .97rem; font-weight: 600; color: var(--txt); }
.hub-card .desc { font-size: .83rem; color: var(--txt2); margin-bottom: .4rem; line-height: 1.5; }
.hub-card .meta { font-size: .75rem; color: var(--txt3); }

/* Chat bubble styles */
.chat-wrap { display: flex; flex-direction: column; gap: .8rem; margin: 1rem 0; }
.bubble { max-width: 80%; padding: .75rem 1rem; border-radius: var(--r2); font-size: .88rem; line-height: 1.6; }
.bubble.user { background: var(--acc); color: #fff; align-self: flex-end; border-radius: var(--r2) var(--r2) 4px var(--r2); }
.bubble.bot  { background: var(--s2); color: var(--txt); align-self: flex-start; border-radius: var(--r2) var(--r2) var(--r2) 4px; border: 1px solid var(--b1); }
.bubble .sender { font-size: .7rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; margin-bottom: .3rem; opacity: .7; }

.tag { display: inline-block; background: var(--s3); border: 1px solid var(--b2);
  border-radius: 999px; padding: .15rem .65rem; font-size: .72rem; color: var(--txt2); margin: .1rem; }
.tag.acc { background: #1a1a44; border-color: #3030a0; color: var(--acc2); }

.pill { display: inline-block; background: var(--s2); border: 1px solid var(--b1);
  border-radius: 999px; padding: .2rem .85rem; font-size: .78rem;
  color: var(--txt2); font-family: 'JetBrains Mono', monospace; }

.key-box { background: var(--s2); border: 1px solid var(--b2); border-radius: var(--r);
  padding: .7rem 1rem; font-family: 'JetBrains Mono', monospace; font-size: .82rem;
  color: var(--acc2); word-break: break-all; letter-spacing: .02em; }

.stat-num { font-size: 2rem; font-weight: 600; color: var(--txt); line-height: 1; }
.stat-lbl { font-size: .73rem; color: var(--txt3); margin-top: .25rem; text-transform: uppercase; letter-spacing: .05em; }

.note  { background: #0a1030; border: 1px solid #1a2060; border-radius: var(--r);
  padding: .65rem 1rem; color: #7dd3fc; font-size: .82rem; margin: .5rem 0; }
.warn  { background: #180808; border: 1px solid #4a1010; border-radius: var(--r);
  padding: .65rem 1rem; color: #fca5a5; font-size: .82rem; margin: .5rem 0; }
.ok    { background: #081808; border: 1px solid #104a10; border-radius: var(--r);
  padding: .65rem 1rem; color: #6ee7b7; font-size: .82rem; margin: .5rem 0; }

.admin-bar { background: linear-gradient(90deg,#3030a020,transparent 80%);
  border-left: 3px solid var(--acc); border-radius: 0 var(--r) var(--r) 0;
  padding: .5rem 1rem; color: var(--acc2); font-size: .8rem; margin-bottom: 1rem; }

.divider { border: none; border-top: 1px solid var(--b1); margin: 1.5rem 0; }

/* ── Streamlit overrides ── */
div[data-testid="stVerticalBlock"] { gap: .5rem; }
.stAlert { border-radius: var(--r) !important; font-size: .85rem !important; }
footer { display: none !important; }
#MainMenu { display: none !important; }
header { display: none !important; }
</style>
"""

def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)

def hero(title: str, sub: str = "", badge: str = ""):
    badge_html = f'<div class="badge">{badge}</div>' if badge else ""
    st.markdown(f"""
<div class="hero">
  {badge_html}
  <h1>{title}</h1>
  {'<p>' + sub + '</p>' if sub else ''}
</div>""", unsafe_allow_html=True)

def card(content_html: str, glow: bool = False):
    cls = "card glow" if glow else "card"
    st.markdown(f'<div class="{cls}">{content_html}</div>', unsafe_allow_html=True)

def tag(text: str, accent: bool = False) -> str:
    cls = "tag acc" if accent else "tag"
    return f'<span class="{cls}">{text}</span>'

def tags_html(tags: list, accent: bool = False) -> str:
    return "".join(tag(t, accent) for t in (tags or []))

def sidebar_nav(user: dict) -> str:
    plan = PLANS[user["plan"]]
    with st.sidebar:
        # Logo
        st.markdown(f"""
<div style="padding:1rem 0 .5rem;text-align:center">
  <div style="font-size:1.3rem;font-weight:700;letter-spacing:-.02em;
    background:linear-gradient(120deg,#a5b4fc,#818cf8);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent">
    ⚡ Asian Inference
  </div>
  <div style="font-size:.7rem;color:var(--txt3);margin-top:.1rem;letter-spacing:.08em">AI PLATFORM</div>
</div>""", unsafe_allow_html=True)

        st.markdown('<hr class="divider" style="margin:.5rem 0 1rem">', unsafe_allow_html=True)

        # User info
        st.markdown(f"""
<div style="background:var(--s2);border:1px solid var(--b1);border-radius:var(--r);
  padding:.85rem 1rem;margin-bottom:1rem">
  <div style="font-size:.7rem;color:var(--txt3);letter-spacing:.06em;text-transform:uppercase">Account</div>
  <div style="font-weight:600;color:var(--txt);margin:.2rem 0 .05rem;font-size:.92rem">
    {user.get('name') or 'User'}
  </div>
  <div style="font-size:.72rem;color:var(--txt3);margin-bottom:.5rem">{user['email']}</div>
  <span class="pill">🪙 {user['tokens']:,}</span>
  <span style="color:var(--txt3);font-size:.72rem;margin-left:.4rem">{plan['badge']} {plan['name']}</span>
</div>""", unsafe_allow_html=True)

        pages = [
            "🏠  Home",
            "💬  Dataset Chat",
            "🤖  My Models",
            "📦  Dataset Hub",
            "🌐  Model Hub",
            "🔑  API Keys",
            "⚡  Upgrade",
            "💬  Support",
        ]
        if user["email"] == ADMIN_EMAIL:
            pages.append("👑  Admin")

        choice = st.radio("Navigation", pages, label_visibility="collapsed")

        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True, type="secondary"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("""
<div style="font-size:.68rem;color:var(--txt3);text-align:center;margin-top:.5rem;line-height:1.6">
  ⚡ Asian Inference Platform<br>Powered by HuggingFace
</div>""", unsafe_allow_html=True)

    return choice

def plan_cards_auth():
    cols = st.columns(3)
    for i, (pid, p) in enumerate(PLANS.items()):
        with cols[i]:
            price = "Free" if p["price"] == 0 else f"${p['price']}/mo"
            feats = [
                f"{p['monthly_tokens']:,} tokens/month",
                f"Up to {p['max_rows']:,} rows/dataset",
                f"{p['max_datasets']} datasets · {p['max_models']} models",
                "Public sharing" if p["share"] else "Private only",
                f"{p['api_keys']} API key{'s' if p['api_keys'] != 1 else ''}",
            ]
            popular = ' popular' if i == 1 else ''
            cur = ' current' if i == 0 else ''
            feats_html = "".join(
                f'<div style="display:flex;align-items:center;gap:.4rem;'
                f'margin:.3rem 0;font-size:.82rem;color:var(--txt2)">'
                f'<span style="color:var(--grn)">✓</span>{f}</div>'
                for f in feats
            )
            st.markdown(f"""
<div class="plan-card{popular}{cur}">
  <div style="font-size:1.5rem;margin-bottom:.4rem">{p['badge']}</div>
  <div style="font-size:1rem;font-weight:600;color:var(--txt);margin-bottom:.3rem">{p['name']}</div>
  <div style="font-size:1.8rem;font-weight:700;color:var(--txt);line-height:1">{price}</div>
  <div style="font-size:.74rem;color:var(--txt3);margin-bottom:1rem">
    {'via Traakteer · cancel anytime' if p['price'] > 0 else 'forever free'}
  </div>
  {feats_html}
</div>""", unsafe_allow_html=True)
