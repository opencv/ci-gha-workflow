#!/bin/bash

set -e

REPO="avdivan/ci-gha-workflow"
DEST_DIR="/usr/share/nginx/html/opencv-docs"
TMP_DIR="/tmp/artifacts"
TOKEN="key"  

mkdir -p "$TMP_DIR"

echo "[*] Fetching artifacts list..."
ARTIFACTS=$(curl -s -H "Authorization: token $TOKEN" "https://api.github.com/repos/$REPO/actions/artifacts")

for BRANCH in 4.x 5.x; do
    ARTIFACT_NAME="opencv-docs-$BRANCH"
    echo "[*] Looking for latest artifact named $ARTIFACT_NAME..."

    ARTIFACT_INFO=$(echo "$ARTIFACTS" | jq -r \
        --arg NAME "$ARTIFACT_NAME" '
        .artifacts
        | map(select(.name == $NAME and .expired == false))
        | sort_by(.created_at)
        | reverse
        | .[0]
    ')

    ARTIFACT_ID=$(echo "$ARTIFACT_INFO" | jq -r .id)

    if [[ "$ARTIFACT_ID" == "null" || -z "$ARTIFACT_ID" ]]; then
        echo "[!] No artifact found named $ARTIFACT_NAME"
        continue
    fi

    ZIP_PATH="$TMP_DIR/$ARTIFACT_NAME.zip"
    DEST_PATH="$DEST_DIR/$BRANCH"

    echo "[*] Downloading $ARTIFACT_NAME -> $ZIP_PATH"
    curl -sL -H "Authorization: token $TOKEN" \
        -o "$ZIP_PATH" \
        "https://api.github.com/repos/$REPO/actions/artifacts/$ARTIFACT_ID/zip"

    echo "[*] Extracting to $DEST_PATH"
    mkdir -p "$DEST_PATH"
    echo "[*] Cleaning old contents in $DEST_PATH"
    rm -rf "$DEST_PATH"/*
    unzip -q -o "$ZIP_PATH" -d "$DEST_PATH"
done

echo "[*] Reloading nginx..."
nginx -s reload

echo "[*] Cleaning old temp zip files..."
find "$TMP_DIR" -type f -name "*.zip" -mtime +1 -delete

echo "[✔] Done."
