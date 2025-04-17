#!/bin/bash

# Print all commands as they are executed
# set -x

# Function to find the monorepo root by looking for 'lib' and 'project' directories
find_monorepo_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -d "$dir/lib" ] && [ -d "$dir/project" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo "Error: Could not find monorepo root." >&2
    return 1
}

# Function to get the path of a package
get_package_path() {
    local package_name="$1"
    local project_path="$MONOREPO_ROOT/project/$package_name"
    local lib_path="$MONOREPO_ROOT/lib/$package_name"

    if [ -d "$project_path" ]; then
        echo "$project_path"
        return 0
    elif [ -d "$lib_path" ]; then
        echo "$lib_path"
        return 0
    else
        echo "Error: Package '$package_name' not found in project/ or lib/ directories." >&2
        return 1
    fi
}

# Function to activate an env and cd there
activate_env() {
    local package_name="$1"

    if [ -n "$package_name" ]; then
        PACKAGE_PATH="$(get_package_path "$package_name")"
        if [ $? -ne 0 ]; then
            echo "$PACKAGE_PATH" >&2
            return 1
        fi
        VENV_PATH="$PACKAGE_PATH/.venv/bin/activate"
        if [ -f "$VENV_PATH" ]; then
            source "$VENV_PATH"
            cd "$PACKAGE_PATH"
        else
            echo "Error: Virtual environment for package '$package_name' not found at $VENV_PATH" >&2
        fi
    else
        # Activate base clarity venv
        BASE_VENV_PATH="$MONOREPO_ROOT/.venv/bin/activate"
        if [ -f "$BASE_VENV_PATH" ]; then
            source "$BASE_VENV_PATH"
            cd "$MONOREPO_ROOT"
        else
            echo "Error: Base virtual environment not found at $BASE_VENV_PATH" >&2
        fi
    fi
}

# Function to install an env
install_env() {
    local dir="$1"
    local do_activate="$2"

    cd "$dir"
    uv sync
    if [ "$dir" = "$MONOREPO_ROOT" ]; then
        .venv/bin/pre-commit install
    fi
    if [ "$do_activate" = true ]; then
        source "$dir/.venv/bin/activate"
    fi
}

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Check if "lucepkg" is in the script directory
if [[ "$SCRIPT_DIR" != *"/lucepkg/"* ]]; then
    echo "Warning: This script is not being run from the expected 'lucepkg' directory. Something might be wrong." >&2
    echo "Current directory: $SCRIPT_DIR" >&2
fi

# Find the monorepo root
MONOREPO_ROOT="$(find_monorepo_root "$SCRIPT_DIR")"
if [ $? -ne 0 ]; then
    echo "Error: Could not find monorepo root." >&2
    return 1
fi

CONFIG_FILE="$HOME/.luce/config.json"

# Function to push to a single server
push_to_server() {
    local SERVER_NAME="$1"
    HOSTNAME=$(jq -r ".servers[\"$SERVER_NAME\"].hostname" "$CONFIG_FILE")
    USER=$(jq -r ".servers[\"$SERVER_NAME\"].user" "$CONFIG_FILE")
    IDENTITY_FILE=$(jq -r ".servers[\"$SERVER_NAME\"].identity_file" "$CONFIG_FILE")
    REMOTE_PATH=$(jq -r ".servers[\"$SERVER_NAME\"].remote_path" "$CONFIG_FILE")

    if [[ -z "$HOSTNAME" || -z "$USER" || -z "$IDENTITY_FILE" || -z "$REMOTE_PATH" ]]; then
        echo "Invalid configuration for server '$SERVER_NAME'."
        return 1
    fi

    cd "$MONOREPO_ROOT" || exit 1

    echo "Pushing to $SERVER_NAME ($USER@$HOSTNAME)..."

    # Ensure the remote path exists, and set up an rsync backup directory.
    local remote_cmds=$(
        echo "set -euo pipefail";
        echo "mkdir -p '$REMOTE_PATH/.rsync_backups'";
        echo "echo '/*' >'$REMOTE_PATH/.rsync_backups/.gitignore'";
    )
    ssh -i "$IDENTITY_FILE" "$USER@$HOSTNAME" "$remote_cmds"

    local backupdir="$REMOTE_PATH/.rsync_backups/before_push"
    # Use rsync with gitignore filtering to sync files efficiently.
    # Keep a copy of all overwritten or deleted files in the .rsync_backups
    # directory. (Note: we only keep one copy, so if you edit a file twice, the
    # original version will be gone. This is OK, since the main use case is to
    # recover from a single bad command; also, deleted files stay backed up.)
    rsync -avz \
        -e "ssh -i $IDENTITY_FILE" \
        --filter=':- .gitignore' \
        --include='**/.gitignore' \
        --exclude='/.git' \
        --exclude='/.rsync_backups' \
        --backup \
        --backup-dir="$backupdir" \
        --delete \
        ./ "$USER@$HOSTNAME:$REMOTE_PATH"

    if [[ $? -ne 0 ]]; then
        echo "Push to $SERVER_NAME failed."
        return 1
    fi

    echo "Push to $SERVER_NAME completed successfully."
}

do_push() {
    if [[ "$server_name" == "--all" ]]; then
        local servers=()
        while IFS= read -r server; do
            servers+=("$server")
        done < <(jq -r '.servers | keys[]' "$CONFIG_FILE")

        local pids=()
        for server in "${servers[@]}"; do
            push_to_server "$server" &
            pids+=($!)
        done

        for pid in "${pids[@]}"; do
            wait $pid
            push_status=$?
            if [ $push_status -ne 0 ]; then
                echo "Warning: Push process $pid failed with status $push_status"
            fi
        done

    elif [ -n "$server_name" ]; then
        push_to_server "$server_name"
    else
        echo "Please specify a server name or '--all'."
        return 1
    fi
}

# Function to handle the sync command
do_sync() {
    if [ -z "$server_name" ]; then
        echo "Please specify a server name or '--all'."
        return 1
    fi

    echo "Starting sync for $server_name. Running initial push..."
    do_push

    echo "Watching for changes..."
    fswatch -o "$MONOREPO_ROOT" | while read; do
        do_push
    done
}

# Define the luce function
luce() {
    local command=""
    local subcommand=""
    local package_name=""
    local destination=""
    local all=false
    local port=""
    local node_version=""
    local server_name=""
    local file=""
    local ssh_key=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            activate|remove|install|nb|node|uv|push|sync|rsync|ssh)
                command="$1"
                shift
                if [ "$command" = "nb" ] || [ "$command" = "node" ] || [ "$command" = "uv" ]; then
                    subcommand="$1"
                    shift
                fi
                ;;
            --all|-a)
                all=true
                server_name="--all"
                shift
                ;;
            --port|-p)
                port="$2"
                shift 2
                ;;
            --version|-v)
                node_version="$2"
                shift 2
                ;;
            --file|-f)
                file="$2"
                shift 2
                ;;
            --dest|-d)
                destination="$2"
                shift 2
                ;;
            --ssh)
                ssh_key="$2"
                shift 2
                ;;
            -*)
                echo "Error: Unknown option $1" >&2
                return 1
                ;;
            *)
                # For commands that require an argument
                if [ -z "$package_name" ] && [[ "$command" != "push" && "$command" != "sync" && "$command" != "ssh" ]]; then
                    package_name="$1"
                elif [[ "$command" = "push" || "$command" = "sync" || "$command" = "ssh" ]]; then
                    if [ -z "$server_name" ] && [ "$all" = false ]; then
                        server_name="$1"
                    else
                        echo "Error: Unexpected argument $1" >&2
                        return 1
                    fi
                else
                    echo "Error: Unexpected argument $1" >&2
                    return 1
                fi
                shift
                ;;
        esac
    done

    # Validate options
    if [ "$all" = true ] && [[ "$command" != "install" && "$command" != "push" && "$command" != "sync" ]]; then
        echo "Error: --all option can only be used with install, push, or sync commands." >&2
        return 1
    fi

    # For luce node install, set default node version if not specified
    if [ "$command" = "node" ] && [ "$subcommand" = "install" ] && [ -z "$node_version" ]; then
        node_version="22"
    fi

    # Execute command
    case "$command" in
        activate)
            activate_env "$package_name"
            ;;
        remove)
            if [ -z "$package_name" ]; then
                echo "Error: Package name is required for remove." >&2
                return 1
            fi
            PACKAGE_PATH="$(get_package_path "$package_name")"
            if [ $? -ne 0 ]; then
                echo "$PACKAGE_PATH" >&2
                return 1
            fi
            VENV_PATH="$PACKAGE_PATH/.venv"

            if [ -d "$VENV_PATH" ]; then
                echo "Removing virtual environment for $package_name..."
                rm -rf "$VENV_PATH"
                if [ $? -ne 0 ]; then
                    echo "Error: Failed to remove virtual environment." >&2
                    return 1
                fi
                echo "Virtual environment for $package_name removed successfully."
            else
                echo "No virtual environment found for $package_name." >&2
            fi
            ;;
        install)
            # Deactivate any active virtual environment if it exists
            if [ -n "$VIRTUAL_ENV" ]; then
                echo "Deactivating current virtual environment..."
                deactivate
            fi
            # Install different packages depending on args
            if $all; then
                # Install all packages
                for dir in "$MONOREPO_ROOT"/lib/* "$MONOREPO_ROOT"/project/*; do
                    if [ -d "$dir" ]; then
                        echo "Installing package in $dir"
                        install_env "$dir" false
                    fi
                done
                install_env "$MONOREPO_ROOT" true
            elif [ -z "$package_name" ]; then
                install_env "$MONOREPO_ROOT" true
            else
                PACKAGE_PATH="$(get_package_path "$package_name")"
                if [ $? -ne 0 ]; then
                    echo "$PACKAGE_PATH" >&2
                    return 1
                fi
                install_env "$PACKAGE_PATH" true
            fi
            ;;
        nb)
            case "$subcommand" in
                start)
                    if [ -z "$port" ]; then
                        echo "Error: --port option is required for nb start" >&2
                        return 1
                    fi
                    # Activate base environment
                    activate_env ""
                    # Start Jupyter notebook server in the background and capture PID

                    # Check for existing certificate
                    CERT_DIR="$HOME/.luce/cert"
                    CERT_PATH="$CERT_DIR/notebook.pem"
                    KEY_PATH="$CERT_DIR/notebook.key"

                    if [ ! -f "$CERT_PATH" ] || [ ! -f "$KEY_PATH" ]; then
                        # Create cert directory if it doesn't exist
                        mkdir -p "$CERT_DIR"

                        # Generate self-signed certificate
                        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                            -keyout "$KEY_PATH" \
                            -out "$CERT_PATH" \
                            -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

                        echo "Generated new self-signed certificate in $CERT_DIR"
                    fi

                    # Start Jupyter with SSL certificate
                    jupyter notebook --notebook-dir="$MONOREPO_ROOT" \
                        --allow_origin='*' \
                        --ip=0.0.0.0 \
                        --port="$port" \
                        --certfile="" \
                        --keyfile="" \
                        --no-browser \
                        > "jupyter_${port}_log_gitignore.txt" 2>&1 & JUPYTER_PID=$!

                        # If you want SSL, uncomment and provide the cert/key:
                        # --certfile="$CERT_PATH" \
                        # --keyfile="$KEY_PATH" \

                    # Wait a bit for the server to start
                    sleep 5
                    # Get and print the token URL
                    echo "Jupyter notebook server started with PID: $JUPYTER_PID"
                    echo "Server logs are being written to: $MONOREPO_ROOT/jupyter_${port}_log_gitignore.txt"
                    jupyter server list | grep ":$port/"
                    ;;
                register)
                    # Activate the package's environment
                    activate_env "$package_name"
                    # Register the kernel
                    .venv/bin/python -m ipykernel install --user --name="$package_name" --display-name="Clarity Remote: $package_name"
                    echo "Kernel for $package_name registered successfully."
                    ;;
                *)
                    echo "Usage: luce nb <subcommand> [options] [<package_name>]"
                    echo "Subcommands:"
                    echo "  start --port|-p <port>    Start a Jupyter notebook server from base environment"
                    echo "  register <package_name>   Register a kernel for the specified package"
                    echo "Options:"
                    echo "  --port, -p <port>         Specify the port for the Jupyter notebook server (required for start)"
                    ;;
            esac
            ;;
        node)
            case "$subcommand" in
                install)
                    # Check if node is already installed
                    if command -v node &> /dev/null && command -v npm &> /dev/null; then
                        echo "Node.js is already installed:"
                        echo "Node.js version: $(node -v)"
                        echo "npm version: $(npm -v)"
                        echo "Use 'nvm install -v <version>' if you want to switch Node.js versions."
                        return 0
                    fi

                    echo "Installing Node.js environment..."

                    # Check if nvm is already installed
                    if [ -d "$HOME/.nvm" ]; then
                        echo "nvm is already installed"
                    else
                        echo "Installing nvm..."
                        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
                    fi

                    # Source nvm
                    export NVM_DIR="$HOME/.nvm"
                    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

                    # Verify nvm is available
                    if ! command -v nvm &> /dev/null; then
                        echo "Error: nvm installation failed or not properly sourced" >&2
                        echo "Please restart your terminal and try again" >&2
                        return 1
                    fi

                    # Install Node.js with specified version
                    echo "Installing Node.js version $node_version..."
                    nvm install "$node_version"

                    # Verify installation
                    echo "Installation complete!"
                    echo "Node.js version:"
                    node -v
                    echo "npm version:"
                    npm -v
                    ;;
                *)
                    echo "Usage: luce node <subcommand> [options]"
                    echo "Subcommands:"
                    echo "  install [--version|-v <version>]    Install Node.js using nvm (default version: 22)"
                    echo "Options:"
                    echo "  --version, -v <version>          Specify Node.js version to install"
                    ;;
            esac
            ;;
        uv)
            case "$subcommand" in
                install)
                    echo "Installing uv package installer..."
                    curl -LsSf https://astral.sh/uv/install.sh | sh

                    # Source the appropriate RC file based on shell
                    if [ -n "$ZSH_VERSION" ]; then
                        echo "Sourcing ~/.zshrc..."
                        source ~/.zshrc
                    elif [ -n "$BASH_VERSION" ]; then
                        echo "Sourcing ~/.bashrc..."
                        source ~/.bashrc
                    else
                        echo "Warning: Unknown shell type. You may need to restart your shell or manually source your .rc file."
                    fi
                    ;;
                *)
                    echo "Usage: luce uv <subcommand>"
                    echo "Subcommands:"
                    echo "  install    Install the uv package installer"
                    ;;
            esac
            ;;
        push)
            do_push
            ;;
        sync)
            do_sync
            ;;
        rsync)
            if [ -z "$destination" ]; then
                echo "Error: --dest (user@host:path) is required." >&2
                return 1
            fi
            if [ -z "$file" ]; then
                echo "Error: --file option is required." >&2
                return 1
            fi

            # Set default SSH key if not specified
            ssh_key="${ssh_key:-$HOME/.ssh/clarity-ssh.pem}"

            # Validate SSH key exists
            if [ ! -f "$ssh_key" ]; then
                echo "Error: SSH key not found at $ssh_key" >&2
                return 1
            fi

            # Construct and execute rsync command
            rsync -avzP -e "ssh -i $ssh_key" \
                "$file" \
                "$destination"
            ;;
        ssh)
            # If no server name is given, fallback to the first server in the config file
            if [ -z "$server_name" ] || [ "$server_name" = "--all" ]; then
                local default_server
                default_server=$(jq -r '.servers | keys[0]' "$CONFIG_FILE" 2>/dev/null)

                if [ -z "$default_server" ] || [ "$default_server" = "null" ]; then
                    echo "Error: No servers found in config file." >&2
                    return 1
                fi

                server_name="$default_server"
            fi

            HOSTNAME=$(jq -r ".servers[\"$server_name\"].hostname" "$CONFIG_FILE")
            USER=$(jq -r ".servers[\"$server_name\"].user" "$CONFIG_FILE")
            IDENTITY_FILE=$(jq -r ".servers[\"$server_name\"].identity_file" "$CONFIG_FILE")

            if [[ -z "$HOSTNAME" || -z "$USER" || -z "$IDENTITY_FILE" || "$HOSTNAME" = "null" || "$USER" = "null" || "$IDENTITY_FILE" = "null" ]]; then
                echo "Error: Server '$server_name' not found or missing configuration fields in $CONFIG_FILE." >&2
                return 1
            fi

            echo "Connecting to $USER@$HOSTNAME using key $IDENTITY_FILE..."
            ssh -i "$IDENTITY_FILE" "$USER@$HOSTNAME"
            ;;
        *)
            echo "Usage: luce <command> [options] [<package_name>|<server_name>]"
            echo "Commands:"
            echo "  activate [<package_name>]       Activate a virtual environment"
            echo "  remove <package_name>           Remove a virtual environment"
            echo "  install [options] [<package_name>]  Install monorepo package(s) and activate environment"
            echo "  nb <subcommand> [options] [<package_name>]  Notebook-related commands"
            echo "  node <subcommand> [options]     Node.js-related commands"
            echo "  uv <subcommand>                 UV package installer commands"
            echo "  push <server_name|--all>        Push current changes to specified server or all servers"
            echo "  sync <server_name|--all>        Sync changes to server(s) as they happen"
            echo "  rsync --file <file> --dest <user@host:path> [--ssh <key_path>]  Sync files to remote host"
            echo "  ssh [<server_name>]            SSH into the specified server or (if none) the first server in config"
            echo "Options:"
            echo "  --all, -a        Install all packages (for install command or push/sync command)"
            echo "  --port, -p <port>    Specify the port for Jupyter notebook server (for nb start command)"
            echo "  --version, -v <version>  Specify Node.js version to install (for node install command)"
            echo "  --file <file>        Specify the local file to sync"
            echo "  --dest <user@host:path>   Specify the destination host and path"
            echo "  --ssh <key_path>     Specify the SSH key to use for syncing (default: ~/.ssh/clarity-ssh.pem)"
            ;;
    esac
}

# Export MONOREPO_ROOT in case it's useful elsewhere
export MONOREPO_ROOT
