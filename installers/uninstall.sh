#!/usr/bin/env bash
# VexNet Uninstaller for macOS/Linux
# Run: curl -fsSL https://vexnet.ai/uninstall.sh | bash

set -e

echo ""
echo "========================================"
echo "   VexNet Uninstaller for macOS/Linux   "
echo "========================================"
echo ""

VEX_DIR="$HOME/.vex"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ─── Confirm ───
echo -e "${YELLOW}This will remove VexNet and all its data from your system.${NC}"
echo ""
echo "  The following will be deleted:"
echo "    $VEX_DIR              (venv, config, data, chat history)"
echo "    PATH entry in shell config"
echo ""
echo -e "  ${YELLOW}Note: Ollama and its models will NOT be removed.${NC}"
echo ""

read -r -p "  Continue? [y/N] " confirm < /dev/tty
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo ""
    echo "  Cancelled."
    echo ""
    exit 0
fi

echo ""

# ─── Step 1: Remove VexNet directory ───
echo -e "${YELLOW}[1/2] Removing VexNet...${NC}"

if [ -d "$VEX_DIR" ]; then
    rm -rf "$VEX_DIR"
    echo -e "  Removed $VEX_DIR ${GREEN}OK${NC}"
else
    echo "  $VEX_DIR not found, skipping."
fi

# ─── Step 2: Clean up shell config ───
echo -e "${YELLOW}[2/2] Cleaning up shell config...${NC}"

cleaned=false
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    if [ -f "$rc_file" ]; then
        if grep -qF ".vex/bin" "$rc_file" 2>/dev/null; then
            # Remove the VexNet PATH line and comment
            sed -i.bak '/.vex\/bin/d' "$rc_file" 2>/dev/null || \
                sed -i '' '/.vex\/bin/d' "$rc_file" 2>/dev/null
            sed -i.bak '/^# VexNet$/d' "$rc_file" 2>/dev/null || \
                sed -i '' '/^# VexNet$/d' "$rc_file" 2>/dev/null
            # Clean up backup files from sed -i.bak
            rm -f "${rc_file}.bak" 2>/dev/null
            echo -e "  Cleaned $rc_file ${GREEN}OK${NC}"
            cleaned=true
        fi
    fi
done

if [ "$cleaned" = false ]; then
    echo "  No shell config changes found."
fi

# ─── Done ───
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   VexNet uninstalled successfully.     ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  To also remove Ollama and its models:"
echo "    ollama rm qwen3:30b-a3b"
echo "    ollama rm nomic-embed-text:latest"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "    brew uninstall ollama"
else
    echo "    sudo rm /usr/local/bin/ollama"
fi
echo ""
echo -e "  ${YELLOW}Restart your terminal to apply PATH changes.${NC}"
echo ""
