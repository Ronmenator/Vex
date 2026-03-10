# ⚡ Vex - Ultimate AI, AGI Reborn 🧠

Your powerful Telegram bot for managing kanban boards with intelligent task assistance.

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Credentials

**Get your Telegram Bot Token:**
- Talk to [@BotFather](https://t.me/BotFather) on Telegram
- Create a new bot and get your API token

**Get your Kanban Board API credentials:**
- Get your API key from your kanban board (check `kanban_client.py` for default endpoints)

### 3. Set Environment Variables

Create a `.env` file in the workspace:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
KANBAN_API_KEY=your_kanban_api_key
KANBAN_BASE_URL=https://your-dashboard-api.vercel.app
```

### 4. Run the Bot

```bash
python telegram_bot.py
```

## 📖 Features

### Kanban Board Management
- ✅ Create and manage lists
- ✅ Add cards to lists
- ✅ Add comments to cards
- ✅ Upload attachments
- ✅ Get board overview

### Built-in Features
- ✅ Interactive menu system
- ✅ Help guide
- ✅ Conversation handlers
- ✅ Error handling

## 🎮 Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/menu` | Main menu |
| `/help` | Help guide |

## 🤖 Usage

After starting the bot, use the interactive menus or commands:

1. `/start` - Initialize the bot
2. `/menu` - See all available options
3. `/help` - Get help information
4. Navigate through menu buttons to perform actions

## 📁 Project Structure

```
workspace/
├── telegram_bot.py        # Main bot implementation
├── kanban_client.py        # Kanban API client
├── telegram_bot_config.py  # Bot configuration
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## 🧠 Vex's Capabilities

- **AI-Powered**: Intelligent interactions and task management
- **AGI-Ready**: Built on robust architecture for future expansion
- **Adaptive**: Learns from interactions and improves over time
- **Comprehensive**: Full kanban board integration

## 🔧 Development

All development happens under the `workspace` directory. The modular design allows for easy feature additions.

## 🎯 Future Plans

- Voice commands (STT/NLP integration)
- Natural language task creation
- Board analytics and insights
- Team collaboration features
- Custom integrations

---

**Ready to experience the future of task management!** 🚀