"""ui.py — animated visual system, sidebar, shared components, and optional background audio helper.

This file provides CSS injection, hero and card helpers, sidebar navigation, plan cards
and a small floating audio player helper. It is written defensively to avoid
syntax issues when embedded HTML/JS is used.
"""
from typing import Optional
import streamlit as st
from core import PLANS, ADMIN_EMAIL
from streamlit.components.v1 import html as st_html

# Polished CSS with subtle animations and readable variables.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{
  --bg:#09090b;
  --panel:#151518;
  --panel2:#1b1b20;
  --line:#2b2b31;
  --line2:#404047;
  --text:#f4f4f5;
  --muted:#a1a1aa;
  --subtle:#71717a;
  --brand:#ff9d3d;
  --brand2:#ffb45e;
  --violet:#9b8cff;
  --cyan:#6bdcff;
  --green:#34d399;
  --radius:12px;
  --small:8px;
}
html,body,[class*=css]{font-family:Inter,sans-serif;background:var(--bg)!important;color:var(--text)}
section[data-testid=stSidebar]{background:linear-gradient(180deg, #08080a, #0c0c0f) !important;border-right:1px solid var(--line) !important}

/* Inputs */
input,textarea,.stTextInput input,.stTextArea textarea,[data-baseweb=select]>div{background:var(--panel2)!important;border:1px solid var(--line)!important;color:var(--text)!important;border-radius:10px}

/* Buttons */
.stButton>button{background:linear-gradient(90deg,var(--brand),var(--brand2))!important;color:#1a1208!important;border-radius:10px;border:none;padding:.6rem .9rem;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.45);transition:transform .18s cubic-bezier(.2,.9,.2,1),box-shadow .18s}
.stButton>button[kind=secondary]{background:transparent!important;border:1px solid var(--line);color:var(--subtle)!important}
/* Hover: float + aura */
.stButton>button:hover{transform:translateY(-6px) scale(1.02);box-shadow:0 18px 40px rgba(107,61,252,0.14),0 6px 18px rgba(0,0,0,.5)}
.stButton>button:focus{outline:none;box-shadow:0 12px 30px rgba(107,61,252,0.12)}

/* Hero */
.hero{position:relative;overflow:hidden;min-height:160px;display:flex;flex-direction:column;justify-content:flex-end;padding:1.6rem;border-radius:16px;background:linear-gradient(135deg,#0f0f12 0%, #121216 60%);border:1px solid rgba(255,255,255,0.02)}
.hero h1{font-family:'Space Grotesk',sans-serif;font-size:2rem;margin:0;background:linear-gradient(90deg,var(--violet),var(--brand2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{color:var(--muted);margin:.35rem 0 1rem}
.hero .badge{position:absolute;right:1rem;top:1rem;background:linear-gradient(90deg,var(--brand),var(--violet));padding:.45rem .7rem;border-radius:999px;font-weight:700;color:#120a05;box-shadow:0 6px 18px rgba(0,0,0,.45);transform:translateY(-2px)}

/* Cards */
.card,.hub-card,.plan-card{background:linear-gradient(145deg,#141417,#0f0f11);border:1px solid var(--line);border-radius:12px;padding:1rem;margin-bottom:.75rem}

/* Hub card */
.hub-card h4{margin:0;font-size:1rem}
.hub-card .meta{color:var(--subtle);font-size:.82rem}
.hub-card .desc{color:var(--muted);font-size:0.9rem;margin-top:.35rem}

/* Chat bubbles */
.chat-wrap{display:flex;flex-direction:column;gap:.6rem;margin:.6rem 0}
.bubble{max-width:86%;padding:.7rem .9rem;border-radius:12px;font-size:.92rem;line-height:1.5;animation:rise .28s cubic-bezier(.2,.9,.2,1)}
.bubble.user{align-self:flex-end;background:linear-gradient(90deg,var(--brand),var(--brand2));color:#1a1208}
.bubble.assistant{align-self:flex-start;background:#111217;color:var(--text);border:1px solid var(--line2)}

@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* small text */
.small{font-size:.78rem;color:var(--subtle)}

/* floating audio control */
.bg-audio-ctl{position:fixed;right:18px;bottom:18px;z-index:9999;display:flex;gap:.5rem;align-items:center}
.bg-audio-ctl button{background:transparent;border-radius:999px;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;color:var(--text);backdrop-filter:blur(4px);box-shadow:0 8px 20px rgba(0,0,0,.45)}
.bg-audio-ctl button:hover{transform:translateY(-6px);box-shadow:0 18px 40px rgba(107,61,252,0.12)}
.bg-audio-ctl .label{font-size:.78rem;color:var(--muted);padding:.35rem .6rem;border-radius:999px;background:linear-gradient(90deg,#ffffff05,#ffffff02)}
</style>
"""


def inject_css() -> None:
    """Inject the shared CSS into the Streamlit app."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, sub: str = "", badge: str = "") -> None:
    """Render a hero banner with optional badge."""
    badge_html = f'<div class="badge">{badge}</div>' if badge else ""
    st.markdown(f'<div class="hero">{badge_html}<h1>{title}</h1>{("<p>"+sub+"</p>") if sub else ""}</div>', unsafe_allow_html=True)


def card(content_html: str, glow: bool = False) -> None:
    class_name = "card glow" if glow else "card"
    st.markdown(f'<div class="{class_name}">{content_html}</div>', unsafe_allow_html=True)


def tag(text: str, accent: bool = False) -> str:
    cls = "tag acc" if accent else "tag"
    return f'<span class="{cls}">{text}</span>'


def tags_html(tags: list, accent: bool = False) -> str:
    return "".join(tag(t, accent) for t in (tags or []))


def sidebar_nav(user: dict) -> str:
    """Render the sidebar navigation and return the chosen page label."""
    plan = PLANS[user["plan"]]
    with st.sidebar:
        st.markdown(
            '''
            <div style="padding:.55rem 0 1rem;text-align:left">
              <div style="display:flex;align-items:center;gap:.55rem;font-family:'Space Grotesk';font-size:1.1rem;font-weight:700">
                ✦ <div style="font-size:0.95rem;margin-left:.2rem">Asian Inference</div>
              </div>
            </div>
            ''', unsafe_allow_html=True)

        st.markdown(
            f'''
            <div style="background:linear-gradient(145deg,#ff9d3d12,#15151880);border:1px solid var(--line);border-radius:8px;padding:.75rem .9rem;margin-bottom:1rem">
              <div style="font-size:.75rem;color:var(--subtle)">Plan</div>
              <div style="font-weight:700;margin-top:.28rem">{plan['badge']} {plan['name']}</div>
              <div style="margin-top:.5rem;font-size:.82rem;color:var(--muted)">🪙 {user['tokens']:,} tokens</div>
            </div>
            ''', unsafe_allow_html=True)

        pages = ["🏠  Home", "💬  Dataset Chat", "🤖  My Models", "📦  Dataset Hub", "🌐  Model Hub", "🔑  API Keys", "⚡  Upgrade", "💬  Support"]
        if user.get("email") == ADMIN_EMAIL:
            pages.append("👑  Admin")
        choice = st.radio("", pages, label_visibility="collapsed")
        st.markdown('<hr style="opacity:.06;margin:.6rem 0">', unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True, type="secondary"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.markdown('<div class="small" style="margin-top:.6rem">Private by default · built for builders</div>', unsafe_allow_html=True)
    return choice


def plan_cards_auth() -> None:
    cols = st.columns(3)
    for i, (pid, p) in enumerate(PLANS.items()):
        with cols[i]:
            price = "Free" if p["price"] == 0 else f"${p['price']}/mo"
            feats = [f"{p['monthly_tokens']:,} tokens/month", f"Up to {p['max_rows']:,} rows/dataset", f"{p['max_datasets']} datasets · {p['max_models']} models", "Public sharing" if p["share"] else "Private only"]
            classes = (' popular' if i == 1 else '') + (' current' if i == 0 else '')
            feats_html = ''.join(
                f'<div style="display:flex;align-items:center;gap:.5rem;margin:.35rem 0;font-size:.8rem;color:var(--muted)"><span style="color:var(--green)">✓</span>{feature}</div>'
                for feature in feats
            )
            st.markdown(
                f'''<div class="plan-card{classes}"><div style="font-size:1.45rem;margin-bottom:.45rem">{p['badge']}</div><div style="font-family:'Space Grotesk';font-size:1.05rem;font-weight:700">{p['name']}</div><div style="font-size:1.05rem;margin-top:.25rem;font-weight:600">{price}</div>{feats_html}</div>''',
                unsafe_allow_html=True,
            )
            btn_label = "Selected" if st.session_state.get("selected_plan") == pid else f"Choose {p['name']}"
            if st.button(btn_label, key=f"auth_plan_{pid}", use_container_width=True):
                st.session_state["selected_plan"] = pid
                st.rerun()


# Background audio helper
# Provide a calm music URL in Streamlit secrets as MUSIC_URL or pass url param.
# Usage: ui.inject_audio() or ui.inject_audio('https://example.com/mycalm.mp3')

def inject_audio(url: Optional[str] = None, autoplay: bool = False) -> None:
    """Render a floating audio control. Autoplay may be blocked by the browser.

    The function uses st.secrets['MUSIC_URL'] if url is not provided.
    """
    music = url or (st.secrets.get("MUSIC_URL") if hasattr(st, "secrets") else None)
    if not music:
        return

    # Small HTML + JS for a play/pause button. Keep it minimal and resilient.
    safe_html = f"""
<div class="bg-audio-ctl">
  <audio id="gemby-bg-audio" src="{music}" loop preload="none"></audio>
  <button id="gemby-audio-toggle" title="Play / pause">⏯️</button>
  <div class="label">Calm music</div>
</div>
<script>
(function(){
  try{
    const audio = document.getElementById('gemby-bg-audio');
    const btn = document.getElementById('gemby-audio-toggle');
    function update(){ btn.innerText = audio.paused ? '⏯️' : '⏸️'; }
    btn.addEventListener('click', function(){
      try{
        if(audio.paused){ audio.play(); } else { audio.pause(); }
        update();
      }catch(e){ console.log('audio error', e); }
    });
    // attempt autoplay if requested (may be blocked)
    if({"true" if autoplay else "false"}){
      audio.play().then(update).catch(function(e){console.log('autoplay blocked', e);});
    }
  }catch(e){ console.log('inject_audio init failed', e); }
})();
</script>
"""
    # Use streamlit.components.v1.html to inject the control.
    st_html(safe_html, height=80)
