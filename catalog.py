"""Curated interview content: tracks, levels, interview kinds, styles, and seeds.

A *seed* is a known-good topic a human picked. The planner model expands a
seed into a full interview; it never invents a topic from nothing. Picking
seeds here (in code) instead of asking the model for "a random problem" is
what keeps interviews varied and keeps them from drifting into generic slop.
"""
import random
from dataclasses import dataclass

TRACKS = {
    "swe": "Software Engineering",
    "aiml": "AI/ML Engineering",
    "security": "Cybersecurity",
}
LEVELS = {
    "intern": "Intern",
    "newgrad": "New grad",
}
KINDS = {
    "coding": {"label": "Coding", "minutes": 45, "blurb": "Solve a problem in Python while talking it through."},
    "system_design": {"label": "System design", "minutes": 45, "blurb": "Design a system out loud. Ask questions, make trade-offs."},
    "behavioral": {"label": "Behavioral", "minutes": 30, "blurb": "Tell real stories about how you work."},
    "resume": {"label": "Resume deep dive", "minutes": 30, "blurb": "Explain your projects, then get drilled on them."},
}


@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    voice: str  # Gemini prebuilt voice
    style: str  # injected into the interviewer's instructions


PERSONAS = {
    "warm": Persona(
        "warm", "Warm", "Sulafat",
        "Friendly and encouraging. Smile in your voice, put the candidate at ease, "
        "acknowledge good points briefly. Still hold the bar: friendly is not lenient, "
        "and you still redirect and probe.",
    ),
    "neutral": Persona(
        "neutral", "Neutral", "Charon",
        "Professional and even. Polite but not effusive. Short acknowledgements "
        "('okay', 'got it'), no praise. Typical big-tech interviewer.",
    ),
    "tough": Persona(
        "tough", "Tough", "Kore",
        "Terse and demanding. Push back on vague or hand-wavy answers, ask 'why?' and "
        "'what would break?', interrupt rambling quickly. Never rude or insulting, "
        "but you do not fill silences or reassure.",
    ),
}

# First names for the interviewer, so each interview feels like a new person.
INTERVIEWER_NAMES = ["Maya", "Daniel", "Priya", "Marcus", "Elena", "Kenji", "Sofia", "Omar", "Hannah", "Lucas"]


@dataclass(frozen=True)
class Seed:
    id: str
    title: str
    brief: str  # guidance for the planner


def _s(id_: str, title: str, brief: str) -> Seed:
    return Seed(id_, title, brief)


# --- Coding: problem patterns, per track. Each yields a fresh problem. -------
CODING_SEEDS = {
    "swe": [
        _s("hash-map-counting", "Hash map counting", "Frequency counting / grouping with dicts (e.g. anagram groups, first unique, top-k frequent)."),
        _s("two-pointers", "Two pointers", "Two pointers on a sorted array or string (pair sums, dedupe in place, container problems)."),
        _s("sliding-window", "Sliding window", "Variable-size window with a dict/set (longest substring with a constraint, minimum window)."),
        _s("intervals", "Intervals", "Sort-then-sweep intervals (merge, insert, meeting rooms, free time)."),
        _s("bfs-grid", "BFS on a grid", "Shortest path or flood fill on a 2D grid (islands, rotting oranges, walls and gates)."),
        _s("graph-topo", "Topological sort", "Dependency ordering with cycle detection (course schedule, build order)."),
        _s("heap-topk", "Heaps", "Heap for top-k / k-way merge / running median / task scheduling."),
        _s("binary-search", "Binary search on the answer", "Binary search over a monotonic condition (min capacity, koko bananas, first bad version variants)."),
        _s("stack-monotonic", "Stacks", "Stack or monotonic stack (valid brackets, next greater element, daily temperatures, basic calculator)."),
        _s("linked-structures", "Linked structures / design", "Design a small data structure (LRU cache, min stack, iterator) with complexity guarantees."),
        _s("trees-dfs", "Trees", "Binary tree recursion/DFS (diameter, lowest common ancestor, serialize, path sums)."),
        _s("dp-1d", "1-D dynamic programming", "Classic 1-D DP with a clear recurrence (house robber, decode ways, coin change, word break)."),
        _s("distributed-flavor", "Distributed-systems flavored", "An algorithm with a systems story: consistent hashing ring lookup, rate limiter window counting, merging sorted logs from many servers, or dedupe of retried requests by id."),
    ],
    "aiml": [
        _s("topk-scores", "Top-k with a heap", "Return top-k items by model score from a stream; discuss heap vs sort and ties."),
        _s("kmeans-step", "One k-means step", "Implement one assignment+update step of k-means in plain Python (no numpy); edge cases like empty clusters."),
        _s("tokenizer", "Tokenizer", "A simple whitespace/punctuation tokenizer or a greedy longest-match (WordPiece-style) tokenizer over a vocab."),
        _s("sliding-metrics", "Sliding-window metrics", "Moving average / rolling accuracy over a stream of predictions with O(1) updates."),
        _s("confusion-matrix", "Metrics from scratch", "Compute precision/recall/F1 per class from labels and predictions; macro vs micro averaging."),
        _s("cosine-nn", "Nearest neighbors", "Find the k most similar embeddings by cosine similarity in plain Python; discuss brute force vs ANN."),
        _s("batching", "Batching and padding", "Group variable-length sequences into batches under a max token budget, minimizing padding."),
        _s("dedupe-data", "Dataset dedupe", "Detect near-duplicate text examples via normalization + hashing (or shingles); discuss trade-offs."),
        _s("graph-bfs-ml", "Graph traversal", "BFS/DFS over a dependency graph of pipeline steps or a knowledge graph; detect cycles."),
        _s("dp-edit-distance", "Edit distance", "Levenshtein distance DP (used for fuzzy matching / eval); space optimization follow-up."),
        _s("reservoir-sampling", "Sampling a stream", "Reservoir sampling of k examples from an unbounded stream; prove uniformity informally."),
    ],
    "security": [
        _s("bruteforce-logs", "Brute-force detection", "Parse auth log lines and flag IPs with >N failed logins within a sliding time window."),
        _s("log-parsing", "Log parsing", "Parse semi-structured log lines (regex or split), aggregate by user/status, handle malformed lines."),
        _s("anomaly-baseline", "Baseline anomalies", "Flag users whose daily request count deviates from their own rolling baseline."),
        _s("password-policy", "Input validation", "Validate passwords or usernames against a policy; return all violated rules; avoid regex pitfalls."),
        _s("path-traversal", "Path normalization", "Normalize a user-supplied file path and reject traversal outside a base dir (like os.path.normpath by hand)."),
        _s("ip-ranges", "IP allow/deny lists", "Check IPv4 addresses against CIDR ranges; merge overlapping ranges."),
        _s("hash-integrity", "File integrity", "Compare file hash manifests between two snapshots; report added/removed/modified files."),
        _s("session-tokens", "Session expiry", "Track sessions with expiry and refresh; evict expired ones efficiently (heap or ordered dict)."),
        _s("port-scan-detect", "Scan detection", "From connection records, detect hosts contacting many distinct ports/hosts in a short window."),
        _s("url-sanitize", "URL checks", "Parse URLs and flag suspicious ones (lookalike domains, IP hosts, credentials in URL, odd ports)."),
    ],
}

# --- System design prompts, per track. ---------------------------------------
DESIGN_SEEDS = {
    "swe": [
        _s("rate-limiter", "Distributed rate limiter", "Rate limiter shared across many API servers; token bucket vs sliding window; where state lives; failure mode if the store is down."),
        _s("url-shortener", "URL shortener", "ID generation, read-heavy caching, redirects, analytics, hot keys."),
        _s("kv-store", "Distributed key-value store", "Partitioning, replication, quorum reads/writes, consistency trade-offs, node failure."),
        _s("chat-system", "Chat system", "1:1 and group messaging, delivery guarantees, ordering, online presence, offline users."),
        _s("news-feed", "News feed", "Fan-out on write vs read, celebrity problem, ranking, caching."),
        _s("job-queue", "Distributed job queue", "At-least-once delivery, retries, idempotency, visibility timeouts, dead-letter queues."),
        _s("notification-service", "Notification service", "Multi-channel notifications, rate limits per user, retries, templating, priorities."),
        _s("file-storage", "File storage / sync", "Upload chunking, dedupe, metadata vs blob storage, sync conflicts."),
        _s("metrics-pipeline", "Metrics collection pipeline", "Ingest from many hosts, aggregation, retention, querying recent vs old data."),
        _s("leaderboard", "Real-time leaderboard", "High write rate scores, top-N queries, sharding sorted sets, consistency."),
    ],
    "aiml": [
        _s("rag-chatbot", "RAG chatbot over company docs", "Ingestion, chunking, embeddings, vector index, retrieval, prompt assembly, evals, hallucination control."),
        _s("recommender", "Recommendation system", "Candidate generation + ranking, features, cold start, offline vs online metrics, feedback loops."),
        _s("model-serving", "Model serving platform", "Latency SLOs, batching, autoscaling GPUs, model versioning, canary rollouts."),
        _s("feature-store", "Feature store", "Offline/online consistency, point-in-time correctness, freshness, backfills."),
        _s("eval-pipeline", "LLM evaluation pipeline", "Datasets, automatic and human evals, regression detection, cost control."),
        _s("content-moderation", "Content moderation system", "Classifier cascade, human review queue, thresholds, appeals, adversarial users."),
        _s("search-ranking", "Search with learned ranking", "Indexing, retrieval, learning-to-rank, click feedback, A/B testing."),
        _s("training-pipeline", "Distributed training pipeline", "Data loading, sharding, checkpointing, failure recovery, experiment tracking."),
    ],
    "security": [
        _s("secure-login", "Secure login system", "Password storage, MFA, session management, brute-force protection, account recovery; threat model it."),
        _s("secrets-manager", "Secrets management", "How services get credentials: storage, rotation, access control, audit, blast radius."),
        _s("siem-pipeline", "Detection / logging pipeline", "Collecting logs from many hosts, normalization, detection rules, alert fatigue, retention."),
        _s("api-gateway-auth", "API gateway authentication", "Tokens (JWT vs opaque), service-to-service auth, rate limiting, revocation."),
        _s("file-upload", "Secure file upload service", "Malware scanning, content-type validation, storage isolation, signed URLs."),
        _s("zero-trust", "Zero-trust internal access", "Device posture, identity-aware proxy, least privilege, lateral-movement limits."),
        _s("incident-response", "Incident response tooling", "Detecting a compromised account, containment, forensics data, communication."),
        _s("vuln-management", "Vulnerability management", "Asset inventory, scanning, prioritization (CVSS vs exploitability), patch SLAs."),
    ],
}

# --- Behavioral competencies (an interview covers 3-4). ----------------------
BEHAVIORAL_COMPETENCIES = [
    _s("ownership", "Ownership", "A time they took responsibility beyond their assigned scope."),
    _s("conflict", "Conflict", "A disagreement with a teammate or lead and how it was resolved."),
    _s("failure", "Failure", "A mistake or failure, what they learned, what they changed."),
    _s("ambiguity", "Ambiguity", "Making progress when requirements were unclear."),
    _s("learning", "Learning fast", "Picking up an unfamiliar technology or domain quickly."),
    _s("teamwork", "Teamwork", "Contributing to a team project; their specific role."),
    _s("deadline", "Pressure / deadlines", "Delivering under time pressure; trade-offs they made."),
    _s("feedback", "Receiving feedback", "Critical feedback they got and what they did with it."),
    _s("impact", "Impact", "The project they're proudest of and its measurable result."),
    _s("motivation", "Motivation", "Why this field / this kind of role; what draws them."),
]

# --- Resume deep dive angles. -----------------------------------------------
RESUME_ANGLES = [
    _s("technical-depth", "Technical depth", "Push on how things actually work under the hood: data flow, choices of libraries, limits."),
    _s("decisions", "Decisions and trade-offs", "Why each design choice was made, what alternatives were considered, what they'd change."),
    _s("impact-ownership", "Impact and ownership", "What exactly they built vs the team, how success was measured, numbers behind claims."),
    _s("debugging", "Debugging and failure", "The hardest bug or failure in each project and how they found and fixed it."),
]


# --- Structure: fixed phases and rubric per kind. ---------------------------
# Phases and rubric categories are fixed in code, not invented per interview,
# so every interview of a kind has the same shape and scores stay comparable
# over time. The planner only fills in the content of each phase.
PHASES = {
    "coding": [
        ("intro", "Introductions", 4),
        ("problem", "Problem: clarify, approach, code, test", 30),
        ("follow_up", "Follow-up variant and complexity", 6),
        ("candidate_questions", "Candidate's questions", 5),
    ],
    "system_design": [
        ("intro", "Introductions", 4),
        ("requirements", "Requirements and scale", 9),
        ("high_level", "High-level design", 12),
        ("deep_dive", "Deep dives and trade-offs", 15),
        ("candidate_questions", "Candidate's questions", 5),
    ],
    "behavioral": [
        ("intro", "Introductions", 3),
        ("questions", "Behavioral questions", 22),
        ("candidate_questions", "Candidate's questions", 5),
    ],
    "resume": [
        ("intro", "Introductions", 3),
        ("projects", "Project deep dives", 22),
        ("candidate_questions", "Candidate's questions", 5),
    ],
}

RUBRICS = {
    "coding": [
        ("understanding", "Problem understanding", "Restates the problem, asks clarifying questions, identifies edge cases before coding."),
        ("approach", "Approach & problem solving", "Starts from a workable approach, improves it, reasons about alternatives. Needing hints lowers this."),
        ("correctness", "Code correctness", "Code works for the examples and edge cases; bugs found and fixed by the candidate count in their favor."),
        ("code_quality", "Code quality", "Readable Pythonic code, good names, small functions, no needless complexity."),
        ("complexity", "Complexity analysis", "States correct time and space complexity and can justify it."),
        ("communication", "Communication", "Thinks out loud, explains decisions before and while coding, keeps the interviewer in the loop."),
    ],
    "system_design": [
        ("requirements", "Requirements gathering", "Asks about users, scale, functional and non-functional requirements before designing."),
        ("high_level", "High-level design", "Clear components and data flow that meet the requirements; sensible APIs and data model."),
        ("tradeoffs", "Deep dives & trade-offs", "Goes deep on the hard parts and names real trade-offs instead of buzzwords."),
        ("scale_failure", "Scale & failure handling", "Back-of-envelope numbers, bottlenecks, replication, what happens when things fail."),
        ("communication", "Communication", "Structured, drives the discussion, checks in with the interviewer, adapts to hints."),
    ],
    "behavioral": [
        ("structure", "Structure (STAR)", "Situation, task, action, result: easy to follow, not rambling."),
        ("specificity", "Specificity & impact", "Concrete details, their own actions, and measurable results."),
        ("ownership", "Ownership", "Says 'I' for their own work, takes responsibility, shows initiative."),
        ("reflection", "Reflection", "What they learned and would do differently; self-aware, not defensive."),
        ("communication", "Communication", "Concise, answers the question asked, engaging to listen to."),
    ],
    "resume": [
        ("depth", "Depth of understanding", "Explains how their projects really work, beyond the resume bullet."),
        ("accuracy", "Technical accuracy", "Technical claims are correct; knows the limits of what they built."),
        ("ownership", "Ownership & impact", "Clear about their own contribution and how success was measured."),
        ("clarity", "Clarity", "Explains complex work simply, at the right level for the listener."),
        ("communication", "Communication", "Concise, engaging, handles follow-ups calmly."),
    ],
}


def _pick_weighted(pool: list[Seed], recent: list[str], rng: random.Random) -> Seed:
    """Prefer seeds not used recently. Recent use lowers weight; never zero."""
    weights = []
    for seed in pool:
        if seed.id in recent:
            # The more recently used, the lower the weight (index 0 = newest).
            age = recent.index(seed.id)
            weights.append(0.01 + 0.005 * age)
        else:
            weights.append(1.0)
    return rng.choices(pool, weights=weights, k=1)[0]


def pick_seeds(kind: str, track: str, recent: list[str], rng: random.Random | None = None) -> list[Seed]:
    """Pick the seed(s) for one interview, avoiding ones in `recent` (newest first)."""
    rng = rng or random.Random()
    if kind == "coding":
        return [_pick_weighted(CODING_SEEDS[track], recent, rng)]
    if kind == "system_design":
        return [_pick_weighted(DESIGN_SEEDS[track], recent, rng)]
    if kind == "behavioral":
        pool = list(BEHAVIORAL_COMPETENCIES)
        chosen: list[Seed] = []
        for _ in range(4):
            seed = _pick_weighted(pool, recent, rng)
            chosen.append(seed)
            pool.remove(seed)
        return chosen
    if kind == "resume":
        return [_pick_weighted(RESUME_ANGLES, recent, rng)]
    raise ValueError(f"Unknown interview kind: {kind}")


def pick_persona(choice: str, rng: random.Random | None = None) -> Persona:
    rng = rng or random.Random()
    if choice in PERSONAS:
        return PERSONAS[choice]
    return rng.choice(list(PERSONAS.values()))


def options() -> dict:
    """Everything the setup screen needs to render its choices."""
    return {
        "tracks": [{"id": k, "label": v} for k, v in TRACKS.items()],
        "levels": [{"id": k, "label": v} for k, v in LEVELS.items()],
        "kinds": [{"id": k, **v} for k, v in KINDS.items()],
        "personas": [{"id": p.id, "label": p.label} for p in PERSONAS.values()]
        + [{"id": "random", "label": "Surprise me"}],
        "rubrics": {k: [{"id": cid, "label": label} for cid, label, _ in v] for k, v in RUBRICS.items()},
    }
