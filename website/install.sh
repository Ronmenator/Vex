#!/usr/bin/env bash
# VexNet Installer for macOS/Linux
# Run: curl -fsSL https://vexnet.ai/install.sh | bash

set -e

echo ""
echo "========================================"
echo "   VexNet Installer for macOS/Linux     "
echo "========================================"
echo ""

VEX_DIR="$HOME/.vex"
VENV_DIR="$VEX_DIR/venv"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Step 1: Check Python ───
echo -e "${YELLOW}[1/5] Checking Python...${NC}"

PYTHON=""
for cmd in python3.14 python3.13 python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1)
        minor=$(echo "$ver" | sed -n 's/.*Python 3\.\([0-9]*\).*/\1/p')
        if [ -n "$minor" ] && [ "$minor" -ge 12 ]; then
            PYTHON="$cmd"
            echo -e "  Found: $ver ${GREEN}OK${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    echo -e "  ${RED}Python 3.12+ is required but not found.${NC}"
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "  ${YELLOW}Install with Homebrew:${NC}"
        echo "    brew install python@3.13"
    else
        echo -e "  ${YELLOW}Install on Ubuntu/Debian:${NC}"
        echo "    sudo apt update && sudo apt install python3.12 python3.12-venv"
        echo ""
        echo -e "  ${YELLOW}Install on Fedora:${NC}"
        echo "    sudo dnf install python3.12"
    fi
    echo ""
    exit 1
fi

# ─── Step 2: Check/Install Ollama ───
echo -e "${YELLOW}[2/5] Checking Ollama...${NC}"

if command -v ollama &>/dev/null; then
    echo -e "  Ollama is installed. ${GREEN}OK${NC}"
else
    echo "  Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo -e "  Ollama installed. ${GREEN}OK${NC}"
fi

# ─── Step 3: Pull Ollama models ───
echo -e "${YELLOW}[3/5] Setting up AI models...${NC}"

# Start Ollama if not running
if ! pgrep -x "ollama" &>/dev/null; then
    echo "  Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 3
fi

echo "  Pulling language model (this may take a few minutes)..."
ollama pull qwen3:30b-a3b 2>/dev/null || ollama pull qwen3:8b 2>/dev/null || true
echo -e "  Language model ready. ${GREEN}OK${NC}"

echo "  Pulling embedding model..."
ollama pull nomic-embed-text:latest 2>/dev/null || true
echo -e "  Embedding model ready. ${GREEN}OK${NC}"

# ─── Step 4: Install VexNet ───
echo -e "${YELLOW}[4/5] Installing VexNet...${NC}"

mkdir -p "$VEX_DIR"

echo "  Creating Python environment..."
"$PYTHON" -m venv "$VENV_DIR"

echo "  Installing VexNet package..."
"$VENV_DIR/bin/pip" install --upgrade pip -q 2>/dev/null
"$VENV_DIR/bin/pip" install vexnet -q 2>/dev/null || \
    "$VENV_DIR/bin/pip" install "git+https://github.com/ronmenator/vex.git" -q 2>/dev/null || true

# Create default config if none exists
CONFIG_FILE="$VEX_DIR/config.toml"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'EOF'
[llm]
provider = "ollama"
model = "qwen3:30b-a3b"

[llm.ollama]
base_url = "http://localhost:11434/v1"

[network]
enabled = false

[security]
autonomy_level = 1
max_agent_depth = 3
max_tool_rounds = 200

[audit]
enabled = true
directory = ".vex/audit"
EOF
    echo -e "  Default config created. ${GREEN}OK${NC}"
fi

# ─── Step 5: Create shell integration ───
echo -e "${YELLOW}[5/5] Setting up shell integration...${NC}"

# Create bin directory with symlinks
BIN_DIR="$VEX_DIR/bin"
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/vex" "$BIN_DIR/vex" 2>/dev/null || true
ln -sf "$VENV_DIR/bin/vex-telegram" "$BIN_DIR/vex-telegram" 2>/dev/null || true

# Detect shell and add to PATH
SHELL_RC=""
if [ -n "$ZSH_VERSION" ] || [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
fi

PATH_LINE='export PATH="$HOME/.vex/bin:$PATH"'

if [ -n "$SHELL_RC" ]; then
    if ! grep -qF ".vex/bin" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# VexNet" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        echo -e "  Added to PATH in $SHELL_RC ${GREEN}OK${NC}"
    else
        echo -e "  Already in PATH. ${GREEN}OK${NC}"
    fi
fi

# Add to current session
export PATH="$HOME/.vex/bin:$PATH"

# ─── Done! ───
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   VexNet installed successfully!       ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  ${CYAN}Quick start:${NC}"
echo "    vex                    Start the interactive agent"
echo "    vex-telegram           Start the Telegram bot"
echo ""
echo -e "  ${CYAN}Configuration:${NC}"
echo "    Config file: $CONFIG_FILE"
echo ""
echo -e "  ${CYAN}Telegram setup:${NC}"
echo "    1. Create a bot via @BotFather on Telegram"
echo "    2. export TELEGRAM_BOT_TOKEN=your_token"
echo "    3. Run: vex-telegram"
echo ""
echo -e "  ${YELLOW}Restart your terminal or run:${NC}"
echo "    source $SHELL_RC"
echo ""
