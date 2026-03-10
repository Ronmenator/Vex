"""
Vex Agent System - Main Entry Point
Integrates Telegram and direct input into unified agent system
"""
import sys
import os
import time

# Add workspace to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'workspace'))

from telegram_agent import TelegramAgent
from telegram_bot_config import BOT_NAME, TELEGRAM_TOKEN


class VexAgentSystem:
    """Unified agent system with dual input sources"""
    
    def __init__(self):
        self.telegram = None
        self.running = False
        
        if TELEGRAM_TOKEN:
            self.telegram = TelegramAgent()
            print(f"🎬 Telegram agent initialized")
    
    def start(self):
        """Start the agent system"""
        print(f"\n🚀 Starting {BOT_NAME} System...")
        
        if self.telegram and self.telegram.enabled:
            if self.telegram.start():
                print(f"✅ Telegram activated on @{self.telegram.config.get('BOT_USERNAME', '') or BOT_NAME}")
            else:
                print("⚠️ Telegram failed to start")
        
        print("\n🎯 System ready. Both direct input and Telegram are active.")
        self.running = True
        
        return self
        
    def stop(self):
        """Stop the agent system"""
        self.running = False
        if self.telegram:
            self.telegram.stop()
        print("🛑 Agent system stopped")


def main():
    """Main entry point"""
    print(f"🤖 {BOT_NAME} - Ultimate AI, AGI Reborn")
    print("=" * 40)
    
    system = VexAgentSystem().start()
    
    # Keep running
    print("\n⏳ Maintaining agent loop...")
    while system.running:
        time.sleep(1)
        
    system.stop()


if __name__ == "__main__":
    main()