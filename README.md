# Multibase

Ask a question in plain English about a competitive programming platform.
One LLM call reads the schema of three different databases, picks the one
your question actually needs, writes the query, and hands back a table,
chart, document view, or graph — automatically.

**Live**: [multibase-ten.vercel.app](https://multibase-ten.vercel.app) ·

## Highlights

- **Three databases, one question box** — Postgres for structured data,
  MongoDB for flexible documents, Neo4j for relationships. No database
  picker, ever.
- **One routing call, not two** — the same LLM call that picks the
  database also writes the query, using forced tool-use / structured
  output so the response is always valid.
- **Asks when it should, not guesses** — bare superlatives like "top
  students" trigger a clarifying question instead of a silent default.
  Multi-turn context persists across the follow-up.
- **Claude → Gemini fallback** — a provider-agnostic interface means a
  Claude outage transparently falls through to Gemini mid-request.
- **Defense in depth, honestly documented** — every generated query is
  validated before execution. Two layers where the platform allows it
  (Postgres, MongoDB); one layer where it doesn't (Neo4j's free tier has
  no read-only role) — stated plainly, not hidden.
- **Zero self-hosted databases** — Postgres (Neon), MongoDB (Atlas), and
  Neo4j (AuraDB) are all managed, so the same setup works identically on
  a laptop and in production.

Full system design, diagrams, and the security model: see
[`ARCHITECTURE.md`](./ARCHITECTURE.md). Full history of *why* things are
built this way: see [`DECISIONS.md`](./DECISIONS.md).

## Run it locally

**Prerequisites**: Docker, and free accounts for [Neon](https://neon.tech)
(Postgres), [MongoDB Atlas](https://mongodb.com/cloud/atlas), and
[Neo4j AuraDB](https://console.neo4j.io) — all managed, no local database
containers needed.

```bash
cp .env.example .env    # fill in your database URLs + ANTHROPIC_API_KEY
                         # (GEMINI_API_KEY optional, enables fallback)
make up                  # builds + starts backend and frontend,
                          # auto-seeds any database that's currently empty
```

Open **http://localhost:5173**. Backend runs at **http://localhost:8000**
(interactive API docs at `/docs`).

```bash
make logs            # tail all service logs
make down             # stop everything, keep data
make seed-all         # force-reseed all three databases with fresh data
```

## Local dev gotchas

- **`.env` changes need a container recreate**: `docker compose up -d
  --force-recreate <service>` — editing `.env` alone doesn't affect an
  already-running container.
- **`requirements.txt` changes need a rebuild**: `docker compose up -d
  --build <service>`.
- **After any manual multi-line Python edit**: run `python3 -m py_compile
  <file>` before rebuilding — catches indentation errors in a second
  instead of a rebuild cycle.
- **Removing a service from `docker-compose.yml`** doesn't stop its
  already-running container — `docker rm -f <container>` if you hit
  "Resource is still in use."
