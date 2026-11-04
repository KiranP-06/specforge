"""NLP/ML primitives used by the generator and the consistency checker.

All heavy models are optional. With ``USE_TRANSFORMER_MODELS=true`` and the
``requirements-ml.txt`` extras installed, SPECForge uses sentence-transformers
embeddings and an NLI cross-encoder (CPU-only). Otherwise it falls back to
lightweight, deterministic methods so the system runs anywhere.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache

from ..config import get_settings
from ..db import EMBEDDING_DIM

STOPWORDS = set(
    """a an the and or of to in on for with by from at as is are be been being shall should must will
    would can could may might system user users able allow allows allowed provide provides that this
    these those it its into via per each all any so such than then there their they we our you your
    i me my also only not no""".split()
)

NEGATIONS = re.compile(r"\b(not|never|no|cannot|can't|won't|without|neither|nor|prohibit\w*|forbid\w*|disallow\w*)\b", re.I)
ANTONYMS = [
    ("online", "offline"), ("public", "private"), ("allow", "deny"), ("enable", "disable"),
    ("manual", "automatic"), ("mandatory", "optional"), ("encrypted", "plaintext"),
    ("synchronous", "asynchronous"), ("increase", "decrease"), ("accept", "reject"),
    ("anonymous", "authenticated"), ("always", "never"), ("required", "optional"),
]
NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|sec|seconds?|minutes?|hours?|days?|%|percent|users|requests|mb|gb|tb)\b", re.I)

VAGUE_TERMS = [
    "user-friendly", "user friendly", "easy", "easily", "simple", "fast", "quick", "quickly", "efficient",
    "efficiently", "flexible", "robust", "seamless", "seamlessly", "intuitive", "adequate", "appropriate",
    "as appropriate", "as needed", "if possible", "etc", "and/or", "tbd", "to be decided", "minimal",
    "maximize", "minimize", "state-of-the-art", "high performance", "scalable", "reliable", "secure enough",
    "some", "several", "various", "normally", "usually", "best", "optimal", "sufficient", "reasonable",
]
_VAGUE_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t in sorted(VAGUE_TERMS, key=len, reverse=True)) + r")(?![\w-])", re.I)

NFR_LEXICON: dict[str, list[str]] = {
    "performance": ["response time", "latency", "within", "seconds", "ms", "throughput", "fast", "load time", "per second", "performance"],
    "security": ["encrypt", "password", "authenticat", "authoriz", "role", "permission", "secure", "security", "audit", "jwt", "token", "access control",
                 "gdpr", "attack", "owasp"],
    "availability": ["available", "availability", "uptime", "24/7", "downtime", "99."],
    "scalability": ["scale", "scalab", "concurrent", "simultaneous", "users at once", "horizontal"],
    "usability": ["easy to use", "usability", "intuitive", "user-friendly", "user friendly", "accessib", "wcag", "learn", "training"],
    "maintainability": ["maintain", "modular", "extensib", "code quality", "documented", "refactor"],
    "portability": ["browser", "platform", "mobile", "android", "ios", "chrome", "firefox", "portab", "responsive", "cross-platform"],
    "reliability": ["reliab", "fault", "recover", "backup", "failover", "data loss", "retry", "consistent"],
    "legal": ["comply", "complian", "regulation", "law", "legal", "licen", "privacy", "consent"],
    "look_and_feel": ["look", "color", "colour", "theme", "brand", "font", "layout", "appearance"],
    "operational": ["deploy", "monitor", "log", "operat", "environment", "docker", "cloud", "aws", "server"],
}


SYNONYMS = {
    "add": "create", "new": "create", "edit": "update", "modify": "update", "change": "update", "remove": "delete",
    "erase": "delete", "see": "view", "browse": "view", "display": "view", "show": "view", "signin": "login",
    "logon": "login", "signup": "register", "purchase": "buy", "fetch": "get", "retrieve": "get", "mail": "email",
    "e-mail": "email", "quick": "fast", "rapid": "fast",
}


def tokens(text: str) -> list[str]:
    low = re.sub(r"\b(log|sign)[ -]?in\b", "login", text.lower())
    low = re.sub(r"\bsign[ -]?up\b", "register", low)
    words = re.findall(r"[a-z][a-z0-9]+", low)
    out = []
    for w in words:
        if w in STOPWORDS or len(w) <= 2 or w in ("using", "via", "through"):
            continue
        w = SYNONYMS.get(w, w)
        out.append(SYNONYMS.get(_stem(w), _stem(w)))
    return out


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def find_vague_terms(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _VAGUE_RE.finditer(text)})


def has_measurable_criterion(text: str) -> bool:
    return bool(re.search(r"\d", text))


# --------------------------------------------------------------------------- classifier
@lru_cache
def _sk_model():
    path = os.environ.get("CLASSIFIER_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "models", "fr_nfr.joblib"))
    if os.path.exists(path):
        try:
            import joblib

            return joblib.load(path)
        except Exception:  # pragma: no cover - optional
            return None
    return None


def classify_requirement(text: str) -> tuple[str, str]:
    """Return (kind, category) where kind is FR or NFR."""
    model = _sk_model()
    if model is not None:
        label = str(model.predict([text])[0])
        if label == "F":
            return "FR", "functional"
        return "NFR", _PROMISE_LABELS.get(label, "other")
    low = text.lower()
    scores = {cat: sum(1 for kw in kws if kw in low) for cat, kws in NFR_LEXICON.items()}
    best, score = max(scores.items(), key=lambda kv: kv[1])
    action_verbs = re.search(r"\b(create|add|view|edit|delete|upload|download|search|filter|register|login|log in|"
                             r"send|book|pay|assign|track|generate|export|import|submit|approve|manage|notify|list|share)\b", low)
    if score >= 2 or (score == 1 and not action_verbs):
        return "NFR", best
    return "FR", "functional"


_PROMISE_LABELS = {
    "A": "availability", "FT": "reliability", "L": "legal", "LF": "look_and_feel", "MN": "maintainability",
    "O": "operational", "PE": "performance", "PO": "portability", "SC": "scalability", "SE": "security", "US": "usability",
}


# --------------------------------------------------------------------------- embeddings
@lru_cache
def _st_model():
    s = get_settings()
    if not s.use_transformer_models:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(s.embedding_model, device="cpu")
    except Exception:
        return None


def using_transformers() -> bool:
    return _st_model() is not None


def embed(texts: list[str]) -> list[list[float]]:
    model = _st_model()
    if model is not None:
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in vecs]
    return [_hash_embed(t) for t in texts]


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words + bigrams vector (fallback embedding)."""
    toks = tokens(text)
    feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:], strict=False)]
    vec = [0.0] * EMBEDDING_DIM
    for f in feats:
        h = int(hashlib.md5(f.encode(), usedforsecurity=False).hexdigest(), 16)
        vec[h % EMBEDDING_DIM] += 1.0 if (h >> 9) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def jaccard(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def similarity(a_text: str, b_text: str, a_vec: list[float], b_vec: list[float]) -> float:
    """Semantic similarity used for duplicate detection.

    With transformer embeddings this is plain cosine. In lightweight mode the hashed
    vectors miss paraphrases, so we blend in the token containment coefficient
    (overlap / size of the shorter requirement) over synonym-normalised tokens.
    """
    cos = cosine(a_vec, b_vec)
    if using_transformers():
        return cos
    ta, tb = set(tokens(a_text)), set(tokens(b_text))
    if min(len(ta), len(tb)) < 3:
        return cos
    containment = len(ta & tb) / min(len(ta), len(tb))
    return max(cos, 0.9 * containment)


def duplicate_threshold() -> float:
    return get_settings().duplicate_threshold if using_transformers() else 0.72


# --------------------------------------------------------------------------- contradictions (NLI)
@lru_cache
def _nli_model():
    s = get_settings()
    if not s.use_transformer_models:
        return None
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(s.nli_model, device="cpu")
    except Exception:
        return None


def contradiction_score(a: str, b: str) -> float:
    """Probability-like score in [0, 1] that statements a and b contradict each other."""
    model = _nli_model()
    if model is not None:
        import numpy as np

        logits = model.predict([(a, b), (b, a)])
        probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
        return float(probs[:, 0].max())  # label 0 = contradiction for nli-deberta-v3 models
    return _heuristic_contradiction(a, b)


def _heuristic_contradiction(a: str, b: str) -> float:
    overlap = jaccard(a, b)
    if overlap < 0.25:
        return 0.0
    la, lb = a.lower(), b.lower()
    score = 0.0
    if bool(NEGATIONS.search(la)) != bool(NEGATIONS.search(lb)):
        score = max(score, 0.55 + 0.4 * overlap)
    for x, y in ANTONYMS:
        if (re.search(rf"\b{x}", la) and re.search(rf"\b{y}", lb)) or (re.search(rf"\b{y}", la) and re.search(rf"\b{x}", lb)):
            score = max(score, 0.6 + 0.35 * overlap)
    # universal permission vs. bounded permission ("at any time" vs "up to 10 minutes before")
    univ = re.compile(r"\b(any ?time|at all times|always|unlimited|without (any )?limit|even after)\b")
    bound = re.compile(r"\b(up to|only|until|before|within|no later than|at most|maximum)\b")
    if (univ.search(la) and bound.search(lb) and not univ.search(lb)) or (univ.search(lb) and bound.search(la) and not univ.search(la)):
        score = max(score, 0.6 + 0.35 * overlap)
    na = {(_unit(u), float(n)) for n, u in NUM_UNIT.findall(la)}
    nb = {(_unit(u), float(n)) for n, u in NUM_UNIT.findall(lb)}
    for ua, va in na:
        for ub, vb in nb:
            if ua == ub and va != vb:
                score = max(score, 0.5 + 0.45 * overlap)
    return min(score, 0.99)


def _unit(u: str) -> str:
    u = u.lower()
    if u.startswith("ms") or u.startswith("milli"):
        return "ms"
    if u in ("s", "sec") or u.startswith("second"):
        return "s"
    return u.rstrip("s")


# --------------------------------------------------------------------------- sentence splitting
def split_sentences(text: str) -> list[str]:
    lines = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^([-*•▪◦]|\d+[.)]|[a-z][.)]|(REQ|FR|NFR)[-_ ]?\d+[:.)]?)\s*", "", line, flags=re.I)
        lines.extend(s.strip() for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", line) if s.strip())
    return lines
