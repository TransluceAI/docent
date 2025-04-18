#!/bin/bash

# Exit on error
set -e

echo "Checking existing Node.js installation..."

# Check if Node.js is already installed
if command -v node &> /dev/null; then
    echo "Node.js is already installed:"
    node -v

    # Check if it's the requested version
    if [ -n "$1" ]; then
        current_version=$(node -v | cut -d 'v' -f 2)
        if [[ "$current_version" == "$1"* ]]; then
            echo "Requested Node.js version $1 is already installed (current: $current_version)."
            exit 0
        else
            echo "Installed version ($current_version) differs from requested version $1."
            echo "Will proceed with installation of requested version."
        fi
    else
        echo "No specific version requested. Using existing Node.js installation."
        exit 0
    fi
fi

# Check if nvm is already installed
if [ -d "$HOME/.nvm" ]; then
    echo "nvm is already installed"
else
    echo "Installing nvm..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
fi

# Source nvm
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# Verify nvm is available
if ! command -v nvm &> /dev/null; then
    echo "Error: nvm installation failed or not properly sourced" >&2
    echo "Please restart your terminal and try again" >&2
    exit 1
fi

# Install Node.js with specified version
version="$1"
echo "Installing Node.js version $version..."
nvm install "$version"

# Verify installation
echo "Installation complete!"
echo "Node.js version:"
node -v
echo "npm version:"
npm -v
