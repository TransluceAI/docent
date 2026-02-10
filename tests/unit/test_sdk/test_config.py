"""Unit tests for config file loading and precedence logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docent.sdk.client import Docent, load_config_file


class TestLoadConfigFile:
    """Tests for the load_config_file function."""

    @pytest.mark.unit
    def test_explicit_path_loads_file(self, tmp_path: Path) -> None:
        """Test that passing an explicit path loads that file."""
        config_file = tmp_path / "custom.env"
        config_file.write_text("DOCENT_API_KEY=explicit-key\nDOCENT_DOMAIN=explicit.com\n")

        result = load_config_file(config_file)

        assert result["DOCENT_API_KEY"] == "explicit-key"
        assert result["DOCENT_DOMAIN"] == "explicit.com"

    @pytest.mark.unit
    def test_explicit_path_not_found_raises(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised when explicit path doesn't exist."""
        nonexistent = tmp_path / "nonexistent.env"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config_file(nonexistent)

    @pytest.mark.unit
    def test_auto_discovery_in_current_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that docent.env is found in current directory."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=discovered-key\n")

        monkeypatch.chdir(tmp_path)

        result = load_config_file()

        assert result["DOCENT_API_KEY"] == "discovered-key"

    @pytest.mark.unit
    def test_auto_discovery_in_parent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that docent.env is found by traversing up from a child directory."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=parent-key\n")

        child_dir = tmp_path / "subdir" / "nested"
        child_dir.mkdir(parents=True)

        monkeypatch.chdir(child_dir)

        result = load_config_file()

        assert result["DOCENT_API_KEY"] == "parent-key"

    @pytest.mark.unit
    def test_no_file_returns_empty_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that empty dict is returned when no docent.env exists."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        monkeypatch.chdir(empty_dir)

        result = load_config_file()

        assert result == {}

    @pytest.mark.unit
    def test_handles_comments_and_whitespace(self, tmp_path: Path) -> None:
        """Test that comments and whitespace are handled correctly."""
        config_file = tmp_path / "test.env"
        config_file.write_text(
            "# This is a comment\nDOCENT_API_KEY=key-value\n  \nDOCENT_DOMAIN=example.com\n"
        )

        result = load_config_file(config_file)

        assert result["DOCENT_API_KEY"] == "key-value"
        assert result["DOCENT_DOMAIN"] == "example.com"


class TestDocentConfigPrecedence:
    """Tests for Docent.__init__ config precedence logic."""

    @pytest.mark.unit
    def test_api_key_param_takes_precedence(self, tmp_path: Path) -> None:
        """Test that api_key parameter takes precedence over env and config."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=config-key\n")

        mock_login = MagicMock()
        with patch.object(Docent, "_login", mock_login):
            Docent(api_key="param-key", config_file=config_file)

        mock_login.assert_called_once_with("param-key")

    @pytest.mark.unit
    def test_api_key_missing_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing api_key raises ValueError."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_DOMAIN=example.com\n")

        monkeypatch.delenv("DOCENT_API_KEY", raising=False)

        with pytest.raises(ValueError, match="api_key is required"):
            Docent(config_file=config_file)

    @pytest.mark.unit
    def test_domain_param_takes_precedence(self, tmp_path: Path) -> None:
        """Test that domain parameter takes precedence over env and config."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=config.com\n")

        with patch.object(Docent, "_login"):
            client = Docent(domain="param.com", config_file=config_file)

        assert client._domain == "param.com"  # type: ignore[reportPrivateUsage]
        assert "api.param.com" in client._server_url  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_domain_default_value(self, tmp_path: Path) -> None:
        """Test that domain defaults to docent.transluce.org."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\n")

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._domain == "docent.transluce.org"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_server_url_constructed_from_domain(self, tmp_path: Path) -> None:
        """Test that server_url is constructed from domain when not specified."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._server_url == "https://api.custom.com/rest"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_frontend_url_constructed_from_domain(self, tmp_path: Path) -> None:
        """Test that frontend_url is constructed from domain when not specified."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._frontend_url == "https://custom.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_partial_constructor_url_overrides_warn_and_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that partial constructor URL overrides warn and use inferred fallback."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            api_only = Docent(server_url="https://api.override.com", config_file=config_file)
            frontend_only = Docent(frontend_url="https://web.override.com", config_file=config_file)

        assert "will become an error in a future version" in caplog.text
        assert api_only._server_url == "https://api.override.com/rest"  # type: ignore[reportPrivateUsage]
        assert api_only._frontend_url == "https://custom.com"  # type: ignore[reportPrivateUsage]
        assert frontend_only._server_url == "https://api.custom.com/rest"  # type: ignore[reportPrivateUsage]
        assert frontend_only._frontend_url == "https://web.override.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_new_url_params_take_precedence_over_legacy_params(self, tmp_path: Path) -> None:
        """Test that api_url/frontend_url take precedence over server_url/web_url."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            client = Docent(
                api_url="https://api.new.com",
                frontend_url="https://new.com",
                server_url="https://api.new.com",
                web_url="https://new.com",
                config_file=config_file,
            )

        assert client._api_url == "https://api.new.com/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "https://new.com"  # type: ignore[reportPrivateUsage]
        assert client._server_url == client._api_url  # type: ignore[reportPrivateUsage]
        assert client._web_url == client._frontend_url  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_conflicting_new_and_legacy_url_params_raise(self, tmp_path: Path) -> None:
        """Test that conflicting new/legacy constructor URL parameters are rejected."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            with pytest.raises(ValueError, match="conflicting values for api_url and server_url"):
                Docent(
                    api_url="https://api.new.com",
                    server_url="https://api.old.com",
                    frontend_url="https://new.com",
                    config_file=config_file,
                )

            with pytest.raises(ValueError, match="conflicting values for frontend_url and web_url"):
                Docent(
                    frontend_url="https://new.com",
                    web_url="https://old.com",
                    api_url="https://api.new.com",
                    config_file=config_file,
                )

    @pytest.mark.unit
    def test_new_and_legacy_url_params_match_after_normalization(self, tmp_path: Path) -> None:
        """Test that equivalent URL params do not conflict after normalization."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")

        with patch.object(Docent, "_login"):
            client = Docent(
                api_url=" https://api.new.com/ ",
                server_url="https://api.new.com",
                frontend_url=" https://new.com/ ",
                web_url="https://new.com",
                config_file=config_file,
            )

        assert client._api_url == "https://api.new.com/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "https://new.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "local_domain", ["localhost", "localhost:8888", "127.0.0.1:3000", "[::1]:3000"]
    )
    def test_local_domain_without_overrides_raises(self, tmp_path: Path, local_domain: str) -> None:
        """Test that local domains require explicit URL overrides."""
        config_file = tmp_path / "docent.env"
        config_file.write_text(f"DOCENT_API_KEY=key\nDOCENT_DOMAIN={local_domain}\n")

        with patch.object(Docent, "_login"):
            with pytest.raises(ValueError, match="Local domains require explicit"):
                Docent(config_file=config_file)

    @pytest.mark.unit
    def test_local_domain_with_both_overrides_succeeds(self, tmp_path: Path) -> None:
        """Test that local domain works with explicit API and frontend URLs."""
        config_file = tmp_path / "docent.env"
        config_file.write_text(
            "DOCENT_API_KEY=key\nDOCENT_DOMAIN=localhost\nDOCENT_API_URL=http://localhost:8888\n"
            "DOCENT_FRONTEND_URL=http://localhost:3000\n"
        )

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._server_url == "http://localhost:8888/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "http://localhost:3000"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_env_var_url_overrides_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that URL overrides can be provided via environment variables."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")
        monkeypatch.setenv("DOCENT_API_URL", "https://api.from-env.com")
        monkeypatch.setenv("DOCENT_FRONTEND_URL", "https://from-env.com")

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._server_url == "https://api.from-env.com/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "https://from-env.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_env_var_partial_override_warns_and_falls_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that partial URL override from environment warns and falls back."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\n")
        monkeypatch.setenv("DOCENT_API_URL", "https://api.from-env.com")
        monkeypatch.delenv("DOCENT_FRONTEND_URL", raising=False)

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert "will become an error in a future version" in caplog.text
        assert client._server_url == "https://api.from-env.com/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "https://custom.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_env_var_domain_takes_precedence_over_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that DOCENT_DOMAIN env var takes precedence over config file value."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=key\nDOCENT_DOMAIN=config.com\n")
        monkeypatch.setenv("DOCENT_DOMAIN", "env.com")

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._domain == "env.com"  # type: ignore[reportPrivateUsage]
        assert client._server_url == "https://api.env.com/rest"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_api_url_rest_suffix_normalized(self, tmp_path: Path) -> None:
        """Test that explicit API URL receives /rest suffix if missing."""
        config_file = tmp_path / "docent.env"
        config_file.write_text(
            "DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\nDOCENT_API_URL=https://api.custom.com\n"
            "DOCENT_FRONTEND_URL=https://custom.com\n"
        )

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._server_url == "https://api.custom.com/rest"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_empty_url_overrides_in_config_do_not_enable_override_mode(
        self, tmp_path: Path
    ) -> None:
        """Test that empty API/web URL assignments are treated as unset values."""
        config_file = tmp_path / "docent.env"
        config_file.write_text(
            "DOCENT_API_KEY=key\nDOCENT_DOMAIN=custom.com\nDOCENT_API_URL=\nDOCENT_FRONTEND_URL=\n"
        )

        with patch.object(Docent, "_login"):
            client = Docent(config_file=config_file)

        assert client._server_url == "https://api.custom.com/rest"  # type: ignore[reportPrivateUsage]
        assert client._frontend_url == "https://custom.com"  # type: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_auto_discovery_with_docent_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that Docent auto-discovers docent.env when no config_file specified."""
        config_file = tmp_path / "docent.env"
        config_file.write_text("DOCENT_API_KEY=auto-discovered-key\nDOCENT_DOMAIN=auto.com\n")
        monkeypatch.chdir(tmp_path)

        mock_login = MagicMock()
        with patch.object(Docent, "_login", mock_login):
            client = Docent()

        mock_login.assert_called_once_with("auto-discovered-key")
        assert client._domain == "auto.com"  # type: ignore[reportPrivateUsage]
