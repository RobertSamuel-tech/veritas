"""Veritas — Agentic fact checker."""

node Claim {
    has text: str;
    has status: str = "unverified";
    has confidence: float = 0.0;
    has evidence_log: list = [];
}

node Evidence {
    has url: str;
    has snippet: str;
    has supports: bool = False;
    has confidence: float = 0.0;
    has credibility: float = 0.5;
}

node Task {
    has query: str;
    has step: str;
    has done: bool = False;
}

node Verdict {
    has summary: str;
    has confidence: float;
    has reasoning: str;
}

edge Supports { has strength: float; }
edge Contradicts { has severity: float; }
edge Discovered { has search_term: str; }
edge Requires {}

def decompose_claim(claim_text: str) -> list[str] by llm();
sem decompose_claim = "Break claim into 2-3 search queries. Return JSON list.";
sem decompose_claim.claim_text = "Claim to verify.";

def assess_evidence(snippet: str, claim: str) -> str by llm();
sem assess_evidence = "Return JSON: {supports: bool, confidence: float}.";
sem assess_evidence.snippet = "Web text.";
sem assess_evidence.claim = "Claim being checked.";

def assess_credibility(snippet: str, url: str) -> float by llm();
sem assess_credibility = "Rate 0.0-1.0. Return float only.";
sem assess_credibility.snippet = "Web text.";
sem assess_credibility.url = "Source URL.";

def synthesize_verdict(claim: str, evidence_list: list) -> str by llm();
sem synthesize_verdict = "Return JSON: {summary: str, confidence: float, reasoning: str}.";
sem synthesize_verdict.claim = "Original claim.";
sem synthesize_verdict.evidence_list = "Evidence list.";

walker:pub Investigator {
    has max_results: int = 3;
    has target_claim: Claim | None = None;

    can investigate with Task entry {
        claim_node: Claim | None = self.target_claim;
        if not claim_node {
            here.done = True;
            disengage;
        }

        import json;
        import duckduckgo_search;
        ddgs = duckduckgo_search.DDGS();
        results = ddgs.text(here.query, max_results=self.max_results);

        for r in results {
            cred = assess_credibility(r["body"], r["href"]);
            assessment = json.loads(assess_evidence(r["body"], claim_node.text));

            ev = Evidence(
                url=r["href"],
                snippet=r["body"][:200],
                supports=bool(assessment["supports"]),
                confidence=float(assessment["confidence"]),
                credibility=cred
            );

            here +>: Discovered(search_term=here.query) :+> ev;

            if assessment["supports"] {
                ev +>: Supports(strength=cred) :+> claim_node;
                claim_node.confidence += float(assessment["confidence"]) * cred;
            } else {
                ev +>: Contradicts(severity=1.0 - cred) :+> claim_node;
                claim_node.confidence -= float(assessment["confidence"]) * cred;
            }

            claim_node.evidence_log.append({
                "url": r["href"],
                "snippet": r["body"][:200],
                "supports": assessment["supports"],
                "confidence": assessment["confidence"],
                "credibility": str(cred)
            });
        }

        here.done = True;
    }
}

walker:pub VerdictAgent {
    can judge with Claim entry {
        import json;
        ev_list = here.evidence_log;

        result = json.loads(synthesize_verdict(here.text, ev_list));

        v = Verdict(
            summary=result["summary"],
            confidence=float(result["confidence"]),
            reasoning=result["reasoning"]
        );

        here ++> v;
        here.status = "verified";

        report v;
    }
}

walker:pub VerifyClaim {
    has claim_text: str;
    has max_results: int = 3;

    can verify with entry {
        import json;
        report {"probe": "walker_started"};

        try {
            c = Claim(text=self.claim_text);
            root ++> c;
            report {"probe": "claim_created", "claim_text": self.claim_text};

            queries = decompose_claim(self.claim_text);
            if not queries {
                queries = [self.claim_text];
            }

            import ddgs;

            for q in queries {
                t = Task(query=q, step="search", done=False);
                c +>: Requires() :+> t;
                evidence_count = 0;

                try {
                    searcher = ddgs.DDGS();
                    results = list(searcher.text(q, max_results=self.max_results));
                    report {"probe": "search_results", "query": q, "count": len(results)};

                    for r in results {
                        try {
                            url: str = str(r.get("href") or r.get("link") or "");
                            snippet: str = str(r.get("body") or r.get("snippet") or "");

                            if not snippet {
                                continue;
                            }

                            cred = assess_credibility(snippet, url);
                            assessment = json.loads(assess_evidence(snippet, self.claim_text));

                            ev = Evidence(
                                url=str(url),
                                snippet=str(snippet[:200]),
                                supports=bool(assessment["supports"]),
                                confidence=float(assessment["confidence"]),
                                credibility=float(cred)
                            );

                            t +>: Discovered(search_term=q) :+> ev;

                            if assessment["supports"] {
                                ev +>: Supports(strength=cred) :+> c;
                            } else {
                                ev +>: Contradicts(severity=1.0 - cred) :+> c;
                            }

                            c.evidence_log.append({
                                "url": url,
                                "snippet": snippet[:200],
                                "supports": assessment["supports"],
                                "confidence": assessment["confidence"],
                                "credibility": str(cred)
                            });

                            evidence_count += 1;
                        } except Exception as result_err {
                            report {"probe": "result_error", "query": q, "error": str(result_err)};
                        }
                    }
                    t.done = True;
                } except Exception as search_err {
                    report {"probe": "search_error", "query": q, "error": str(search_err)};
                }

                report {"probe": "investigator_run", "query": q, "evidence_count": evidence_count};
            }

            if not c.evidence_log {
                report {"probe": "no_evidence", "claim": self.claim_text};
                disengage;
            }

            result = json.loads(synthesize_verdict(self.claim_text, c.evidence_log));
            report {"probe": "verdict_spawned"};

            c.status = "verified";
            c.confidence = float(result["confidence"]);
            report {"probe": "verdict_collected", "verdict": result};

            report {
                "summary": result["summary"],
                "confidence": result["confidence"],
                "reasoning": result["reasoning"],
                "evidence": c.evidence_log
            };
            report {"probe": "walker_finished"};
        } except Exception as e {
            report {"probe": "outer_exception", "error": str(e)};
        }
    }
}