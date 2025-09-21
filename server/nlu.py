# server/nlu.py
import string
import os, re, json, httpx
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import Optional

BASE = Path(__file__).parent.parent
CONFIG = BASE / "config"

def load_json(path): return json.load(open(path, "r", encoding="utf-8"))

INTENTS = load_json(CONFIG/"intents.json")
KEYMAP  = load_json(CONFIG/"keymap.json")
SLOTS   = load_json(CONFIG/"slots.json")
SYSTEM_PROMPT_TMPL = open(CONFIG/"system_prompt.txt", "r", encoding="utf-8").read()

# Allow actions defined in keymap plus a few server-handled meta actions
ALLOWED_ACTIONS = set(KEYMAP.keys()) | {"set_browser", "compose_email"}

def slot_app(name: str) -> str:
    n = (name or "").lower().strip()
    return SLOTS.get("apps", {}).get(n, name)

def slot_site(token: str) -> str:
    t = (token or "").lower().strip()
    site_map = SLOTS.get("sites", {})
    if t in site_map: return site_map[t]
    if not t: return ""
    if not t.startswith(("http://", "https://")) and "." in t and " " not in t:
        return "https://" + t
    return t

def slot_browser(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    if t in {"safari", "apple safari"}:
        return "Safari"
    if t in {"chrome", "google chrome", "chromium"}:
        return "Google Chrome"
    return None

def _normalize_url(u: str) -> str:
    if not u:
        return ""
    # trim whitespace & common trailing punctuation
    u = u.strip().strip(' \t\r\n' + '.,;!?)"]\'')
    # if it's just an alias we’ll map elsewhere; leave here as-is

    # already has scheme?
    if u.startswith(("http://", "https://")):
        return u

    # bare domain? (foo.com[/...])
    if re.match(r'^[\w.-]+\.[A-Za-z]{2,}(/.*)?$', u):
        return "https://" + u

    return u  # let caller decide if this should become a search

def _extract_first_json_obj(text: str):
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return json.loads(m.group(0)) if m else None

def actions_list_for_prompt():
    return "\n".join([f"- {name}" for name in sorted(ALLOWED_ACTIONS)])

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=3))
def ollama_route(text: str):
    prompt = SYSTEM_PROMPT_TMPL.replace("{{ACTIONS_LIST}}", actions_list_for_prompt())
    prompt = f"{prompt}\nUser: {text.strip()}\nOutput:"
    with httpx.Client(timeout=45) as client:
        r = client.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0}
        })
    r.raise_for_status()
    data = r.json()
    raw = (data.get("response") or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = re.sub(r"^json\\s*", "", raw, flags=re.IGNORECASE)
    return _extract_first_json_obj(raw)

def validate_and_normalize_plan(plan: dict):
    if not isinstance(plan, dict): return None, "bad_plan"
    action = (plan.get("action") or "").strip()

    # Special actions handled directly by the server and not necessarily present in keymap
    if action == "set_browser":
        b = slot_browser(plan.get("browser", ""))
        if not b:
            return None, "missing_or_bad_browser"
        return (action, {"browser": b}), None

    if action == "compose_email":
        slots = {
            "to": (plan.get("to") or "").strip(),
            "subject": (plan.get("subject") or "").strip(),
            "body": (plan.get("body") or "").strip()
        }
        # All fields optional; server opens compose with whatever is provided
        return (action, slots), None

    if action == "send_email":
        slots = {}
        # Optional one-shot fields
        if "to" in plan: slots["to"] = (plan.get("to") or "").strip()
        if "subject" in plan: slots["subject"] = (plan.get("subject") or "").strip()
        if "body" in plan: slots["body"] = (plan.get("body") or "").strip()
        return (action, slots), None

    if action not in ALLOWED_ACTIONS:
        return None, "blocked_action"

    entry = KEYMAP[action]
    ptype = entry.get("type", "")
    slots = {}

    if action == "type_text":
        txt = (plan.get("text") or "").strip()
        if not txt: return None, "missing_text"
        slots["text"] = txt

    elif ptype == "applescript_open_url":
        url = _normalize_url(plan.get("url",""))
        if not url: return None, "missing_url"
        slots["url"] = url

    elif ptype == "applescript_open_app":
        app_raw = (plan.get("app_name") or plan.get("app") or "").strip()
        app = slot_app(app_raw)
        if not app: return None, "missing_app"
        slots["app"] = app

    # others: no extra fields
    return (action, slots), None

class LocalRouter:
    def __init__(self, intents: dict, threshold: float = 0.42):
        self.threshold = threshold
        exs, labs = [], []
        for intent, spec in intents.items():
            if intent == "meta": continue
            for ex in spec.get("examples", []):
                exs.append(ex.lower()); labs.append(intent)
        self.labels = labs
        if exs:
            self.vec = TfidfVectorizer(ngram_range=(1,2), min_df=1)
            self.X = self.vec.fit_transform(exs)
        else:
            self.vec = None; self.X = None

    def infer(self, text: str):
        if not self.vec or not text: return (None, 0.0)
        qv = self.vec.transform([text.lower().strip()])
        sims = cosine_similarity(qv, self.X)[0]
        idx = sims.argmax()
        score = float(sims[idx]); label = self.labels[idx]
        if score >= self.threshold: return (label, score)
        return (None, score)

LOCAL = LocalRouter(INTENTS)

def local_route(text: str):
    raw = (text or "").strip().lower()
    # 1) regex first
    for intent, spec in INTENTS.items():
        if intent == "meta": continue
        for pat in spec.get("patterns", []):
            m = re.match(pat, raw)
            if m:
                slots = {k:v for k,v in m.groupdict().items() if v}
                return intent, slots, "regex"
    # 2) keyword contains
    for intent, spec in INTENTS.items():
        if intent == "meta": continue
        for ex in spec.get("examples", []):
            if ex in raw:
                return intent, {}, "keyword"
    # 3) tf-idf
    intent, score = LOCAL.infer(raw)
    if intent: return intent, {}, f"tfidf:{score:.2f}"
    return None, {}, "none"