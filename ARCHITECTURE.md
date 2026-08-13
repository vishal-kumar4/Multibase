# Multibase — Architecture

One question, automatically routed to the right database. The **Query
Router** is a single LLM call that reads all three database schemas,
picks the one the question needs, and generates the matching query in
the same step — no manual database picker, no separate classification
pass.

## Flow

```mermaid
flowchart TD
    A([User asks a question]) --> B[Frontend]
    B --> C[Backend]
    C --> D{{"Claude LLM → Gemini fallback"}}
    D --> E[["Query Routing Layer"]]
    E --> F{Ambiguous?}
    F -->|yes| G[Clarifying question]
    G --> B
    B --> A
    F -->|no| H1[(Postgres)]
    F -->|no| H2[(Neo4j)]
    F -->|no| H3[(MongoDB)]
    H1 --> I[Response]
    H2 --> I
    H3 --> I
    I --> B
```

## Components

| | |
|---|---|
| **Frontend** | React + Vite — renders per response `source`: table/chart, document card, or graph |
| **Backend** | FastAPI — validates and executes the query the router generated |
| **LLM providers** | Claude Sonnet 5 (primary), Gemini 2.5 Flash (fallback on failure) — interprets the question first |
| **Query Routing Layer** | Takes the LLM's interpretation, picks the database *and* writes the query together; if the question is ambiguous, skips the databases entirely and sends a clarifying question straight back to the user |
| **Postgres** | Students, contests, problems, submissions — relational data |
| **MongoDB** | Editorials, problem statements, submission code — nested/flexible content |
| **Neo4j** | Mentorship, follows, rivalries, problem similarity — relationships |

## Docker & seeding flow

`make up` builds and starts everything, then seeds only what's empty —
safe to run on a fresh clone or a machine that already has data.

```mermaid
flowchart TD
    A([make up]) --> B[docker compose up --build]
    subgraph DC["Docker Compose — local"]
        direction LR
        PG[(postgres container)]
        BE[backend container]
        FE[frontend container]
    end
    B --> DC
    PG -->|healthy| BE --> FE
    BE --> S[["seed_if_needed.py"]]
    S --> C1{Postgres empty?}
    S --> C2{Mongo empty?}
    S --> C3{Neo4j empty?}
    C1 -->|yes| SP[seed_postgres.py]
    C1 -->|no| X1[skip]
    C2 -->|yes| SM[seed_mongo.py]
    C2 -->|no| X2[skip]
    C3 -->|yes| SN[seed_neo4j.py]
    C3 -->|no| X3[skip]
    SP & X1 & SM & X2 & SN & X3 --> R([Ready at localhost:5173])
```

Only Postgres runs in a local container — Mongo (Atlas) and Neo4j
(AuraDB) are managed cloud services the backend connects to over the
network, so there's nothing local to wait on for those two, just a
live connection check per database inside `seed_if_needed.py`.

See [`DECISIONS.md`](./DECISIONS.md) for the reasoning behind each piece.
