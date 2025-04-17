# Luce CLI Tool

The `luce` command-line tool helps manage Python virtual environments and code synchronization across the Transluce monorepo.

There are currently two versions of `luce`:

- `scripts/shellenv.sh`: The original version; implemented as a shell script.
- `lucepkg/cli.py` and `scripts/activate_luce.sh`: The new version; implemented as a Python package.

## Package Management Commands

See `luce --help` for the full list of commands. Below the main commands are documented; the new
version has some additional commands.

### Environment Management

- `luce install [package_name]`
  - Without arguments: Installs and activates the base environment
  - With package name: Installs and activates the specified package's environment
  - Options:
    - `--force, -f`: Force reinstallation (removes existing environment)
    - `--all, -a`: Install all packages in lib/ and project/ directories

- `luce activate [package_name]`
  - Without arguments: Activates the base environment
  - With package name: Activates the specified package's environment and changes to its directory

- `luce remove <package_name>`
  - Removes the virtual environment for the specified package

### Jupyter Notebook Integration

- `luce nb start --port <port>`
  - Starts a Jupyter notebook server from the base environment
  - Required: `--port` to specify the server port
  - Creates a log file: jupyter_<port>_log_gitignore.txt

- `luce nb register <package_name>`
  - Registers a Jupyter kernel for the specified package
  - Makes the package available as a kernel in Jupyter notebooks

### Package Manager Installation

- `luce uv install`
  - Installs the uv package manager
  - Required for managing Python dependencies

- `luce node install [--version <version>]`
  - Installs Node.js and npm using nvm
  - Optional: `--version` flag to specify Node.js version (defaults to 22)

## Code Synchronization Commands

### Push Commands

- `luce push <server_name>`
  - Pushes current codebase to the specified remote server
  - Uses rsync to efficiently transfer files
  - Respects .gitignore rules
  - Options:
    - `--all`: Push to all configured servers in parallel

### Sync Commands

- `luce sync <server_name>`
  - Watches for file changes and automatically pushes to the specified server
  - Provides real-time synchronization of your local changes
  - Options:
    - `--all`: Sync with all configured servers

### Server Configuration

To use push/sync commands, create a config file at `~/.luce/config.json`:

```json
{
  "servers": {
    "server_name": {
      "hostname": "[IP ADDRESS]",
      "user": "ubuntu",
      "identity_file": "~/.ssh/clarity-ssh.pem",
      "remote_path": "/home/ubuntu/clarity"
    },
    ...
  }
}
```

## Examples

```bash
# Install and activate a package
luce install mypackage

# Force reinstall all packages
luce install --all --force

# Start a Jupyter server on port 8888
luce nb start --port 8888

# Register a package's kernel
luce nb register mypackage

# Push code to a specific server
luce push dev-server

# Sync code changes with all servers
luce sync --all
```

## Requirements

- bash or zsh shell
- `uv` package manager (installed via `luce uv install`)
- `jq` command-line JSON processor
- `fswatch` (for sync command)
- ssh access to remote servers (for push/sync commands)
