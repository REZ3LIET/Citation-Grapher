FROM python:3.10-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY backend ./backend
RUN pip install --no-cache-dir '.[embeddings]'
RUN mkdir -p /app/data/runs
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"]

