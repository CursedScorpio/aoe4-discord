import sqlite3
import logging
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger('AOE4RankBot')

class AOE4Database:
    def __init__(self, db_path='players.db'):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.init_db()
    
    def init_db(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            
            # Player table
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                discord_id INTEGER,
                ingame_id TEXT UNIQUE,
                ingame_name TEXT,
                rank_level TEXT,
                solo_rank INTEGER,
                team_rank INTEGER,
                is_main BOOLEAN DEFAULT 1,
                PRIMARY KEY (discord_id, ingame_id)
            )
            """)
            
            # Bot state table
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)
            
            # News table
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS aoe4_news (
                post_id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                date TEXT,
                category TEXT,
                content_type TEXT,
                is_patch BOOLEAN,
                message_id TEXT,
                url_hash TEXT,
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            self.conn.commit()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def update_news_table_schema(self):
        """Add columns to news table if they don't exist"""
        try:
            # Check if url_hash column exists
            try:
                self.cursor.execute("SELECT url_hash FROM aoe4_news LIMIT 1")
            except sqlite3.OperationalError:
                self.cursor.execute("ALTER TABLE aoe4_news ADD COLUMN url_hash TEXT")
                
            # Check if message_id column exists
            try:
                self.cursor.execute("SELECT message_id FROM aoe4_news LIMIT 1")
            except sqlite3.OperationalError:
                self.cursor.execute("ALTER TABLE aoe4_news ADD COLUMN message_id TEXT")
                
            self.conn.commit()
            logger.info("News table schema updated to include message_id and url_hash")
        except Exception as e:
            logger.error(f"Error updating news table schema: {e}")
    
    def get_bot_state(self) -> Dict[str, Any]:
        """Get all bot state values"""
        state = {}
        try:
            self.cursor.execute("SELECT key, value FROM bot_state")
            for key, value in self.cursor.fetchall():
                if key == 'leaderboard_message_id' or key == 'active_players_message_id':
                    state[key] = int(value) if value else None
                else:
                    state[key] = value
            return state
        except Exception as e:
            logger.error(f"Error getting bot state: {e}")
            return {}
    
    def save_bot_state(self, key: str, value: str):
        """Save a bot state value"""
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                (key, value)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error saving bot state: {e}")
    
    def execute(self, query: str, params: tuple = ()):
        """Execute a SQL query"""
        try:
            return self.cursor.execute(query, params)
        except Exception as e:
            logger.error(f"Database error executing query: {e}")
            logger.error(f"Query: {query}, Params: {params}")
            # Reconnect and retry
            self.close()
            self.init_db()
            return self.cursor.execute(query, params)
    
    def query(self, query: str, params: tuple = ()) -> List[tuple]:
        """Execute a query and fetch all results"""
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Database error querying: {e}")
            logger.error(f"Query: {query}, Params: {params}")
            # Reconnect and retry
            self.close()
            self.init_db()
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
    
    def query_one(self, query: str, params: tuple = ()) -> Optional[tuple]:
        """Execute a query and fetch one result"""
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"Database error querying one: {e}")
            logger.error(f"Query: {query}, Params: {params}")
            # Reconnect and retry
            self.close()
            self.init_db()
            self.cursor.execute(query, params)
            return self.cursor.fetchone()
    
    def commit(self):
        """Commit changes to the database"""
        try:
            self.conn.commit()
        except Exception as e:
            logger.error(f"Database error committing: {e}")
            # Reconnect and retry
            self.close()
            self.init_db()
    
    def close(self):
        """Close the database connection"""
        try:
            if self.conn:
                self.conn.close()
        except Exception as e:
            logger.error(f"Error closing database: {e}")