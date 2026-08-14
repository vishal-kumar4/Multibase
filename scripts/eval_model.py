"""
Evaluates Multibase's routing and clarification accuracy against a fixed
test set, then writes a markdown report.

Usage:
    python3 eval_model.py                          # tests http://localhost:8000
    python3 eval_model.py https://your-app.onrender.com

Paced at ~7s between calls to stay comfortably under the 10/min rate
limit on /ask. A 24-question set takes ~3 minutes to run.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DELAY_SECONDS = 7

# each entry: question, expected_db (postgres/mongo/neo4j/None), expected_ambiguous (bool)
TEST_SET = [
    # --- Postgres: clear, unambiguous ---
    {"q": "Which student has the highest rating?", "expected_db": "postgres", "expected_ambiguous": False},
    {"q": "How many contests has each platform hosted?", "expected_db": "postgres", "expected_ambiguous": False},
    {"q": "Which students solved at least 10 hard problems?", "expected_db": "postgres", "expected_ambiguous": False},
    {"q": "Average submission runtime by language", "expected_db": "postgres", "expected_ambiguous": False},
    {"q": "Show me the top students by rating", "expected_db": "postgres", "expected_ambiguous": False},
    {"q": "How many submissions were accepted versus wrong answer?", "expected_db": "postgres", "expected_ambiguous": False},

    # --- MongoDB: clear, unambiguous ---
    {"q": "What approach does the editorial for problem 35 use?", "expected_db": "mongo", "expected_ambiguous": False},
    {"q": "Show me editorials that use dynamic programming", "expected_db": "mongo", "expected_ambiguous": False},
    {"q": "What are the constraints for problem 12?", "expected_db": "mongo", "expected_ambiguous": False},
    {"q": "Show me a Python submission that got wrong answer", "expected_db": "mongo", "expected_ambiguous": False},
    {"q": "Which editorial has the most upvoted comment?", "expected_db": "mongo", "expected_ambiguous": False},
    {"q": "Show me the sample input and output for problem 5", "expected_db": "mongo", "expected_ambiguous": False},

    # --- Neo4j: clear, unambiguous ---
    {"q": "Who does Jordan Hines mentor?", "expected_db": "neo4j", "expected_ambiguous": False},
    {"q": "Which problems are similar to problem 35?", "expected_db": "neo4j", "expected_ambiguous": False},
    {"q": "Who follows Gary Williams?", "expected_db": "neo4j", "expected_ambiguous": False},
    {"q": "Who are Jake Washington's rivals?", "expected_db": "neo4j", "expected_ambiguous": False},
    {"q": "What problems share the dp tag with problem 12?", "expected_db": "neo4j", "expected_ambiguous": False},
    {"q": "Which students mentor more than one person?", "expected_db": "neo4j", "expected_ambiguous": False},

    # --- Deliberately ambiguous ---
    {"q": "Show me the top students", "expected_db": None, "expected_ambiguous": True},
    {"q": "Which problems are hardest?", "expected_db": None, "expected_ambiguous": True},
    {"q": "Who are the worst performers?", "expected_db": None, "expected_ambiguous": True},
    {"q": "Show me the best editorials", "expected_db": None, "expected_ambiguous": True},
    {"q": "Recent activity", "expected_db": None, "expected_ambiguous": True},
    {"q": "Show me the most active students", "expected_db": None, "expected_ambiguous": True},
]


def call_ask(question):
    payload = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms = round((time.time() - start) * 1000)
            body = json.loads(resp.read())
            return {"http_status": resp.status, "elapsed_ms": elapsed_ms, "body": body}
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.time() - start) * 1000)
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"detail": str(e)}
        return {"http_status": e.code, "elapsed_ms": elapsed_ms, "body": body}
    except Exception as e:
        return {"http_status": None, "elapsed_ms": None, "body": {"error": str(e)}}


def run_eval():
    results = []
    print(f"Testing {BASE_URL} against {len(TEST_SET)} questions, ~{DELAY_SECONDS}s apart...\n")

    for i, case in enumerate(TEST_SET, 1):
        r = call_ask(case["q"])
        body = r["body"]
        status = body.get("status")
        source = body.get("source")
        is_ambiguous = status == "ambiguous"

        routing_correct = None
        if not case["expected_ambiguous"]:
            routing_correct = (source == case["expected_db"])

        ambiguity_correct = (is_ambiguous == case["expected_ambiguous"])

        result = {
            "question": case["q"],
            "expected_db": case["expected_db"],
            "expected_ambiguous": case["expected_ambiguous"],
            "http_status": r["http_status"],
            "elapsed_ms": r["elapsed_ms"],
            "actual_status": status,
            "actual_source": source,
            "ambiguity_correct": ambiguity_correct,
            "routing_correct": routing_correct,
            "clarifying_question": body.get("clarifying_question"),
            "row_count": body.get("row_count"),
            "error_detail": body.get("detail") if r["http_status"] and r["http_status"] >= 400 else None,
        }
        results.append(result)

        tag = "OK" if (ambiguity_correct and (routing_correct is not False)) else "MISS"
        print(f"[{i}/{len(TEST_SET)}] {tag:4} | {r['elapsed_ms']}ms | {case['q'][:55]}")

        if i < len(TEST_SET):
            time.sleep(DELAY_SECONDS)

    return results


def build_report(results):
    total = len(results)
    ambiguous_cases = [r for r in results if r["expected_ambiguous"]]
    clear_cases = [r for r in results if not r["expected_ambiguous"]]

    ambiguity_hits = sum(1 for r in results if r["ambiguity_correct"])
    routing_hits = sum(1 for r in clear_cases if r["routing_correct"])
    errors = sum(1 for r in results if r["error_detail"])

    latencies = [r["elapsed_ms"] for r in results if r["elapsed_ms"] is not None]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else None
    max_latency = max(latencies) if latencies else None
    min_latency = min(latencies) if latencies else None

    per_db = {}
    for db in ["postgres", "mongo", "neo4j"]:
        cases = [r for r in clear_cases if r["expected_db"] == db]
        hits = sum(1 for r in cases if r["routing_correct"])
        per_db[db] = (hits, len(cases))

    lines = []
    lines.append("# Multibase — Model Performance Report")
    lines.append("")
    lines.append(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · target: `{BASE_URL}` · {total} questions")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Result |")
    lines.append("|---|---|")
    lines.append(f"| Routing accuracy (clear questions) | {routing_hits}/{len(clear_cases)} ({round(100*routing_hits/len(clear_cases)) if clear_cases else 0}%) |")
    lines.append(f"| Ambiguity detection accuracy | {ambiguity_hits}/{total} ({round(100*ambiguity_hits/total)}%) |")
    lines.append(f"| Requests with errors | {errors}/{total} |")
    lines.append(f"| Avg / min / max latency | {avg_latency}ms / {min_latency}ms / {max_latency}ms |")
    lines.append("")
    lines.append("## Routing accuracy by database")
    lines.append("")
    lines.append("| Database | Correct | Total | Accuracy |")
    lines.append("|---|---|---|---|")
    for db, (hits, total_db) in per_db.items():
        pct = round(100 * hits / total_db) if total_db else 0
        lines.append(f"| {db} | {hits} | {total_db} | {pct}% |")
    lines.append("")
    lines.append("## Detail: clear questions (routing)")
    lines.append("")
    lines.append("| Question | Expected | Actual | Correct | Latency |")
    lines.append("|---|---|---|---|---|")
    for r in clear_cases:
        mark = "PASS" if r["routing_correct"] else "FAIL"
        lines.append(f"| {r['question']} | {r['expected_db']} | {r['actual_source'] or '-'} | {mark} | {r['elapsed_ms']}ms |")
    lines.append("")
    lines.append("## Detail: ambiguous questions (should ask for clarification)")
    lines.append("")
    lines.append("| Question | Result | Clarifying question asked | Latency |")
    lines.append("|---|---|---|---|")
    for r in ambiguous_cases:
        mark = "PASS" if r["ambiguity_correct"] else "FAIL"
        cq = (r["clarifying_question"] or "-")[:70]
        lines.append(f"| {r['question']} | {mark} | {cq} | {r['elapsed_ms']}ms |")
    lines.append("")
    if errors:
        lines.append("## Errors")
        lines.append("")
        for r in results:
            if r["error_detail"]:
                lines.append(f"- **{r['question']}** - HTTP {r['http_status']}: {r['error_detail']}")
        lines.append("")
    lines.append("## Known limitations of this eval")
    lines.append("")
    lines.append("- Checks *routing* correctness (right database) and *ambiguity* detection, not")
    lines.append("  whether the returned data values are factually correct - that depends on the")
    lines.append("  current seeded data, which is randomized per `seed_postgres.py` run.")
    lines.append("- Doesn't distinguish whether Claude or the Gemini fallback answered - check")
    lines.append("  backend logs during the run if fallback behavior needs verifying separately.")
    lines.append("- LLM responses aren't fully deterministic - re-running may shift a few results,")
    lines.append("  especially on borderline-ambiguous questions.")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    results = run_eval()
    with open("eval_results.json", "w") as f:
        json.dump(results, f, indent=2)
    report = build_report(results)
    with open("MODEL_PERFORMANCE.md", "w") as f:
        f.write(report)
    print("\nWrote eval_results.json and MODEL_PERFORMANCE.md")
