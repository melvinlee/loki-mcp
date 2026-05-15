# Loki MCP Query Guide

## Tools Overview

| Tool                | When to use                                             |
| ------------------- | ------------------------------------------------------- |
| `query_logs`        | Instant snapshot — latest matching lines right now      |
| `query_range`       | Logs over a time window (most common)                   |
| `get_labels`        | Discover available label names                          |
| `get_label_values`  | Discover values for a label (e.g. all namespaces)       |
| `get_series`        | List all streams matching a selector                    |
| `get_stats`         | Check log volume before running a heavy query           |

All tools accept an optional `org_id` parameter for multi-tenant Loki deployments (`X-Scope-OrgID` header).

---

## Time Formats

All `start` / `end` parameters accept:

| Format                | Example                  |
| --------------------- | ------------------------ |
| Relative offset       | `5m`, `1h`, `24h`, `7d`  |
| ISO-8601              | `2026-01-15T10:00:00Z`   |
| Unix epoch (seconds)  | `1737000000`             |

---

## LogQL Cheatsheet

### Stream selectors

```logql
# Exact match
{namespace="prod"}

# Regex match
{namespace=~"prod|staging"}

# Exclude
{namespace!="kube-system"}

# All streams
{stream=~".+"}
```

### Log filters

```logql
# Contains string
{namespace="prod"} |= "error"

# Does not contain
{namespace="prod"} != "health"

# Regex filter
{namespace="prod"} |~ "timeout|refused"

# JSON field filter
{namespace="prod"} | json | level="error"

# Label filter after parse
{namespace="prod"} | json | duration > 500ms
```

### Metric queries

```logql
# Log rate per minute
rate({namespace="prod"}[1m])

# Count errors per app over time
sum by (app) (count_over_time({namespace="prod"} |= "error" [5m]))

# Top 5 pods by log volume
topk(5, sum by (pod) (rate({namespace="prod"}[5m])))
```

---

## Common Recipes

### Find errors in the last hour

```text
query_range(query='{namespace="prod"} |= "error"', start="1h")
```

### Filter by cluster and level

```text
query_range(query='{cluster="homelab"} |= "INFO"', start="5m")
```

### JSON logs — filter by field

```text
query_range(query='{namespace="prod"} | json | level="error"', start="30m")
```

### Check volume before querying

```text
get_stats(query='{namespace="prod"}', start="6h")
```

### Discover all pods in a namespace

```text
get_label_values(label="pod", query='{namespace="prod"}')
```

### Multi-tenant query

```text
query_range(query='{namespace="prod"}', start="1h", org_id="tenant-123")
```

### Count errors per service

```text
query_range(
  query='sum by (service_name) (count_over_time({namespace="prod"} |= "error" [5m]))',
  start="1h",
  step="5m"
)
```

---

## Known Services

### Grafana (`namespace=monitoring`)

Grafana and its sidecars run in the `monitoring` namespace on the `homelab` cluster.
Use `namespace="monitoring"` to scope all Grafana-related queries.

```text
query_range(query='{cluster="homelab", namespace="monitoring"}', start="1h")
```

Filter to the sidecar specifically:

```text
query_range(query='{cluster="homelab", namespace="monitoring", container="grafana-sc-dashboard"}', start="1h")
```

---

## Tips

- Always run `get_stats` first for large time ranges to estimate volume.
- Use `get_series` to confirm a stream exists before querying it.
- Prefer `query_range` over `query_logs` for time-windowed analysis.
- JSON logs unlock field-level filtering with `| json` — much more precise than `|=`.
- Increase `limit` (default 100) when you need more lines; be mindful of response size.
