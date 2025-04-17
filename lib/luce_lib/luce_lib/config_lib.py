import dataclasses
import getpass
import json
import pathlib
import sys
from typing import Any, Dict, Optional

import tomlkit

from . import monorepo_util

# pyright: reportUnknownMemberType=false


@dataclasses.dataclass
class ServerConfig:
    hostname: str
    remote_path: str
    user: Optional[str] = None
    identity_file: Optional[str] = None
    repos: Optional[dict[str, str]] = None  # Maps repo names to remote paths


@dataclasses.dataclass
class RepoConfig:
    local_path: str


def load_config() -> Dict[str, Any]:
    """Load raw configuration from ~/.luce/config.json or ~/.luce/config.toml.

    Returns:
        Dict containing the raw config data

    Raises:
        RuntimeError: If config file not found or invalid, or if both exist
    """
    config_dir = pathlib.Path.home() / ".luce"
    json_config = config_dir / "config.json"
    toml_config = config_dir / "config.toml"

    if json_config.exists() and toml_config.exists():
        RuntimeError(
            f"Error: Both {json_config} and {toml_config} exist. Please remove one.",
            file=sys.stderr,
        )

    if json_config.exists():
        try:
            with open(json_config) as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Error: Failed to parse {json_config}: {e}")
    elif toml_config.exists():
        try:
            with open(toml_config, "rb") as f:
                return tomlkit.load(f)
        except tomlkit.TOMLKitError as e:  # pyright: ignore
            raise RuntimeError(f"Error: Failed to parse {toml_config}: {e}")
    else:
        raise RuntimeError(
            f"Error: No config file found. Please create {toml_config} (or {json_config})"
        )


def get_server_configs() -> Dict[str, ServerConfig]:
    """Get server configurations from config file.

    Returns:
        Dict mapping server names to their configurations

    Raises:
        RuntimeError: If config is invalid or missing servers
    """
    data = load_config()
    try:
        servers: Dict[str, ServerConfig] = {}
        for name, config in data["servers"].items():
            identity_file = config.get("identity_file")
            if identity_file:
                identity_file = str(pathlib.Path(identity_file).expanduser())

            servers[name] = ServerConfig(
                hostname=config["hostname"],
                remote_path=config["remote_path"],
                user=config.get("user"),
                identity_file=identity_file,
                repos=config.get("repos"),
            )

        return servers
    except KeyError as e:
        raise RuntimeError(f"Error: Missing required field in config: {e}")


def get_repo_configs() -> dict[str, RepoConfig]:
    """Get repository configurations from config file.

    Returns:
        Dict mapping repository names to their configurations

    Raises:
        RuntimeError: If config is invalid
    """
    data = load_config()
    try:
        repos: dict[str, RepoConfig] = {}

        # Monorepo is always included for now.
        repos["clarity"] = RepoConfig(
            local_path=monorepo_util.find_monorepo_root(),
        )

        for name, config in data.get("repositories", {}).items():
            assert name not in repos, f"Repository '{name}' already exists"
            repos[name] = RepoConfig(
                local_path=config["local_path"],
            )
        return repos
    except KeyError as e:
        raise RuntimeError(f"Error: Missing required field in config: {e}")


def get_or_create_toml_doc() -> tuple[tomlkit.TOMLDocument, pathlib.Path]:
    """Get existing TOML config or create a new one.

    Returns:
        Tuple of (TOML document, path to config file)

    Raises:
        RuntimeError: If JSON config exists (need to convert first)
    """
    config_dir = pathlib.Path.home() / ".luce"
    json_config = config_dir / "config.json"
    toml_config = config_dir / "config.toml"

    if json_config.exists():
        raise RuntimeError(
            "Error: JSON config file exists. Please run `luce config json-to-toml` first."
        )

    # Create config dir if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)

    # Load or create TOML document
    if toml_config.exists():
        with open(toml_config, "rb") as f:
            doc = tomlkit.load(f)
    else:
        doc = _create_empty_config()
        print(f"Creating new config file at {toml_config}")

    with open(toml_config, "w") as f:
        f.write(tomlkit.dumps(doc))
    return doc, toml_config


def _save_and_show_toml_doc(doc: tomlkit.TOMLDocument, path: pathlib.Path) -> None:
    """Save TOML document and print the updated config.

    Args:
        doc: TOML document to save
        path: Path to save the document to
    """
    with open(path, "w") as f:
        f.write(tomlkit.dumps(doc))

    print("\nUpdated configuration:")
    print(tomlkit.dumps(doc))


def set_artifact_dir(path: str) -> None:
    """Set the artifact directory in the config file.
    Create it if it doesn't exist.

    The path can be:
    - An absolute path (e.g. /home/user/artifacts)
    - A path relative to the current working directory (e.g. artifacts)
    - A path relative to home using ~ (e.g. ~/artifacts)

    The path will be stored as an absolute path in the config.
    """
    # Convert to absolute path, expanding ~ and resolving relative paths
    abs_path = pathlib.Path(path).expanduser()
    if not abs_path.is_absolute():
        # If path is relative, make it absolute relative to current working directory
        abs_path = pathlib.Path.cwd() / abs_path

    # Resolve any .. or . in the path
    abs_path = abs_path.resolve()

    # Verify the parent directory exists
    if not abs_path.parent.exists():
        raise RuntimeError(
            f"Error: Parent directory does not exist: {abs_path.parent}\n"
            "Please create the parent directory first."
        )

    # Create the directory if it doesn't exist
    abs_path.mkdir(exist_ok=True)

    # Store the absolute path in config
    doc, config_path = get_or_create_toml_doc()
    doc["artifact_dir"] = str(abs_path)
    _save_and_show_toml_doc(doc, config_path)


def get_artifact_dir() -> pathlib.Path:
    """Get the artifact directory from the config file."""
    try:
        data = load_config()
        return pathlib.Path(data["artifact_dir"]).expanduser()
    except KeyError:
        raise RuntimeError("No artifact directory found in config")


def get_user_name() -> str:
    """Get the user name from the config file (or infer from OS username)."""
    try:
        data = load_config()
        return data["name"]
    except KeyError:
        os_username = getpass.getuser()
        # Don't allow generic names.
        if os_username in {"root", "ubuntu", "ec2-user", "admin"}:
            raise RuntimeError(
                "Cannot infer user name from OS username. Please set it in ~/.luce/config.toml "
                "with the key 'name'."
            )
        else:
            print(
                f"Warning: Using OS username {os_username} as user name. "
                "To customize this and silence this warning, set it in ~/.luce/config.toml with "
                "the key 'name'."
            )
        return os_username


def add_server_to_config(
    name: str,
    hostname: str,
    remote_path: str,
    user: Optional[str] = None,
    identity_file: Optional[str] = None,
) -> None:
    """Add a new server to the config file."""
    doc, config_path = get_or_create_toml_doc()

    # Get or create servers table
    servers: Any = doc.get("servers")
    if not servers:
        servers = doc["servers"] = tomlkit.table()

    # Check if server already exists
    if name in servers:
        raise RuntimeError(f"Error: Server '{name}' already exists in config")

    # Create new server config
    server = tomlkit.table()
    server["hostname"] = hostname
    server["remote_path"] = remote_path
    if user:
        server["user"] = user
    if identity_file:
        server["identity_file"] = str(pathlib.Path(identity_file).expanduser())

    # Add server to config
    servers[name] = server

    _save_and_show_toml_doc(doc, config_path)


def remove_server_from_config(name: str) -> None:
    """Remove a server from the config file."""
    doc, config_path = get_or_create_toml_doc()

    # Get servers table
    servers: Any = doc.get("servers")
    if not servers or name not in servers:
        raise RuntimeError(f"Error: Server '{name}' not found in config")

    # Remove server
    del servers[name]

    _save_and_show_toml_doc(doc, config_path)


def complete_server_names(incomplete: str) -> list[str | tuple[str, str]]:
    """Complete server names from config.

    Args:
        incomplete: Partial server name to complete

    Returns:
        List of (server_name, description) tuples for matching servers.
        Returns empty list if config can't be loaded.
    """
    try:
        servers = get_server_configs()
        completions: list[str | tuple[str, str]] = []
        for name, config in servers.items():
            if name.startswith(incomplete):
                # Show description if either hostname differs or username is set
                if config.hostname != name or config.user:
                    desc = f"{config.user}@{config.hostname}" if config.user else config.hostname
                else:
                    desc = ""
                completions.append((name, desc))
        return completions
    except RuntimeError:
        return []


def _create_empty_config() -> tomlkit.TOMLDocument:
    """Create empty config from template."""
    template_path = monorepo_util.find_monorepo_root() / "luce_config.toml.template"
    return tomlkit.loads(template_path.read_text())
