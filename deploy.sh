#!/bin/bash
#
# Deploy Trading Assistant to Home Assistant via Samba
#
# Usage: ./deploy.sh [--dry-run] [--restart]
#

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Paths
LOCAL_SRC="/Users/jirimerz/Projects/TAv70/src/trading_assistant"
SAMBA_TARGET="/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant"
ADDON_ID="a0d7b954_appdaemon"

# Parse arguments
DRY_RUN=false
AUTO_RESTART=false

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --restart)
            AUTO_RESTART=true
            shift
            ;;
        --help)
            echo "Usage: ./deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run    Show what would be deployed without actually deploying"
            echo "  --restart    Automatically restart AppDaemon after deploy"
            echo "  --help       Show this help message"
            exit 0
            ;;
    esac
done

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Trading Assistant Deployment${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# 1. Check if Samba share is mounted
echo -e "${YELLOW}[1/5]${NC} Checking Samba mount..."
if [ ! -d "$SAMBA_TARGET" ]; then
    echo -e "${RED}✗ Samba share not mounted at: $SAMBA_TARGET${NC}"
    echo ""
    echo "Please mount the share first:"
    echo "  Finder → Go → Connect to Server → smb://homeassistant.local/addon_configs"
    exit 1
fi
echo -e "${GREEN}✓ Samba share mounted${NC}"
echo ""

# 2. Check local source
echo -e "${YELLOW}[2/5]${NC} Checking local source..."
if [ ! -d "$LOCAL_SRC" ]; then
    echo -e "${RED}✗ Local source not found: $LOCAL_SRC${NC}"
    exit 1
fi

FILE_COUNT=$(ls -1 "$LOCAL_SRC"/*.py 2>/dev/null | wc -l | tr -d ' ')
echo -e "${GREEN}✓ Found $FILE_COUNT Python files in local source${NC}"
echo ""

# 3. Show what will be deployed
echo -e "${YELLOW}[3/5]${NC} Files to deploy:"
if [ "$DRY_RUN" = true ]; then
    rsync -avn --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' "$LOCAL_SRC/" "$SAMBA_TARGET/"
else
    rsync -avn --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' "$LOCAL_SRC/" "$SAMBA_TARGET/" | grep -v "/$" | head -25
fi
echo ""

# 4. Deploy
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[4/5]${NC} ${BLUE}DRY RUN - No files deployed${NC}"
    echo ""
    exit 0
else
    echo -e "${YELLOW}[4/5]${NC} Deploying files..."
    rsync -av --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' "$LOCAL_SRC/" "$SAMBA_TARGET/" | grep -E "(sending|sent|total size)" | tail -3
    echo -e "${GREEN}✓ Deployment complete${NC}"
    echo ""
fi

# 5. Restart AppDaemon
echo -e "${YELLOW}[5/5]${NC} AppDaemon restart..."
if [ "$AUTO_RESTART" = true ]; then
    echo "Attempting to restart AppDaemon addon..."
    if command -v ha &> /dev/null; then
        ha addons restart "$ADDON_ID" && echo -e "${GREEN}✓ AppDaemon restarted${NC}" || echo -e "${RED}✗ Restart failed${NC}"
    else
        echo -e "${YELLOW}⚠ 'ha' command not available - please restart manually${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Manual restart required:${NC}"
    echo "  Settings → Add-ons → AppDaemon → RESTART"
fi
echo ""

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Deployment finished!${NC}"
echo -e "${GREEN}================================${NC}"
