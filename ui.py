"""
ui.py — the shared visual system: design tokens, components and navigation.

Every class and custom property used anywhere in the app is defined here. The
previous stylesheet referenced one palette (``--text``, ``--brand``) while the
pages used another (``--txt``, ``--acc``, ``--grn``), so cards, notes, stats,
tags and chat bubbles rendered with undefined colours and no styling at all.

:func:`esc` is the other half of this module's job: user-supplied text is
escaped before it is ever placed into ``unsafe_allow_html`` markup.
"""
from __future__ import annotations

import html
import re
from typing import Iterable, Optional

import streamlit as st
from streamlit.components.v1 import html as st_html

from config import ADMIN_EMAIL, APP_NAME, PLANS, display_limit, plan_for

# ─────────────────────────────────────────────────────────────────────
# ESCAPING
# ─────────────────────────────────────────────────────────────────────
def esc(value: object) -> str:
    """Escape a value for safe interpolation into raw HTML.

    Dataset names, descriptions, tags and emails are attacker-controlled and
    are rendered through ``unsafe_allow_html``; without this a public dataset
    called ``<img onerror=...>`` would execute in every visitor's browser.
    """
    return html.escape("" if value is None else str(value), quote=True)


def markdown_lite(value: object) -> str:
    """Escape text, then render a safe subset of Markdown as HTML.

    Chat bubbles are raw HTML, so Streamlit's Markdown renderer never sees
    them and ``**bold**`` was shown to users literally. Escaping happens first,
    so the only tags that can reach the page are the ones produced here.
    """
    text = esc(value)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<em>\1</em>", text)
    text = re.sub(r"^- (.+)$", r"• \1", text, flags=re.MULTILINE)
    return text.replace("\n", "<br>")


# ─────────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

:root{
  --bg:#09090b;
  --panel:#141417;
  --panel2:#1b1b20;
  --line:#2a2a31;
  --line2:#3b3b44;

  --txt:#f4f4f5;
  --txt2:#a9a9b4;
  --txt3:#74747f;

  --acc:#ff9d3d;
  --acc2:#ffb45e;
  --violet:#9b8cff;
  --cyan:#6bdcff;
  --grn:#34d399;
  --red:#f87171;
  --amber:#fbbf24;

  --radius:14px;
  --radius-sm:10px;
  --shadow:0 10px 30px rgba(0,0,0,.45);
}

html,body,[class*="css"]{font-family:Inter,system-ui,sans-serif;color:var(--txt)}
.stApp{background:var(--bg)}
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#08080a,#0c0c10)!important;
  border-right:1px solid var(--line)!important;
}
#MainMenu,footer{visibility:hidden}

/* ── Forms ─────────────────────────────────────────────── */
input,textarea,.stTextInput input,.stTextArea textarea,[data-baseweb="select"]>div{
  background:var(--panel2)!important;border:1px solid var(--line)!important;
  color:var(--txt)!important;border-radius:var(--radius-sm)!important;
}
input:focus,textarea:focus{border-color:var(--acc)!important;outline:none!important}
::placeholder{color:var(--txt3)!important}

/* ── Buttons ───────────────────────────────────────────── */
.stButton>button,.stDownloadButton>button,.stLinkButton>a{
  background:linear-gradient(90deg,var(--acc),var(--acc2))!important;
  color:#1a1208!important;border:none!important;border-radius:var(--radius-sm)!important;
  padding:.58rem .95rem;font-weight:600;box-shadow:var(--shadow);
  transition:transform .18s cubic-bezier(.2,.9,.2,1),box-shadow .18s,filter .18s;
}
.stButton>button:hover,.stDownloadButton>button:hover,.stLinkButton>a:hover{
  transform:translateY(-3px);filter:brightness(1.05);
  box-shadow:0 16px 34px rgba(255,157,61,.18),0 6px 18px rgba(0,0,0,.5);
}
.stButton>button:active{transform:translateY(0)}
.stButton>button:focus-visible,.stDownloadButton>button:focus-visible{
  outline:2px solid var(--cyan)!important;outline-offset:2px;
}
.stButton>button[kind="secondary"]{
  background:transparent!important;border:1px solid var(--line2)!important;
  color:var(--txt2)!important;box-shadow:none;
}
.stButton>button[kind="secondary"]:hover{border-color:var(--acc)!important;color:var(--txt)!important}
.stButton>button:disabled{opacity:.45;transform:none;box-shadow:none;cursor:not-allowed}

/* ── Hero ──────────────────────────────────────────────── */
.hero{
  position:relative;overflow:hidden;padding:1.7rem;margin-bottom:1.1rem;
  border-radius:18px;border:1px solid var(--line);
  background:
    radial-gradient(120% 140% at 88% -10%,rgba(155,140,255,.16),transparent 55%),
    linear-gradient(135deg,#0f0f13,#131318);
}
.hero h1{
  font-family:'Space Grotesk',sans-serif;font-size:1.9rem;line-height:1.2;margin:0;
  background:linear-gradient(90deg,var(--violet),var(--acc2));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}
.hero p{color:var(--txt2);margin:.45rem 0 0;font-size:.93rem;max-width:62ch}
.hero .badge{
  position:absolute;right:1.1rem;top:1.1rem;
  background:linear-gradient(90deg,var(--acc),var(--violet));
  color:#120a05;padding:.34rem .7rem;border-radius:999px;
  font-size:.66rem;font-weight:700;letter-spacing:.07em;
}

/* ── Surfaces ──────────────────────────────────────────── */
.card,.hub-card,.plan-card{
  background:linear-gradient(145deg,var(--panel),#101012);
  border:1px solid var(--line);border-radius:var(--radius);
  padding:1rem 1.1rem;margin-bottom:.8rem;
}
.hub-card{transition:border-color .18s,transform .18s}
.hub-card:hover{border-color:var(--line2);transform:translateY(-2px)}
.hub-card h4{margin:0 0 .15rem;font-size:1rem;font-weight:600;color:var(--txt)}
.hub-card .desc{color:var(--txt2);font-size:.88rem;margin:.25rem 0}
.hub-card .meta{color:var(--txt3);font-size:.78rem}

.plan-card{padding:1.25rem 1.1rem}
.plan-card.current{border-color:var(--grn);box-shadow:0 0 0 1px rgba(52,211,153,.18)}
.plan-card.popular{border-color:var(--acc);box-shadow:0 0 0 1px rgba(255,157,61,.2)}
.card.glow{border-color:var(--acc);box-shadow:0 0 0 1px rgba(255,157,61,.2)}

/* ── Stats ─────────────────────────────────────────────── */
.stat-num{
  font-family:'Space Grotesk',sans-serif;font-size:1.7rem;font-weight:700;
  color:var(--txt);line-height:1.15;
}
.stat-lbl{color:var(--txt3);font-size:.74rem;text-transform:uppercase;letter-spacing:.07em;margin-top:.2rem}

/* ── Callouts ──────────────────────────────────────────── */
.note,.warn,.ok{
  border-radius:var(--radius-sm);padding:.7rem .9rem;margin:.5rem 0;
  font-size:.85rem;line-height:1.6;border:1px solid;
}
.note{background:rgba(155,140,255,.07);border-color:rgba(155,140,255,.24);color:var(--txt2)}
.warn{background:rgba(251,191,36,.08);border-color:rgba(251,191,36,.3);color:#fcd34d}
.ok{background:rgba(52,211,153,.08);border-color:rgba(52,211,153,.3);color:var(--grn)}
.note a{color:var(--cyan)}

.admin-bar{
  background:linear-gradient(90deg,rgba(255,157,61,.18),rgba(155,140,255,.12));
  border:1px solid rgba(255,157,61,.34);border-radius:var(--radius-sm);
  padding:.7rem 1rem;margin-bottom:1rem;font-weight:600;color:var(--txt);
}

.key-box{
  font-family:'DM Mono',ui-monospace,monospace;font-size:.86rem;
  background:var(--panel2);border:1px dashed var(--line2);border-radius:var(--radius-sm);
  padding:.8rem .95rem;color:var(--acc2);word-break:break-all;
}

/* ── Tags ──────────────────────────────────────────────── */
.tag{
  display:inline-block;background:var(--panel2);border:1px solid var(--line);
  color:var(--txt2);border-radius:999px;padding:.16rem .6rem;
  font-size:.7rem;margin:.15rem .25rem .15rem 0;
}
.tag.acc{border-color:rgba(255,157,61,.4);color:var(--acc2);background:rgba(255,157,61,.08)}

/* ── Chat ──────────────────────────────────────────────── */
.chat-wrap{display:flex;flex-direction:column;gap:.7rem;margin:.6rem 0 1rem}
.bubble{
  max-width:min(86%,640px);padding:.75rem .95rem;border-radius:var(--radius);
  font-size:.9rem;line-height:1.6;animation:rise .28s cubic-bezier(.2,.9,.2,1);
}
.bubble .sender{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;opacity:.65;margin-bottom:.3rem}
.bubble.user{align-self:flex-end;background:linear-gradient(90deg,var(--acc),var(--acc2));color:#1a1208}
.bubble.bot{align-self:flex-start;background:var(--panel);border:1px solid var(--line);color:var(--txt)}
.bubble code{background:rgba(255,255,255,.08);padding:.08rem .3rem;border-radius:5px;font-size:.84em}

@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}
  .stButton>button:hover,.hub-card:hover{transform:none}
}

/* ── Misc ──────────────────────────────────────────────── */
.divider{border:none;border-top:1px solid var(--line);margin:1.3rem 0}
.small{font-size:.76rem;color:var(--txt3)}
code{font-family:'DM Mono',ui-monospace,monospace}

.bg-audio-ctl{position:fixed;right:18px;bottom:18px;z-index:9999;display:flex;gap:.5rem;align-items:center}
.bg-audio-ctl button{
  background:var(--panel2);border-radius:999px;border:1px solid var(--line2);
  padding:.5rem .6rem;color:var(--txt);cursor:pointer;
}
.bg-audio-ctl .label{font-size:.74rem;color:var(--txt2);padding:.3rem .6rem;border-radius:999px;background:var(--panel)}

@media (max-width:640px){
  .hero{padding:1.2rem}
  .hero h1{font-size:1.45rem}
  .hero .badge{position:static;display:inline-block;margin-bottom:.6rem}
  .bubble{max-width:96%}
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# COMPONENTS
# ─────────────────────────────────────────────────────────────────────
def hero(title: str, sub: str = "", badge: str = "") -> None:
    badge_html = f'<div class="badge">{esc(badge)}</div>' if badge else ""
    sub_html = f"<p>{esc(sub)}</p>" if sub else ""
    st.markdown(
        f'<div class="hero">{badge_html}<h1>{esc(title)}</h1>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def card(content_html: str, glow: bool = False) -> None:
    """Render a card. `content_html` is trusted markup built by the caller."""
    st.markdown(
        f'<div class="{"card glow" if glow else "card"}">{content_html}</div>',
        unsafe_allow_html=True,
    )


def note(message: str, kind: str = "note") -> None:
    """Show a callout. `kind` is one of note | warn | ok."""
    st.markdown(f'<div class="{kind}">{esc(message)}</div>', unsafe_allow_html=True)


def divider() -> None:
    st.markdown('<hr class="divider">', unsafe_allow_html=True)


def stat(value: object, label: str) -> str:
    formatted = f"{value:,}" if isinstance(value, int) else esc(value)
    return (
        '<div class="card" style="text-align:center;padding:1.2rem">'
        f'<div class="stat-num">{formatted}</div>'
        f'<div class="stat-lbl">{esc(label)}</div></div>'
    )


def tag(text: str, accent: bool = False) -> str:
    return f'<span class="tag{" acc" if accent else ""}">{esc(text)}</span>'


def tags_html(tags: Iterable[str] | None, accent: bool = False) -> str:
    return "".join(tag(t, accent) for t in (tags or []))


def hub_card(name: str, owner: str = "", desc: str = "", tags: Iterable[str] | None = None,
             stats: str = "", is_public: bool = False, extra_html: str = "") -> None:
    """A dataset/model listing card. All user text is escaped."""
    visibility = "🌐" if is_public else "🔒"
    owner_html = (
        f'<span style="color:var(--txt3);font-weight:400;font-size:.75rem"> by {esc(owner)}</span>'
        if owner else ""
    )
    st.markdown(
        f'<div class="hub-card">'
        f'<h4>{visibility} {esc(name)}{owner_html}</h4>'
        f'<div class="desc">{esc(desc) or "No description"}</div>'
        f'<div class="meta">{esc(stats)}</div>'
        f'<div style="margin-top:.35rem">{tags_html(tags)}</div>'
        f'{extra_html}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────
# NAVIGATION
# ─────────────────────────────────────────────────────────────────────
PAGES = [
    "🏠  Home",
    "💬  Dataset Chat",
    "🤖  My Models",
    "📦  Dataset Hub",
    "🌐  Model Hub",
    "🔑  API Keys",
    "⚡  Upgrade",
    "⚙️  Account",
    "💬  Support",
]
ADMIN_PAGE = "👑  Admin"
NAV_STATE_KEY = "nav_page"
NAV_REQUEST_KEY = "nav_request"


def go_to(page: str) -> None:
    """Request a page change from inside a page body.

    Streamlit refuses to let you write a widget's own key after that widget has
    been instantiated, and the sidebar radio is created before any page renders.
    So the request is parked under a separate key and applied by
    :func:`sidebar_nav` on the next run, before the radio is built. Callers
    follow this with ``st.rerun()``.
    """
    st.session_state[NAV_REQUEST_KEY] = page


def sidebar_nav(user: dict) -> str:
    """Render the sidebar and return the selected page label."""
    plan = plan_for(user["plan"])
    pages = list(PAGES)
    if user.get("email") == ADMIN_EMAIL:
        pages.append(ADMIN_PAGE)

    # Apply any pending go_to() request while the radio still does not exist.
    requested = st.session_state.pop(NAV_REQUEST_KEY, None)
    if requested in pages:
        st.session_state[NAV_STATE_KEY] = requested

    # Keep the widget's own state valid if a page was removed between runs.
    if st.session_state.get(NAV_STATE_KEY) not in pages:
        st.session_state[NAV_STATE_KEY] = pages[0]

    with st.sidebar:
        st.markdown(
            '<div style="padding:.5rem 0 1rem">'
            '<div style="display:flex;align-items:center;gap:.5rem;'
            "font-family:'Space Grotesk';font-size:1.05rem;font-weight:700\">"
            f'⚡ <span>{esc(APP_NAME)}</span></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="background:linear-gradient(145deg,rgba(255,157,61,.08),rgba(21,21,24,.5));'
            'border:1px solid var(--line);border-radius:10px;padding:.75rem .9rem;margin-bottom:1rem">'
            '<div style="font-size:.7rem;color:var(--txt3);text-transform:uppercase;'
            'letter-spacing:.07em">Plan</div>'
            f'<div style="font-weight:700;margin-top:.25rem">{plan["badge"]} {esc(plan["name"])}</div>'
            '<div style="margin-top:.45rem;font-size:.82rem;color:var(--txt2)">'
            f'🪙 {user.get("tokens", 0):,} tokens</div></div>',
            unsafe_allow_html=True,
        )

        choice = st.radio("Navigation", pages, key=NAV_STATE_KEY, label_visibility="collapsed")

        divider()
        if st.button("Sign out", use_container_width=True, type="secondary"):
            st.session_state.clear()
            st.rerun()
        st.markdown(
            '<div class="small" style="margin-top:.6rem">Private by default · built for builders</div>',
            unsafe_allow_html=True,
        )
    return choice


# ─────────────────────────────────────────────────────────────────────
# PLAN CARDS
# ─────────────────────────────────────────────────────────────────────
def _plan_features(plan: dict) -> list[tuple[str, bool]]:
    return [
        (f"{plan['monthly_tokens']:,} tokens/month", True),
        (f"Up to {plan['max_rows']:,} rows per dataset", True),
        (f"{display_limit(plan['max_datasets'])} datasets · "
         f"{display_limit(plan['max_models'])} models", True),
        ("Public sharing on the Hub", plan["share"]),
        (f"{display_limit(plan['api_keys'])} stored API "
         f"{'key' if plan['api_keys'] == 1 else 'keys'}", True),
        ("Priority generation queue", plan["priority_queue"]),
    ]


def plan_card_html(plan: dict, *, current: bool = False, popular: bool = False) -> str:
    price = "Free" if plan["price"] == 0 else f"${plan['price']}/mo"
    features = "".join(
        '<div style="display:flex;gap:.5rem;align-items:flex-start;margin:.38rem 0;'
        f'font-size:.81rem;color:{"var(--txt2)" if ok else "var(--txt3)"}">'
        f'<span style="color:{"var(--grn)" if ok else "var(--txt3)"}">{"✓" if ok else "✗"}</span>'
        f"<span>{esc(label)}</span></div>"
        for label, ok in _plan_features(plan)
    )
    badge = (
        '<div style="position:absolute;top:0;right:0;background:var(--acc);color:#1a1208;'
        'font-size:.6rem;font-weight:700;letter-spacing:.08em;padding:.22rem .7rem;'
        'border-radius:0 13px 0 12px">POPULAR</div>' if popular else ""
    )
    current_note = (
        '<div style="color:var(--grn);font-size:.75rem;margin:.25rem 0 .5rem">'
        "✓ Your current plan</div>" if current else ""
    )
    classes = "plan-card" + (" current" if current else "") + (" popular" if popular else "")
    return (
        f'<div class="{classes}" style="position:relative;min-height:330px">{badge}'
        f'<div style="font-size:1.5rem;margin-bottom:.4rem">{plan["badge"]}</div>'
        f'<div style="font-size:1rem;font-weight:600">{esc(plan["name"])}</div>'
        f"{current_note}"
        f'<div style="font-size:1.8rem;font-weight:700;line-height:1.15">{price}</div>'
        '<div style="font-size:.72rem;color:var(--txt3);margin-bottom:.9rem">'
        f'{"cancel anytime" if plan["price"] > 0 else "forever free · no card needed"}</div>'
        f"{features}</div>"
    )


def plan_cards_auth() -> None:
    """Plan chooser shown on the sign-in screen."""
    columns = st.columns(3)
    for column, (plan_id, plan) in zip(columns, PLANS.items()):
        with column:
            selected = st.session_state.get("selected_plan") == plan_id
            st.markdown(
                plan_card_html(plan, current=selected, popular=plan_id == "pro"),
                unsafe_allow_html=True,
            )
            label = "✓ Selected" if selected else f"Choose {plan['name']}"
            if st.button(label, key=f"auth_plan_{plan_id}", use_container_width=True):
                st.session_state["selected_plan"] = plan_id
                st.rerun()


plan_cards = plan_cards_auth  # backwards-compatible alias


# ─────────────────────────────────────────────────────────────────────
# OPTIONAL BACKGROUND AUDIO
# ─────────────────────────────────────────────────────────────────────
def inject_audio(url: Optional[str] = None, autoplay: bool = False) -> None:
    """Render a floating play/pause control for an ambient track.

    The URL comes from the ``MUSIC_URL`` secret when not passed explicitly.
    Reading secrets is guarded: on a deployment without a secrets file the
    lookup raises, which previously took the whole page down.
    """
    music = url
    if not music:
        try:
            music = st.secrets.get("MUSIC_URL")
        except Exception:
            music = None
    if not music:
        return

    source = html.escape(str(music), quote=True)
    markup = """
<div class="bg-audio-ctl">
  <audio id="ambient-audio" src="__SRC__" loop preload="none"></audio>
  <button id="ambient-toggle" aria-label="Play or pause background music">⏯️</button>
  <div class="label">Calm music</div>
</div>
<script>
(function(){
  var audio  = document.getElementById('ambient-audio');
  var button = document.getElementById('ambient-toggle');
  if(!audio || !button){ return; }
  function sync(){ button.textContent = audio.paused ? '⏯️' : '⏸️'; }
  button.addEventListener('click', function(){
    if(audio.paused){ audio.play().then(sync).catch(sync); } else { audio.pause(); sync(); }
  });
  audio.addEventListener('ended', sync);
  if(__AUTOPLAY__){ audio.play().then(sync).catch(function(){}); }
})();
</script>
"""
    markup = markup.replace("__SRC__", source).replace(
        "__AUTOPLAY__", "true" if autoplay else "false"
    )
    st_html(markup, height=80)
