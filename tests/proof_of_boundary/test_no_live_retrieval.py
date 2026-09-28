# PB: no live retrieval on the core path (supplied-only / deterministic / offline)
#
# docs/02 declares a supplied-only, deterministic, offline v1 core path (no LLM, DB, vector store,
# or external API — PB-3 is N/A for exactly this reason). This test statically proves it: every
# module under src/ is AST-parsed and asserted to import NO network / DB / retrieval / cloud-LLM
# client. It performs no real network call. langgraph, the framework (framework.* / shared.*), the
# template's own src.* and the standard library are NOT in the forbidden set, so they never
# false-positive.

import ast
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1].parent / "src"

# Top-level module names that would introduce live retrieval / network / DB / cloud egress on the
# core path. shared.services.llm / shared.tools (framework-provided substrate) are intentionally not
# forbidden — a template composing the substrate is allowed; a direct third-party client is not.
_FORBIDDEN_TOP_LEVEL = {
    # HTTP / network
    "requests", "httpx", "urllib3", "aiohttp", "socket", "http", "urllib", "websocket", "websockets",
    # databases
    "psycopg2", "psycopg", "pymysql", "mysql", "sqlalchemy", "sqlite3", "asyncpg", "pymongo",
    "redis", "cassandra", "clickhouse_driver",
    # vector stores / retrieval SDKs
    "pinecone", "qdrant_client", "weaviate", "chromadb", "elasticsearch", "opensearchpy", "faiss",
    # cloud / third-party LLM clients (the template must use shared.services.llm, not these directly)
    "boto3", "botocore", "openai", "anthropic", "cohere", "google", "ollama", "vertexai", "litellm",
}


def _iter_src_modules():
    for path in sorted(_SRC.rglob("*.py")):
        yield path


def _imported_top_levels(tree: ast.AST):
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # ignore relative imports
                tops.add(node.module.split(".")[0])
    return tops


def test_no_network_db_or_retrieval_imports_in_src():
    violations = []
    scanned = 0
    for path in _iter_src_modules():
        scanned += 1
        tree = ast.parse(path.read_text(), filename=str(path))
        for top in _imported_top_levels(tree):
            if top in _FORBIDDEN_TOP_LEVEL:
                violations.append(f"{path.relative_to(_SRC.parent)} imports forbidden module '{top}'")
    assert scanned > 0, "no src modules scanned"
    assert not violations, "live-retrieval / network / DB imports found on the core path:\n" + "\n".join(violations)


def test_forbidden_set_is_a_denylist_not_flagging_the_substrate():
    # guard against a future edit that would false-positive framework / shared / langgraph / stdlib
    for allowed in ("framework", "shared", "src", "langgraph", "json", "re", "math", "copy",
                    "typing", "abc", "enum", "uuid", "pathlib", "ast"):
        assert allowed not in _FORBIDDEN_TOP_LEVEL
