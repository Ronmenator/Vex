"""
Telegram Bot for Vex - Ultimate AI, AGI Reborn
Main bot implementation file
"""
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    ParseMode, InputFile
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, ConversationHandler
)
from kanban_client import KanbanClient

# Import configuration
import telegram_bot_config as config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
kanban_client = None

class VexBot:
    """Main Vex Bot class"""
    
    def __init__(self):
        """Initialize the bot"""
        self.updater = None
        if config.TELEGRAM_TOKEN:
            self.updater = Updater(config.TELEGRAM_TOKEN, use_context=True)
            self.dispatcher = self.updater.dispatcher
            self._setup_handlers()
            self.updater.start_polling()
            logger.info(f"🤖 {config.BOT_NAME} is running as @{config.BOT_USERNAME}")
        else:
            logger.warning("⚠️ TELEGRAM_TOKEN not found - bot starting in demo mode")
    
    def _setup_handlers(self):
        """Setup all message handlers"""
        # Command handlers
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("menu", self.menu_command))
        
        # Conversation handlers for multi-step operations
        self.dispatcher.add_handler(ConversationHandler(
            entry_points=[CallbackQueryHandler(self.kanban_menu, pattern='^kanban:')],
            states={
                'CREATE_LIST': [(CallbackQueryHandler(self.create_list_step, pattern='^create_list:')],),
                'CREATE_CARD': [(CallbackQueryHandler(self.create_card_step, pattern='^create_card:')],),
            },
            fallbacks=[],
        ))
        
        # Message handlers
        self.dispatcher.add_handler(MessageHandler(
            Filters.text & ~Filters.command, 
            self.handle_message
        ))
    
    def start_command(self, update, context):
        """Handle /start command"""
        welcome_text = f"""
# ⚡ Vex - Ultimate AI, AGI Reborn

**I'm here to help you manage your kanban boards efficiently!**

Type /menu to see available commands
"""
        keyboard = [
            [InlineKeyboardButton("📋 Kanban Commands", callback_data='kanban:')],
            [InlineKeyboardButton("❓ Help", callback_data='help:')],
            [InlineKeyboardButton("🚀 Start New Task", callback_data='create_task:')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
        update.message.reply_text("Main menu:", reply_markup=reply_markup)
    
    def help_command(self, update, context):
        """Handle /help command"""
        help_text = f"""
# 📖 {config.BOT_NAME} - Help Guide

## Available Commands:
/start - Welcome message
/menu - Main menu
/help - This help guide

## Kanban Features:
Create Lists
Add Cards
Add Comments
Upload Attachments
View Board Status

Type /menu to get started!
"""
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    def menu_command(self, update, context):
        """Handle /menu command"""
        keyboard = [
            [InlineKeyboardButton("📋 Board Operations", callback_data='kanban:')],
            [InlineKeyboardButton("❓ Ask Vex", callback_data='ask:')],
            [InlineKeyboardButton("✨ Start Task", callback_data='create_task:')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text("Main menu:", reply_markup=reply_markup)
    
    def kanban_menu(self, update, context):
        """Handle kanban menu callback"""
        keyboard = [
            [InlineKeyboardButton("➕ Create List", callback_data='create_list:')],
            [InlineKeyboardButton("📝 Add Card", callback_data='create_card:')],
            [InlineKeyboardButton("🔄 Get Board", callback_data='get_board:')],
            [InlineKeyboardButton("← Back", callback_data='menu:')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.callback_query.edit_message_text(
            text="📋 Kanban Board Operations",
            reply_markup=reply_markup
        )
    
    def create_list_step(self, update, context):
        """Step 1 of creating a new list"""
        update.callback_query.edit_message_text(
            "📝 Creating a new list...",
            reply_markup=None
        )
        context.bot.send_message(
            chat_id=update.callback_query.message.chat_id,
            text="Please type the name of your new list:"
        )
        return 'WAITING_FOR_LIST_NAME'
    
    def waiting_for_list_name(self, update, context):
        """Wait for list name and create the list"""
        list_name = update.message.text.strip()
        
        try:
            # Initialize kanban client if not already done
            global kanban_client
            if not kanban_client:
                kanban_client = KanbanClient(
                    api_key=os.getenv('KANBAN_API_KEY', ''),
                    base_url=os.getenv('KANBAN_BASE_URL', '')
                )
            
            # Create the list
            result = kanban_client.create_list(list_name)
            
            update.message.reply_text(
                f"✅ List '{list_name}' created successfully!"
            )
            return ConversationHandler.END
        except Exception as e:
            update.message.reply_text(f"❌ Error creating list: {str(e)}")
            return ConversationHandler.END
    
    def handle_message(self, update, context):
        """Handle incoming text messages"""
        text = update.message.text.strip().lower()
        
        # Simple command parsing
        if text.startswith('/'):
            update.message.reply_text("Use /menu to see available commands")
        else:
            update.message.reply_text(
                f"Echo (for testing): {update.message.text}\n"
                f"Ask Vex about how to use me!"
            )

if __name__ == '__main__':
    bot = VexBot()
    print(f"🧠 {config.BOT_NAME} is ready to assist!")