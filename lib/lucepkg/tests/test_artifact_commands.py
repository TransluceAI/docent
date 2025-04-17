"""Tests for the artifact commands."""

import json
import unittest
from unittest.mock import MagicMock, patch

from lucepkg.commands.artifact import ls


class TestArtifactCommands(unittest.TestCase):
    """Tests for the artifact commands."""

    @patch("subprocess.run")
    def test_ls_with_trailing_slash(self, mock_run):
        """Test that ls command trims trailing slashes from keys."""
        # Mock the subprocess.run result
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {"CommonPrefixes": [{"Prefix": "test/subdir/"}], "Contents": [{"Key": "test/file.txt"}]}
        )
        mock_run.return_value = mock_result

        # Call ls with a key that has a trailing slash
        ls("test/")

        # Check that the subprocess.run was called with the correct arguments
        # The key should have had its trailing slash removed
        args, _ = mock_run.call_args
        cmd_args = args[0]

        # Find the index of "--prefix" and check the next argument
        prefix_index = cmd_args.index("--prefix")
        self.assertEqual(cmd_args[prefix_index + 1], "test/")  # Should be "test/" not "test//"

    @patch("subprocess.run")
    def test_ls_without_trailing_slash(self, mock_run):
        """Test that ls command works correctly with keys without trailing slashes."""
        # Mock the subprocess.run result
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {"CommonPrefixes": [{"Prefix": "test/subdir/"}], "Contents": [{"Key": "test/file.txt"}]}
        )
        mock_run.return_value = mock_result

        # Call ls with a key that doesn't have a trailing slash
        ls("test")

        # Check that the subprocess.run was called with the correct arguments
        args, _ = mock_run.call_args
        cmd_args = args[0]

        # Find the index of "--prefix" and check the next argument
        prefix_index = cmd_args.index("--prefix")
        self.assertEqual(cmd_args[prefix_index + 1], "test/")  # Should be "test/"
