import discord
from discord.ext import commands, tasks
import logging
import os
import asyncio
from dotenv import load_dotenv

# Import our modules
from config import *
from database import AOE4Database
from commands import register_commands
from tasks import (
    update_all_players,
    update_active_players_status,
    check_aoe4_news,
    cleanup_deleted_news
)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger('AOE4RankBot')

# Load environment variables
load_dotenv()

class AOE4RankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=get_intents())
        self.leaderboard_message_id = None
        self.active_players_message_id = None
        self.db = AOE4Database()
        self.load_state()

    def load_state(self):
        state = self.db.get_bot_state()
        self.leaderboard_message_id = state.get('leaderboard_message_id')
        self.active_players_message_id = state.get('active_players_message_id')

    def save_state(self):
        if self.leaderboard_message_id:
            self.db.save_bot_state('leaderboard_message_id', str(self.leaderboard_message_id))
        if self.active_players_message_id:
            self.db.save_bot_state('active_players_message_id', str(self.active_players_message_id))

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Slash commands synced")

    async def close(self):
        self.save_state()
        self.db.close()
        await super().close()

def get_intents():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    return intents

async def on_message_delete(bot, message):
    if message.channel.id != PATCH_NOTES_CHANNEL_ID:
        return
        
    # Check if this was a news post
    post = bot.db.query_one("SELECT post_id FROM aoe4_news WHERE message_id = ?", (str(message.id),))
    
    if post:
        post_id = post[0]
        logger.info(f"News post {post_id} message was deleted, removing from database")
        bot.db.execute("DELETE FROM aoe4_news WHERE post_id = ?", (post_id,))
        bot.db.commit()

async def on_ready(bot):
    logger.info(f"Bot logged in as {bot.user}")
    
    # Make sure the database is properly initialized
    bot.db.update_news_table_schema()
    
    # Start background tasks
    update_all_players.start(bot)
    update_active_players_status.start(bot)
    check_aoe4_news.start(bot)
    cleanup_deleted_news.start(bot)
    
    # Check for latest news on startup
    logger.info("Checking for latest AOE4 news on startup...")
    try:
        from news import fetch_aoe4_news, post_aoe4_news
        
        # Check for latest patch, then latest announcement
        patch_articles = await fetch_aoe4_news(news_type="patch")
        if patch_articles and len(patch_articles) > 0:
            latest_patch = patch_articles[0]
            
            # Check if already posted
            url_hash = latest_patch.get('url_hash')
            existing = None
            
            if url_hash:
                existing = bot.db.query_one(
                    "SELECT post_id FROM aoe4_news WHERE url_hash = ?", 
                    (url_hash,)
                )
            
            if not existing:
                success = await post_aoe4_news(bot, latest_patch)
                if success:
                    logger.info(f"Posted latest AOE4 patch on startup: {latest_patch['title']}")
                    return
        
        # If no patch was posted, try with announcement
        announcement_articles = await fetch_aoe4_news(news_type="announcement")
        if announcement_articles and len(announcement_articles) > 0:
            latest_announcement = announcement_articles[0]
            
            # Check if already posted
            url_hash = latest_announcement.get('url_hash')
            existing = None
            
            if url_hash:
                existing = bot.db.query_one(
                    "SELECT post_id FROM aoe4_news WHERE url_hash = ?", 
                    (url_hash,)
                )
            
            if not existing:
                success = await post_aoe4_news(bot, latest_announcement)
                if success:
                    logger.info(f"Posted latest AOE4 announcement on startup: {latest_announcement['title']}")
    except Exception as e:
        logger.error(f"Error checking for latest AOE4 news on startup: {e}", exc_info=True)

def main():
    bot = AOE4RankBot()
    
    # Register event handlers
    @bot.event
    async def on_ready():
        await on_ready(bot)
    
    @bot.event
    async def on_message_delete(message):
        await on_message_delete(bot, message)
    
    # Register commands
    register_commands(bot)
    
    # Run the bot
    bot_token = os.getenv('DISCORD_TOKEN')
    if not bot_token:
        logger.error("No Discord token found! Set the DISCORD_TOKEN environment variable")
        return
        
    bot.run(bot_token)

if __name__ == "__main__":
    main()