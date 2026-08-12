FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# scripts/ and db/ are mounted as volumes in dev (docker-compose.yml),
# copied here too so the same image also works standalone in production
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY db/ ./db/

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
