#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <relative-path-to-file> [s3://bucket/path/]" >&2
  exit 1
fi

FILE="$1"
BUCKET="${2:-s3://docent-test-data/}"

if [[ "$FILE" = /* ]]; then
  echo "Please supply the file path relative to the current working directory." >&2
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "File not found: $FILE" >&2
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found; install it before running this script." >&2
  exit 1
fi

OBJECT_URI="${BUCKET%/}/$(basename "$FILE")"

echo "Uploading $FILE to $BUCKET ..."
aws s3 cp "$FILE" "$BUCKET"

echo "Verifying upload at $OBJECT_URI ..."
aws s3 ls "$OBJECT_URI"

echo "Done."
