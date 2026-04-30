# Multi-stage for small final image.
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir poetry==1.8.3
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true \
 && poetry install --only main --no-root --no-interaction

FROM python:3.12-slim
WORKDIR /app

# Non-root user
RUN useradd -u 10001 -m pflapp
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

USER pflapp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
