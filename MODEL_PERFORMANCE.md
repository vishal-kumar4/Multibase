# Multibase — Model Performance Report

Generated 2026-08-14 19:22 · target: `http://localhost:8000` · 24 questions

## Summary

| Metric | Result |
|---|---|
| Routing accuracy (clear questions) | 18/18 (100%) |
| Ambiguity detection accuracy | 21/24 (88%) |
| Requests with errors | 0/24 |
| Avg / min / max latency | 3726ms / 2931ms / 4636ms |

## Routing accuracy by database

| Database | Correct | Total | Accuracy |
|---|---|---|---|
| postgres | 6 | 6 | 100% |
| mongo | 6 | 6 | 100% |
| neo4j | 6 | 6 | 100% |

## Detail: clear questions (routing)

| Question | Expected | Actual | Result | Latency |
|---|---|---|---|---|
| Which student has the highest rating? | postgres | postgres | PASS | 3168ms |
| How many contests has each platform hosted? | postgres | postgres | PASS | 3418ms |
| Which students solved at least 10 hard problems? | postgres | postgres | PASS | 4338ms |
| Average submission runtime by language | postgres | postgres | PASS | 3377ms |
| Show me the top students by rating | postgres | postgres | PASS | 3557ms |
| How many submissions were accepted versus wrong answer? | postgres | postgres | PASS | 3032ms |
| What approach does the editorial for problem 35 use? | mongo | mongo | PASS | 3070ms |
| Show me editorials that use dynamic programming | mongo | mongo | PASS | 3425ms |
| What are the constraints for problem 12? | mongo | mongo | PASS | 3219ms |
| Show me a Python submission that got wrong answer | mongo | mongo | PASS | 3626ms |
| Which editorial has the most upvoted comment? | mongo | mongo | PASS | 3673ms |
| Show me the sample input and output for problem 5 | mongo | mongo | PASS | 2931ms |
| Who does Jordan Hines mentor? | neo4j | neo4j | PASS | 4343ms |
| Which problems are similar to problem 35? | neo4j | neo4j | PASS | 3497ms |
| Who follows Gary Williams? | neo4j | neo4j | PASS | 4284ms |
| Who are Jake Washington's rivals? | neo4j | neo4j | PASS | 3639ms |
| What problems share the dp tag with problem 12? | neo4j | neo4j | PASS | 4575ms |
| Which students mentor more than one person? | neo4j | neo4j | PASS | 4636ms |

## Detail: ambiguous questions (should ask for clarification)

| Question | Result | Clarifying question asked | Latency |
|---|---|---|---|
| Show me the top students | PASS | By "top students," do you mean by rating, number of AC submissions, or | 4177ms |
| Which problems are hardest? | PASS | By "hardest," do you mean by the difficulty label (e.g., most 'hard' p | 4034ms |
| Who are the worst performers? | PASS | Could you clarify what you mean by "worst performers"? For example, sh | 3350ms |
| Show me the best editorials | FAIL | - | 3837ms |
| Recent activity | FAIL | - | 4379ms |
| Show me the most active students | FAIL | - | 3851ms |

## Known limitations of this eval

- Checks *routing* correctness (right database) and *ambiguity* detection, not
  whether the returned data values are factually correct - that depends on the
  current seeded data, which is randomized per `seed_postgres.py` run.
- Doesn't distinguish whether Claude or the Gemini fallback answered - check
  backend logs during the run if fallback behavior needs verifying separately.
- LLM responses aren't fully deterministic - re-running may shift a few results,
  especially on borderline-ambiguous questions.
