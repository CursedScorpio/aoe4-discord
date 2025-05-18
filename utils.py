import discord
import aiohttp
import logging
from config import *

logger = logging.getLogger('AOE4RankBot')

def format_rank_display(rank_level: str) -> str:
    """Format rank level for display"""
    return RANK_DISPLAY.get(rank_level.lower(), rank_level.capitalize())

def get_base_rank(rank_level: str) -> str:
    """Get the base rank from a rank level (e.g. 'gold_2' -> 'gold')"""
    return rank_level.split('_')[0].lower()

async def update_player_role(guild, user_id, new_rank_level, old_rank_level=None):
    """Update a player's rank role"""
    member = guild.get_member(user_id)
    if not member:
        return False

    # Remove old rank role if it exists
    if old_rank_level:
        old_base_rank = get_base_rank(old_rank_level)
        old_role_id = RANK_ROLES.get(old_base_rank)
        if old_role_id:
            old_role = guild.get_role(old_role_id)
            if old_role and old_role in member.roles:
                await member.remove_roles(old_role)

    # Add new rank role
    new_base_rank = get_base_rank(new_rank_level)
    new_role_id = RANK_ROLES.get(new_base_rank)
    if new_role_id:
        new_role = guild.get_role(new_role_id)
        if new_role and new_role not in member.roles:
            await member.add_roles(new_role)
            return True
    return False

async def fetch_player_data(ingame_id):
    """Fetch player data from aoe4world.com API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}{ingame_id}.json") as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"Failed to fetch data for {ingame_id}: HTTP {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error fetching player data: {e}")
        return None