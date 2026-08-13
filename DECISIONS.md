# Design decisions

## Postgres for v1 (not Mongo/Neo4j yet)
Contest → problem → submission data is inherently relational (foreign keys,
joins). Starting with one well-understood DB keeps the NL→query layer simple;
Mongo/Neo4j get added later for specific use cases (raw logs, relationship
queries) once the core pipeline works.
Trade-off: less flexible for unstructured data (e.g. raw submitted code) until
Mongo is added.

## LLM provider abstraction (Claude or Gemini, configurable)
A thin `LLMProvider` interface means swapping models is a config change, not
a rewrite, and lets us A/B cost/quality later.
Trade-off: slight upfront complexity vs. hardcoding one providear.

## Docker Postgres on a non-default port (5433)
Local machine already had a Homebrew Postgres bound to 5432. Rather than
touch that install, Docker's container maps to 5433 instead.
Trade-off: anyone cloning this repo needs to check their own 5432 isn't
occupied, or adjust DATABASE_URL accordingly. Documented in .env.example.

## Forced tool use for LLM structured output
Rather than prompting Claude to "return JSON" and hoping it complies, we
define a tool whose schema IS the response shape we want, then force
Claude to call it. Guarantees valid, parseable output every time.
Trade-off: slightly more setup than a plain prompt, but eliminates a whole
class of parsing failures.

## Two-layer safety: app-level validation + DB-level read-only role
LLM-generated SQL runs through a keyword/prefix check in db.py before
execution, AND the DB connection itself uses a Postgres role with only
SELECT granted. Neither layer alone is trusted - if the app check has a
bug or gets bypassed, the DB role still blocks writes.
Verified independently: DELETE was rejected both by the app check and,
separately, by Postgres directly when tested as nl2sql_readonly.

## Stateless multi-turn via client-supplied history
Rather than storing conversation state server-side (sessions, Redis, etc.),
the client resends the full conversation each time as a `history` array.
Keeps the backend simple and horizontally scalable from day one.
Trade-off: slightly more payload per request, and the client must track
history correctly - acceptable for v1, revisit if this becomes a real API
with many concurrent users.

## Project renamed nl2sql-project -> Multibase
Reflects the actual direction: Postgres now, Mongo and Neo4j later. The old
name only described the first phase.

## Schema + read-only role live in db/init/, not manual commands
Early on, the read-only Postgres role was created by hand via psql. Every
`docker compose down -v` silently deleted it, causing repeated
"password authentication failed" errors that took real debugging time to
trace back to a wiped volume.
Fixed by moving both schema.sql and the role creation into db/init/*.sql,
which Postgres runs automatically on first boot of a fresh volume. Schema
and permissions are now self-healing; only seed data needs a manual rerun
after a volume wipe (`python3 scripts/seed_progress.py`).

## Renaming the project folder requires recreating the venv
Python virtual environments bake in absolute paths at creation time.
Renaming nl2sql-project -> Multibase left the venv silently pointing at
the old path, causing confusing "module not found" and stale-code errors
that looked unrelated to the actual cause.
Fixed by deleting and recreating venv/ inside the new folder. Documented
here so future renames don't cost another debugging session.

## Chart type auto-detected from result shape
Rather than always showing a bar chart, the frontend inspects the query
result: a date-like label column -> line chart, few rows -> pie, long
labels or many rows -> horizontal bar, otherwise -> vertical bar. Falls
back to a plain table when the shape doesn't fit any chart (e.g. 2+
numeric columns). Every chart gets a legend (swatch + label + value).

## SQL panel is per-card, not a global drawer
Each result card has its own collapsible query panel that opens beside
its own output, sized to match. Kept as a single persistent DOM node
that toggles a CSS class (rather than swapping between two different
elements) after an early version's collapse button silently stopped
responding to clicks.

## Backend and frontend containerized, not just Postgres
Originally only Postgres ran in Docker; backend and frontend were started
manually in separate terminals with a venv that had to be activated each
time. Now `docker-compose.yml` runs all three services, with a Makefile
(`make up`, `make down`, `make reset`, `make seed`, `make logs`) wrapping
the common commands.
This also doubles as the deployment artifact - the same containers that
run locally are what would run in production - and gives a template for
adding mongo/neo4j services the same way.
Trade-off: `.env` had to be restructured (individual POSTGRES_* vars
instead of one DATABASE_URL) so docker-compose could build connection
strings using the internal service name (`postgres`) rather than
`localhost`, since containers reach each other by service name on the
docker network, not localhost.

## Known simplification: read-only role password isn't templated
db/init/01-readonly-role.sql hardcodes the read-only role's password
rather than reading it from READONLY_PASSWORD in .env, since Postgres
doesn't template init SQL files with env vars. Fine for local dev; needs
proper secret handling before real deployment.

## Retry Claude API calls on 529 (overloaded), not other errors
Anthropic's API occasionally returns 529 during high demand, which is
transient and worth a short retry (exponential backoff with jitter, 5
attempts). Other errors (bad key, invalid request) fail immediately
rather than wasting time retrying something that won't self-resolve.
Correction after initial fix attempts: the raised exception is
`anthropic.OverloadedError`, but it isn't reliably importable across SDK
versions. Settled on catching the base `anthropic.APIStatusError` and
checking `e.status_code == 529` instead - robust to exact subclass
naming, works regardless of which specific error class the SDK raises.

## Multi-provider fallback: Claude -> Gemini
Built on top of the existing LLMProvider interface, so main.py didn't
need to change shape - only the factory and the /ask endpoint's call
site.
- llm/gemini_provider.py implements the same LLMProvider interface, using
  Gemini's response_schema (structured output) as the equivalent of
  Claude's forced tool use.
- get_llm_provider() became get_llm_providers(), reading
  LLM_PROVIDER_ORDER (e.g. "claude,gemini") and returning an ordered list.
- /ask tries providers in order, catching APIStatusError (and other
  exceptions) per provider and falling through to the next on failure.
- Frontend priority selection (letting the user choose "Claude first" vs
  "Gemini first") is deferred - not needed yet, noted for later.
Direct motivation: repeated Claude 529 overload errors during dev were
blocking testing entirely, with no fallback path.

## MongoDB via Atlas (managed), not self-hosted Docker
Considered running Mongo in docker-compose like Postgres, but chose Atlas
free tier (M0) instead - consistent with the earlier decision to use
managed Postgres (Neon/Supabase) for deployment rather than self-hosting.
Same connection string works locally and in production with zero extra
setup at deploy time, unlike a self-hosted container which would need
somewhere to run in production.
Trade-off: requires an Atlas account/signup before local dev works at
all, and network access is currently 0.0.0.0/0 (open) for dev
convenience - needs tightening to specific IPs before real deployment.

## Three Mongo collections, not one
editorials alone felt like a token gesture rather than genuine polyglot
use. Added problem_statements (full problem text - description,
constraints, examples, which Postgres's problems table doesn't store)
and submission_code (actual submitted code, which Postgres only has
metadata for - verdict/runtime). Each is a natural fit for Mongo's
flexible-document model and gives the upcoming routing logic real,
distinct signal to route on.
Links back to Postgres loosely via problem_id/submission_id - shared id
convention, not a foreign key, checked at query time by the app rather
than enforced by either database.

## Mongo schema described in plain text for the LLM, same as Postgres
Mongo has no enforced schema, but the LLM still needs to know field names
and types to generate correct queries. mongo_schema_context.py mirrors
schema_context.py's job - not database-level validation, just what the
LLM is told before it writes a query. Considered adding a $jsonSchema
validator on the collections too, for actual write-time enforcement -
deferred for now since it's easy to retrofit later and the LLM-facing
schema doc was the higher-priority piece.

## seed_mongo.py needs the full container path, not a relative one
The backend Dockerfile sets WORKDIR to /app/backend, but scripts/ lives
at /app/scripts (one level up) - same layout as the local project.
`docker compose exec backend python /app/scripts/seed_mongo.py`, not a
path relative to the backend folder.

## Mongo safety: allowed-collection allowlist + read-only Atlas role, no query-string validation needed
Unlike Postgres (where the LLM generates a raw SQL string that needs
keyword/prefix validation), Mongo queries are never raw strings here -
only find() and aggregate() are exposed as callable operations, so
insert/update/delete aren't reachable even in principle. Added an
explicit block on aggregation's $merge/$out stages, since those can
write despite aggregate() otherwise being read-only.
Verified independently, same pattern as Postgres: insert was rejected
both by Atlas itself (read-only database user) and by the app-level
collection allowlist.

## .env changes require recreating the container, not just editing the file
docker-compose reads env_file once at container start. Editing .env
afterward has no effect on an already-running container - caused a
confusing "URL still has placeholder value" bug that looked like a typo
but was actually a stale container.
Fix: `docker compose up -d --force-recreate <service>` after any .env
change, or `docker compose up -d` which usually recreates services with
changed config automatically.

## Routing: one forced-tool-call picks the database AND generates the query
Rather than a separate "classify which DB" step before query generation,
Claude gets three tools in one call (query_postgres, query_mongo,
ask_clarification) with tool_choice: "any" (forces some tool, not a
specific one). It picks the right database and writes the matching query
language in a single round trip.

## tool_choice: "any" doesn't guarantee every "required" schema field is filled
Unlike tool_choice targeting one specific tool, forcing "any" tool from a
set is looser - Claude called query_mongo but sometimes omitted
"operation" despite it being marked required in the schema. Fixed by
inferring operation from whichever of filter/pipeline was actually
present, rather than trusting the field blindly.

## Lesson: verify a fix landed in the actual running file, not just what was pasted
Spent real debugging time because a shown "fix" wasn't actually saved to
main.py on disk - the container kept running the old code. Now standard
practice after any edit: grep the change on the host file AND inside the
container before retesting, rather than assuming a save took effect.

## Neo4j via AuraDB (managed), same reasoning as Mongo/Postgres
Consistent with the earlier managed-over-self-hosted decisions - one
connection string, works locally and in production, no stateful
container to host ourselves at deploy time.

## Graph model: thin Student/Problem nodes, relationships carry the value
Nodes only hold {id, name} or {id, title} - the real data stays in
Postgres, linked by the same id convention used for Mongo. The actual
payload is in the relationships: MENTORS, FOLLOWS, RIVAL_OF (students),
SIMILAR_TO with shared_tags (problems). This is what makes graph
questions (mentorship chains, "who's connected to whom") answerable in
Cypher in ways that would need recursive/self-joins in SQL.

## Recurring pattern: env var changes and requirements.txt changes both need a container recreate/rebuild
Hit this exact class of bug three times now across three different
databases (readonly Postgres role, MONGO_READONLY_URL, NEO4J_URI/neo4j
package) - editing .env or requirements.txt has zero effect on an
already-running container. Standard fix going forward:
- .env changes -> `docker compose up -d --force-recreate <service>`
- requirements.txt changes -> `docker compose up -d --build <service>`
Worth checking this FIRST whenever a value seems "correct but not
working" or an import fails right after adding a package.

## Neo4j safety: app-level Cypher validation only, no DB-level read-only role
Checked Aura's console directly - Free tier doesn't support custom
role/user creation (no Viewer role option), unlike Postgres (read-only
role) and Mongo (read-only Atlas user), which both got genuine DB-level
enforcement in addition to app-level checks.
Neo4j's safety here is single-layer: a regex check in neo4j_db.py blocks
CREATE/MERGE/DELETE/SET/REMOVE/DROP/LOAD CSV appearing anywhere in the
query text (Cypher write clauses can appear mid-query, unlike SQL where
a leading SELECT check is closer to sufficient).
Known gap, not hidden: if this app-level check has a bug, there's
currently no second layer to catch it, unlike the other two databases.
Worth revisiting if this project moves to Aura Professional (which does
support read-only roles) before real deployment.
Verified: write clauses (DETACH DELETE) correctly rejected; normal reads
return correct data.

## Neo4j wired into routing - all three databases live
Fourth tool (query_neo4j) added alongside query_postgres/query_mongo/
ask_clarification, same forced-tool-use pattern. Verified against known-
correct data from earlier direct checkpoint tests: "who does Jordan
Hines mentor" correctly returned Michael Smith and Jeffrey White via
neo4j; "problems similar to problem 35" correctly returned the same
shared-tag matches.

## Conversation history persists client-side with a rolling 24h expiry
Chat history is saved to localStorage, with a rolling 24-hour window
that resets on each new message rather than a fixed expiry from the
first message - a conversation stays alive as long as it's actively
used, only going stale after a full day of no activity.
Chosen over server-side session storage (Redis, etc.) for the same
reason as the stateless multi-turn design elsewhere in the app - keeps
the backend simple, no session store to run or scale.
Trade-off: history is tied to one browser - lost if localStorage is
cleared, doesn't sync across devices or browsers. Acceptable for v1.

## Auto-seed-if-empty on `make up`, explicit force-reseed kept separate
`make up` now runs seed_if_needed.py automatically - checks if
Postgres/Mongo/Neo4j are empty and seeds only if so, so a fresh fork's
setup is just "fill .env, make up" with no separate seed step to
remember. Kept explicit `make seed-postgres` / `seed-mongo` / `seed-neo4j`
/ `seed-all` for force-reseeding with fresh random data on demand -
different purpose (auto-seed is "make sure it's not empty", force-reseed
is "I want new random numbers"), so kept as separate commands.
Renamed scripts/seed.py -> scripts/seed_postgres.py for symmetry with
seed_mongo.py/seed_neo4j.py now that there are three databases.

## GeminiProvider had drifted out of sync with the 3-database routing
gemini_provider.py was still the original Postgres-only version from
before Mongo/Neo4j routing was added - would have silently only ever
queried Postgres if it were ever actually used as a fallback, despite
LLMResponse requiring target_db/mongo_query/cypher fields. Rewrote to
mirror ClaudeProvider's shape: a flat response_schema with target_db +
per-database fields (sql / mongo_collection+operation+filter+pipeline /
cypher), normalized to the same LLMResponse via _to_response(), same
pattern as Claude's tool-based routing.
Verified the fallback actually works, not just that each provider works
alone: temporarily invalidated ANTHROPIC_API_KEY, confirmed /ask still
returned a correct answer via Gemini, then restored the real key.

## /schema endpoint added - live record counts, not hardcoded numbers
Frontend's schema modal was calling /schema before the endpoint existed.
Built it to return structure (tables/collections/nodes/relationships)
plus a live count per one, queried through the same safe read functions
used everywhere else (run_query, run_aggregate with a $count stage,
run_cypher with count()) rather than a separate raw-access path.
This also makes the README's "Results" numbers unnecessary to hand-
maintain - the in-app schema modal is now the live source of truth.

## Neo4j frontend visualization: not yet built
Neo4j results currently render as a plain table/list like any other
result, not the static node-link diagram originally planned (see the
"simple static node-link diagram first, upgrade later" decision).
Routing and safety are done and verified; the graph visualization itself
is still open work.

## Postgres moved to Neon (managed), local Docker container removed
Completed the pattern started with Mongo/Neo4j - Postgres was the last
self-hosted stateful piece. Moved to Neon's free tier for the same
reasoning as Atlas/AuraDB: one connection string works locally and in
production, nothing stateful to host at deploy time.
Schema and read-only role applied manually via psql (Neon has no
docker-entrypoint-initdb.d equivalent - db/init/*.sql auto-runs only for
a local container's fresh volume). One correction needed during setup:
db/init/01-readonly-role.sql hardcodes `GRANT CONNECT ON DATABASE
nl2sql_db`, but Neon's default database is named `neondb` - the CONNECT
grant had to be re-run manually with the correct database name.
Verified independently, same as every other database: read-only role
can read (300 students) and correctly can't write (DELETE rejected).

## docker-compose.yml: postgres service removed entirely
DATABASE_URL/READONLY_DATABASE_URL now come straight from .env (already
complete Neon connection strings) via env_file, rather than being
reconstructed from POSTGRES_USER/PASSWORD/DB parts. Removed the pgdata
volume, the postgres healthcheck, and backend's depends_on: postgres -
nothing local left to wait on. Multibase now has zero self-hosted
stateful containers; only backend and frontend run locally.
Also removed: stale commented-out mongo/neo4j service blocks that
described a self-hosted approach we deliberately didn't take (see the
earlier Atlas/AuraDB decisions) - left as dead comments they'd mislead
anyone reading the file later.

## Lesson: removing a service from docker-compose.yml doesn't stop its running container
Editing the file to drop the `postgres` service didn't tear down the
already-running `multibase_postgres` container from before the edit -
Compose only manages containers matching its *current* config, so the
orphaned container kept holding the shared network open, causing
`docker compose down` to fail with "Resource is still in use."
Fix: `docker rm -f <container>` then `docker network rm <network>`
manually when a service is deliberately removed from the compose file,
don't assume `down` cleans up containers that are no longer defined.

## UptimeRobot pings /health every 10 min to prevent Render sleep
Render's free tier sleeps the backend after 15 min idle, causing a ~30s
cold start on the next request. UptimeRobot (free, 10-min interval)
pings GET /health to keep it awake — comfortably under the 15-min sleep
threshold with margin to spare.
Considered a GitHub Actions scheduled workflow instead - rejected, since
GitHub's own docs note scheduled cron isn't guaranteed to fire on time
(can be delayed or skipped under load), which defeats the purpose of a
tight keep-alive interval. UptimeRobot is dedicated monitoring infra,
not a side effect of a CI system.
Trade-off: keeping the backend always-on uses close to the full 750
free instance-hours/month Render grants - fine for one service, but
would need watching if a second free Render service is ever added on
the same account.
