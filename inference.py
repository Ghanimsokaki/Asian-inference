"""
inference.py — Hugging Face inference, dataset synthesis and Colab notebooks.

Failures are raised as typed exceptions rather than encoded into magic strings
in the return value, so a caller can never mistake an error message for model
output (the previous ``"__MODEL_LOADING__"`` sentinel was never actually
produced, so warm-up responses were shown to users as errors).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import requests

import config

HF_ROUTER = "https://router.huggingface.co/hf-inference/models"
TIMEOUT = 60
MAX_ROWS_PER_REQUEST = 10


class InferenceError(RuntimeError):
    """The model could not be reached, or returned something unusable."""


class ModelLoadingError(InferenceError):
    """The model is cold-starting; retrying shortly usually succeeds."""


# ─────────────────────────────────────────────────────────────────────
# LOW-LEVEL CALL
# ─────────────────────────────────────────────────────────────────────
def call_hf(repo_id: str, prompt: str, hf_token: str | None = None,
            max_new: int = 512, temperature: float = 0.7,
            retries: int = 2) -> str:
    """Run text generation against a Hub model and return the generated text.

    Raises :class:`ModelLoadingError` while the model is warming up and
    :class:`InferenceError` for every other failure.
    """
    if not (repo_id or "").strip():
        raise InferenceError("No model repository was specified.")
    if not (prompt or "").strip():
        raise InferenceError("Enter a prompt first.")

    user_token = (hf_token or "").strip()
    deployment_token = (config.MODEL_PROVIDER_TOKEN or config.HF_TOKEN or "").strip()
    token = user_token or deployment_token
    if not token:
        raise InferenceError(
            "Live generation is not configured right now. Ask an administrator to "
            "connect the deployment model token, or add your own model registry "
            "token in API Keys."
        )

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new,
            "temperature": temperature,
            "return_full_text": False,
        },
    }

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(
                f"{HF_ROUTER}/{repo_id}", headers=headers, json=payload, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise InferenceError(f"Could not reach the inference service: {exc}") from exc

        if response.status_code == 503:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise ModelLoadingError(
                "The model is warming up. Try again in about 20 seconds."
            )
        if response.status_code in (401, 403):
            if user_token:
                raise InferenceError(
                    "Your saved model registry token was rejected. Update it in API "
                    "Keys and try again."
                )
            raise InferenceError(
                "The inference service rejected the deployment model token. Ask an "
                "administrator to refresh it, or add your own model registry token "
                "in API Keys."
            )
        if response.status_code == 404:
            raise InferenceError(f"Model '{repo_id}' was not found in the configured registry.")
        if response.status_code == 429:
            raise InferenceError("Rate limited by the inference service. Try again shortly.")
        if not response.ok:
            raise InferenceError(
                f"Inference failed (HTTP {response.status_code}). Please try again."
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise InferenceError("The inference service returned an unreadable response.") from exc

        return _extract_text(result)

    raise InferenceError(f"Inference failed: {last_error}")


def _extract_text(result: Any) -> str:
    """Pull generated text out of the several shapes the Hub returns."""
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            return str(first.get("generated_text", "")).strip()
        return str(first).strip()
    if isinstance(result, dict):
        if "generated_text" in result:
            return str(result["generated_text"]).strip()
        if "error" in result:
            raise InferenceError(str(result["error"]))
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") or {}
            return str(message.get("content", "")).strip()
    return str(result).strip()


def call_agent(prompt: str, **kwargs: Any) -> str:
    """Call the platform's default agent model."""
    return call_hf(config.DEFAULT_AGENT_REPO, prompt, **kwargs)


# Kept so older callers and notebooks keep working.
call_gemby = call_agent


# ─────────────────────────────────────────────────────────────────────
# DATASET SYNTHESIS
# ─────────────────────────────────────────────────────────────────────
def _row_prompt(topic: str, columns: Sequence[str], style: str, count: int) -> str:
    schema = ", ".join(f'"{c}": "..."' for c in columns)
    if count == 1:
        shape = f"a single JSON object: {{{schema}}}"
    else:
        shape = f"a JSON array of exactly {count} objects, each shaped {{{schema}}}"
    return (
        f"You generate synthetic training data.\n"
        f"Topic: {topic}\n"
        f"Dataset style: {style}\n"
        f"Produce {shape}.\n"
        f"Every value must be realistic, varied and specific to the topic.\n"
        f"Respond with JSON only — no commentary, no markdown fences."
    )


def _parse_rows(raw: str, columns: Sequence[str]) -> list[dict]:
    """Extract JSON objects from model output and coerce them to `columns`."""
    if not raw:
        return []
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.MULTILINE)

    candidates: list[Any] = []
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group())
            if isinstance(parsed, list):
                candidates = parsed
        except ValueError:
            candidates = []
    if not candidates:
        for match in re.finditer(r"\{[^{}]*\}", text, re.DOTALL):
            try:
                candidates.append(json.loads(match.group()))
            except ValueError:
                continue

    rows: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in item.items()}
        row = {}
        for column in columns:
            value = lowered.get(column.strip().lower(), "")
            row[column] = value if isinstance(value, (str, int, float, bool)) else json.dumps(value)
        if any(str(v).strip() for v in row.values()):
            rows.append(row)
    return rows


def generate_rows(topic: str, columns: Sequence[str], style: str, num_rows: int,
                  progress_cb: Callable[[int, int], None] | None = None,
                  model_repo: str | None = None,
                  user_hf_token: str | None = None) -> list[dict]:
    """Generate `num_rows` synthetic rows.

    Rows are requested in batches rather than one HTTP round-trip each, which
    is what made large datasets take minutes. Partial success is an error: the
    caller is charged per row, so it gets all the rows or an exception.
    """
    columns = [c.strip() for c in columns if c and c.strip()]
    if not columns:
        raise InferenceError("At least one column is required.")
    num_rows = max(1, int(num_rows))
    repo = model_repo or config.DEFAULT_AGENT_REPO

    rows: list[dict] = []
    failures = 0
    while len(rows) < num_rows:
        remaining = num_rows - len(rows)
        batch = min(remaining, MAX_ROWS_PER_REQUEST)
        prompt = _row_prompt(topic, columns, style, batch)

        raw = call_hf(repo, prompt, hf_token=user_hf_token,
                      max_new=min(256 * batch, 2048), temperature=0.9)
        parsed = _parse_rows(raw, columns)[:remaining]

        if not parsed:
            failures += 1
            if failures >= 3:
                raise InferenceError(
                    "The model did not return usable rows. Try a simpler topic, "
                    "fewer columns, or try again in a moment."
                )
            continue

        failures = 0
        rows.extend(parsed)
        if progress_cb:
            progress_cb(min(len(rows), num_rows), num_rows)

    return rows[:num_rows]


# Backwards-compatible alias for the older argument order.
def generate_dataset_rows(topic: str, num_rows: int, columns: Sequence[str], style: str,
                          model_repo: str | None = None, user_hf_token: str | None = None,
                          progress_cb: Callable[[int, int], None] | None = None) -> list[dict]:
    return generate_rows(topic, columns, style, num_rows, progress_cb, model_repo, user_hf_token)


# ─────────────────────────────────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are Asian, the assistant built into the Asian Inference platform.\n"
    "Talk like a normal, helpful AI tutor — warm, clear, practical and agentic. "
    "Teach step by step when the person is learning, and answer whatever they ask: "
    "machine learning, datasets, training, code, apps, or anything else they are curious about.\n"
    "You can generate synthetic datasets, prepare training notebooks, and help plan apps, "
    "but only trigger those build workflows when the person explicitly asks you to make, "
    "build or generate them. If they are just asking a question, answer the question.\n"
    "Be concise: two to four sentences unless they ask for depth. Never invent facts "
    "about their account, and say so plainly when you do not know."
)

#: Verbs that signal "please build me data", as opposed to merely mentioning data.
_BUILD_VERBS = (
    "generate", "create", "make", "build", "produce", "give me", "i need",
    "i want", "can you make", "can you generate", "synthesi", "mock up", "draft",
)
_DATA_NOUNS = (
    "dataset", "data set", "rows", "samples", "examples", "training data",
    "test data", "records", "entries", "pairs", "synthetic data",
)
_EXPLICIT_DATASET_NOUNS = (
    "dataset", "data set", "training data", "test data", "synthetic data",
)
_NOTEBOOK_NOUNS = (
    "notebook", "ipynb", "colab", "jupyter",
)
_MODEL_NOUNS = (
    "model", "fine tune", "finetune", "training notebook", "lora",
)
_AFFIRMATIVES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please do", "go ahead",
    "do it", "sounds good", "let's do it", "lets do it", "perfect", "great",
)


def detect_dataset_intent(message: str, history: Iterable[dict] | None = None) -> dict | None:
    """Decide whether the person is explicitly asking for a dataset to be built.

    Returns a spec (``topic``, ``rows``, ``columns``) or None to keep chatting.
    Dataset generation must be explicitly requested — the assistant should not
    launch a build flow just because data is mentioned in passing.
    """
    text = (message or "").strip()
    if not text:
        return None

    lowered = text.lower()

    # "yes" / "do it" accepts a build the assistant just offered.
    if _is_affirmative(lowered):
        offered = _last_offer(history)
        if offered:
            return offered

    has_verb = any(verb in lowered for verb in _BUILD_VERBS)
    has_explicit_dataset_noun = any(noun in lowered for noun in _EXPLICIT_DATASET_NOUNS)
    if not (has_verb and has_explicit_dataset_noun):
        return None

    row_count = extract_row_count(text)
    if row_count is None:
        bare = re.search(r"\b(\d{1,6})\b", text)
        if bare and 1 <= int(bare.group(1)) <= 100_000:
            row_count = int(bare.group(1))

    return {
        "topic": text,
        "rows": row_count or 20,
        "columns": suggest_columns(text),
    }


def suggest_model_name(text: str) -> str:
    """Derive a friendly default model name from a free-text request."""
    cleaned = (text or "").lower()
    for phrase in _NOTEBOOK_NOUNS + _MODEL_NOUNS + _BUILD_VERBS:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"\b(for|with|using|about|please|me|a|an|the|my|to)\b", " ", cleaned)
    words = [w for w in re.split(r"[^a-z0-9]+", cleaned) if w]
    if not words:
        return "My Model"
    title = " ".join(words[:4]).title()
    return title if title.lower().endswith("model") else f"{title} Model"


def detect_notebook_intent(message: str) -> dict | None:
    """Decide whether the person is asking for a training notebook to be built."""
    text = (message or "").strip()
    if not text:
        return None

    lowered = text.lower()
    has_notebook = any(noun in lowered for noun in _NOTEBOOK_NOUNS)
    has_model = any(noun in lowered for noun in _MODEL_NOUNS)
    has_build = any(verb in lowered for verb in _BUILD_VERBS)

    if not (has_notebook and (has_build or has_model)):
        return None
    if text.rstrip().endswith("?") and not has_build:
        return None

    return {
        "request": text,
        "name": suggest_model_name(text),
        "base_model": config.DEFAULT_AGENT_REPO,
    }


def looks_data_adjacent(message: str) -> bool:
    """True when a message explicitly points toward building a dataset.

    Used to attach a provisional offer to a reply, but stays conservative so the
    assistant does not nudge people into dataset generation unexpectedly.
    """
    lowered = (message or "").lower()
    return any(noun in lowered for noun in _EXPLICIT_DATASET_NOUNS)


def _is_affirmative(lowered: str) -> bool:
    stripped = lowered.strip(" .!?")
    return stripped in _AFFIRMATIVES or stripped.startswith(("yes ", "yeah ", "sure "))


def _last_offer(history: Iterable[dict] | None) -> dict | None:
    """Recover the dataset the assistant most recently proposed."""
    for entry in reversed(list(history or [])):
        if entry.get("role") == "bot" and entry.get("offer"):
            return dict(entry["offer"])
    return None


def chat_response(message: str, history: Iterable[dict] | None = None,
                  user_hf_token: str | None = None) -> str:
    """Hold a normal conversation, with dataset generation as one capability."""
    message = (message or "").strip()
    if not message:
        return "What would you like to talk about?"

    if not (user_hf_token or config.HF_TOKEN):
        return _offline_reply(message)

    transcript = []
    for entry in list(history or [])[-10:]:
        speaker = "User" if entry.get("role") == "user" else "Asian"
        content = str(entry.get("content", "")).strip()
        if content:
            transcript.append(f"{speaker}: {content}")
    transcript.append(f"User: {message}")

    prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(transcript) + "\nAsian:"
    try:
        reply = call_agent(prompt, hf_token=user_hf_token,
                           max_new=320, temperature=0.75, retries=1)
    except InferenceError:
        return _offline_reply(message)

    return _clean_reply(reply) or _offline_reply(message)


def _clean_reply(reply: str) -> str:
    """Trim a completion that ran on into the next imagined turn."""
    for marker in ("\nUser:", "\nAsian:", "User:", "Asian:"):
        if marker in reply:
            reply = reply.split(marker)[0]
    return reply.strip()


def suggest_columns(text: str) -> list[str]:
    """Guess sensible column names from a free-text dataset description."""
    low = (text or "").lower()
    rules: list[tuple[tuple[str, ...], list[str]]] = [
        (("review", "sentiment", "opinion", "feeling", "rating"), ["text", "sentiment", "score"]),
        (("q&a", "qa pair", "question", "answer", "faq"), ["question", "answer"]),
        (("instruct", "command", "assistant", "prompt"), ["instruction", "response"]),
        (("classif", "label", "categor", "spam"), ["text", "label"]),
        (("summar", "article", "document"), ["document", "summary"]),
        (("product", "description", "catalog"), ["name", "description", "price", "category"]),
        (("translat",), ["source", "target", "language"]),
        (("code", "function", "program"), ["prompt", "code", "language"]),
    ]
    for keywords, columns in rules:
        if any(word in low for word in keywords):
            return columns
    return ["input", "output"]


def extract_row_count(text: str) -> int | None:
    """Find an explicit row count such as '50 rows' in a message."""
    match = re.search(r"\b(\d{1,6})\s*(rows?|samples?|examples?|entries|items|pairs)\b",
                      text or "", re.I)
    if match:
        return int(match.group(1))
    return None


#: Platform questions the assistant can answer from its own knowledge, so the
#: chat stays genuinely useful when no inference model is connected.
_KNOWN_ANSWERS: list[tuple[tuple[str, ...], str]] = [
    (("hello", "hi", "hey", "good morning", "good evening", "yo", "sup"),
     "Hey! I'm Asian, the assistant built into this platform. I can talk through "
     "dataset design, training and models — and I can generate synthetic datasets "
     "for you. What are you working on?"),
    (("who are you", "what are you", "your name", "introduce yourself"),
     "I'm Asian, the assistant inside Asian Inference. I help you design and "
     "generate synthetic datasets, then turn them into a fine-tuning notebook you "
     "can run on a free Colab GPU."),
    (("what can you do", "help me", "how do you work", "what do you do"),
     "Three things, mainly: talk through how to structure a dataset, generate one "
     "row by row from a description, and hand you a Colab notebook that fine-tunes "
     "a model on it. Describe the data you want and I'll set it up."),
    (("token", "tokens", "cost", "how much", "price", "pricing", "credit"),
     "Each generated row costs 10 tokens. You're only charged after rows come back "
     "successfully, and you're refunded if saving fails. Starter includes 500 "
     "tokens a month, Pro 15,000, Elite effectively unlimited."),
    (("train", "training", "fine tune", "finetune", "colab", "gpu"),
     "Go to My Models, pick a base model and one of your datasets, and you'll get a "
     "generated .ipynb. Open it in Colab, switch the runtime to the free T4 GPU and "
     "run all — it LoRA fine-tunes and pushes the weights for you."),
    (("plan", "plans", "upgrade", "elite", "limit", "limits", "subscription"),
     "Starter is free with 2 datasets and 2 models. Pro ($9.99) gives you 6 of each "
     "plus public sharing, and Elite ($29.99) is unlimited. The Upgrade page has the "
     "full comparison."),
    (("thank", "thanks", "cheers", "appreciate", "nice one"),
     "Any time. Tell me what you want to build next."),
    (("storage", "private", "secure", "where is my data", "is my data"),
     "Your datasets live in the platform database, private by default. If the admin "
     "has connected managed offsite storage they're also mirrored to a private remote "
     "registry. Nothing is public unless you switch it on, and that needs Pro or Elite."),
]


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation so keyword matching is not defeated by '!'."""
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip() + " "


def _mentions(normalised: str, keyword: str) -> bool:
    """Whole-word containment, so 'pro' does not match inside 'backpropagation'."""
    return f" {keyword.strip()} " in normalised or normalised.startswith(f" {keyword.strip()} ")


def _basic_math_reply(message: str) -> str | None:
    text = (message or "").strip().lower().rstrip("?!.")
    calc = re.fullmatch(r"(?:what(?:'s| is)\s+)?(-?\d+(?:\.\d+)?)\s*([+\-*/x])\s*(-?\d+(?:\.\d+)?)", text)
    if calc:
        left = float(calc.group(1))
        op = calc.group(2)
        right = float(calc.group(3))
        if op == "+":
            result = left + right
        elif op == "-":
            result = left - right
        elif op in {"*", "x"}:
            result = left * right
        else:
            if right == 0:
                return "Division by zero is undefined."
            result = left / right
        return str(int(result)) if float(result).is_integer() else str(result)

    single = re.fullmatch(r"(?:what(?:'s| is)\s+)?(-?\d+(?:\.\d+)?)", text)
    if single:
        value = single.group(1)
        return (
            f"{value} is a number. If you meant a calculation, send it like `{value} + 4`."
        )
    return None



def _offline_reply(message: str) -> str:
    """Answer without a model.

    The platform runs fine with no inference token, so this is a real fallback
    rather than an error page: it answers what it genuinely knows and is honest
    about the rest.
    """
    normalised = _normalise(message)

    for keywords, answer in _KNOWN_ANSWERS:
        if any(_mentions(normalised, word) for word in keywords):
            return answer

    math_reply = _basic_math_reply(message)
    if math_reply:
        return math_reply

    if detect_dataset_intent(message):
        columns = ", ".join(suggest_columns(message))
        return (
            "I can help with that dataset. "
            f"A good starting schema would be `{columns}`."
        )

    if "?" in message:
        return (
            "I can't answer that one fully right now — my language model isn't connected "
            "on this deployment, so I'm running on built-in answers only.\n\n"
            "If you want a dataset, say it directly like `make a dataset about ...`, "
            "and I'll help you structure it."
        )

    return (
        "Tell me what you want to do next. If you want a dataset, say it directly like "
        "`make a dataset about coffee shop reviews` and I'll set that up. If you want an "
        "answer or app plan, just ask normally."
    )


# ─────────────────────────────────────────────────────────────────────
# COLAB NOTEBOOK
# ─────────────────────────────────────────────────────────────────────
def _code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": source.splitlines(keepends=True),
        "execution_count": None,
        "outputs": [],
    }


def _markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def build_colab_notebook(model_name: str, base_model: str, output_repo: str,
                         dataset_rows: Sequence[dict], epochs: int = 3,
                         lr: float = 2e-4, max_length: int = 512,
                         batch_size: int = 4, max_embedded_rows: int = 500) -> dict:
    """Build the training notebook as a real object.

    The previous implementation pasted a JSON dump of the dataset into a JSON
    string template, which produced a file Colab refused to open. Building a
    dict and serialising once makes malformed output impossible.
    """
    rows = list(dataset_rows)[:max_embedded_rows]
    columns = list(rows[0].keys()) if rows else []
    try:
        lr_value = float(lr)
    except (TypeError, ValueError):
        lr_value = 2e-4

    intro = _markdown_cell(
        f"# 🤖 Train: {model_name}\n"
        f"Auto-generated by **Asian Inference**\n\n"
        f"- Base model: `{base_model}`\n"
        f"- Dataset: {len(rows)} rows · {len(columns)} columns\n"
        f"- Target repo: `{output_repo}`\n\n"
        "Runtime → Change runtime type → **T4 GPU**, then Run all."
    )

    install = _code_cell(
        "# Install dependencies\n"
        "!pip install -q transformers datasets peft trl accelerate bitsandbytes huggingface_hub"
    )

    auth = _code_cell(
        "# Authenticate with your model registry.\n"
        "# Paste a WRITE token when prompted — never hard-code it in the notebook.\n"
        "from huggingface_hub import notebook_login\n"
        "notebook_login()"
    )

    cfg = _code_cell(
        "# Training configuration\n"
        f"BASE_MODEL    = {base_model!r}\n"
        f"OUTPUT_REPO   = {output_repo!r}\n"
        f"EPOCHS        = {int(epochs)}\n"
        f"LEARNING_RATE = {lr_value}\n"
        f"MAX_LENGTH    = {int(max_length)}\n"
        f"BATCH_SIZE    = {int(batch_size)}"
    )

    data = _code_cell(
        "import json\n"
        "from datasets import Dataset\n\n"
        "raw = json.loads(" + repr(json.dumps(rows, ensure_ascii=False)) + ")\n\n"
        "def format_row(row):\n"
        '    return {"text": " | ".join(f"{k}: {v}" for k, v in row.items())}\n\n'
        "ds = Dataset.from_list([format_row(r) for r in raw])\n"
        "print(ds)"
    )

    model_cell = _code_cell(
        "import torch\n"
        "from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig\n\n"
        "bnb_cfg = BitsAndBytesConfig(\n"
        "    load_in_4bit=True,\n"
        "    bnb_4bit_quant_type='nf4',\n"
        "    bnb_4bit_compute_dtype=torch.float16,\n"
        ")\n\n"
        "tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)\n"
        "if tokenizer.pad_token is None:\n"
        "    tokenizer.pad_token = tokenizer.eos_token\n\n"
        "model = AutoModelForCausalLM.from_pretrained(\n"
        "    BASE_MODEL,\n"
        "    quantization_config=bnb_cfg,\n"
        "    device_map='auto',\n"
        "    trust_remote_code=True,\n"
        ")"
    )

    lora = _code_cell(
        "from peft import LoraConfig, get_peft_model\n\n"
        "lora_cfg = LoraConfig(\n"
        "    r=16,\n"
        "    lora_alpha=32,\n"
        "    target_modules=['q_proj', 'v_proj'],\n"
        "    lora_dropout=0.05,\n"
        "    bias='none',\n"
        "    task_type='CAUSAL_LM',\n"
        ")\n"
        "model = get_peft_model(model, lora_cfg)\n"
        "model.print_trainable_parameters()"
    )

    train = _code_cell(
        "from trl import SFTConfig, SFTTrainer\n\n"
        "args = SFTConfig(\n"
        "    output_dir='./output',\n"
        "    num_train_epochs=EPOCHS,\n"
        "    per_device_train_batch_size=BATCH_SIZE,\n"
        "    learning_rate=LEARNING_RATE,\n"
        "    max_length=MAX_LENGTH,\n"
        "    fp16=True,\n"
        "    logging_steps=10,\n"
        "    save_strategy='epoch',\n"
        "    push_to_hub=True,\n"
        "    hub_model_id=OUTPUT_REPO,\n"
        "    hub_private_repo=True,\n"
        "    dataset_text_field='text',\n"
        ")\n\n"
        "trainer = SFTTrainer(\n"
        "    model=model,\n"
        "    processing_class=tokenizer,\n"
        "    train_dataset=ds,\n"
        "    args=args,\n"
        ")\n"
        "trainer.train()"
    )

    push = _code_cell(
        "trainer.push_to_hub()\n"
        "print('✅ Training complete — weights pushed to', OUTPUT_REPO)\n"
        "print('Your model is now live on Asian Inference.')"
    )

    return {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "accelerator": "GPU",
        },
        "cells": [intro, install, auth, cfg, data, model_cell, lora, train, push],
    }


def generate_colab_notebook(model_name: str, base_model: str, output_repo: str,
                            dataset_rows: Sequence[dict], hf_token: str = "",
                            epochs: int = 3, lr: float = 2e-4,
                            max_length: int = 512, batch_size: int = 4) -> str:
    """Return a valid ``.ipynb`` document as a JSON string.

    ``hf_token`` is accepted for backwards compatibility and deliberately
    ignored — the notebook prompts for credentials instead of embedding them
    in a file the user will share and re-upload.
    """
    notebook = build_colab_notebook(model_name, base_model, output_repo, dataset_rows,
                                    epochs, lr, max_length, batch_size)
    return json.dumps(notebook, indent=1, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────
# APPS / DEPLOYMENT STARTERS
# ─────────────────────────────────────────────────────────────────────
SPACE_APP_RUNTIMES = {
    "streamlit": {
        "label": "Streamlit",
        "entrypoint": "app.py",
        "requirements": ["streamlit>=1.35.0", "pandas>=2.0.0"],
    },
    "gradio": {
        "label": "Gradio",
        "entrypoint": "app.py",
        "requirements": ["gradio>=4.0.0", "pandas>=2.0.0"],
    },
    "fastapi": {
        "label": "FastAPI",
        "entrypoint": "app.py",
        "requirements": ["fastapi>=0.110.0", "uvicorn>=0.29.0", "pandas>=2.0.0"],
    },
}
PLAN_MODAL_GPU = {
    "starter": "T4",
    "pro": "A10G",
    "elite": "A100",
}


def modal_gpu_for_plan(plan_id: str) -> str:
    return PLAN_MODAL_GPU.get((plan_id or "").strip().lower(), "T4")


def apache_2_license_text() -> str:
    """Return the repository's Apache 2.0 license text for generated app bundles."""
    try:
        return Path(__file__).with_name("LICENSE").read_text(encoding="utf-8")
    except OSError:
        return (
            "Apache License\n"
            "Version 2.0, January 2004\n"
            "http://www.apache.org/licenses/LICENSE-2.0\n"
        )


def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug[:48] or "app"


def _bundle_root(slug: str) -> str:
    return f"apps/{slug}"


def _streamlit_space_app(app_name: str, description: str, sample_rows: Sequence[dict]) -> str:
    return f'''"""{app_name} — Apache-2.0 starter app."""
import json

import pandas as pd
import streamlit as st

APP_NAME = {app_name!r}
APP_DESCRIPTION = {description!r}
SAMPLE_ROWS = json.loads({json.dumps(json.dumps(list(sample_rows), ensure_ascii=False))})


st.set_page_config(page_title=APP_NAME, page_icon="🚀", layout="wide")
st.title(f"🚀 {{APP_NAME}}")
st.caption(APP_DESCRIPTION)

st.markdown("### Agentic playground")
prompt = st.text_area("Prompt", placeholder="Ask the app to help with something…", height=120)


def run_demo(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Write a prompt first."
    return (
        "Starter app is ready. Replace `run_demo()` with your real workflow, model or agent.\n\n"
        f"You asked: {{text}}"
    )


if st.button("Run", type="primary"):
    st.success(run_demo(prompt))

st.markdown("### Sample dataset")
if SAMPLE_ROWS:
    st.dataframe(pd.DataFrame(SAMPLE_ROWS), use_container_width=True)
else:
    st.info("No dataset was attached when this starter was generated.")

st.markdown("### Next steps")
st.markdown(
    "1. Replace the demo function with your own logic.\n"
    "2. Keep the UI here and move heavy workloads into `modal_app.py`.\n"
    "3. Use the included GitHub workflow to deploy the Modal worker."
)
'''


def _gradio_space_app(app_name: str, description: str, sample_rows: Sequence[dict]) -> str:
    return f'''"""{app_name} — Apache-2.0 starter app."""
import json

import gradio as gr
import pandas as pd

APP_NAME = {app_name!r}
APP_DESCRIPTION = {description!r}
SAMPLE_ROWS = json.loads({json.dumps(json.dumps(list(sample_rows), ensure_ascii=False))})


def run_demo(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Write a prompt first."
    return (
        "Starter app is ready. Replace `run_demo()` with your real workflow, model or agent.\n\n"
        f"You asked: {{text}}"
    )


with gr.Blocks(title=APP_NAME) as demo:
    gr.Markdown(f"# 🚀 {{APP_NAME}}\n\n{{APP_DESCRIPTION}}")
    prompt = gr.Textbox(label="Prompt", lines=5, placeholder="Ask the app to help with something…")
    output = gr.Textbox(label="Output", lines=8)
    gr.Button("Run").click(run_demo, inputs=prompt, outputs=output)
    if SAMPLE_ROWS:
        gr.Dataframe(value=pd.DataFrame(SAMPLE_ROWS), label="Sample dataset")


demo.launch()
'''


def _fastapi_space_app(app_name: str, description: str, sample_rows: Sequence[dict]) -> str:
    return f'''"""{app_name} — Apache-2.0 starter app."""
from fastapi import FastAPI
from pydantic import BaseModel

APP_NAME = {app_name!r}
APP_DESCRIPTION = {description!r}
SAMPLE_ROWS = {json.dumps(list(sample_rows), ensure_ascii=False)}

app = FastAPI(title=APP_NAME, description=APP_DESCRIPTION)


class PromptRequest(BaseModel):
    prompt: str


@app.get("/")
def root() -> dict:
    return {{
        "name": APP_NAME,
        "description": APP_DESCRIPTION,
        "sample_rows": SAMPLE_ROWS[:5],
        "message": "Starter app is ready. Replace the demo handler with your real workflow.",
    }}


@app.post("/run")
def run_demo(payload: PromptRequest) -> dict:
    return {{
        "output": (
            "Starter app is ready. Replace this route with your real model or workflow.\n\n"
            f"You asked: {{payload.prompt.strip()}}"
        )
    }}
'''


def _modal_worker_file(app_name: str, description: str, gpu: str) -> str:
    return f'''"""Modal GPU worker for {app_name}."""
import modal

APP_NAME = {app_name!r}
APP_DESCRIPTION = {description!r}
GPU_TYPE = {gpu!r}

image = modal.Image.debian_slim().pip_install_from_requirements("requirements.txt")
app = modal.App(APP_NAME)


@app.function(image=image, gpu=GPU_TYPE, timeout=3600)
def run_agent(prompt: str) -> dict:
    prompt = (prompt or "").strip()
    return {{
        "app": APP_NAME,
        "gpu": GPU_TYPE,
        "prompt": prompt,
        "message": "Replace this function with your real agent or model pipeline.",
    }}


@app.local_entrypoint()
def main(prompt: str = "Hello from Modal"):
    print(run_agent.remote(prompt))
'''


def _github_workflow_file(bundle_root: str) -> str:
    return f'''name: Deploy Modal Worker

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - '{bundle_root}/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Modal CLI
        run: |
          python -m pip install --upgrade pip
          pip install modal
      - name: Deploy Modal app
        env:
          MODAL_TOKEN_ID: ${{{{ secrets.MODAL_TOKEN_ID }}}}
          MODAL_TOKEN_SECRET: ${{{{ secrets.MODAL_TOKEN_SECRET }}}}
        run: modal deploy {bundle_root}/modal_app.py
'''


def _github_readme_file(github_repo: str, bundle_root: str) -> str:
    repo_line = github_repo or "your-name/your-app-repo"
    return f'''# GitHub + Modal setup

1. Create a GitHub repository, for example `{repo_line}`.
2. Keep the generated bundle under the same path: `{bundle_root}`.
3. Add these GitHub secrets:
   - `MODAL_TOKEN_ID`
   - `MODAL_TOKEN_SECRET`
4. Push to `main` or run the **Deploy Modal Worker** workflow manually.

If you flatten the bundle so `modal_app.py` lives at repository root, update the deploy path inside `.github/workflows/modal-deploy.yml` to match.
'''


def build_space_app_files(app_name: str, description: str, runtime: str = "streamlit",
                          sample_rows: Sequence[dict] | None = None,
                          model_label: str = "", plan_id: str = "starter",
                          github_repo: str = "") -> dict[str, str]:
    """Generate an app bundle plus GitHub + Modal deployment files under ``apps/``."""
    runtime_id = (runtime or "streamlit").strip().lower()
    if runtime_id not in SPACE_APP_RUNTIMES:
        raise InferenceError(f"Unsupported app runtime: {runtime}")

    safe_name = (app_name or "My App").strip()[:80] or "My App"
    safe_description = (description or "Build an AI app inside Asian Inference.").strip()[:500]
    rows = list(sample_rows or [])[:20]
    runtime_info = SPACE_APP_RUNTIMES[runtime_id]
    slug = _slugify_name(safe_name)
    bundle_root = _bundle_root(slug)
    sample_columns = list(rows[0].keys()) if rows else []
    gpu = modal_gpu_for_plan(plan_id)

    if runtime_id == "streamlit":
        app_py = _streamlit_space_app(safe_name, safe_description, rows)
    elif runtime_id == "gradio":
        app_py = _gradio_space_app(safe_name, safe_description, rows)
    else:
        app_py = _fastapi_space_app(safe_name, safe_description, rows)

    readme = f"""# {safe_name}

{safe_description}

## Runtime

- Template: {runtime_info['label']}
- Entry point: `{runtime_info['entrypoint']}`
- License: Apache-2.0
- Modal GPU target for the current plan: `{gpu}`
- GitHub workflow: included

## Included files

- `app.py` — starter application UI or API
- `modal_app.py` — Modal GPU worker template
- `.github/workflows/modal-deploy.yml` — GitHub Action to deploy the Modal worker
- `github_setup.md` — GitHub setup checklist
- `requirements.txt` — base dependencies
- `data/sample_rows.json` — sample dataset snapshot
- `LICENSE` — Apache License 2.0

## Suggested next steps

1. Replace the demo handler in `app.py` with your own app logic.
2. Put heavy inference or agent work into `modal_app.py`.
3. Add your Modal credentials as GitHub secrets.
4. Push the bundle to GitHub and let the workflow deploy the worker.

## Context snapshot

- Bundle root: `{bundle_root}`
- Slug: `{slug}`
- Sample rows included: {len(rows)}
- Sample columns: {', '.join(sample_columns) if sample_columns else 'none'}
- Model reference: {model_label or 'none attached'}
- Suggested GitHub repo: {github_repo or 'not specified'}
"""
    requirements = "\n".join(list(runtime_info["requirements"]) + ["modal>=0.72.0"]) + "\n"

    return {
        f"{bundle_root}/README.md": readme,
        f"{bundle_root}/LICENSE": apache_2_license_text(),
        f"{bundle_root}/requirements.txt": requirements,
        f"{bundle_root}/app.py": app_py,
        f"{bundle_root}/modal_app.py": _modal_worker_file(safe_name, safe_description, gpu),
        f"{bundle_root}/github_setup.md": _github_readme_file(github_repo, bundle_root),
        f"{bundle_root}/.github/workflows/modal-deploy.yml": _github_workflow_file(bundle_root),
        f"{bundle_root}/data/sample_rows.json": json.dumps(rows, indent=2, ensure_ascii=False),
    }


def build_kaggle_space_app_notebook(app_name: str, runtime: str,
                                    files: dict[str, str]) -> dict:
    """Create a helper notebook that writes the generated app bundle."""
    runtime_id = (runtime or "streamlit").strip().lower()
    runtime_info = SPACE_APP_RUNTIMES.get(runtime_id, SPACE_APP_RUNTIMES["streamlit"])
    file_dump = json.dumps(files, ensure_ascii=False)

    intro = _markdown_cell(
        f"# 🚀 {app_name} — App Bundle Writer\n"
        "Apache-2.0 starter prepared by **Asian Inference**\n\n"
        f"- Runtime: `{runtime_info['label']}`\n"
        "- Purpose: write the generated bundle to disk so you can package it or move it to GitHub\n"
    )

    write_files = _code_cell(
        "import json\n"
        "from pathlib import Path\n\n"
        f"FILES = json.loads({file_dump!r})\n"
        "base = Path('.')\n"
        "for relative_path, content in FILES.items():\n"
        "    target = base / relative_path\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text(content, encoding='utf-8')\n"
        "print('Wrote', len(FILES), 'files.')"
    )

    package = _code_cell(
        "import shutil\n"
        "from pathlib import Path\n\n"
        "root = Path('apps')\n"
        "archive = shutil.make_archive('apps_bundle', 'zip', root)\n"
        "print('Created archive:', archive)"
    )

    return {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
        },
        "cells": [intro, write_files, package],
    }


def generate_kaggle_space_app_notebook(app_name: str, runtime: str,
                                       files: dict[str, str]) -> str:
    """Return the helper notebook as JSON text."""
    notebook = build_kaggle_space_app_notebook(app_name, runtime, files)
    return json.dumps(notebook, indent=1, ensure_ascii=False)
