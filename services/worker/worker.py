# services/worker/worker.py
import os
import time
import requests
from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

COORD = os.getenv("COORD_URL", "http://localhost:8000")
WORKER_ID = os.getenv("WORKER_ID", "worker-1")

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2] if len(HERE.parents) >= 3 else Path("/home/vscode")
HF_HOME = Path(os.getenv("HF_HOME", str(REPO_ROOT / ".hf-cache")))
HF_HOME.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=str(HF_HOME))
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME, cache_dir=str(HF_HOME))
model.eval()


def classify(text: str):
    inputs = tokenizer(text, return_tensors="pt",
                       truncation=True, max_length=256)
    with torch.no_grad():
        logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1).numpy()[0]
    label_id = int(probs.argmax())
    # usually "positive"/"negative"
    label = model.config.id2label[label_id].lower()
    conf = float(probs[label_id])
    # Normalize labels to exactly "positive"/"negative"
    if label.startswith("pos"):
        label = "positive"
    elif label.startswith("neg"):
        label = "negative"
    return label, conf


def get_task():
    r = requests.post(f"{COORD}/tasks/next",
                      json={"worker_id": WORKER_ID}, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("task_id"), data.get("text")


def submit(task_id, label, conf):
    r = requests.post(f"{COORD}/workers/submit", json={
        "worker_id": WORKER_ID,
        "task_id": task_id,
        "label": label,
        "confidence": float(conf)
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def register_and_heartbeat(base_url: str, worker_id: str):
    import threading
    import time
    import requests

    def hb():
        while True:
            try:
                requests.post(f"{base_url}/workers/heartbeat",
                              json={"worker_id": worker_id}, timeout=5)
            except Exception:
                pass
            time.sleep(30)

    # register once
    try:
        requests.post(f"{base_url}/workers/register",
                      json={"worker_id": worker_id}, timeout=5)
    except Exception:
        pass

    t = threading.Thread(target=hb, daemon=True)
    t.start()


def main():
    print(f"[{WORKER_ID}] starting...")
    while True:
        try:
            task_id, text = get_task()
            if not task_id:
                time.sleep(1.0)
                continue
            label, conf = classify(text)
            print(f"[{WORKER_ID}] task={task_id} -> {label} ({conf:.3f})")
            submit(task_id, label, conf)
        except Exception as e:
            print(f"[{WORKER_ID}] error: {e}")
            time.sleep(1.0)


if __name__ == "__main__":
    main()
