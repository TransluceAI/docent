from unittest.mock import MagicMock, patch

import pytest

from docent.sdk.client import Docent


def _make_client() -> Docent:
    with patch.object(Docent, "_login"):
        return Docent(api_key="test-key", domain="example.com")


class TestUpdateAgentRunMetadata:
    @pytest.mark.unit
    def test_sends_put_with_metadata_payload(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"model": "gpt-4", "temperature": 0.7}

        client._session.put = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        result = client.update_agent_run_metadata("col-1", "run-1", {"model": "gpt-4"})

        client._session.put.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/agent_run/run-1/metadata",
            json={"metadata": {"model": "gpt-4"}},
        )
        assert result == {"model": "gpt-4", "temperature": 0.7}

    @pytest.mark.unit
    def test_returns_full_merged_metadata(self) -> None:
        client = _make_client()

        merged = {"existing_key": "kept", "new_key": "added", "nested": {"a": 1, "b": 2}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = merged

        client._session.put = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        result = client.update_agent_run_metadata("col-1", "run-1", {"new_key": "added"})

        assert result == merged

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Agent run not found"}
        mock_response.text = "Agent run not found"

        client._session.put = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.update_agent_run_metadata("col-1", "bad-run", {"key": "val"})


class TestDeleteAgentRunMetadataKeys:
    @pytest.mark.unit
    def test_sends_post_with_keys_payload(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"remaining": "value"},
            "not_found": [],
        }

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        metadata, not_found = client.delete_agent_run_metadata_keys("col-1", "run-1", ["remove_me"])

        client._session.post.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/agent_run/run-1/metadata/delete",
            json={"keys": ["remove_me"]},
        )
        assert metadata == {"remaining": "value"}
        assert not_found == []

    @pytest.mark.unit
    def test_returns_not_found_keys(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"kept": 1},
            "not_found": ["missing_key", "nested.gone"],
        }

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        metadata, not_found = client.delete_agent_run_metadata_keys(
            "col-1", "run-1", ["kept", "missing_key", "nested.gone"]
        )

        assert metadata == {"kept": 1}
        assert not_found == ["missing_key", "nested.gone"]

    @pytest.mark.unit
    def test_supports_dot_delimited_keys(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"config": {"remaining": True}},
            "not_found": [],
        }

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        metadata, not_found = client.delete_agent_run_metadata_keys(
            "col-1", "run-1", ["config.model"]
        )

        # Verify the SDK passes dot-delimited keys through to the server
        call_kwargs = client._session.post.call_args  # type: ignore[reportPrivateUsage]
        assert call_kwargs[1]["json"]["keys"] == ["config.model"]
        assert metadata == {"config": {"remaining": True}}
        assert not_found == []

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Agent run not found"}
        mock_response.text = "Agent run not found"

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.delete_agent_run_metadata_keys("col-1", "bad-run", ["key"])

    @pytest.mark.unit
    def test_response_must_contain_metadata_and_not_found(self) -> None:
        """Catch contract violations where the server response shape changes."""
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        # Simulate a server returning an unexpected shape (missing "not_found")
        mock_response.json.return_value = {"metadata": {"a": 1}}

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(KeyError):
            client.delete_agent_run_metadata_keys("col-1", "run-1", ["a"])


class TestGetAgentRunMetadata:
    @pytest.mark.unit
    def test_sends_get_to_correct_url(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"model": "gpt-4"}

        client._session.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        result = client.get_agent_run_metadata("col-1", "run-1")

        client._session.get.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/agent_run/run-1/metadata",
        )
        assert result == {"model": "gpt-4"}

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Agent run not found"}
        mock_response.text = "Agent run not found"

        client._session.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.get_agent_run_metadata("col-1", "bad-run")


class TestGetTranscriptGroupMetadata:
    @pytest.mark.unit
    def test_sends_get_to_correct_url(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"env": "prod"}

        client._session.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        result = client.get_transcript_group_metadata("col-1", "tg-1")

        client._session.get.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/transcript_group/tg-1/metadata",
        )
        assert result == {"env": "prod"}

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Transcript group not found"}
        mock_response.text = "Transcript group not found"

        client._session.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.get_transcript_group_metadata("col-1", "bad-tg")


class TestUpdateTranscriptGroupMetadata:
    @pytest.mark.unit
    def test_sends_put_with_metadata_payload(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"env": "prod", "version": 2}

        client._session.put = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        result = client.update_transcript_group_metadata("col-1", "tg-1", {"version": 2})

        client._session.put.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/transcript_group/tg-1/metadata",
            json={"metadata": {"version": 2}},
        )
        assert result == {"env": "prod", "version": 2}

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Transcript group not found"}
        mock_response.text = "Transcript group not found"

        client._session.put = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.update_transcript_group_metadata("col-1", "bad-tg", {"k": "v"})


class TestDeleteTranscriptGroupMetadataKeys:
    @pytest.mark.unit
    def test_sends_post_with_keys_payload(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"remaining": "value"},
            "not_found": [],
        }

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        metadata, not_found = client.delete_transcript_group_metadata_keys(
            "col-1", "tg-1", ["remove_me"]
        )

        client._session.post.assert_called_once_with(  # type: ignore[reportPrivateUsage]
            "https://api.example.com/rest/col-1/transcript_group/tg-1/metadata/delete",
            json={"keys": ["remove_me"]},
        )
        assert metadata == {"remaining": "value"}
        assert not_found == []

    @pytest.mark.unit
    def test_returns_not_found_keys(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"kept": 1},
            "not_found": ["missing_key"],
        }

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        metadata, not_found = client.delete_transcript_group_metadata_keys(
            "col-1", "tg-1", ["kept", "missing_key"]
        )

        assert metadata == {"kept": 1}
        assert not_found == ["missing_key"]

    @pytest.mark.unit
    def test_raises_on_not_found(self) -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Transcript group not found"}
        mock_response.text = "Transcript group not found"

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(Exception, match="404"):
            client.delete_transcript_group_metadata_keys("col-1", "bad-tg", ["key"])

    @pytest.mark.unit
    def test_response_must_contain_metadata_and_not_found(self) -> None:
        """Catch contract violations where the server response shape changes."""
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"metadata": {"a": 1}}

        client._session.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign, reportPrivateUsage]

        with pytest.raises(KeyError):
            client.delete_transcript_group_metadata_keys("col-1", "tg-1", ["a"])
