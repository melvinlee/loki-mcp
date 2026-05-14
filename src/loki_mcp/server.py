import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100").rstrip("/")
LOKI_USERNAME = os.getenv("LOKI_USERNAME", "")
LOKI_PASSWORD = os.getenv("LOKI_PASSWORD", "")
LOKI_TIMEOUT = float(os.getenv("LOKI_TIMEOUT", "30"))

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("loki_mcp")

mcp = FastMCP(
    "Loki MCP",
    instructions=(
        "Tools for querying Grafana Loki log aggregation system using LogQL. "
        "Use query_logs for instant queries, query_range for log retrieval over a time window, "
        "get_labels / get_label_values to explore available metadata, and get_series to discover streams."
    ),
)


def _auth() -> tuple[str, str] | None:
    if LOKI_USERNAME and LOKI_PASSWORD:
        return (LOKI_USERNAME, LOKI_PASSWORD)
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=LOKI_URL,
        auth=_auth(),
        timeout=LOKI_TIMEOUT,
    )


async def _loki_get(path: str, params: dict) -> dict:
    """Make a GET request to Loki with structured request/response logging."""
    start = time.perf_counter()
    async with _client() as client:
        try:
            resp = await client.get(path, params=params)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.info(
                "loki_request",
                path=path,
                status_code=resp.status_code,
                duration_ms=duration_ms,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.error(
                "loki_request_error",
                path=path,
                status_code=exc.response.status_code,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise
        except httpx.RequestError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.error(
                "loki_connection_error",
                path=path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise


def _parse_time(value: str | None, default_offset_hours: int = 1) -> str:
    """Convert a human-friendly time string to an RFC3339 timestamp.

    Accepts: ISO-8601 strings, Unix epoch integers (as string), or duration
    offsets from now like '1h', '30m', '2d', '1w'.
    """
    if value is None:
        dt = datetime.now(timezone.utc) - timedelta(hours=default_offset_hours)
        return dt.isoformat()

    value = value.strip()

    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if len(value) >= 2 and value[-1] in units and value[:-1].isdigit():
        seconds = int(value[:-1]) * units[value[-1]]
        dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return dt.isoformat()

    if value.isdigit():
        ts = int(value)
        if ts > 1e18:
            ts //= 1_000_000_000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    return value


def _format_streams(data: dict) -> str:
    result = data.get("data", {}).get("result", [])
    if not result:
        return "No log entries found."

    lines: list[str] = []
    for stream in result:
        labels = stream.get("stream", {})
        label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        lines.append(f"[Stream: {{{label_str}}}]")
        for ts_ns, log_line in stream.get("values", []):
            ts_s = int(ts_ns) / 1e9
            ts = datetime.fromtimestamp(ts_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            lines.append(f"  {ts}  {log_line}")
    return "\n".join(lines)


def _format_matrix(data: dict) -> str:
    result = data.get("data", {}).get("result", [])
    if not result:
        return "No metric results found."

    lines: list[str] = []
    for series in result:
        labels = series.get("metric", {})
        label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        lines.append(f"[Series: {{{label_str}}}]")
        for ts, value in series.get("values", []):
            ts_str = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(f"  {ts_str}  {value}")
    return "\n".join(lines)


def _render_response(data: dict) -> str:
    result_type = data.get("data", {}).get("resultType", "")
    if result_type == "streams":
        return _format_streams(data)
    if result_type == "matrix":
        return _format_matrix(data)
    return json.dumps(data.get("data", data), indent=2)


@mcp.tool()
async def query_logs(
    query: str,
    limit: int = 100,
    time: Optional[str] = None,
) -> str:
    """Execute an instant LogQL query and return matching log lines.

    Args:
        query: LogQL expression, e.g. '{app="nginx"} |= "error"'
        limit: Maximum number of log lines to return (default 100).
        time: Point-in-time for the query. Accepts ISO-8601, Unix epoch,
              or duration offsets like '1h', '30m', '2d' (relative to now).
              Defaults to now.
    """
    log.info("tool_called", tool="query_logs", query=query, limit=limit, time=time)

    params: dict = {"query": query, "limit": limit}
    if time is not None:
        params["time"] = _parse_time(time, default_offset_hours=0)

    data = await _loki_get("/loki/api/v1/query", params)
    result = _render_response(data)

    log.info("tool_completed", tool="query_logs", query=query)
    return result


@mcp.tool()
async def query_range(
    query: str,
    start: str = "1h",
    end: Optional[str] = None,
    limit: int = 100,
    step: Optional[str] = None,
    direction: str = "backward",
) -> str:
    """Execute a LogQL range query and return log lines or metric values over time.

    Args:
        query: LogQL expression, e.g. '{namespace="prod"} |= "exception"'
        start: Range start. Accepts ISO-8601, Unix epoch, or offsets like '1h',
               '30m', '2d' (relative to now). Defaults to '1h' ago.
        end: Range end. Same format as start. Defaults to now.
        limit: Maximum number of log lines (log queries only, default 100).
        step: Query resolution for metric queries, e.g. '1m', '5m', '1h'.
              Loki infers a sensible default when omitted.
        direction: 'forward' (oldest first) or 'backward' (newest first, default).
    """
    log.info("tool_called", tool="query_range", query=query, start=start, end=end, limit=limit, step=step, direction=direction)

    params: dict = {
        "query": query,
        "start": _parse_time(start, default_offset_hours=1),
        "end": _parse_time(end, default_offset_hours=0),
        "limit": limit,
        "direction": direction,
    }
    if step:
        params["step"] = step

    data = await _loki_get("/loki/api/v1/query_range", params)
    result = _render_response(data)

    log.info("tool_completed", tool="query_range", query=query)
    return result


@mcp.tool()
async def get_labels(
    start: str = "24h",
    end: Optional[str] = None,
) -> str:
    """Return all label names present in Loki within the given time range.

    Args:
        start: Start of the time range (default '24h' ago).
        end: End of the time range (defaults to now).
    """
    log.info("tool_called", tool="get_labels", start=start, end=end)

    params = {
        "start": _parse_time(start, default_offset_hours=24),
        "end": _parse_time(end, default_offset_hours=0),
    }
    data = await _loki_get("/loki/api/v1/labels", params)

    labels = data.get("data", [])
    if not labels:
        log.info("tool_completed", tool="get_labels", label_count=0)
        return "No labels found."

    log.info("tool_completed", tool="get_labels", label_count=len(labels))
    return "Available labels:\n" + "\n".join(f"  - {l}" for l in sorted(labels))


@mcp.tool()
async def get_label_values(
    label: str,
    start: str = "24h",
    end: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """Return all values for a specific label in Loki.

    Args:
        label: The label name, e.g. 'app', 'namespace', 'pod'.
        start: Start of the time range (default '24h' ago).
        end: End of the time range (defaults to now).
        query: Optional LogQL stream selector to scope results,
               e.g. '{namespace="prod"}'.
    """
    log.info("tool_called", tool="get_label_values", label=label, start=start, end=end, query=query)

    params: dict = {
        "start": _parse_time(start, default_offset_hours=24),
        "end": _parse_time(end, default_offset_hours=0),
    }
    if query:
        params["query"] = query

    data = await _loki_get(f"/loki/api/v1/label/{label}/values", params)

    values = data.get("data", [])
    if not values:
        log.info("tool_completed", tool="get_label_values", label=label, value_count=0)
        return f"No values found for label '{label}'."

    log.info("tool_completed", tool="get_label_values", label=label, value_count=len(values))
    return f"Values for label '{label}':\n" + "\n".join(f"  - {v}" for v in sorted(values))


@mcp.tool()
async def get_series(
    match: str,
    start: str = "1h",
    end: Optional[str] = None,
) -> str:
    """Return log stream descriptors (label sets) matching a selector.

    Args:
        match: LogQL stream selector, e.g. '{app="nginx"}' or '{job=~".+"}'.
        start: Start of the time range (default '1h' ago).
        end: End of the time range (defaults to now).
    """
    log.info("tool_called", tool="get_series", match=match, start=start, end=end)

    params = {
        "match[]": match,
        "start": _parse_time(start, default_offset_hours=1),
        "end": _parse_time(end, default_offset_hours=0),
    }
    data = await _loki_get("/loki/api/v1/series", params)

    series = data.get("data", [])
    if not series:
        log.info("tool_completed", tool="get_series", match=match, series_count=0)
        return f"No series found matching '{match}'."

    log.info("tool_completed", tool="get_series", match=match, series_count=len(series))
    lines = [f"Series matching '{match}' ({len(series)} found):"]
    for s in series:
        label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(s.items()))
        lines.append(f"  {{{label_str}}}")
    return "\n".join(lines)


@mcp.tool()
async def get_stats(
    query: str,
    start: str = "1h",
    end: Optional[str] = None,
) -> str:
    """Return index and ingester statistics for a LogQL query without fetching log data.

    Useful for understanding log volume before running a full query.

    Args:
        query: LogQL stream selector, e.g. '{namespace="prod"}'.
        start: Start of the time range (default '1h' ago).
        end: End of the time range (defaults to now).
    """
    log.info("tool_called", tool="get_stats", query=query, start=start, end=end)

    params = {
        "query": query,
        "start": _parse_time(start, default_offset_hours=1),
        "end": _parse_time(end, default_offset_hours=0),
    }
    data = await _loki_get("/loki/api/v1/index/stats", params)

    log.info("tool_completed", tool="get_stats", query=query)
    return json.dumps(data, indent=2)


def main() -> None:
    global LOKI_URL, LOKI_USERNAME, LOKI_PASSWORD, LOKI_TIMEOUT

    parser = argparse.ArgumentParser(description="Loki MCP server")
    parser.add_argument("--loki-url", default=LOKI_URL, help="Loki base URL (default: %(default)s)")
    parser.add_argument("--username", default=LOKI_USERNAME, help="Basic-auth username")
    parser.add_argument("--password", default=LOKI_PASSWORD, help="Basic-auth password")
    parser.add_argument("--timeout", type=float, default=LOKI_TIMEOUT, help="HTTP timeout in seconds (default: %(default)s)")
    args = parser.parse_args()

    LOKI_URL = args.loki_url.rstrip("/")
    LOKI_USERNAME = args.username
    LOKI_PASSWORD = args.password
    LOKI_TIMEOUT = args.timeout

    log.info(
        "server_starting",
        loki_url=LOKI_URL,
        loki_username=LOKI_USERNAME or "(none)",
        timeout_s=LOKI_TIMEOUT,
        auth_enabled=bool(LOKI_USERNAME and LOKI_PASSWORD),
    )

    mcp.run()


if __name__ == "__main__":
    main()
