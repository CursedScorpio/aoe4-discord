import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
import logging

from config import *
from database import fetch_player_data
from utils import format_rank_display, update_player_role
from news import fetch_aoe4_news, post_aoe4_news
from tasks import update_leaderboards, update_active_players

logger = logging.getLogger('AOE4RankBot')

def register_commands(bot):
    @bot.tree.command(name="register", description="Register a main or smurf account")
    async def register(interaction: discord.Interaction, user: discord.Member, ingame_id: str, account_type: Literal["main", "smurf"]):
        await interaction.response.defer(ephemeral=False)
        
        try:
            if account_type == "smurf":
                has_main = bot.db.query_one(
                    "SELECT COUNT(*) FROM players WHERE discord_id = ? AND is_main = 1", 
                    (user.id,)
                )
                
                if has_main and has_main[0] <= 0:
                    await interaction.followup.send("User must have a main account before registering smurfs. Register a main account first.", ephemeral=True)
                    return

            data = await fetch_player_data(ingame_id)
            if not data:
                await interaction.followup.send("Invalid in-game ID or data could not be fetched.", ephemeral=True)
                return

            modes = data.get('modes', {})
            rm_team = modes.get('rm_team', {})
            rm_solo = modes.get('rm_solo', {})
            
            rank_level = rm_team.get('rank_level', rm_solo.get('rank_level', 'unranked')).lower()
            team_rank = rm_team.get('rating', 0)
            solo_rank = rm_solo.get('rating', 0)
            ingame_name = data.get('name', ingame_id)

            is_main = account_type == "main"
            
            bot.db.execute("""
                INSERT OR REPLACE INTO players 
                (discord_id, ingame_id, ingame_name, rank_level, solo_rank, team_rank, is_main) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user.id, ingame_id, ingame_name, rank_level, solo_rank, team_rank, is_main))
            bot.db.commit()

            if is_main:
                try:
                    await update_player_role(interaction.guild, user.id, rank_level)
                except discord.Forbidden:
                    logger.warning(f"Bot lacks permission to update roles for user {user.id}")
                except Exception as e:
                    logger.error(f"Error updating role: {e}")

            await interaction.followup.send(
                f"Registered {'main' if is_main else 'smurf'} account for {user.mention} with in-game name `{ingame_name}` (Rank: `{format_rank_display(rank_level)}`).",
                ephemeral=False
            )

        except Exception as e:
            logger.error(f"Registration error: {e}")
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

    @bot.tree.command(name="leaderboard", description="Update the leaderboard")
    async def leaderboard(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        leaderboard_channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            await interaction.followup.send("Leaderboard channel not found!", ephemeral=True)
            return

        try:
            solo_embed, team_embed = await update_leaderboards(
                bot,
                interaction.channel, 
                forced_update=True,
                trigger_user=interaction.user
            )
            
            if bot.leaderboard_message_id:
                try:
                    message = await leaderboard_channel.fetch_message(bot.leaderboard_message_id)
                    await message.edit(embeds=[solo_embed, team_embed])
                    await interaction.followup.send("Leaderboard updated successfully!", ephemeral=True)
                except discord.NotFound:
                    message = await leaderboard_channel.send(embeds=[solo_embed, team_embed])
                    bot.leaderboard_message_id = message.id
                    bot.save_state()
                    await interaction.followup.send("Created new leaderboard message!", ephemeral=True)
            else:
                message = await leaderboard_channel.send(embeds=[solo_embed, team_embed])
                bot.leaderboard_message_id = message.id
                bot.save_state()
                await interaction.followup.send("Created new leaderboard message!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error updating leaderboard: {e}")
            await interaction.followup.send("An error occurred while updating the leaderboard.", ephemeral=True)

    @bot.tree.command(name="stats", description="Show detailed player stats")
    async def player_stats(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=False)

        target_user = user or interaction.user
        
        accounts = bot.db.query(
            "SELECT ingame_id, is_main FROM players WHERE discord_id = ? ORDER BY is_main DESC", 
            (target_user.id,)
        )
        
        if not accounts:
            await interaction.followup.send(f"{target_user.mention} is not registered.", ephemeral=False)
            return

        embeds = []
        total_games = {'solo': 0, 'team': 0}
        total_wins = {'solo': 0, 'team': 0}

        for ingame_id, is_main in accounts:
            data = await fetch_player_data(ingame_id)
            if not data:
                continue

            profile_embed = discord.Embed(
                title=f"🏆 {data['name']}'s Profile {'(Main)' if is_main else '(Smurf)'} - {target_user.display_name}",
                url=data.get('site_url', ''),
                color=discord.Color.blue() if is_main else discord.Color.orange()
            )
            profile_embed.add_field(
                name="Discord User",
                value=target_user.mention,
                inline=True
            )
            if data.get('country'):
                profile_embed.add_field(name="Country", value=f":flag_{data['country'].lower()}:", inline=True)

            solo_data = data.get('modes', {}).get('rm_solo', {})
            if solo_data:
                streak_emoji = "🔥" if solo_data.get('streak', 0) > 2 else "❄️" if solo_data.get('streak', 0) < -2 else "➖"
                total_games['solo'] += solo_data.get('games_count', 0)
                total_wins['solo'] += solo_data.get('wins_count', 0)
                
                profile_embed.add_field(
                    name="🎮 Ranked Solo",
                    value=(
                        f"Rank: `{format_rank_display(solo_data.get('rank_level', 'unranked'))}` (#{solo_data.get('rank', 0):,})\n"
                        f"Rating: `{solo_data.get('rating', 0)}` (Peak: `{solo_data.get('max_rating', 0)}`)\n"
                        f"W/L: `{solo_data.get('wins_count', 0)}/{solo_data.get('losses_count', 0)}` ({solo_data.get('win_rate', 0):.1f}%)\n"
                        f"Streak: `{solo_data.get('streak', 0):+d}` {streak_emoji}"
                    ),
                    inline=False
                )

                civs = solo_data.get('civilizations', [])
                if civs:
                    civs.sort(key=lambda x: x.get('games_count', 0), reverse=True)
                    civ_text = ""
                    for civ in civs[:3]:
                        name = civ['civilization'].replace('_', ' ').title()
                        civ_text += f"`{name}`: {civ.get('games_count', 0)} games, {civ.get('win_rate', 0):.1f}% WR\n"
                    profile_embed.add_field(name="🏰 Top Civilizations", value=civ_text, inline=False)

            team_data = data.get('modes', {}).get('rm_team', {})
            if team_data:
                streak_emoji = "🔥" if team_data.get('streak', 0) > 2 else "❄️" if team_data.get('streak', 0) < -2 else "➖"
                total_games['team'] += team_data.get('games_count', 0)
                total_wins['team'] += team_data.get('wins_count', 0)
                
                profile_embed.add_field(
                    name="👥 Ranked Team",
                    value=(
                        f"Rank: `{format_rank_display(team_data.get('rank_level', 'unranked'))}` (#{team_data.get('rank', 0):,})\n"
                        f"Rating: `{team_data.get('rating', 0)}` (Peak: `{team_data.get('max_rating', 0)}`)\n"
                        f"W/L: `{team_data.get('wins_count', 0)}/{team_data.get('losses_count', 0)}` ({team_data.get('win_rate', 0):.1f}%)\n"
                        f"Streak: `{team_data.get('streak', 0):+d}` {streak_emoji}"
                    ),
                    inline=False
                )

            seasons = solo_data.get('previous_seasons', [])
            if seasons:
                season_text = ""
                for season in seasons[:3]:
                    season_text += (
                        f"S{season['season']}: "
                        f"`{format_rank_display(season.get('rank_level', 'unranked'))}` "
                        f"({season.get('rating', 0)} MMR, {season.get('win_rate', 0):.1f}% WR)\n"
                    )
                profile_embed.add_field(name="📅 Previous Seasons", value=season_text, inline=False)

            embeds.append(profile_embed)

        # Add combined stats if user has multiple accounts
        if len(accounts) > 1:
            combined_embed = discord.Embed(
                title=f"📊 Combined Stats for {target_user.display_name}",
                color=discord.Color.purple()
            )
            
            if total_games['solo'] > 0:
                wr_solo = (total_wins['solo'] / total_games['solo']) * 100
                combined_embed.add_field(
                    name="Solo Queue Total",
                    value=f"Games: `{total_games['solo']}` | Wins: `{total_wins['solo']}` | WR: `{wr_solo:.1f}%`",
                    inline=False
                )
                
            if total_games['team'] > 0:
                wr_team = (total_wins['team'] / total_games['team']) * 100
                combined_embed.add_field(
                    name="Team Queue Total",
                    value=f"Games: `{total_games['team']}` | Wins: `{total_wins['team']}` | WR: `{wr_team:.1f}%`",
                    inline=False
                )
                
            embeds.append(combined_embed)

        await interaction.followup.send(embeds=embeds)

    @bot.tree.command(name="delete", description="Delete a player's data")
    async def delete(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        
        has_permission = interaction.user.guild_permissions.manage_roles

        # If no user specified, show a list of all registered players including those who left
        if not user:
            if not has_permission:
                await interaction.followup.send("You can only delete your own data.", ephemeral=True)
                return

            # Fetch all registered players
            players = bot.db.query("SELECT DISTINCT discord_id, ingame_name FROM players")
            
            if not players:
                await interaction.followup.send("No registered players found.", ephemeral=True)
                return

            # Create embed with all players, marking those who left
            embed = discord.Embed(
                title="🗑️ Delete Player Data",
                description="Select a player to delete their data:\n\n",
                color=discord.Color.red()
            )

            for discord_id, ingame_name in players:
                member = interaction.guild.get_member(discord_id)
                status = "❌ Left Server" if not member else "✅ Active"
                embed.add_field(
                    name=f"{ingame_name}",
                    value=f"Status: {status}\nID: {discord_id}",
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If user is specified, handle deletion
        target_id = user.id
        if interaction.user.id != target_id and not has_permission:
            await interaction.followup.send("You can only delete your own data.", ephemeral=True)
            return

        # Delete the user's data
        bot.db.execute("DELETE FROM players WHERE discord_id = ?", (target_id,))
        bot.db.commit()
        
        await interaction.followup.send(f"Successfully deleted data for {user.mention}.", ephemeral=True)

    @bot.tree.command(name="showall", description="Show all registered players")
    async def showall(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
            
        players = bot.db.query("SELECT discord_id, ingame_id, ingame_name, is_main FROM players")
        
        # Create a list to hold all embeds
        embeds = []
        current_embed = discord.Embed(
            title="📋 Registered Players",
            description="List of all registered players:",
            color=discord.Color.blue()
        )
        field_count = 0
        
        # Group players by their discord_id to keep main and smurf accounts together
        players_by_discord = {}
        for discord_id, ingame_id, ingame_name, is_main in players:
            if discord_id not in players_by_discord:
                players_by_discord[discord_id] = []
            players_by_discord[discord_id].append((ingame_id, ingame_name, is_main))
        
        # Create fields for each player
        for discord_id, accounts in players_by_discord.items():
            # If we've hit the field limit, create a new embed
            if field_count >= 25:
                embeds.append(current_embed)
                current_embed = discord.Embed(
                    title="📋 Registered Players (Continued)",
                    description="List of all registered players:",
                    color=discord.Color.blue()
                )
                field_count = 0
            
            member = interaction.guild.get_member(discord_id)
            user_status = "🟢 Active" if member else "🔴 Left Server"
            user_mention = member.mention if member else f"<@{discord_id}>"
            
            # Sort accounts so main account comes first
            accounts.sort(key=lambda x: x[2], reverse=True)
            
            # Create account list text
            account_text = ""
            for ingame_id, ingame_name, is_main in accounts:
                account_type = "『Main』" if is_main else "『Smurf』"
                account_text += f"• `{ingame_name}` {account_type}\n"
            
            # Add field for this user
            current_embed.add_field(
                name=f"{user_mention} ({user_status})",
                value=account_text,
                inline=False
            )
            field_count += 1
        
        # Add the last embed if it has any fields
        if field_count > 0:
            embeds.append(current_embed)
        
        # If no embeds were created (no players found), create one with a message
        if not embeds:
            empty_embed = discord.Embed(
                title="📋 Registered Players",
                description="No players are currently registered.",
                color=discord.Color.blue()
            )
            embeds.append(empty_embed)
        
        # Add page numbers to embed titles if there are multiple pages
        if len(embeds) > 1:
            for i, embed in enumerate(embeds):
                embed.title = f"📋 Registered Players (Page {i+1}/{len(embeds)})"
        
        # Add footer with total count
        total_players = len(players)
        total_accounts = sum(len(accounts) for accounts in players_by_discord.values())
        for embed in embeds:
            embed.set_footer(text=f"Total Players: {total_players} • Total Accounts: {total_accounts}")
        
        # Send all embeds
        await interaction.followup.send(embeds=embeds)

    @bot.tree.command(name="forcenewscheck", description="Force check for new Age of Empires IV news")
    @app_commands.default_permissions(administrator=True)
    async def force_news_check(interaction: discord.Interaction, news_type: Literal["patch", "announcement", "both"] = "both"):
        """Admin command to force check for new AOE4 news"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            await interaction.followup.send(f"Checking for Age of Empires IV {news_type} news... This may take a moment.", ephemeral=True)
            
            articles = []
            if news_type == "both" or news_type == "patch":
                patch_articles = await fetch_aoe4_news(news_type="patch")
                if patch_articles:
                    articles.extend(patch_articles)
                    
            if news_type == "both" or news_type == "announcement":
                announcement_articles = await fetch_aoe4_news(news_type="announcement")
                if announcement_articles:
                    articles.extend(announcement_articles)
            
            if not articles:
                await interaction.followup.send(f"No AOE4 {news_type} news found. The website may have changed structure or there might be connectivity issues.", ephemeral=True)
                return
            
            # Deduplicate by URL to avoid posting the same article twice
            unique_articles = []
            seen_urls = set()
            for article in articles:
                url_hash = article.get('url_hash')
                if url_hash not in seen_urls:
                    seen_urls.add(url_hash)
                    unique_articles.append(article)
                    
            articles = unique_articles
            
            await interaction.followup.send(f"Found {len(articles)} AOE4 news articles. Posting up to 3 most recent ones if they haven't been posted already.", ephemeral=True)
            
            posted_count = 0
            max_to_post = 3  # Limit to avoid spam
            
            for article in articles[:max_to_post]:
                posted = await post_aoe4_news(bot, article)
                if posted:
                    posted_count += 1
                    await asyncio.sleep(2)  # Small delay between posts
                    
            if posted_count > 0:
                await interaction.followup.send(f"Successfully posted {posted_count} new AOE4 news items.", ephemeral=True)
            else:
                await interaction.followup.send("No new AOE4 news to post. All recent articles have already been posted.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in force news check: {e}", exc_info=True)
            await interaction.followup.send(f"Error checking for AOE4 news: {str(e)}\nCheck server logs for more details.", ephemeral=True)