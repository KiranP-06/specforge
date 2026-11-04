"""Offline, deterministic blueprint generator.

Used when ``LLM_PROVIDER=heuristic`` (no API key / no budget, e.g. AWS Academy),
as the fallback when an LLM keeps returning invalid JSON, and for repair stubs.
It produces a ``BlueprintDraft``-shaped dict using rule-based NLP.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from functools import lru_cache

from . import nlp

MODAL = r"(?:shall|must|should|will|can|could|may|needs? to|is able to|are able to|be able to|wants? to|would like to)"
CUE = re.compile(rf"\b({MODAL}|allow(?:s|ed)? |support(?:s)? |provide(?:s)? |ensure(?:s)? |enable(?:s)? |let(?:s)? )", re.I)
ROLE_WORDS = {
    "admin", "administrator", "customer", "student", "teacher", "faculty", "manager", "doctor", "patient", "vendor",
    "guest", "reviewer", "analyst", "seller", "buyer", "driver", "rider", "member", "employee", "staff", "owner",
    "visitor", "operator", "agent", "instructor", "learner", "author", "editor", "client", "tenant", "landlord",
    "recruiter", "candidate", "user", "developer", "team lead", "project manager", "auditor", "librarian",
}
ACTION_VERBS = [
    "register", "login", "log in", "sign up", "create", "add", "view", "see", "browse", "edit", "update", "modify",
    "delete", "remove", "upload", "download", "search", "filter", "sort", "book", "reserve", "cancel", "pay",
    "purchase", "order", "assign", "track", "generate", "export", "import", "submit", "approve", "reject",
    "manage", "notify", "send", "receive", "list", "share", "comment", "rate", "review", "schedule", "invite",
    "configure", "monitor", "report", "chat", "message", "checkout", "enroll", "verify", "reset",
]
GENERIC_OBJECTS = {"account", "data", "information", "details", "system", "application", "app", "platform", "page",
                   "feature", "option", "way", "time", "item", "items", "list", "status", "dashboard", "them", "their",
                   "own", "new", "existing", "all", "multiple", "different", "relevant", "real", "notification",
                   "notifications", "email", "emails", "report", "reports", "password"}
FIELD_HINTS = {
    "user": [("email", "string"), ("name", "string"), ("password_hash", "string"), ("role", "enum")],
    "order": [("customer_id", "fk"), ("total_amount", "decimal"), ("status", "enum")],
    "payment": [("order_id", "fk"), ("amount", "decimal"), ("method", "enum"), ("status", "enum")],
    "booking": [("user_id", "fk"), ("start_at", "datetime"), ("end_at", "datetime"), ("status", "enum")],
    "appointment": [("patient_id", "fk"), ("scheduled_at", "datetime"), ("status", "enum")],
    "product": [("name", "string"), ("price", "decimal"), ("stock", "integer")],
    "course": [("title", "string"), ("instructor_id", "fk"), ("capacity", "integer")],
    "task": [("title", "string"), ("assignee_id", "fk"), ("due_date", "date"), ("status", "enum")],
    "ticket": [("subject", "string"), ("priority", "enum"), ("status", "enum"), ("assignee_id", "fk")],
    "document": [("filename", "string"), ("storage_key", "string"), ("uploaded_by", "fk")],
    "file": [("filename", "string"), ("storage_key", "string"), ("size_bytes", "integer")],
    "message": [("sender_id", "fk"), ("body", "text"), ("sent_at", "datetime")],
    "review": [("author_id", "fk"), ("rating", "integer"), ("body", "text")],
}
INTEGRATION_WORDS = re.compile(r"\b(payment gateway|third[- ]party|external|integrat\w*|api|sms|e-?mail|stripe|razorpay|paypal|google|maps|oauth|webhook)\b", re.I)


def _key(prefix: str, n: int) -> str:
    return f"{prefix}-{n:03d}"


def _clean_title(sentence: str, limit: int = 140) -> str:
    s = sentence.strip().rstrip(".;")
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.I)
    s = s[0].upper() + s[1:] if s else s
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def _priority(s: str) -> str:
    low = s.lower()
    if re.search(r"\b(must|shall|critical|required|mandatory)\b", low):
        return "must"
    if re.search(r"\b(could|may|nice to have|optional|optionally|ideally)\b", low):
        return "could"
    if re.search(r"\b(won't|will not be|out of scope)\b", low):
        return "wont"
    return "should"


def _singular(w: str) -> str:
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def _role(sentence: str) -> str:
    low = sentence.lower()
    m = re.search(rf"\b(?:the|an?|each|every|registered|logged-in|authorised|authorized)?\s*([a-z]+(?: [a-z]+)?)\s+{MODAL}", low)
    if m:
        cand = m.group(1).split()[-1]
        if _singular(cand) in ROLE_WORDS:
            return _singular(cand).title()
    for r in sorted(ROLE_WORDS, key=len, reverse=True):
        if re.search(rf"\b{r}s?\b", low):
            return r.title()
    return "User"


def _goal(sentence: str) -> str:
    low = sentence.strip().rstrip(".;")
    m = re.search(rf"\b{MODAL}\s+(?:be able to\s+)?(.+)", low, re.I)
    goal = m.group(1) if m else low
    goal = re.split(r"\b(so that|in order to)\b", goal, flags=re.I)[0].strip(" ,")
    goal = re.sub(r"^(allow|enable|let)s?\s+(the\s+)?\w+\s+to\s+", "", goal, flags=re.I)
    goal = re.sub(r"^(provide|support)s?\s+", "have ", goal, flags=re.I)
    return goal[:1].lower() + goal[1:] if goal else "use this capability"


def _benefit(sentence: str, category: str) -> str:
    m = re.search(r"\b(?:so that|in order to)\s+(.+)", sentence, re.I)
    if m:
        return m.group(1).strip().rstrip(".")
    return {
        "functional": "I can complete my work without manual effort",
    }.get(category, "the product meets its quality expectations")


def _actions(sentence: str) -> list[str]:
    low = sentence.lower()
    return [v for v in ACTION_VERBS if re.search(rf"\b{v}\b", low)]


NP_STOP = {"to", "for", "by", "with", "as", "in", "on", "at", "from", "up", "after", "before", "using", "through", "via",
           "into", "of", "and", "or", "but", "that", "which", "when", "while", "so", "if", "until", "within", "per", "than"}
DETERMINERS = {"a", "an", "the", "their", "his", "her", "its", "our", "your", "my", "this", "that", "these", "those", "any",
               "each", "every", "some", "all", "new", "existing", "multiple", "own", "and", "or"}
NON_NOUNS = {"online", "offline", "incoming", "outgoing", "daily", "weekly", "monthly", "available", "relevant", "real",
             "different", "various", "current", "previous", "next", "other", "same", "more", "less", "easily", "quickly",
             "securely", "directly", "automatically", "also", "only", "them", "it", "they", "up", "out", "back", "down"}
DOMAIN_ENTITIES = [(r"\b(pay|payment|checkout|upi|card)\b", "payment"), (r"\b(order|orders|cart)\b", "order")]


@lru_cache
def _spacy():
    """spaCy English pipeline if installed (USE_SPACY=false disables it)."""
    if os.environ.get("USE_SPACY", "true").lower() in ("0", "false", "no"):
        return None
    try:
        import spacy

        return spacy.load("en_core_web_sm", disable=["ner"])
    except Exception:  # noqa: BLE001 - optional dependency
        return None


def using_spacy() -> bool:
    return _spacy() is not None


CRUD_VERBS = {"create", "add", "edit", "update", "modify", "delete", "remove", "view", "manage", "deactivate", "list"}
SPACY_VERBS = set(ACTION_VERBS) | {"place", "set", "leave", "write", "post", "open", "close", "rate", "pay"}


def _objects(sentence: str) -> list[str]:
    nlp_ = _spacy()
    return _objects_spacy(sentence, nlp_) if nlp_ is not None else _objects_regex(sentence)


def _objects_spacy(sentence: str, nlp_) -> list[str]:
    """Domain entities = heads of noun chunks governed (via prep/conj) by an action verb, from spaCy's parse."""
    doc = nlp_(sentence)
    objs: list[str] = []
    for chunk in doc.noun_chunks:
        root = chunk.root
        # coordinated nouns ("title, author or ISBN") inherit the role of the first conjunct
        base = root
        while base.dep_ == "conj" and base.head.pos_ in ("NOUN", "PROPN"):
            base = base.head
        if base.dep_ not in ("dobj", "pobj", "conj", "nsubjpass", "attr", "appos") or root.pos_ == "PROPN":
            continue
        # "search by title", "pay using UPI", "within 2 seconds" are attributes/instruments, not entities
        if base.dep_ == "pobj" and base.head.lemma_.lower() not in ("to", "from", "into", "of"):
            continue
        verb, hops = root.head, 0
        while verb.pos_ != "VERB" and verb.head is not verb and hops < 3:
            verb, hops = verb.head, hops + 1
        if verb.pos_ != "VERB" or verb.lemma_.lower() not in SPACY_VERBS:
            continue
        candidates = [root] + [c for c in root.children if c.dep_ == "compound"]
        for tok in candidates:
            noun = _singular(tok.lemma_.lower())
            if (noun in GENERIC_OBJECTS or noun in ROLE_WORDS or noun in NON_NOUNS or noun in nlp.STOPWORDS
                    or noun in CRUD_VERBS or len(noun) <= 2):
                continue
            objs.append(noun)
            break
    for pat, ent in DOMAIN_ENTITIES:
        if re.search(pat, sentence, re.I) and ent not in objs:
            objs.append(ent)
    return list(dict.fromkeys(objs))


def _objects_regex(sentence: str) -> list[str]:
    """Fallback: head nouns of the noun phrases that follow action verbs (light-weight NP chunking)."""
    words = re.findall(r"[a-z][a-z'-]*|[,.;:]", sentence.lower())
    verbs = {v for v in ACTION_VERBS if " " not in v} | {"place", "set", "leave", "write", "post", "open", "close", "use", "log", "sign"}
    objs: list[str] = []
    for i, w in enumerate(words):
        if w not in verbs:
            continue
        # noun/verb ambiguity ("the order is ready"): a word after a determiner or before a copula is a noun
        if (i > 0 and words[i - 1] in DETERMINERS - {"and", "or"}) or (i + 1 < len(words) and words[i + 1] in {"is", "are", "was", "were", "has", "status"}):
            continue
        j, np_ = i + 1, []
        while j < len(words) and (words[j] in DETERMINERS or words[j] in verbs or words[j] == ","):
            j += 1
        while j < len(words) and words[j] not in NP_STOP and words[j] not in ",.;:" and words[j] not in verbs and len(np_) < 4:
            np_.append(words[j])
            j += 1
        np_ = [t for t in np_ if t not in NON_NOUNS and t not in nlp.STOPWORDS]
        for head in reversed(np_):
            noun = _singular(head)
            if noun in GENERIC_OBJECTS or noun in ROLE_WORDS or len(noun) <= 2:
                continue
            objs.append(noun)
            break
    for pat, ent in DOMAIN_ENTITIES:
        if re.search(pat, sentence, re.I) and ent not in objs:
            objs.append(ent)
    return objs


CONSTRAINT_RE = re.compile(r"\b(budget|deadline|within \d+ (weeks|months)|must (use|be built)|be built (with|using|within)|"
                           r"using (react|python|java|aws|node)|constraint)\b", re.I)


def _is_requirement(sentence: str) -> bool:
    words = sentence.split()
    if len(words) < 4 or sentence.endswith(":") or sentence.lstrip().startswith("#") or CONSTRAINT_RE.search(sentence):
        return False
    return bool(CUE.search(sentence))


def generate(brief: str) -> dict:
    sentences = nlp.split_sentences(brief)
    candidates = [s for s in sentences if _is_requirement(s)]
    if not candidates:
        candidates = [s for s in sentences if len(s.split()) >= 5]
    if not candidates and brief.strip():
        candidates = [brief.strip()[:500]]

    # -------- requirements
    reqs, seen = [], set()
    for s in candidates:
        norm = " ".join(nlp.tokens(s))
        if norm in seen:
            continue
        seen.add(norm)
        kind, cat = nlp.classify_requirement(s)
        reqs.append({
            "key": _key("REQ", len(reqs) + 1), "title": _clean_title(s), "description": s.strip(), "kind": kind,
            "category": cat, "priority": _priority(s), "stakeholder": _role(s), "source_quote": s.strip()[:300],
        })

    # -------- stakeholders & constraints
    roles = Counter(r["stakeholder"] for r in reqs)
    stakeholders = [{"name": r, "description": f"Interacts with {n} requirement(s)"} for r, n in roles.most_common()]
    constraints = [s.strip() for s in sentences if CONSTRAINT_RE.search(s) and not s.lstrip().startswith("#")][:10]

    # -------- entities
    obj_counter: Counter[str] = Counter()
    req_objects: dict[str, list[str]] = {}
    for r in reqs:
        objs = _objects(r["description"]) if r["kind"] == "FR" else []
        req_objects[r["key"]] = objs
        obj_counter.update(set(objs))
    needs_user = any(re.search(r"\b(login|log in|register|sign up|account|role|password|profile)\b", r["description"], re.I) for r in reqs)
    entity_names = [o for o, _ in obj_counter.most_common(8)]
    if needs_user and "user" not in entity_names:
        entity_names.insert(0, "user")
    entities = []
    ent_key: dict[str, str] = {}
    for name in entity_names:
        k = _key("ENT", len(entities) + 1)
        ent_key[name] = k
        fields = [{"name": "id", "type": "uuid"}]
        fields += [{"name": f, "type": t} for f, t in FIELD_HINTS.get(name, [("name", "string"), ("description", "text"), ("status", "enum"), ("owner_id", "fk")])]
        fields.append({"name": "created_at", "type": "datetime"})
        entities.append({"key": k, "name": name.title().replace(" ", ""), "fields": fields, "module_key": None})

    # -------- modules: group by entity / concern
    groups: dict[str, list[str]] = defaultdict(list)
    for r in reqs:
        d = r["description"].lower()
        if r["kind"] == "NFR":
            groups["Platform & Quality"].append(r["key"])
        elif re.search(r"\b(login|log in|register|sign up|password|role|permission|authenticat)\w*", d):
            groups["Identity & Access"].append(r["key"])
        elif re.search(r"\b(notify|notification|e-?mail|sms|alert|remind)\w*", d):
            groups["Notifications"].append(r["key"])
        elif re.search(r"\b(report|analytics|dashboard|chart|statistic|export)\w*", d):
            groups["Reporting & Analytics"].append(r["key"])
        elif req_objects.get(r["key"]):
            groups[f"{req_objects[r['key']][0].title()} Management"].append(r["key"])
        else:
            groups["Core Workflow"].append(r["key"])
    modules, mod_of_req, mod_key_by_name = [], {}, {}
    for name, keys in groups.items():
        k = _key("MOD", len(modules) + 1)
        mod_key_by_name[name] = k
        modules.append({"key": k, "name": name, "description": f"Handles {len(keys)} requirement(s) for {name.lower()}.",
                        "requirement_keys": keys, "story_keys": []})
        for rk in keys:
            mod_of_req[rk] = k
    for e in entities:
        lname = e["name"].lower()
        if lname == "user" and "Identity & Access" in mod_key_by_name:
            e["module_key"] = mod_key_by_name["Identity & Access"]
        else:
            e["module_key"] = mod_key_by_name.get(f"{e['name'].title()} Management") or next(
                (mod_of_req[rk] for rk, objs in req_objects.items() if lname in objs and rk in mod_of_req), None)

    # -------- stories
    stories = []
    for r in reqs:
        if r["kind"] != "FR":
            continue
        k = _key("US", len(stories) + 1)
        stories.append(make_story(k, r))
        if r["key"] in mod_of_req:
            next(m for m in modules if m["key"] == mod_of_req[r["key"]])["story_keys"].append(k)

    # -------- APIs
    apis, api_index = [], {}

    def add_api(method, path, summary, module_key, entity_keys, req_key):
        sig = (method, path)
        if sig in api_index:
            if req_key and req_key not in api_index[sig]["requirement_keys"]:
                api_index[sig]["requirement_keys"].append(req_key)
            return
        a = {"key": _key("API", len(apis) + 1), "method": method, "path": path, "summary": summary,
             "module_key": module_key, "entity_keys": entity_keys, "requirement_keys": [req_key] if req_key else []}
        apis.append(a)
        api_index[sig] = a

    for r in reqs:
        if r["kind"] != "FR":
            continue
        d = r["description"].lower()
        mk = mod_of_req.get(r["key"])
        if re.search(r"\b(register|sign up)\b", d):
            add_api("POST", "/auth/register", "Register a new account", mk, [ent_key["user"]] if "user" in ent_key else [], r["key"])
        if re.search(r"\b(login|log in|sign in|authenticat\w*)\b", d):
            add_api("POST", "/auth/login", "Authenticate and issue a JWT", mk, [ent_key["user"]] if "user" in ent_key else [], r["key"])
        if re.search(r"\breset\b.*\bpassword\b", d):
            add_api("POST", "/auth/password-reset", "Request a password reset", mk, [], r["key"])
        for obj in dict.fromkeys(req_objects.get(r["key"], [])):
            if obj not in ent_key:
                continue
            res = "/" + (obj + "s" if not obj.endswith("s") else obj).replace(" ", "-")
            ek = [ent_key[obj]]
            acts = _actions(d) or ["view"]
            for act in acts:
                if act in ("create", "add", "upload", "submit", "register", "book", "reserve", "enroll", "invite", "schedule"):
                    add_api("POST", res, f"Create {obj}", mk, ek, r["key"])
                elif act in ("view", "see", "browse", "list", "search", "filter", "sort", "track", "monitor"):
                    add_api("GET", res, f"List / search {obj}s", mk, ek, r["key"])
                    add_api("GET", f"{res}/{{id}}", f"Get one {obj}", mk, ek, r["key"])
                elif act in ("edit", "update", "modify", "manage", "configure"):
                    add_api("PUT", f"{res}/{{id}}", f"Update {obj}", mk, ek, r["key"])
                elif act in ("delete", "remove", "cancel"):
                    add_api("DELETE", f"{res}/{{id}}", f"Delete / cancel {obj}", mk, ek, r["key"])
                elif act in ("download", "export", "generate", "report"):
                    add_api("GET", f"{res}/export", f"Export {obj} data", mk, ek, r["key"])
                elif act in ("login", "log in", "sign up", "reset"):
                    continue
                else:
                    add_api("POST", f"{res}/{{id}}/{act.replace(' ', '-')}", f"{act.title()} {obj}", mk, ek, r["key"])

    # -------- tests
    tests = []
    for r in reqs:
        tests.append(make_test(_key("TC", len(tests) + 1), r))
        if r["kind"] == "FR" and r["priority"] == "must":
            tests.append(make_test(_key("TC", len(tests) + 1), r, negative=True))

    # -------- risks
    risks = []

    def add_risk(title, desc, lk, im, mit, rkeys):
        risks.append({"key": _key("RSK", len(risks) + 1), "title": title, "description": desc, "likelihood": lk,
                      "impact": im, "mitigation": mit, "requirement_keys": rkeys})

    vague = [r["key"] for r in reqs if nlp.find_vague_terms(r["description"])]
    if vague:
        add_risk("Ambiguous requirements", f"{len(vague)} requirement(s) use vague wording that cannot be verified.", 4, 3,
                 "Rewrite with measurable acceptance criteria before baselining.", vague[:10])
    sec = [r["key"] for r in reqs if r["category"] == "security" or "password" in r["description"].lower()]
    if sec or needs_user:
        add_risk("Security / data breach", "User data and credentials could be exposed.", 3, 5,
                 "Hash passwords (bcrypt), enforce RBAC, TLS everywhere, SAST + dependency scanning in CI.", sec[:10])
    integ = [r["key"] for r in reqs if INTEGRATION_WORDS.search(r["description"])]
    if integ:
        add_risk("Third-party integration failure", "External services may be unavailable or change their API.", 3, 4,
                 "Wrap integrations behind adapters, add retries/timeouts and contract tests.", integ[:10])
    perf = [r["key"] for r in reqs if r["category"] in ("performance", "scalability", "availability")]
    if perf:
        add_risk("Performance targets not met", "Load or availability targets may not hold in production.", 3, 4,
                 "Load-test early, add caching and horizontal scaling, monitor with CloudWatch alarms.", perf[:10])
    add_risk("Scope creep", "New requirements arriving mid-delivery can derail the schedule.", 3 if len(reqs) < 25 else 4, 3,
             "Baseline the blueprint and route every change through change-impact review.", [])

    summary = (f"Blueprint with {len(reqs)} requirements ({sum(r['kind'] == 'FR' for r in reqs)} functional, "
               f"{sum(r['kind'] == 'NFR' for r in reqs)} non-functional) across {len(modules)} modules.")
    return {"summary": summary, "stakeholders": stakeholders, "constraints": constraints, "requirements": reqs,
            "stories": stories, "modules": modules, "entities": entities, "apis": apis, "tests": tests, "risks": risks}


def make_story(key: str, req: dict) -> dict:
    role = req.get("stakeholder") or "User"
    goal = _goal(req["description"])
    return {
        "key": key, "requirement_keys": [req["key"]], "role": role, "goal": goal,
        "benefit": _benefit(req["description"], req.get("category", "functional")),
        "acceptance_criteria": [
            f"Given I am an authorised {role.lower()}, when I {goal}, then the action succeeds and I see a confirmation.",
            "Given invalid or incomplete input, when I submit it, then I see a clear validation error and nothing is saved.",
            "Given the action succeeded, when I reload the page, then the change is persisted.",
        ],
        "priority": req.get("priority", "should"),
    }


def make_test(key: str, req: dict, negative: bool = False) -> dict:
    if req["kind"] == "NFR":
        return {"key": key, "title": f"Verify {req['category'].replace('_', ' ')}: {req['title'][:90]}",
                "requirement_keys": [req["key"]], "type": "non_functional",
                "steps": ["Prepare a production-like environment and test data",
                          f"Measure the system against: {req['description'][:160]}", "Record the measured values"],
                "expected": "Measured values meet the threshold stated in the requirement."}
    if negative:
        return {"key": key, "title": f"Reject invalid input: {req['title'][:100]}", "requirement_keys": [req["key"]],
                "type": "negative",
                "steps": ["Log in as an authorised user", "Attempt the action with missing / invalid data",
                          "Attempt the action as an unauthorised user"],
                "expected": "Validation errors (4xx) are returned and no data is changed."}
    return {"key": key, "title": f"Verify: {req['title'][:120]}", "requirement_keys": [req["key"]], "type": "functional",
            "steps": [f"Log in as {req.get('stakeholder', 'User').lower()}", f"Perform: {_goal(req['description'])[:150]}",
                      "Observe the result"],
            "expected": "The behaviour described in the requirement is observed and persisted."}
