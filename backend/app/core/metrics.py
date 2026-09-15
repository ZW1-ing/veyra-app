"""Prometheus 指标：HTTP、模型、检索和配额拒绝。"""

from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

HTTP_REQUESTS = Counter(
    "veyra_http_requests_total",
    "HTTP requests handled by Veyra.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "veyra_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
)
CHAT_REQUESTS = Counter(
    "veyra_chat_requests_total",
    "Chat requests by mode, model and outcome.",
    ["mode", "model", "status"],
)
CHAT_DURATION = Histogram(
    "veyra_chat_duration_seconds",
    "End-to-end chat duration in seconds.",
    ["mode", "model"],
)
CHAT_FIRST_TOKEN = Histogram(
    "veyra_chat_first_token_seconds",
    "Time to first streamed token in seconds.",
    ["mode", "model"],
)
CHAT_TOKENS = Counter(
    "veyra_chat_tokens_total",
    "Prompt and completion tokens.",
    ["model", "kind"],
)
CHAT_COST = Counter(
    "veyra_chat_cost_usd_total",
    "Estimated model cost in US dollars.",
    ["model"],
)
RETRIEVAL_DURATION = Histogram(
    "veyra_retrieval_duration_seconds",
    "Knowledge retrieval duration in seconds.",
)
RETRIEVAL_HITS = Histogram(
    "veyra_retrieval_hits",
    "Number of knowledge chunks returned per query.",
    buckets=(0, 1, 2, 3, 5, 8, 13, 21),
)
QUOTA_REJECTIONS = Counter(
    "veyra_quota_rejections_total",
    "Chat requests rejected by tenant quota.",
    ["scope"],
)


def latest_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
