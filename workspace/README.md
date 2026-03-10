# 🤖 Vex Agent System
**Vex, Ultimate AI, AGI Reborn** - Unified agent with dual input sources

## 🎯 What is Vex?

Vex is a multi-modal AI agent that can receive and process messages through:
- **Direct console input** - Type commands directly in your terminal
- **Telegram integration** - Messages delivered to @vex_agi_reborn
- **Kanban board API** - Full board management capabilities

## 📦 Architecture

```
workspace/
├── agent_system.py        # Main entry point
├── telegram_agent.py      # Telegram integration
├── main_loop_agent.py     # Message processing core
├── telegram_bot_config.py # Configuration
├── kanban_client.py       # Kanban API client
└── start_vex.py           # Quick start script
```

## 🚀 Installation

```bash
cd workspace
pip install -r requirements.txt
```

## ⚙️ Configuration

Create `.env` file:

```env
TELEGRAM_TOKEN=your_token_here  # Get from @BotFather on Telegram
KANBAN_API_KEY=your_api_key      # From your kanban board
KANBAN_BASE_URL=https://...
BOT_USERNAME=vex_agi_reborn
BOT_NAME=Vex
```

**Get your Telegram token:**
1. Open Telegram
2. Message @BotFather
3. Send `/newbot`
4. Follow instructions

## 🎮 Usage

### Option 1: Quick Start
```bash
python workspace/start_vex.py
```

### Option 2: Main System
```bash
cd workspace
python agent_system.py
```

### Option 3: Terminal Input
```bash
cd workspace
python telegram_bot.py
```

## 💬 Available Commands

### Telegram / Console
- `/help` - Show help
- `/status` - Check agent status
- `/clear` - Clear conversation
- `/kill` - Stop agent

### Kanban Board
- `create_list <name>` - Create new list
- `get_board` - Get board info
- `create_card <list_id> <text>` - Create card
- `get_lists` - List all lists
- `get_cards <list_id>` - List cards

### Advanced Kanban
- `add_comment <card_id> <text>`
- `add_attachment <card_id> <url>`
- `create_task <text>` - Create task card
- `add_to_do <text>` - Add to-do

## 🎯 Usage Examples

### Telegram
Send to @vex_agi_reborn:
```
/help
/status
create_list "My Tasks"
get_board
create_task "Write documentation"
```

### Console
```bash
python agent_system.py

# Then type:
/status
clear
create_list "Development"
```

## 🔌 How Integration Works

1. **Telegram Agent** - Listens for incoming Telegram messages
2. **Message Queue** - Messages enter shared command queue
3. **Main Agent Loop** - Processes unified across all sources
4. **Response** - Same response sent back to original source

## 🛡️ Security

- API keys stored in `.env` (keep private!)
- Never commit `.env` to version control
- Token only used for authenticated connections

## 📊 System Status

When running, you'll see:
```
🚀 Starting Vex System...
✅ Telegram agent started on @vex_agi_reborn
🎯 Both direct input and Telegram are active
⏳ Maintaining agent loop...
```

## 🐛 Troubleshooting

**"TELEGRAM_TOKEN not configured"**
- Create `.env` with `TELEGRAM_TOKEN`

**Agent not responding**
- Check token validity with @BotFather
- Verify token is in `.env`

**Kanban operations fail**
- Check `KANBAN_API_KEY` is valid
- Verify `KANBAN_BASE_URL` is correct

## 🌟 Feature Matrix

| Feature | Status |
|---------|--------|
| Direct Console Input | ✅ |
| Telegram Integration | ✅ |
| Kanban Board API | ✅ |
| Message Queue | ✅ |
| Dual Input Sources | ✅ |
| Status Commands | ✅ |
| Task Management | ✅ |
| Comment Systems | ✅ |

## 🎛️ Customization

Edit `telegram_bot_config.py`:
```python
BOT_NAME = "Vex"           # Your bot name
BOT_USERNAME = "vex_bot"  # Your Telegram username
ENABLE_KANBAN = True
ENABLE_KNOWLEDGE = False
```

## 📝 License

For personal/development use. Update as needed for your use case.

---

**Status:** 🟢 Online and Active | **Version:** 1.0.0 | **Build:** AGI-Reborn