# SlicePoint service: slicepoint-api (FastAPI) serving the live web UI, in one container.
#
#   docker build -t slicepoint slicepoint/
#   docker run --rm -p 127.0.0.1:8100:8100 -e SLICEPOINT_SERVICE_TOKEN=... \
#       -v "$PWD/data/practice:/data:ro" -v slicepoint-results:/results slicepoint
#
# Or use docker-compose.yml next to this file. The UI ships inside the slicepoint-api
# package (`pnpm build:api`), so no Node stage is needed. Dependencies come from the
# workspace uv.lock (--frozen): the image installs exactly what the tests ran against.
# The GPU segmentation worker is a separate image (segmentation/Dockerfile).

FROM python:3.15-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY schemas ./schemas
COPY core ./core
COPY api ./api
RUN uv sync --frozen --no-dev --no-editable --package slicepoint-api

FROM python:3.15-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin slicepoint \
    && mkdir -p /data /results && chown slicepoint /results
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SLICEPOINT_API_HOST=0.0.0.0 \
    SLICEPOINT_API_PORT=8100 \
    SLICEPOINT_DATA_ROOT=/data \
    SLICEPOINT_RESULTS_DIR=/results
USER slicepoint
VOLUME ["/results"]
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/healthz', timeout=2)"]
CMD ["slicepoint-api"]
