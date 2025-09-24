#!/usr/bin/env bash

set -o nounset
set -o pipefail

error() {
    printf 'Error: %s\n' "$*" >&2
}

run_git() {
    local output
    if ! output=$(git "$@" 2>&1); then
        local status=$?
        local message
        message=$(tail -n1 <<<"$output")
        if [[ -z $message ]]; then
            message="$output"
        fi
        error "Git command 'git $*' failed: $message"
        return $status
    fi
    printf '%s\n' "$output"
}

get_latest_tag_info() {
    if ! git fetch --tags; then
        local status=$?
        error "Git command 'git fetch --tags' failed."
        return $status
    fi

    local last_tag
    if ! last_tag=$(run_git describe --tags --abbrev=0); then
        return 1
    fi

    local commits
    if ! commits=$(run_git rev-list --count "${last_tag}..HEAD"); then
        return 1
    fi

    if [[ ! $commits =~ ^[0-9]+$ ]]; then
        error "Unexpected commit count '$commits' from git rev-list."
        return 1
    fi

    printf '%s\n%s\n' "$last_tag" "$commits"
}

bump_version() {
    local current_version="$1"
    local bump_type="$2"
    local pattern='^(v?)([0-9]+)\.([0-9]+)\.([0-9]+)-(alpha|beta)$'

    if [[ ! $current_version =~ $pattern ]]; then
        error "Invalid version format. Expected MAJOR.MINOR.PATCH-alpha/beta."
        return 1
    fi

    local prefix="${BASH_REMATCH[1]}"
    local major="${BASH_REMATCH[2]}"
    local minor="${BASH_REMATCH[3]}"
    local patch="${BASH_REMATCH[4]}"
    local suffix="${BASH_REMATCH[5]}"

    case "$bump_type" in
        major) major=$((major + 1)) ;;
        minor) minor=$((minor + 1)) ;;
        patch) patch=$((patch + 1)) ;;
        *)
            error "Unsupported bump type '$bump_type'."
            return 1
            ;;
    esac

    # Omit the prefix when returning the bumped version
    printf '%s\n' "${major}.${minor}.${patch}-${suffix}"
}

create_tag() {
    local tag="$1"
    local remote="$2"

    if ! git tag "$tag"; then
        local status=$?
        error "Git command 'git tag $tag' failed."
        return $status
    fi

    if ! git push "$remote" "$tag"; then
        local status=$?
        error "Git command 'git push $remote $tag' failed."
        return $status
    fi
}

run_version_bump() {
    # Get bump type from user if not already set
    BUMP_TYPE=""
    echo "What type of version bump do you want to make? [major/minor/patch/rollback]"
    read -r BUMP_TYPE
    BUMP_TYPE=$(printf '%s' "$BUMP_TYPE" | tr '[:upper:]' '[:lower:]')

    if [[ $BUMP_TYPE == "rollback" ]]; then
        echo "Rollback selected; no version bump performed."
        return 0
    fi

    if [[ $BUMP_TYPE != "major" && $BUMP_TYPE != "minor" && $BUMP_TYPE != "patch" ]]; then
        error "Bump type must be one of: major, minor, patch, rollback"
        return 1
    fi


    # Get the latest tag info
    if ! TAG_INFO=$(get_latest_tag_info); then
        return 1
    fi
    LAST_VERSION="${TAG_INFO%%$'\n'*}"
    COMMITS_AHEAD="${TAG_INFO#*$'\n'}"

    # Compute the bumped version
    if ! BUMPED_VERSION=$(bump_version "$LAST_VERSION" "$BUMP_TYPE"); then
        return 1
    fi

    # Confirmation prompt
    echo "Confirm to tag HEAD with $BUMPED_VERSION ($COMMITS_AHEAD commits ahead of $LAST_VERSION) [y/n]"
    read -r confirm
    confirm=$(printf '%s' "$confirm" | tr '[:upper:]' '[:lower:]')
    if [[ $confirm != "y" ]]; then
        echo "Tag creation aborted."
        return 1
    fi

    # Create the tag
    if ! create_tag "$BUMPED_VERSION" "origin"; then
        echo "Tag creation failed."
        return 1
    fi
}

if ! run_version_bump; then
    exit 1
fi
