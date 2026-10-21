ARG PYTHON_IMAGE=python:3.13.14-slim
FROM ${PYTHON_IMAGE} AS builder

ARG POETRY_VERSION=2.4.1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock LICENSE ./
RUN poetry install --only main --no-root
COPY README.md ./
COPY api ./api
COPY models ./models
RUN poetry install --only-root

FROM builder AS test
RUN poetry install --with dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
COPY examples ./examples
COPY benchmarks ./benchmarks
CMD ["poetry", "run", "pytest"]

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY --from=builder /app/.venv /app/.venv
COPY api ./api
COPY models ./models
COPY migrations ./migrations
COPY alembic.ini LICENSE ./
USER app
CMD ["python", "-m", "api"]
