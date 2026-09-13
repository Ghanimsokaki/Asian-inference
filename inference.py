"""
inference.py — HuggingFace inference backend + Colab notebook generator
"""
import json, re, requests
from core import HF_TOKEN

HF_API = "https://api-inference.huggingface.co/models"
DEFAULT_MODEL = "Hwiiiiiiii/gemby-agent-3b"

def call_hf(repo_id: str, prompt: str, hf_token: str = None,
            max_new: int = 600, temperature: float = 0.75) -> str:
    token   = hf_token or HF_TOKEN
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new,
            "temperature": temperature,
            "return_full_text": False,
            "do_sample": True,
        },
    }
    try:
        r = requests.post(f"{HF_API}/{repo_id}", headers=headers,
                          json=payload, timeout=60)
        r.raise_for_status()
        result = r.json()
        if isinstance(result, list) and result:
            return result[0].get("generated_text", "").strip()
        if isinstance(result, dict):
            return result.get("generated_text", str(result)).strip()
        return str(result)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 503:
            return "__MODEL_LOADING__"
        if code == 401:
            return "__BAD_TOKEN__"
        return f"[HTTP {code}]"
    except Exception as e:
        return f"[ERROR] {e}"

def chat_response(message: str, history: list) -> str:
    """
    Chatbot-style call for the dataset assistant.
    Builds a conversation prompt and returns assistant reply.
    """
    system = (
        "You are the Asian Inference Dataset Assistant. "
        "You help users build AI training datasets by asking them questions about "
        "what kind of data they need, then generating it row by row. "
        "Be friendly, concise, and helpful. When the user describes a dataset, "
        "ask for clarification on columns, style, and number of rows if not given. "
        "When you have enough info, say you're ready and wait for confirmation."
    )
    # Build prompt from history
    convo = f"<|system|>{system}\n"
    for msg in history[-10:]:  # last 10 messages for context
        role = "user" if msg["role"] == "user" else "assistant"
        convo += f"<|{role}|>{msg['content']}\n"
    convo += f"<|user|>{message}\n<|assistant|>"

    raw = call_hf(DEFAULT_MODEL, convo, max_new=400, temperature=0.8)
    if raw == "__MODEL_LOADING__":
        return "⏳ Model is warming up, give it 20 seconds then try again!"
    if raw == "__BAD_TOKEN__":
        return "⚠️ HuggingFace token issue. Please check your API key in settings."
    # Clean up any leaked prompt tags
    for tag in ["<|user|>", "<|assistant|>", "<|system|>"]:
        raw = raw.replace(tag, "")
    return raw.strip() or "I didn't quite get that — could you rephrase?"

def generate_rows(topic: str, columns: list, style: str,
                  num_rows: int, progress_cb=None) -> list:
    rows    = []
    col_str = ", ".join(columns)
    for i in range(num_rows):
        if progress_cb:
            progress_cb(i, num_rows)
        prompt = (
            f"You are a data generator. Generate exactly ONE row of a {style} dataset "
            f"about: {topic}.\n"
            f"The columns are: {col_str}\n"
            f"Respond ONLY with valid JSON, no explanation. Example format:\n"
            + "{ " + ", ".join(f'"{c}": "example value"' for c in columns) + " }\n"
            + "Your JSON row:"
        )
        raw = call_hf(DEFAULT_MODEL, prompt, max_new=300, temperature=0.72)
        try:
            m   = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            row = json.loads(m.group()) if m else {c: f"value_{i+1}" for c in columns}
            # ensure all columns present
            for c in columns:
                if c not in row:
                    row[c] = f"value_{i+1}"
        except Exception:
            row = {c: f"value_{i+1}" for c in columns}
        rows.append(row)
    return rows

def generate_colab_notebook(model_name: str, base_model: str,
                            output_repo: str, dataset_rows: list,
                            hf_token: str = "",
                            epochs: int = 3, lr: str = "2e-4",
                            max_length: int = 512, batch_size: int = 4) -> str:
    dataset_json = json.dumps(dataset_rows[:500], indent=2)
    nb = {
        "nbformat": 4, "nbformat_minor": 0,
        "metadata": {
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "accelerator": "GPU"
        },
        "cells": [
            {
                "cell_type": "markdown", "metadata": {},
                "source": [
                    f"# ⚡ Asian Inference — Train: {model_name}\n",
                    f"Base model: `{base_model}` · Dataset: {len(dataset_rows)} rows\n",
                    "**Runtime → Change runtime type → T4 GPU → Run All**"
                ]
            },
            {
                "cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                "source": ["!pip install -q transformers datasets peft trl accelerate bitsandbytes huggingface_hub"]
            },
            {
                "cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                "source": [
                    "from getpass import getpass\n",
                    f'HF_TOKEN      = getpass("Enter your Hugging Face token when prompted: ")\n',
                    f'BASE_MODEL    = "{base_model}"\n',
                    f'OUTPUT_REPO   = "{output_repo}"\n',
                    f'EPOCHS        = {epochs}\n',
                    f'LEARNING_RATE = {lr}\n',
                    f'MAX_LENGTH    = {max_length}\n',
                    f'BATCH_SIZE    = {batch_size}\n',
                ]
            },
            {
                "cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                "source": [
                    "import json, torch\n",
                    "from datasets import Dataset\n",
                    "from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, BitsAndBytesConfig\n",
                    "from peft import LoraConfig, get_peft_model\n",
                    "from trl import SFTTrainer\n",
                    "from huggingface_hub import login\n",
                    "login(HF_TOKEN)\n\n",
                    f"raw = {dataset_json}\n\n",
                    "def fmt(r): return {'text': ' | '.join(f'{k}: {v}' for k,v in r.items())}\n",
                    "ds = Dataset.from_list([fmt(r) for r in raw])\n",
                    "print(f'Dataset: {len(ds)} rows')"
                ]
            },
            {
                "cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                "source": [
                    "bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16)\n",
                    "tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)\n",
                    "tokenizer.pad_token = tokenizer.eos_token\n",
                    "model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb, device_map='auto', trust_remote_code=True)\n",
                    "lora = LoraConfig(r=16, lora_alpha=32, target_modules=['q_proj','v_proj'], lora_dropout=0.05, bias='none', task_type='CAUSAL_LM')\n",
                    "model = get_peft_model(model, lora)\n",
                    "model.print_trainable_parameters()"
                ]
            },
            {
                "cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                "source": [
                    "args = TrainingArguments(\n",
                    "    output_dir='./output',\n",
                    "    num_train_epochs=EPOCHS,\n",
                    "    per_device_train_batch_size=BATCH_SIZE,\n",
                    "    learning_rate=LEARNING_RATE,\n",
                    "    fp16=True, logging_steps=10,\n",
                    "    push_to_hub=True, hub_model_id=OUTPUT_REPO\n",
                    ")\n",
                    "trainer = SFTTrainer(model=model, tokenizer=tokenizer,\n",
                    "    train_dataset=ds, dataset_text_field='text',\n",
                    "    max_seq_length=MAX_LENGTH, args=args)\n",
                    "trainer.train()\n",
                    "trainer.push_to_hub()\n",
                    "print('✅ Done! Your model is ready in Asian Inference.')"
                ]
            },
        ]
    }
    return json.dumps(nb, indent=2)
