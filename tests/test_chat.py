"""The assistant behaves like a chatbot, not a form."""
import config
import inference
import ui


# ── Intent: asking about data is not asking for data ─────────────────
def test_build_requests_are_detected():
    for message in [
        "make me a dataset about coffee shops",
        "build a dataset with 100 Q&A pairs about python",
        "can you create training data for sentiment analysis",
        "generate a synthetic dataset for movie reviews",
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
    spec = inference.detect_dataset_intent("generate a dataset with 75 customer reviews")
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


def test_notebook_requests_are_detected():
    spec = inference.detect_notebook_intent("make me a colab notebook to fine tune a sentiment model")
    assert spec is not None
    assert spec["name"].endswith("Model")


def test_learning_questions_do_not_trigger_notebook_builds():
    assert inference.detect_notebook_intent("how do I fine tune a model in colab?") is None


def test_notebook_requests_win_even_when_the_word_dataset_is_present():
    assert inference.detect_notebook_intent("make me a colab notebook for my dataset")


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


def test_offline_simple_math_does_not_turn_into_a_dataset(monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", "")
    reply = inference.chat_response("what is 8")
    assert "number" in reply.lower()
    assert "dataset" not in reply.lower()


def test_non_explicit_data_requests_do_not_trigger_builds():
    assert inference.detect_dataset_intent("generate 50 customer reviews") is None
    assert inference.detect_dataset_intent("I need 30 spam examples") is None


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


def test_bare_numbers_count_only_inside_an_explicit_dataset_request():
    assert inference.detect_dataset_intent("generate a dataset with 75 customer reviews")["rows"] == 75
    # No explicit dataset request: a year in a sentence is not a row count.
    assert inference.detect_dataset_intent("tell me about the 1990s") is None


def test_a_build_verb_without_data_is_not_a_dataset_request():
    assert inference.detect_dataset_intent("generate ideas for my project") is None
