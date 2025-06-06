#!/bin/bash

set -e

REPO="opencv/ci-gha-workflow"
DEST_DIR="/home/www/site/webapps/docs/test"
TMP_DIR="/tmp/artifacts"
TOKEN="_insert_your_key"

mkdir -p "$TMP_DIR"

echo "[*] Fetching artifacts list..."
ARTIFACTS=$(curl -s -H "Authorization: token $TOKEN" "https://api.github.com/repos/$REPO/actions/artifacts")

for BRANCH in 4.x 5.x; do
    ARTIFACT_NAME="opencv-docs-$BRANCH"
    echo "[*] Looking for latest artifact named $ARTIFACT_NAME..."

    # Парсим id и дату создания вручную
    ARTIFACT_ID=$(echo "$ARTIFACTS" | awk -v name="$ARTIFACT_NAME" '
        BEGIN { RS="{"; FS=","; max_time=0; best_id="" }
        /"name": *"[^"]+"/ {
            this_id=""
            this_name=""
            this_expired="false"
            this_created=""
            for (i=1; i<=NF; i++) {
                if ($i ~ /"id":/) {
                    gsub(/[^0-9]/, "", $i)
                    this_id=$i
                }
                if ($i ~ /"name":/) {
                    gsub(/.*"name": *"/, "", $i)
                    gsub(/".*/, "", $i)
                    this_name=$i
                }
                if ($i ~ /"expired":/) {
                    if ($i ~ /true/) this_expired="true"
                }
                if ($i ~ /"created_at":/) {
                    gsub(/.*"created_at": *"/, "", $i)
                    gsub(/".*/, "", $i)
                    this_created=$i
                }
            }

            if (this_name == name && this_expired == "false") {
                cmd = "date -d \"" this_created "\" +%s"
                cmd | getline epoch
                close(cmd)
                if (epoch > max_time) {
                    max_time = epoch
                    best_id = this_id
                }
            }
        }
        END { print best_id }
    ')

    if [[ -z "$ARTIFACT_ID" ]]; then
        echo "[!] No valid artifact found for $ARTIFACT_NAME"
        continue
    fi

    ZIP_PATH="$TMP_DIR/$ARTIFACT_NAME.zip"
    DEST_PATH="$DEST_DIR/$BRANCH"

    echo "[*] Downloading $ARTIFACT_NAME (ID: $ARTIFACT_ID) -> $ZIP_PATH"
    curl -sL -H "Authorization: token $TOKEN" \
        -o "$ZIP_PATH" \
        "https://api.github.com/repos/$REPO/actions/artifacts/$ARTIFACT_ID/zip"

    echo "[*] Extracting to $DEST_PATH"
    mkdir -p "$DEST_PATH"
    echo "[*] Cleaning old contents in $DEST_PATH"
    rm -rf "$DEST_PATH"/*
    TMP_EXTRACT="$TMP_DIR/extract_$BRANCH"
    rm -rf "$TMP_EXTRACT"
    mkdir -p "$TMP_EXTRACT"
    unzip -q -o "$ZIP_PATH" -d "$TMP_EXTRACT"
    echo "[*] Moving relevant files to $DEST_PATH"
    if [ -d "$TMP_EXTRACT/doc/doxygen/html" ]; then
        mv "$TMP_EXTRACT/doc/doxygen/html"/* "$DEST_PATH/"
    else
        echo "[!] Warning: doc/doxygen/html not found in artifact"
    fi

    if [ -d "$TMP_EXTRACT/js/bin" ]; then
        mv "$TMP_EXTRACT/js/bin"/* "$DEST_PATH/"
    else
        echo "[!] Warning: js/bin not found in artifact"
    fi

done

#echo "[*] Reloading nginx..."
#nginx -s reload

echo "[*] Cleaning old temp zip files..."
find "$TMP_DIR" -type f -name "*.zip" -mtime +1 -delete

echo "[✔] Done."
