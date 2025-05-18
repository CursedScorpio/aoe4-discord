import discord
import aiohttp
import logging
import re
from config import *
from bs4 import BeautifulSoup
import hashlib

logger = logging.getLogger('AOE4RankBot')

# News fetching functions
async def fetch_full_article(url, headers=None):
    """Fetch the complete article HTML content"""
    if not headers:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.text()
                logger.warning(f"Failed to fetch article at {url}: HTTP {response.status}")
                return None
        except Exception as e:
            logger.error(f"Error fetching article at {url}: {e}")
            return None

def extract_article_title(soup):
    """Extract the actual article title from the HTML"""
    # Look for the most specific title elements first
    title_elem = (
        soup.select_one('article h1') or
        soup.select_one('main h1') or
        soup.select_one('.article-title') or
        soup.select_one('.entry-title') or
        soup.select_one('h1')
    )
    
    if title_elem:
        title = title_elem.get_text(strip=True)
        # Remove any unnecessary prefixes
        title = re.sub(r'^(Age of Empires IV:?\s*)', '', title)
        return title
    
    # Fallback to page title
    if soup.title:
        title = soup.title.get_text(strip=True)
        # Clean up page title
        title = re.sub(r'\s*\|\s*Age of Empires.*$', '', title)
        title = re.sub(r'^(Age of Empires IV:?\s*)', '', title)
        return title
        
    return None

def extract_article_date(soup):
    """Extract the publication date from the article"""
    # Try various date elements
    date_elem = (
        soup.select_one('meta[property="article:published_time"]') or
        soup.select_one('.article-date') or
        soup.select_one('.post-date') or
        soup.select_one('time')
    )
    
    if date_elem:
        if date_elem.name == 'meta':
            date_str = date_elem.get('content')
            if date_str:
                try:
                    date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    return date_obj.strftime("%B %d, %Y")
                except:
                    pass
        else:
            return date_elem.get_text(strip=True)
    
    # Try to find date in the text
    date_patterns = [
        r'(\w+ \d{1,2}, 20\d{2})',  # March 10, 2025
        r'(\d{1,2} \w+ 20\d{2})',    # 10 March 2025
        r'(\d{2}/\d{2}/20\d{2})'     # 03/10/2025
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, soup.get_text())
        if match:
            return match.group(1)
    
    return "Unknown date"

def extract_article_author(soup):
    """Extract the author from the article"""
    author_elem = (
        soup.select_one('.author') or
        soup.select_one('.byline') or
        soup.select_one('.post-author') or
        soup.select_one('meta[name="author"]')
    )
    
    if author_elem:
        if author_elem.name == 'meta':
            return author_elem.get('content')
        else:
            author_text = author_elem.get_text(strip=True)
            # Clean up "by Author Name" format
            author_text = re.sub(r'^by\s+', '', author_text, flags=re.IGNORECASE)
            return author_text
    
    return None

def extract_article_content(soup):
    """Extract the main content from the article"""
    # Try to find the main content container
    content_elem = (
        soup.select_one('article .content') or
        soup.select_one('.article-content') or
        soup.select_one('.entry-content') or
        soup.select_one('.post-content') or
        soup.select_one('main')
    )
    
    if not content_elem:
        content_elem = soup
    
    # Extract paragraphs
    paragraphs = content_elem.select('p')
    
    # Filter out navigation, comments, etc.
    filtered_paragraphs = []
    for p in paragraphs:
        # Skip paragraphs in navigation, sidebar, footer, etc.
        if any(p.parent.name == x or p.parent.get('class') and any(c in ' '.join(p.parent.get('class')) for c in x) 
               for x in ['nav', 'menu', 'sidebar', 'footer', 'comment']):
            continue
        
        # Skip empty paragraphs
        if not p.get_text(strip=True):
            continue
            
        # Skip very short paragraphs that might be buttons or navigation
        if len(p.get_text(strip=True)) < 10 and not any(c.name == 'a' for c in p.children):
            continue
            
        filtered_paragraphs.append(p.get_text(strip=True))
    
    # Create full content and preview
    if filtered_paragraphs:
        full_content = '\n\n'.join(filtered_paragraphs)
        
        # Create preview (first few paragraphs)
        preview_paragraphs = []
        preview_length = 0
        for p in filtered_paragraphs:
            preview_paragraphs.append(p)
            preview_length += len(p)
            if preview_length > 800:
                break
                
        preview = '\n\n'.join(preview_paragraphs)
        if len(preview) < len(full_content):
            preview += '\n\n... [Read more on the website]'
            
        return full_content, preview
    
    return None, None

def extract_article_image(soup):
    """Extract the main image from the article"""
    # Try to find header/featured image
    image_elem = (
        soup.select_one('.article-image img') or
        soup.select_one('.featured-image img') or
        soup.select_one('article img') or
        soup.select_one('.post-thumbnail img') or
        soup.select_one('main img')
    )
    
    if image_elem and image_elem.get('src'):
        src = image_elem['src']
        if not src.startswith('http'):
            src = f"https://www.ageofempires.com{src}"
        return src
    
    return None

def extract_article_category(soup):
    """Extract the article category"""
    category_elem = (
        soup.select_one('.category') or
        soup.select_one('.article-category') or
        soup.select_one('.post-category')
    )
    
    if category_elem:
        return category_elem.get_text(strip=True)
    
    # Look for category in breadcrumbs
    breadcrumbs = soup.select('.breadcrumbs a, .breadcrumb a')
    for crumb in breadcrumbs:
        if 'category' in crumb.get('href', ''):
            return crumb.get_text(strip=True)
    
    return "Uncategorized"

async def get_article_details(url, news_type):
    """Fetch and extract full article details"""
    html = await fetch_full_article(url)
    if not html:
        return None
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extract the important article data
    title = extract_article_title(soup)
    date = extract_article_date(soup)
    author = extract_article_author(soup)
    full_content, preview = extract_article_content(soup)
    image_url = extract_article_image(soup)
    category = extract_article_category(soup)
    
    # Generate a unique post ID
    post_id = url.split('/')[-1].split('?')[0]
    if not post_id or post_id == '':
        # Hash the URL for a consistent ID
        post_id = hashlib.md5(url.encode()).hexdigest()
    
    # Generate URL hash for deduplication
    url_hash = hashlib.md5(url.encode()).hexdigest()
    
    article_data = {
        'post_id': post_id,
        'title': title or "Age of Empires IV News",
        'url': url,
        'date': date,
        'author': author,
        'content': full_content,
        'preview': preview,
        'image_url': image_url,
        'category': category,
        'content_type': news_type,
        'is_patch': news_type == "patch",
        'url_hash': url_hash
    }
    
    return article_data

async def get_news_listing(news_type="announcement"):
    """Fetch the news listing page and extract article links"""
    url = PATCH_NOTES_URL if news_type == "patch" else ANNOUNCEMENT_NEWS_URL
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }
    
    try:
        html = await fetch_full_article(url, headers)
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all article cards/links
        articles = []
        
        # Try different selectors for the article cards
        article_elements = (
            soup.select('.article-card, .news-item, article') or
            soup.select('.post, .news-post') or
            soup.select('a[href*="/news/"]')
        )
        
        for article in article_elements:
            # Get the link element
            if article.name == 'a':
                link = article
            else:
                link = article.select_one('a[href*="/news/"]')
                
            if not link or not link.get('href'):
                continue
                
            # Get the URL
            article_url = link['href']
            if not article_url.startswith('http'):
                article_url = f"https://www.ageofempires.com{article_url}"
                
            # Skip if not AOE4 related
            if 'aoeiv' not in article_url and not any(x in article_url.lower() for x in ['age-of-empires-iv', 'age-iv']):
                # Check the text for AOE4 mentions
                if not any(x in article.get_text().lower() for x in ['age of empires iv', 'age iv', 'aoe4', 'aoeiv']):
                    continue
            
            # Add to the list of articles to process
            articles.append(article_url)
            
            # Limit to first 5 articles to avoid too many requests
            if len(articles) >= 5:
                break
                
        return articles
        
    except Exception as e:
        logger.error(f"Error fetching news listing: {e}")
        return []

async def fetch_aoe4_news(news_type="announcement"):
    """Fetch and process AOE4 news articles"""
    try:
        # Get the list of article URLs
        article_urls = await get_news_listing(news_type)
        
        # Process each article
        articles = []
        for url in article_urls:
            article_data = await get_article_details(url, news_type)
            if article_data:
                articles.append(article_data)
                
        # Sort by date (newest first)
        articles.sort(key=lambda x: x['date'], reverse=True)
        
        return articles
        
    except Exception as e:
        logger.error(f"Error fetching AOE4 news: {e}")
        return []

def create_news_embed(article):
    """Create a Discord embed for AOE4 news"""
    content_type = article.get('content_type', 'general')
    
    # Define embed colors based on content type
    colors = {
        "patch": discord.Color.gold(),
        "announcement": discord.Color.blue(),
        "content": discord.Color.green(),
        "general": discord.Color.dark_purple()
    }
    
    # Create the embed with the title and URL
    embed = discord.Embed(
        title=article['title'],
        url=article['url'],
        color=colors.get(content_type, discord.Color.dark_purple()),
        timestamp=datetime.now(timezone.utc)
    )
    
    # Add AOE4 icon as author avatar
    embed.set_author(
        name="Age of Empires IV",
        icon_url=AOE4_ICON_URL
    )
    
    # Add category if available
    if article.get('category') and article['category'] != "Uncategorized":
        embed.add_field(name="Category", value=article['category'], inline=True)
    
    # Add publication date
    embed.add_field(name="Published", value=article['date'], inline=True)
    
    # Add author if available
    if article.get('author'):
        embed.add_field(name="Author", value=article['author'], inline=True)
    
    # Add the content preview
    if article.get('preview'):
        embed.description = article['preview']
    else:
        embed.description = "Click the title to read the full article on the Age of Empires website."
    
    # Add the image if available
    if article.get('image_url'):
        embed.set_image(url=article['image_url'])
    
    # Set appropriate footer based on content type
    footer_texts = {
        "patch": "Age of Empires IV Patch Notes",
        "announcement": "Age of Empires IV Announcement",
        "content": "Age of Empires IV Content Update",
        "general": "Age of Empires IV News"
    }
    
    footer_text = footer_texts.get(content_type, "Age of Empires IV News")
    embed.set_footer(text=f"{footer_text} | Posted by AoE4 MA")
    
    return embed

async def post_aoe4_news(bot, article):
    """Post AOE4 news to the designated Discord channel"""
    channel = bot.get_channel(PATCH_NOTES_CHANNEL_ID)
    if not channel:
        logger.error("News channel not found")
        return False
    
    try:
        # Verify the table exists with correct schema
        bot.db.update_news_table_schema()
        
        # Check if we've already posted this specific URL
        url_hash = article.get('url_hash')
        if not url_hash:
            url_hash = hashlib.md5(article['url'].encode()).hexdigest()
            
        # Check both by post_id and url_hash
        existing = bot.db.query_one(
            "SELECT post_id, message_id FROM aoe4_news WHERE post_id = ? OR url_hash = ?", 
            (article['post_id'], url_hash)
        )
        
        if existing:
            post_id, message_id = existing
            
            # If message_id exists, check if the message still exists
            if message_id:
                try:
                    await channel.fetch_message(int(message_id))
                    # Message still exists, don't repost
                    logger.info(f"News already posted and message still exists: {article['title']}")
                    return False
                except discord.NotFound:
                    # Message was deleted, remove from database so we can repost
                    logger.info(f"News message was deleted, will repost: {article['title']}")
                    bot.db.execute("DELETE FROM aoe4_news WHERE post_id = ?", (post_id,))
                    bot.db.commit()
                except Exception as e:
                    logger.error(f"Error checking message {message_id}: {e}")
        
        # Create and send embed
        embed = create_news_embed(article)
        
        # Create appropriate heading based on content type
        content_type = article.get('content_type', 'general')
        headings = {
            "patch": "📢 **New Age of Empires IV Patch Notes!**",
            "announcement": "🔔 **Age of Empires IV Announcement!**",
            "content": "🎮 **New Age of Empires IV Content!**",
            "general": "📰 **Age of Empires IV News Update**"
        }
        
        heading = f"{headings.get(content_type, '📰 **Age of Empires IV News Update**')}\n{article['title']}"
        
        message = await channel.send(content=heading, embed=embed)
        
        # Save to database with message_id and url_hash
        try:
            bot.db.execute(
                """INSERT INTO aoe4_news 
                (post_id, title, url, date, category, content_type, is_patch, message_id, url_hash) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article['post_id'], 
                    article['title'], 
                    article['url'], 
                    article['date'], 
                    article.get('category', 'Uncategorized'),
                    content_type,
                    content_type == "patch",
                    str(message.id),
                    url_hash
                )
            )
            bot.db.commit()
        except Exception as e:
            logger.error(f"Database error saving news: {e}", exc_info=True)
        
        logger.info(f"Posted new AOE4 {content_type} news: {article['title']}")
        return True
    except Exception as e:
        logger.error(f"Error posting news: {e}", exc_info=True)
        return False