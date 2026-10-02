"""The gateway's bearer check must cover the MCP surface (regression: until
2026-10-02 every /mcp* path skipped auth). Pure-function tests; no app start."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "telegram_gateway" / "main.py"


def _load():
    # Pull just the two pure helpers out of main.py: importing the module would
    # start the Telegram app, which needs a bot token and a database.
    tree = ast.parse(SRC.read_text())
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and any(
        getattr(t, "id", "") == "AUTH_EXEMPT_PATHS" for t in n.targets))
        or (isinstance(n, ast.FunctionDef) and n.name in ("auth_exempt", "bearer_ok"))]
    ns = {}
    exec(compile(ast.Module(body=[ast.parse("import hmac").body[0], *keep], type_ignores=[]), str(SRC), "exec"), ns)
    return ns


def test_mcp_paths_require_auth():
    ns = _load()
    for p in ("/mcp", "/mcp/", "/mcp/mcp", "/mcpx", "/send_message", "/request_approval"):
        assert not ns["auth_exempt"](p), p


def test_public_paths_stay_exempt():
    ns = _load()
    for p in ("/health", "/webhook", "/docs", "/openapi.json"):
        assert ns["auth_exempt"](p), p


def test_bearer_ok():
    ok = _load()["bearer_ok"]
    assert ok("Bearer s3cret", "s3cret")
    assert not ok("Bearer wrong", "s3cret")
    assert not ok("s3cret", "s3cret")
    assert not ok("", "s3cret")
