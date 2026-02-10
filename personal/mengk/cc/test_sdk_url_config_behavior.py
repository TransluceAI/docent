# %%
# IPython autoreload setup
try:
    from IPython.core.getipython import get_ipython

    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

# %%
import io
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator, cast
from unittest.mock import patch

from docent._log_util.logger import LoggerAdapter
from docent.sdk.client import Docent

# %%
# Behavior under test from HEAD..main:
# 1) domain precedence changed: param > env > config > default
# 2) URL override precedence: param > env > config
# 3) local domains now require BOTH API and frontend URL overrides
# 4) partial override currently warns and falls back, but will become an error later
# 5) explicit API URL is normalized with `/rest`
# 6) empty/whitespace URL override values are treated as unset


def _write_config(tmp_dir: str, content: str) -> Path:
    path = Path(tmp_dir) / "docent.env"
    path.write_text(content)
    return path


@contextmanager
def _env(**updates: str | None) -> Iterator[None]:
    old_values: dict[str, str | None] = {}
    for key, value in updates.items():
        old_values[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _make_client(config_text: str, **kwargs: Any) -> tuple[Docent, str]:
    with TemporaryDirectory() as tmp_dir:
        config_path = _write_config(tmp_dir, config_text)
        log_stream = io.StringIO()
        with patch.object(Docent, "_login", return_value=None):
            client = Docent(config_file=config_path, log_stream=log_stream, **kwargs)
        return client, log_stream.getvalue()


def _urls(client: Docent) -> tuple[str, str, str]:
    domain = cast(str, getattr(client, "_domain"))
    server_url = cast(str, getattr(client, "_server_url"))
    web_url = cast(str, getattr(client, "_web_url"))
    return domain, server_url, web_url


def _expect_raises_local_domain(config_text: str) -> str:
    with TemporaryDirectory() as tmp_dir:
        config_path = _write_config(tmp_dir, config_text)
        with patch.object(Docent, "_login", return_value=None):
            try:
                Docent(config_file=config_path)
            except ValueError as exc:
                return str(exc)
    raise AssertionError("Expected ValueError for local domain without URL overrides")


# %%
# Case 1: env DOCENT_DOMAIN beats config DOCENT_DOMAIN
with _env(DOCENT_DOMAIN="env.com", DOCENT_API_URL=None, DOCENT_FRONTEND_URL=None):
    client, logs = _make_client("DOCENT_API_KEY=key\nDOCENT_DOMAIN=config.com\n")
    domain, server_url, web_url = _urls(client)
    assert domain == "env.com"
    assert server_url == "https://api.env.com/rest"
    assert web_url == "https://env.com"
    print("Case 1 passed")

# %%
# Case 2: local domains without BOTH explicit URL overrides now raise
for local_domain in ("localhost", "localhost:8888", "127.0.0.1:3000", "[::1]:3000"):
    message = _expect_raises_local_domain(f"DOCENT_API_KEY=key\nDOCENT_DOMAIN={local_domain}\n")
    assert "Local domains require explicit" in message
print("Case 2 passed")

# %%
# Case 3: local domain works when both URL overrides are provided
with _env(DOCENT_API_URL=None, DOCENT_FRONTEND_URL=None, DOCENT_DOMAIN=None):
    client, logs = _make_client(
        "DOCENT_API_KEY=key\n"
        "DOCENT_DOMAIN=localhost\n"
        "DOCENT_API_URL=http://localhost:8888\n"
        # "DOCENT_FRONTEND_URL=http://localhost:3000\n"
    )
    domain, server_url, web_url = _urls(client)
    assert domain == "localhost"
    assert server_url == "http://localhost:8888/rest"
    assert web_url == "http://localhost:3000", f"web_url: {web_url}"
    print("Case 3 passed")

# %%
# Case 4: partial constructor override warns and falls back to inferred peer URL
with _env(DOCENT_API_URL=None, DOCENT_FRONTEND_URL=None, DOCENT_DOMAIN=None):
    with patch.object(LoggerAdapter, "warning", autospec=True) as warning_spy:
        api_only, _ = _make_client(
            "DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n",
            server_url="https://api.override.com",
        )
    _, api_server_url, api_web_url = _urls(api_only)
    warning_messages = [str(call.args[1]) for call in warning_spy.call_args_list]
    assert any("will become an error in a future version" in msg for msg in warning_messages)
    assert api_server_url == "https://api.override.com/rest"
    assert api_web_url == "https://custom.com"

    with patch.object(LoggerAdapter, "warning", autospec=True) as warning_spy:
        web_only, _ = _make_client(
            "DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n",
            web_url="https://web.override.com",
        )
    _, web_server_url, web_web_url = _urls(web_only)
    warning_messages = [str(call.args[1]) for call in warning_spy.call_args_list]
    assert any("will become an error in a future version" in msg for msg in warning_messages)
    assert web_server_url == "https://api.custom.com/rest"
    assert web_web_url == "https://web.override.com"
    print("Case 4 passed")

# %%
# Case 5: env URL overrides are honored, including partial env override warning+fallback
with _env(
    DOCENT_API_URL="https://api.from-env.com",
    DOCENT_FRONTEND_URL="https://from-env.com",
    DOCENT_DOMAIN=None,
):
    client, logs = _make_client("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")
    _, server_url, web_url = _urls(client)
    assert server_url == "https://api.from-env.com/rest"
    assert web_url == "https://from-env.com"

with _env(DOCENT_API_URL="https://api.from-env.com", DOCENT_FRONTEND_URL=None, DOCENT_DOMAIN=None):
    with patch.object(LoggerAdapter, "warning", autospec=True) as warning_spy:
        client, _ = _make_client("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")
    _, server_url, web_url = _urls(client)
    warning_messages = [str(call.args[1]) for call in warning_spy.call_args_list]
    assert any("will become an error in a future version" in msg for msg in warning_messages)
    assert server_url == "https://api.from-env.com/rest"
    assert web_url == "https://custom.com"
print("Case 5 passed")

# %%
# Case 6: API URL gets `/rest` suffix normalized and empty overrides are ignored
with _env(DOCENT_API_URL=None, DOCENT_FRONTEND_URL=None, DOCENT_DOMAIN=None):
    client, logs = _make_client(
        "DOCENT_API_KEY=key\n"
        "DOCENT_DOMAIN=custom.com\n"
        "DOCENT_API_URL=https://api.custom.com\n"
        "DOCENT_FRONTEND_URL=https://custom.com\n"
    )
    _, server_url, web_url = _urls(client)
    assert server_url == "https://api.custom.com/rest"
    assert web_url == "https://custom.com"

    client, logs = _make_client(
        "DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\nDOCENT_API_URL=   \nDOCENT_FRONTEND_URL=\n"
    )
    _, server_url, web_url = _urls(client)
    assert server_url == "https://api.custom.com/rest"
    assert web_url == "https://custom.com"
print("Case 6 passed")

# %%
print("All SDK URL/config behavior checks passed.")
