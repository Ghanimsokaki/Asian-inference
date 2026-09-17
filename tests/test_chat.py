"""The assistant behaves like a chatbot, not a form."""
import config
import inference
import ui


# ── Intent: asking about data is not asking for data ─────────────────
def test_build_requests_are_detected():
    for message in [
        "generate 50 rows of movie reviews",
        "make me a dataset about coffee shops",
        "build 100 Q&A pairs about python",
        "I need 30 spam examples",
        "can you create training data for sentiment analysis",
    ]:
        assert inference.detect_dataset_intent(message), message


def test_questions_do_not_trigger_a_build():
    for message in [
        "hello there",
        "what is a transformer?",
        "how many rows should I use?",
        "what is a good dataset size?",
        "I already have 50 rows, what now?",
        "how does LoRA work?",
        "thanks, that helped",
    ]:
        assert inference.detect_dataset_intent(message) is None, message


def test_intent_carries_a_row_count_and_columns():
    spec = inference.detect_dataset_intent("generate 75 customer reviews")
    assert spec["rows"] == 75
    assert spec["columns"] == ["text", "sentiment", "score"]


def test_intent_defaults_the_row_count_when_unstated():
    assert inference.detect_dataset_intent("make me a dataset about cats")["rows"] == 20


def test_yes_accepts_the_assistants_previous_offer():
    history = [
        {"role": "user", "content": "I'm working on movie reviews"},
        {"role": "bot", "content": "Want me to build that?",
         "offer": {"topic": "movie reviews", "rows": 40,
                   "columns": ["text", "sentiment"]}},
    ]
    spec = inference.detect_dataset_intent("yes please", history)
    assert spec["topic"] == "movie reviews"
    assert spec["rows"] == 40


def test_yes_without_an_offer_is_just_conversation():
    assert inference.detect_dataset_intent("yes", []) is None


# ── Offline: a real chatbot, not an error page ───────────────────────
def test_offline_answers_platform_questions(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "")
    assert "10 tokens" in inference.chat_response("how much do tokens cost?")
    assert "Colab" in inference.chat_response("how do I train a model?")
    assert "Asian" in inference.chat_response("who are you?")


def test_offline_greets(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "")
    for greeting in ["hi!", "hello", "hey there", "Good morning"]:
        assert "Hey!" in inference.chat_response(greeting), greeting


def test_keyword_matching_is_whole_word(monkeypatch):
    """'pro' must not match inside 'backpropagation'."""
    monkeypatch.setattr(config, "HF_TOKEN", "")
    reply = inference.chat_response("what is backpropagation?")
    assert "Starter is free" not in reply
    assert "isn't connected" in reply


def test_offline_is_honest_about_what_it_cannot_answer(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "")
    reply = inference.chat_response("explain attention heads to me?")
    assert "isn't connected" in reply


def test_placeholder_tokens_count_as_unconfigured():
    assert config._is_placeholder("hf_PASTE_YOUR_TOKEN_HERE")
    assert config._is_placeholder("changeme")
    assert not config._is_placeholder("hf_abcdef1234567890abcdef1234567890ab")


def test_model_replies_are_trimmed_at_an_imagined_next_turn(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "hf_real")
    monkeypatch.setattr(inference, "call_agent",
                        lambda *a, **k: "Sure, here you go.\nUser: and then?\nAsian: more")
    assert inference.chat_response("hi") == "Sure, here you go."


def test_history_is_passed_to_the_model(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "hf_real")
    captured = {}
    monkeypatch.setattr(inference, "call_agent",
                        lambda prompt, **k: captured.setdefault("prompt", prompt) or "ok")
    inference.chat_response("and then?", [{"role": "user", "content": "tell me about LoRA"}])
    assert "tell me about LoRA" in captured["prompt"]


# ── Transcript rendering ─────────────────────────────────────────────
def test_only_the_newest_message_animates():
    html = ui.chat_transcript(
        [{"role": "bot", "content": "a"}, {"role": "user", "content": "b"},
         {"role": "bot", "content": "c"}]
    )
    assert html.count("is-new") == 1, "animating the whole transcript replays every rerun"


def test_thinking_bubble_suppresses_the_entrance_on_the_last_message():
    html = ui.chat_transcript([{"role": "bot", "content": "a"}], pending=True)
    assert "thinking-dots" in html
    assert html.count("is-new") == 1, "only the thinking bubble should animate"


def test_transcript_escapes_message_content():
    html = ui.chat_transcript([{"role": "user", "content": "<img src=x onerror=1>"}])
    assert "<img" not in html


def test_assistant_mark_is_drawn_not_an_emoji():
    assert ui.BOT_MARK.startswith("<svg")
    assert "viewBox" in ui.BOT_MARK


def test_bare_numbers_count_only_alongside_a_build_verb():
    assert inference.detect_dataset_intent("generate 75 customer reviews")["rows"] == 75
    # No build verb: a year in a sentence is not a row count.
    assert inference.detect_dataset_intent("tell me about the 1990s") is None


def test_a_build_verb_without_data_is_not_a_dataset_request():
    assert inference.detect_dataset_intent("generate ideas for my project") is None
