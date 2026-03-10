#!/usr/bin/env python3
"""
Setup Script for Vex - Ultimate AI, AGI Reborn
Handles environment setup and bot initialization
"""
import os
import sys
from pathlib import Path

def main():
    """Main setup function"""
    print("Vex Setup Script")
    print("=" * 40)
    
    # Check environment file
    check_env_file()
    
    # Check API keys
    if check_api_keys():
        print("\nSetup complete! Your bot is ready to run.")
        print("Run: python telegram_bot.py")
    else:
        print("\nPlease configure your API keys in .env file and run setup again")

def check_env_file():
    """Check for .env file and create if missing"""
    env_file = Path(".env")
    if not env_file.exists():
        print("Creating .env file...")
        env_example = Path(".env.example")
        if env_example.exists():
            Path(".env").write_text(env_example.read_text())
            print(".env file created!")
            print("Please edit .env with your credentials")
        else:
            print(".env.example not found, creating default .env...")
            Path(".env").write_text("TELEGRAM_TOKEN=your_token\n")
    else:
        print(".env file exists")

def check_api_keys():
    """Validate API keys are configured"""
    env_vars = ['TELEGRAM_TOKEN', 'KANBAN_API_KEY', 'KANBAN_BASE_URL']
    missing = []
    
    for var in env_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print("Missing API keys:")
        for var in missing:
            print(f"   - {var}")
        return False
    
    print("All API keys configured")
    return True

if __name__ == '__main__':
    main()