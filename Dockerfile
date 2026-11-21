FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    GOVERNED_METRICS_TRACE_DIR=/tmp/metrics-traces
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --python /usr/local/bin/python \
    && groupadd --gid 10001 metrics \
    && useradd --uid 10001 --gid 10001 --no-create-home metrics
COPY src src
COPY metrics metrics
# Run the CLI and its query worker as the metrics user.
USER metrics
ENTRYPOINT ["python", "-m", "governed_metrics.cli"]
