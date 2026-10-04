"""PostgreSQL Portuguese OR-query preparation."""

import re

TOKEN = re.compile(r"\w{3,}", re.UNICODE)
MAX_QUERY_TOKENS = 24


def build_or_tsquery(query: str) -> str:
    tokens = list(dict.fromkeys(TOKEN.findall(query.casefold())))[:MAX_QUERY_TOKENS]
    return " | ".join(tokens)
