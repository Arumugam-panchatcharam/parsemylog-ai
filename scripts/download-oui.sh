#!/bin/bash
#
# Download OUI Database for MAC Vendor Lookups
# =============================================
#
# Downloads the IEEE OUI database (oui.txt) for MAC address vendor resolution.
# This script is optional - the database can also be downloaded via the API:
#   POST /api/utilities/oui-update
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUI_FILE="$PROJECT_ROOT/oui.txt"
OUI_URL="https://standards-oui.ieee.org/oui/oui.txt"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  IEEE OUI Database Download"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if file already exists
if [ -f "$OUI_FILE" ]; then
    FILE_SIZE=$(du -h "$OUI_FILE" | cut -f1)
    FILE_AGE=$(find "$OUI_FILE" -mtime +0 -printf "%Td days ago\n" 2>/dev/null || stat -f "%Sm" -t "%Y-%m-%d" "$OUI_FILE" 2>/dev/null || echo "unknown")
    echo "⚠️  OUI database already exists:"
    echo "   File: $OUI_FILE"
    echo "   Size: $FILE_SIZE"
    echo "   Modified: $FILE_AGE"
    echo ""
    read -p "   Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipped."
        exit 0
    fi
    echo ""
fi

# Download with progress bar
echo "📥 Downloading OUI database from IEEE..."
echo "   URL: $OUI_URL"
echo ""

if command -v wget &> /dev/null; then
    wget --progress=bar:force -O "$OUI_FILE" "$OUI_URL" 2>&1
elif command -v curl &> /dev/null; then
    curl -# -L -o "$OUI_FILE" "$OUI_URL"
else
    echo "❌ Error: Neither wget nor curl is available."
    echo "   Please install wget or curl and try again."
    exit 1
fi

# Verify download
if [ ! -f "$OUI_FILE" ]; then
    echo ""
    echo "❌ Error: Download failed - file not created."
    exit 1
fi

FILE_SIZE=$(du -h "$OUI_FILE" | cut -f1)
if [ ! -s "$OUI_FILE" ]; then
    echo ""
    echo "❌ Error: Downloaded file is empty."
    rm -f "$OUI_FILE"
    exit 1
fi

# Count entries
ENTRY_COUNT=$(grep -c "(hex)" "$OUI_FILE" || echo "0")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Download Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   File: $OUI_FILE"
echo "   Size: $FILE_SIZE"
echo "   Vendors: $ENTRY_COUNT"
echo ""
echo "If running in Docker, restart containers to load the database:"
echo "   docker-compose restart logai-api celery-worker"
echo ""
