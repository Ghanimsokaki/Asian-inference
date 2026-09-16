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

    token = hf_token or config.HF_TOKEN
    headers = {"Authorization": f"Bearer {token}"} if token else {}
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
            raise InferenceError(
                "The inference service rejected the platform credentials. "
                "An administrator needs to check HF_TOKEN."
            )
        if response.status_code == 404:
            raise InferenceError(f"Model '{repo_id}' was not found on Hugging Face.")
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
    "You are the Asian Inference dataset assistant. You help people design "
    "synthetic datasets: you suggest columns, row counts and dataset styles. "
    "Keep replies to two or three short sentences and always steer towards a "
    "concrete dataset specification."
)


def chat_response(message: str, history: Iterable[dict] | None = None) -> str:
    """Reply to a dataset-design message.

    Falls back to a deterministic local reply when no model is reachable, so
    the chat stays usable on a deployment without an inference token.
    """
    message = (message or "").strip()
    if not message:
        return "Tell me what kind of dataset you'd like to build."

    transcript = []
    for entry in list(history or [])[-6:]:
        speaker = "User" if entry.get("role") == "user" else "Assistant"
        transcript.append(f"{speaker}: {entry.get('content', '')}")
    transcript.append(f"User: {message}")

    if not config.HF_TOKEN:
        return _offline_reply(message)

    prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(transcript) + "\nAssistant:"
    try:
        reply = call_agent(prompt, max_new=200, temperature=0.7, retries=1)
    except InferenceError:
        return _offline_reply(message)

    reply = reply.split("User:")[0].strip()
    return reply or _offline_reply(message)


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


def _offline_reply(message: str) -> str:
    columns = ", ".join(suggest_columns(message))
    return (
        f"I can build that. Based on your description I'd use the columns `{columns}`.\n\n"
        "Tell me how many rows you want — for example *\"50 rows\"* — and I'll set up "
        "the generation form."
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
        "# Authenticate with Hugging Face.\n"
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
