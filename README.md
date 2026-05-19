# Veritas — Agentic Fact-Checking with Living Knowledge Graphs
## JacHacks Spring 2026 | Agentic AI Track

---

### 30-Second Pitch

**Veritas turns every claim into a live knowledge graph and lets autonomous walkers traverse it to verdict.**

Misinformation spreads faster than any single model can catch it. Veritas fights back with a multi-agent pipeline written entirely in Jac: one walker decomposes a claim into search queries, a second creates typed `Evidence` nodes from live web results, and a third synthesizes a confidence-weighted verdict — all wired together by Jac's graph-native edge semantics. The result is a single `main.jac` file that compiles into a full FastAPI backend, a live knowledge graph, and an auto-generated `/docs` page, with zero boilerplate.

---

### Architecture Diagram

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────┐
│  walker:pub VerifyClaim                         │
│  ┌──────────┐  :Requires:  ┌──────────────┐    │
│  │  Claim   │─────────────▶│    Task      │    │
│  │  (node)  │              │  (node, q)   │    │
│  └──────────┘              └──────┬───────┘    │
│       ▲                           │ :Discovered:│
│       │                           ▼             │
│  :Supports:              ┌────────────────┐     │
│  :Contradicts:           │   Evidence     │     │
│       │                  │  (node, url,   │     │
│       └──────────────────│   snippet,     │     │
│                          │   supports)    │     │
│                          └────────────────┘     │
│       │                                         │
│       ▼  walker:pub VerdictAgent                │
│  ┌──────────┐                                   │
│  │  Verdict │◀── synthesize_verdict() by llm()  │
│  │  (node)  │                                   │
│  └──────────┘                                   │
└─────────────────────────────────────────────────┘
         │
         ▼
   FastAPI /walker/VerifyClaim  ──▶  Frontend
```

#### Node & Edge Types

| Type | Kind | Description |
|------|------|-------------|
| `Claim` | node | The statement being verified; carries `confidence` float and `evidence_log` |
| `Task` | node | One search sub-query derived from the claim |
| `Evidence` | node | A single web result: `url`, `snippet`, `supports: bool`, `credibility` |
| `Verdict` | node | Final judgment: `summary`, `confidence`, `reasoning` |
| `:Requires:` | edge | Links a `Claim` to each of its `Task` nodes |
| `:Discovered:` | edge | Links a `Task` to the `Evidence` nodes it produced |
| `:Supports:` | edge | Evidence → Claim edge with a `strength` float |
| `:Contradicts:` | edge | Evidence → Claim edge with a `severity` float |

---

### Tech Stack

| Layer | Technology | Why |
|-------|------------|-----|
| Language | [Jac](https://github.com/Jaseci-Labs/jaseci) | AI-native, graph-first; `by llm()` and `walker:pub` eliminate boilerplate |
| LLM | OpenRouter GPT-4o-mini | Cheap, fast, JSON-reliable — routed via Jac's `byllm` plugin |
| Search | DuckDuckGo (`ddgs`) | Real-time, no API key, returns structured results |
| Backend | Auto-generated FastAPI | `jac start main.jac` compiles walkers into REST endpoints |
| Frontend | Vanilla HTML / JS | Calls the auto-generated API; zero build step |
| Proxy | FastAPI + httpx | `serve.py` serves `index.html` at `/` and forwards everything else to Jac |

---

### How It Works

```
① User types claim → POST /walker/VerifyClaim
② VerifyClaim walker:
     decompose_claim()  by llm()  →  ["query 1", "query 2", ...]
③   For each query:
       ddgs.text(query)  →  web results
       assess_credibility(snippet, url)  by llm()  →  float
       assess_evidence(snippet, claim)   by llm()  →  {supports, confidence}
       Evidence node created, linked via :Supports: or :Contradicts:
④ synthesize_verdict(claim, evidence_log)  by llm()  →  {summary, confidence, reasoning}
⑤ Frontend reads data.reports[-1] → renders confidence bar + evidence cards
```

Each `by llm()` call is annotated with `sem` declarations that act as typed prompts — Jac compiles them into structured LLM calls with JSON response enforcement.

---

### Jac Language Features Used

#### `by llm()` with `sem` declarations
```jac
def decompose_claim(claim_text: str) -> list[str] by llm();
sem decompose_claim = "Break claim into 2-3 search queries. Return JSON list.";
sem decompose_claim.claim_text = "Claim to verify.";

def synthesize_verdict(claim: str, evidence_list: list) -> str by llm();
sem synthesize_verdict = "Return JSON: {summary: str, confidence: float, reasoning: str}.";
```
`sem` annotations give the LLM typed, per-parameter context — no prompt engineering in application logic.

#### `walker:pub` auto-generates REST endpoints
```jac
walker:pub VerifyClaim {
    has claim_text: str;
    has max_results: int = 3;

    can verify with entry { ... }
}
```
`jac start main.jac` exposes this as `POST /walker/VerifyClaim` with a Swagger UI at `/docs` automatically.

#### Graph-native node/edge OSP
```jac
// Create and link nodes with typed edges in one expression
ev +>: Supports(strength=cred) :+> c;
ev +>: Contradicts(severity=1.0 - cred) :+> c;

// Traversal: link Claim to each Task
c +>: Requires() :+> t;
```
No ORM, no SQL — the knowledge graph is a first-class runtime structure.

#### Typed nodes with built-in fields
```jac
node Evidence {
    has url: str;
    has snippet: str;
    has supports: bool = False;
    has confidence: float = 0.0;
    has credibility: float = 0.5;
}

node Verdict {
    has summary: str;
    has confidence: float;
    has reasoning: str;
}
```

---

### File Structure

```
veritas/
├── main.jac          # Entire backend: nodes, edges, walkers, LLM calls
├── index.html        # Frontend: claim input, confidence bar, evidence cards
├── serve.py          # Proxy: serves index.html + forwards API to Jac on :8001
├── jac.toml          # Project config: LLM model, OpenRouter endpoint, plugins
└── .venv/            # Python environment with jaclang + dependencies
```

---

### Running Locally

```bash
# 1. Install dependencies
pip install jaclang duckduckgo-search

# 2. Set your OpenRouter API key in jac.toml
#    plugins.byllm.model.api_key = "sk-or-..."

# 3. Start everything (proxy on :8000, Jac backend on :8001)
python serve.py

# 4. Open
open http://localhost:8000
```

API docs auto-generated at `http://localhost:8000/docs`.

---

### Why Jac?

Most hackathon projects bolt an LLM onto an existing web framework. Veritas is different: **the graph is the data model, the walkers are the agents, and the LLM calls are typed language primitives.** Jac lets us express "an agent that traverses a knowledge graph, creates typed nodes from web evidence, and synthesizes a verdict" in a single file with no glue code — because that's exactly what the language was designed for.

---

### Test Claims

Use these claims to try out Veritas:

| Claim | Expected Verdict |
|-------|-----------------|
| Vaccines cause autism. | False |
| Human activity is the primary driver of current global warming. | True |
| Large language models can hallucinate incorrect information. | True |
| Electric vehicles produce fewer lifetime emissions than gasoline cars. | True (generally) |
| Humans use only 10% of their brains. | False |
| 5G networks cause harmful health effects. | False |
| The Great Wall of China is visible from space. | False |
| Drinking coffee causes dehydration. | False |

---

*Built for JacHacks Spring 2026 by the Veritas team.*
