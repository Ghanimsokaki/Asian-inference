"""Escaping and design-token completeness."""
import re

import ui


def test_user_content_is_escaped():
    assert ui.esc('<img src=x onerror="alert(1)">') == (
        "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
    )
    assert "<script>" not in ui.tag("<script>alert(1)</script>")


def test_hub_card_escapes_every_field(monkeypatch):
    captured = {}
    monkeypatch.setattr(ui.st, "markdown",
                        lambda body, **kwargs: captured.setdefault("html", body))

    ui.hub_card("<script>x</script>", owner="<b>o</b>", desc="<i>d</i>",
                tags=["<u>t</u>"], stats="<em>s</em>")

    assert "<script>" not in captured["html"]
    assert "<b>o</b>" not in captured["html"]
    assert "<i>d</i>" not in captured["html"]
    assert "<u>t</u>" not in captured["html"]


def test_every_css_variable_used_is_defined():
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", ui.CSS))
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+):", ui.CSS, re.MULTILINE))
    assert used <= defined, f"undefined CSS variables: {sorted(used - defined)}"


def test_classes_used_by_the_app_are_all_styled():
    app_source = open("app.py").read()
    used = set(re.findall(r'class="([a-z0-9 \-]+)"', app_source))
    classes = {c for group in used for c in group.split()}
    for name in classes:
        assert f".{name}" in ui.CSS, f"app.py uses .{name} but the stylesheet has no rule"


def test_markdown_lite_renders_a_safe_subset():
    assert ui.markdown_lite("**bold**") == "<strong>bold</strong>"
    assert ui.markdown_lite("*italic*") == "<em>italic</em>"
    assert ui.markdown_lite("`code`") == "<code>code</code>"
    assert ui.markdown_lite("a\nb") == "a<br>b"
    assert ui.markdown_lite("- item") == "• item"


def test_markdown_lite_escapes_before_formatting():
    rendered = ui.markdown_lite('<script>alert(1)</script> **safe**')
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<strong>safe</strong>" in rendered


def test_markdown_lite_cannot_be_used_to_inject_attributes():
    rendered = ui.markdown_lite('**x** <img src=y onerror="alert(1)">')
    assert "onerror" in rendered      # kept as text…
    assert "<img" not in rendered     # …but never as a tag


def test_go_to_defers_the_page_change(monkeypatch):
    """go_to must not write the radio's own key, which Streamlit forbids."""
    state = {}
    monkeypatch.setattr(ui.st, "session_state", state)

    ui.go_to("⚡  Upgrade")

    assert state == {ui.NAV_REQUEST_KEY: "⚡  Upgrade"}
    assert ui.NAV_STATE_KEY not in state, (
        "writing the widget key directly raises StreamlitWidgetAlreadyInstantiatedError"
    )


def _contrast(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        value = value.lstrip("#")
        channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                    for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _token(name: str) -> str:
    match = re.search(rf"^\s*{name}:\s*(#[0-9a-fA-F]{{6}})", ui.CSS, re.MULTILINE)
    assert match, f"token {name} not found"
    return match.group(1)


def test_text_tokens_meet_wcag_aa_on_every_surface():
    """Muted text is the one that silently drifts below 4.5:1."""
    surfaces = [_token("--bg"), _token("--panel"), _token("--panel2")]
    for name in ("--txt", "--txt2", "--txt3"):
        colour = _token(name)
        for surface in surfaces:
            ratio = _contrast(colour, surface)
            assert ratio >= 4.5, f"{name} ({colour}) on {surface} is {ratio:.2f}:1"
