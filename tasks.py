import discord
from discord.ext import tasks
import logging
from datetime import datetime, timezone, timedelta
import asyncio

from config import *
from utils import format_rank_display, get_base_rank, update_player_role, fetch_player_data

logger = logging.getLogger('AOE4RankBot')

player_activity_cache = {}
game_id_cache = set()

@tasks.loop(hours=24)
async def update_all_players(bot):
    channel = bot.get_channel(RANK_CHANNEL_ID)
    leaderboard_channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    
    if not channel or not leaderboard_channel:
        logger.error("Required channels not found")
        return

    solo_embed, team_embed = await update_leaderboards(bot, channel)

    try:
        if bot.leaderboard_message_id:
            try:
                message = await leaderboard_channel.fetch_message(bot.leaderboard_message_id)
                await message.edit(embeds=[solo_embed, team_embed])
            except discord.NotFound:
                message = await leaderboard_channel.send(embeds=[solo_embed, team_embed])
                bot.leaderboard_message_id = message.id
        else:
            message = await leaderboard_channel.send(embeds=[solo_embed, team_embed])
            bot.leaderboard_message_id = message.id
        
        bot.save_state()
        logger.info("Completed 24-hour player data update")
    except Exception as e:
        logger.error(f"Error updating leaderboard: {e}")

@tasks.loop(seconds=30)
async def update_active_players_status(bot):
    channel = bot.get_channel(ACTIVE_PLAYERS_CHANNEL_ID)
    if not channel:
        logger.error("Active players channel not found")
        return

    try:
        embed = await update_active_players(bot, channel)
        if not isinstance(embed, discord.Embed):
            logger.error(f"Invalid embed type returned: {type(embed)}")
            return

        try:
            if bot.active_players_message_id:
                try:
                    message = await channel.fetch_message(bot.active_players_message_id)
                    await message.edit(embed=embed)
                except discord.NotFound:
                    message = await channel.send(embed=embed)
                    bot.active_players_message_id = message.id
            else:
                message = await channel.send(embed=embed)
                bot.active_players_message_id = message.id
            
            bot.save_state()
        except Exception as e:
            logger.error(f"Error sending/editing message: {e}")

    except Exception as e:
        logger.error(f"Error updating active players status: {e}", exc_info=True)

@tasks.loop(hours=4)
async def check_aoe4_news(bot):
    logger.info("Checking for new Age of Empires IV news...")
    
    from news import fetch_aoe4_news, post_aoe4_news
    
    try:
        # First check for patch notes
        patch_articles = await fetch_aoe4_news(news_type="patch")
        # Then check for announcements
        announcement_articles = await fetch_aoe4_news(news_type="announcement")
        
        # Combine and deduplicate articles by URL hash
        seen_urls = set()
        articles = []
        
        # Process patch notes first (they take priority)
        if patch_articles:
            for article in patch_articles[:2]:  # At most 2 patches
                url_hash = article.get('url_hash')
                if url_hash not in seen_urls:
                    seen_urls.add(url_hash)
                    articles.append(article)
                    
        # Then process announcements
        if announcement_articles:
            for article in announcement_articles[:2]:  # At most 2 announcements
                url_hash = article.get('url_hash')
                if url_hash not in seen_urls:
                    seen_urls.add(url_hash)
                    articles.append(article)
            
        if not articles:
            logger.info("No AOE4 news found or error occurred")
            return
        
        posted_count = 0
        max_to_post = 3  # Limit to avoid spam if many new articles are found
        
        for article in articles[:max_to_post]:  # Only try the most recent articles
            posted = await post_aoe4_news(bot, article)
            if posted:
                posted_count += 1
                await asyncio.sleep(2)  # Small delay between posts to avoid rate limits
                
        if posted_count > 0:
            logger.info(f"Posted {posted_count} new AOE4 news items")
        else:
            logger.info("No new AOE4 news to post")
    except Exception as e:
        logger.error(f"Error checking for AOE4 news: {e}", exc_info=True)

@tasks.loop(hours=12)
async def cleanup_deleted_news(bot):
    """Check if news posts have been deleted from Discord and update database accordingly"""
    logger.info("Checking for deleted news posts...")
    
    # Get all news posts with saved message IDs
    posts = bot.db.query("SELECT post_id, message_id FROM aoe4_news WHERE message_id IS NOT NULL")
    
    if not posts:
        return
        
    channel = bot.get_channel(PATCH_NOTES_CHANNEL_ID)
    if not channel:
        logger.error("News channel not found during cleanup")
        return
        
    deleted_count = 0
    
    for post_id, message_id in posts:
        try:
            # Try to fetch the message
            await channel.fetch_message(int(message_id))
            # If we get here, message still exists
        except discord.NotFound:
            # Message was deleted
            logger.info(f"News post {post_id} message was deleted, removing from database")
            bot.db.execute("DELETE FROM aoe4_news WHERE post_id = ?", (post_id,))
            deleted_count += 1
        except Exception as e:
            logger.error(f"Error checking message {message_id}: {e}")
            
    if deleted_count > 0:
        bot.db.commit()
        logger.info(f"Removed {deleted_count} deleted news posts from database")

async def create_embed(title="🎮 Live Game Tracker", description="Updates every 30 seconds"):
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )

async def update_active_players(bot, channel):
    main_embed = await create_embed()
    field_count = 0

    players = bot.db.query("SELECT discord_id, ingame_id, ingame_name, is_main FROM players")
    
    current_time = datetime.now(timezone.utc)
    active_players = []
    active_player_ids = set()
    current_game_ids = set()
    recent_games_grouped = {}
    games_grouped = {}

    import aiohttp
    
    async with aiohttp.ClientSession() as session:
        for discord_id, ingame_id, ingame_name, is_main in players:
            # Check if user is still in the guild
            member = channel.guild.get_member(discord_id)
            if not member:
                continue  # Skip users who have left the server

            try:
                logger.info(f"Fetching games for {ingame_name} (ID: {ingame_id})")
                async with session.get(f'https://aoe4world.com/api/v0/games?profile_ids={ingame_id}') as response:
                    if response.status == 200:
                        data = await response.json()
                        games = data.get("games", [])
                        
                        discord_mention = member.mention
                        
                        if games:
                            current_game = games[0]
                            game_id = current_game.get('game_id')
                            
                            # Find player's team and civilization
                            player_civ = None
                            player_result = None
                            player_team = None
                            for team_idx, team in enumerate(current_game.get('teams', [])):
                                for player in team:
                                    player_data = player.get('player', {})
                                    if str(player_data.get('profile_id')) == str(ingame_id):
                                        player_civ = player_data.get('civilization')
                                        player_result = player_data.get('result')
                                        player_team = team_idx
                                        break
                                if player_civ:
                                    break

                            if current_game.get('ongoing'):
                                current_game_ids.add(game_id)
                                started_at = datetime.fromisoformat(current_game['started_at'].replace('Z', '+00:00'))
                                game_duration = int((current_time - started_at).total_seconds())
                                
                                active_players.append({
                                    'name': ingame_name,
                                    'discord_mention': discord_mention,
                                    'is_main': is_main,
                                    'game_type': current_game.get('kind', 'Unknown'),
                                    'map': current_game.get('map', 'Unknown Map'),
                                    'duration': game_duration,
                                    'civ': player_civ,
                                    'game_id': game_id,
                                    'team': player_team
                                })
                                
                            elif not current_game.get('ongoing'):
                                finished_time = datetime.fromisoformat(current_game['updated_at'].replace('Z', '+00:00'))
                                if (current_time - finished_time <= timedelta(minutes=15) and 
                                    game_id not in current_game_ids):
                                    
                                    if game_id not in recent_games_grouped:
                                        recent_games_grouped[game_id] = {
                                            'finish_time': finished_time,
                                            'players': [],
                                            'game_type': current_game.get('kind', 'Unknown'),
                                            'map': current_game.get('map', 'Unknown Map')
                                        }
                                    
                                    recent_games_grouped[game_id]['players'].append({
                                        'name': ingame_name,
                                        'discord_mention': discord_mention,
                                        'is_main': is_main,
                                        'result': player_result,
                                        'civ': player_civ,
                                        'team': player_team
                                    })

            except Exception as e:
                logger.error(f"Error fetching games for {ingame_id}: {e}")
                continue

    if active_players:
        for player in active_players:
            game_id = player['game_id']
            if game_id not in games_grouped:
                games_grouped[game_id] = []
            games_grouped[game_id].append(player)

        live_games_text = ""
        for game_id, game_players in games_grouped.items():
            if field_count >= 24:
                break

            game_players.sort(key=lambda x: (x['team'] if x['team'] is not None else -1))
            
            player = game_players[0]
            duration = timedelta(seconds=player['duration'])
            duration_str = f"{int(duration.total_seconds() // 60)}min"
            game_mode = GAME_MODES.get(player['game_type'], player['game_type'])
            
            if len(game_players) > 1:
                live_games_text += f"**🎮 {game_mode} on {player['map']}** (`{duration_str}`)\n"
            
            current_team = None
            for p in game_players:
                account_type = "『Main』" if p['is_main'] else "『Smurf』"
                civ_emoji = CIV_FLAGS.get(p['civ'], "❓")
                
                if len(game_players) > 1 and p['team'] != current_team:
                    current_team = p['team']
                    live_games_text += f"**Team {current_team + 1}**\n"
                
                if len(game_players) > 1:
                    live_games_text += f"└ **{p['name']}** {account_type} • {p['discord_mention']} • Civ: {civ_emoji}\n"
                else:
                    live_games_text += (
                        f"**{p['name']}** {account_type}\n"
                        f"└ {p['discord_mention']} • `{game_mode}`\n"
                        f"└ Map: `{p['map']}` • Time: `{duration_str}` • Civ: {civ_emoji}\n"
                    )
            
            live_games_text += "\n"
            field_count += 1

        if live_games_text:
            main_embed.add_field(name="🟢 Live Games", value=live_games_text, inline=False)

    # Add recently finished games
    if recent_games_grouped:
        recent_text = ""
        sorted_recent = sorted(
            recent_games_grouped.items(),
            key=lambda x: x[1]['finish_time'],
            reverse=True
        )
        
        for game_id, game_data in sorted_recent[:5]:
            if field_count >= 24:
                break
                
            minutes_ago = int((current_time - game_data['finish_time']).total_seconds() / 60)
            game_mode = GAME_MODES.get(game_data['game_type'], game_data['game_type'])
            
            game_data['players'].sort(key=lambda x: (x['team'] if x['team'] is not None else -1))
            
            if len(game_data['players']) > 1:
                recent_text += f"**🎮 {game_mode} on {game_data['map']}** (`{minutes_ago}min ago`)\n"
            
            current_team = None
            for player in game_data['players']:
                account_type = "『Main』" if player['is_main'] else "『Smurf』"
                result_emoji = "🏆" if player['result'] == 'win' else "❌" if player['result'] == 'loss' else "❓"
                civ_emoji = CIV_FLAGS.get(player['civ'], "❓")
                
                if len(game_data['players']) > 1 and player['team'] != current_team:
                    current_team = player['team']
                    recent_text += f"**Team {current_team + 1}**\n"
                
                if len(game_data['players']) > 1:
                    recent_text += f"└ **{player['name']}** {account_type} • {player['discord_mention']} • {result_emoji} • Civ: {civ_emoji}\n"
                else:
                    recent_text += (
                        f"**{player['name']}** {account_type}\n"
                        f"└ {player['discord_mention']} • `{game_mode}`\n"
                        f"└ Map: `{game_data['map']}` • {result_emoji} • `{minutes_ago}min ago` • Civ: {civ_emoji}\n"
                    )
            
            recent_text += "\n"
            field_count += 1
        
        if recent_text:
            main_embed.add_field(name="🟡 Recently Finished", value=recent_text, inline=False)

    if not active_players and not recent_games_grouped:
        main_embed.description = "😴 No players currently active"

    total_tracked = len(games_grouped) + len(recent_games_grouped)
    main_embed.set_footer(text=f"Tracking {total_tracked} active games • Last updated")

    return main_embed

async def update_leaderboards(bot, channel, forced_update=False, trigger_user=None):
    timestamp = datetime.now(timezone.utc) + timedelta(hours=1)
    
    if forced_update and trigger_user:
        timestamp_text = f"Manually updated by {trigger_user.display_name} at {timestamp:%Y-%m-%d %H:%M:%S} GMT+1"
    else:
        timestamp_text = f"Automatically updated at {timestamp:%Y-%m-%d %H:%M:%S} GMT+1"

    solo_embed = discord.Embed(
        title="🎮 AOE4 Solo Leaderboard",
        description=timestamp_text,
        color=discord.Color.blue(),
        timestamp=timestamp
    )
    
    team_embed = discord.Embed(
        title="👥 AOE4 Team Leaderboard",
        description=timestamp_text,
        color=discord.Color.green(),
        timestamp=timestamp
    )

    players = bot.db.query("SELECT discord_id, ingame_id, rank_level, is_main FROM players")
    
    solo_data = []
    team_data = []
    role_updates = []

    for discord_id, ingame_id, old_rank_level, is_main in players:
        # Check if user is still in the guild
        member = channel.guild.get_member(discord_id)
        if not member:
            continue  # Skip users who have left the server
            
        data = await fetch_player_data(ingame_id)
        if not data:
            continue

        user_mention = member.mention
        
        modes = data.get('modes', {})
        rm_solo = modes.get('rm_solo', {})
        rm_team = modes.get('rm_team', {})
        
        if is_main:
            new_rank_level = rm_team.get('rank_level', 'unranked').lower()
            if new_rank_level != old_rank_level:
                role_updates.append((discord_id, new_rank_level, old_rank_level))
                bot.db.execute("""
                    UPDATE players 
                    SET rank_level = ?
                    WHERE discord_id = ? AND ingame_id = ?
                """, (new_rank_level, discord_id, ingame_id))
                bot.db.commit()
        
        acc_type = "" if is_main else f"(Smurf of {user_mention})"
        
        if rm_solo:
            prev_seasons = rm_solo.get('previous_seasons', [])
            season_info = ""
            if prev_seasons:
                latest_season = prev_seasons[0]
                season_info = f" (S{latest_season['season']}: {format_rank_display(latest_season['rank_level'])})"
            
            solo_data.append({
                'name': f"{data.get('name', '')} {acc_type}",
                'rating': rm_solo.get('rating', 0),
                'rank_level': rm_solo.get('rank_level', 'unranked'),
                'win_rate': rm_solo.get('win_rate', 0),
                'streak': rm_solo.get('streak', 0),
                'rank': rm_solo.get('rank', 0),
                'discord_user': user_mention,
                'season_info': season_info
            })

        if rm_team:
            prev_seasons = rm_team.get('previous_seasons', [])
            season_info = ""
            if prev_seasons:
                latest_season = prev_seasons[0]
                season_info = f" (S{latest_season['season']}: {format_rank_display(latest_season['rank_level'])})"
            
            team_data.append({
                'name': f"{data.get('name', '')} {acc_type}",
                'rating': rm_team.get('rating', 0),
                'rank_level': rm_team.get('rank_level', 'unranked'),
                'win_rate': rm_team.get('win_rate', 0),
                'streak': rm_team.get('streak', 0),
                'rank': rm_team.get('rank', 0),
                'discord_user': user_mention,
                'season_info': season_info
            })

    # Process role updates only for users still in the guild
    for discord_id, new_rank, old_rank in role_updates:
        try:
            role_updated = await update_player_role(channel.guild, discord_id, new_rank, old_rank)
            if role_updated:
                user = channel.guild.get_member(discord_id)
                if user:  # Only log if user is still in the guild
                    log_channel = bot.get_channel(LOG_CHANNEL_ID)
                    if log_channel:
                        await log_channel.send(
                            f"🔄 Rank Update: {user.mention} "
                            f"from `{format_rank_display(old_rank)}` "
                            f"to `{format_rank_display(new_rank)}`"
                        )
        except Exception as e:
            logger.error(f"Error updating role for user {discord_id}: {e}")

    # Sort and format leaderboards
    solo_data.sort(key=lambda x: x['rating'], reverse=True)
    team_data.sort(key=lambda x: x['rating'], reverse=True)

    for embed, data in [(solo_embed, solo_data[:10]), (team_embed, team_data[:10])]:
        leaderboard_text = ""
        for idx, player in enumerate(data, 1):
            streak_symbol = "🔥" if player['streak'] > 2 else "❄️" if player['streak'] < -2 else ""
            leaderboard_text += (
                f"`{idx:2d}.` **{player['name']}** {streak_symbol}\n"
                f"└ Rating: `{player['rating']}` | Global Rank: `#{player['rank']:,}` | "
                f"Rank: `{format_rank_display(player['rank_level'])}` | WR: `{player['win_rate']:.1f}%`{player['season_info']}\n"
                f"└ Discord: {player['discord_user']}\n\n"
            )
        embed.description = leaderboard_text or "No data available"

    return solo_embed, team_embed