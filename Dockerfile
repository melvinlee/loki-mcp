FROM python:3.11-slim

RUN pip install uv --no-cache-dir

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY src/ src/

RUN useradd --no-create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app
USER appuser


EXPOSE 8000

CMD ["uv", "run", "fastmcp", "run", "src/loki_mcp/server.py", "--transport", "streamable-http", "--port", "8000", "--host", "0.0.0.0"]
