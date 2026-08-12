"""
FastAPI app entrypoint for Multibase.

Routes to Postgres, MongoDB, or Neo4j automatically based on the question
- one LLM call reads all three schemas and picks the right database and
query language. See DECISIONS.md for the routing design.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from postgres_db import run_query, UnsafeQueryError
from llm.factory import get_llm_providers
from mongo_db import run_aggregate, run_find, UnsafeMongoQueryError
from mongo_schema_context import MONGO_SCHEMA_CONTEXT
from neo4j_db import run_cypher, UnsafeCypherError
from neo4j_schema_context import NEO4J_SCHEMA_CONTEXT
from schema_context import SCHEMA_CONTEXT
from schemas import (
    AskRequest, AskResponse, HealthResponse, QueryRequest,
    QueryResponse, SchemaResponse,
)

app = FastAPI(
    title="Multibase API",
    description=(
        "Ask questions in plain English about a competitive programming platform. "
        "One LLM call routes each question to Postgres, MongoDB, or Neo4j and "
        "generates the matching query (SQL, a Mongo filter/pipeline, or Cypher)."
    ),
    version="1.0.0",
)

# rate limiting - keyed by client IP, since there's no auth layer here.
# /ask and /query are the expensive ones (real LLM API cost), so they get
# the tightest limits; /health and /schema are cheap, looser limits.
# note: in-memory storage - limits reset on container restart, and won't
# be shared correctly across multiple backend instances. fine for now,
# revisit with a Redis-backed store before scaling out.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://multibase-ten.vercel.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Check API and database connectivity")
@limiter.limit("30/minute")
def health(request: Request):
    """Confirms the API is up and can reach Postgres."""
    try:
        run_query("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"db connection failed: {e}")


@app.post("/query", response_model=QueryResponse, tags=["query"], summary="Run raw SQL directly (scaffold, no LLM)")
@limiter.limit("10/minute")
def query(request: Request, req: QueryRequest):
    """
    Runs raw SQL against Postgres and returns the rows.

    Scaffold endpoint from before the LLM layer existed - kept for direct
    debugging. Same safety checks as /ask's Postgres path (SELECT-only,
    read-only DB role).
    """
    try:
        rows = run_query(req.sql)
        return {"row_count": len(rows), "rows": rows}
    except UnsafeQueryError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ask", response_model=AskResponse, tags=["ask"], summary="Ask a question in plain English")
@limiter.limit("10/minute")
def ask(request: Request, req: AskRequest):
    """
    Takes a natural-language question and optional conversation history.

    Routes to the correct database automatically - one LLM call reads all
    three schemas (Postgres, MongoDB, Neo4j) and picks which one fits the
    question, generating the matching query in the same step.

    If the question is ambiguous, returns a clarifying question instead of
    guessing. Resend the conversation (including the clarifying exchange)
    in `history` on the follow-up request to resolve it.
    """
    # convert Turn models to plain dicts - process_question() does dict-style
    # access (turn["role"]), which Pydantic model instances don't support
    turns = [t.model_dump() for t in req.history] + [{"role": "user", "content": req.question}]
    providers = get_llm_providers()

    result = None
    last_error = None
    for provider in providers:
        try:
            result = provider.process_question(turns, SCHEMA_CONTEXT, MONGO_SCHEMA_CONTEXT, NEO4J_SCHEMA_CONTEXT)
            break
        except Exception as e:
            last_error = e
            continue

    if result is None:
        raise HTTPException(status_code=503, detail=f"all LLM providers failed: {last_error}")

    if result["status"] == "ambiguous":
        return {"status": "ambiguous", "clarifying_question": result["clarifying_question"]}

    if result["target_db"] not in ("postgres", "mongo", "neo4j"):
        raise HTTPException(status_code=500, detail=f"unknown target_db: {result['target_db']}")

    try:
        if result["target_db"] == "postgres":
            rows = run_query(result["sql"])
            return {"status": "ok", "source": "postgres", "sql": result["sql"], "row_count": len(rows), "rows": rows}

        elif result["target_db"] == "mongo":
            mq = result["mongo_query"]
            operation = mq.get("operation") or ("aggregate" if mq.get("pipeline") else "find")
            if operation == "find":
                rows = run_find(mq["collection"], mq.get("filter", {}), mq.get("limit", 20))
            else:
                rows = run_aggregate(mq["collection"], mq.get("pipeline", []))
            return {"status": "ok", "source": "mongo", "sql": f"db.{mq['collection']}.{operation}(...)",
                    "row_count": len(rows), "rows": rows}

        else:  # neo4j
            rows = run_cypher(result["cypher"])
            return {"status": "ok", "source": "neo4j", "sql": result["cypher"], "row_count": len(rows), "rows": rows}

    except (UnsafeQueryError, UnsafeMongoQueryError, UnsafeCypherError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"query failed: {e}")


# ---------- schema descriptions, fed to /schema and (via *_schema_context modules) to the LLM ----------

POSTGRES_SCHEMA = [
    {"name": "students", "columns": [
        {"name": "id", "pk": True}, {"name": "name"}, {"name": "email"},
        {"name": "college"}, {"name": "rating"}, {"name": "joined_date"},
    ]},
    {"name": "platforms", "columns": [
        {"name": "id", "pk": True}, {"name": "name"},
    ]},
    {"name": "contests", "columns": [
        {"name": "id", "pk": True}, {"name": "platform_id", "ref": "platforms.id"},
        {"name": "name"}, {"name": "contest_type"}, {"name": "start_time"}, {"name": "duration_minutes"},
    ]},
    {"name": "problems", "columns": [
        {"name": "id", "pk": True}, {"name": "contest_id", "ref": "contests.id"},
        {"name": "title"}, {"name": "difficulty"}, {"name": "points"}, {"name": "tags"},
    ]},
    {"name": "submissions", "columns": [
        {"name": "id", "pk": True}, {"name": "student_id", "ref": "students.id"},
        {"name": "problem_id", "ref": "problems.id"}, {"name": "contest_id", "ref": "contests.id"},
        {"name": "verdict"}, {"name": "language"}, {"name": "runtime_ms"}, {"name": "submitted_at"},
    ]},
]

MONGO_SCHEMA = [
    {"name": "editorials", "fields": [
        {"name": "problem_id", "note": "-> problems.id"}, {"name": "problem_title"},
        {"name": "editorial.author"}, {"name": "editorial.approach"}, {"name": "editorial.content"},
        {"name": "comments[]"},
    ]},
    {"name": "problem_statements", "fields": [
        {"name": "problem_id", "note": "-> problems.id"}, {"name": "problem_title"},
        {"name": "statement"}, {"name": "constraints[]"}, {"name": "examples[]"},
    ]},
    {"name": "submission_code", "fields": [
        {"name": "submission_id", "note": "-> submissions.id"}, {"name": "language"},
        {"name": "verdict"}, {"name": "code"}, {"name": "line_count"},
    ]},
]

NEO4J_NODES = [
    {"label": "Student", "properties": ["id", "name"]},
    {"label": "Problem", "properties": ["id", "title"]},
]
NEO4J_RELS = [
    {"type": "MENTORS", "note": "Student -> Student, directed"},
    {"type": "FOLLOWS", "note": "Student -> Student, directed"},
    {"type": "RIVAL_OF", "note": "Student - Student, undirected"},
    {"type": "SIMILAR_TO", "note": "Problem - Problem, undirected, shared_tags"},
]


@app.get("/schema", response_model=SchemaResponse, tags=["schema"], summary="Database structure + live record counts")
@limiter.limit("20/minute")
def get_schema(request: Request):
    """
    Describes what's queryable in each database, with a live count per
    table/collection/node/relationship - pulled through the same safe,
    read-only query functions used by /ask, not a separate raw-access path.
    """
    pg_tables = []
    for t in POSTGRES_SCHEMA:
        try:
            count = run_query(f"SELECT COUNT(*) AS count FROM {t['name']}")[0]["count"]
        except Exception:
            count = None
        pg_tables.append({**t, "seed_count": count})

    mongo_collections = []
    for c in MONGO_SCHEMA:
        try:
            result = run_aggregate(c["name"], [{"$count": "count"}])
            count = result[0]["count"] if result else 0
        except Exception:
            count = None
        mongo_collections.append({**c, "seed_count": count})

    neo4j_nodes = []
    for n in NEO4J_NODES:
        try:
            result = run_cypher(f"MATCH (x:{n['label']}) RETURN count(x) AS count")
            count = result[0]["count"] if result else 0
        except Exception:
            count = None
        neo4j_nodes.append({**n, "seed_count": count})

    neo4j_rels = []
    for r in NEO4J_RELS:
        try:
            result = run_cypher(f"MATCH ()-[x:{r['type']}]->() RETURN count(x) AS count")
            count = result[0]["count"] if result else 0
        except Exception:
            count = None
        neo4j_rels.append({**r, "seed_count": count})

    return {
        "postgres": {"tables": pg_tables},
        "mongo": {"collections": mongo_collections},
        "neo4j": {"nodes": neo4j_nodes, "relationships": neo4j_rels},
    }
