from google.colab import drive

drive.mount('/content/drive')

!pip install google-genai requests feedparser beautifulsoup4 yfinance pandas lxml gtts google-cloud-storage feedgen

# Install the Spotify API library if you haven't already
!pip install spotipy -q

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests

# ----------------------------------------------------
# PASTE YOUR SECURED KEYS HERE:
# ----------------------------------------------------
SPOTIPY_CLIENT_ID = "9e66ed09478c4b06957bbaeeb41ad9df"
SPOTIPY_CLIENT_SECRET = "5d3dc7c145d54089a771043290e60997"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8080" # <--- UPDATED TO SECURE IP

TICKETMASTER_API_KEY = "1imLZD2PHeUaudfAEL48eGc7NRrOPU10"
# ----------------------------------------------------

print("🔄 Testing Ticketmaster API connection...")
tm_test_url = f"https://app.ticketmaster.com/discovery/v2/events.json?apikey={TICKETMASTER_API_KEY}&latlong=39.6997,-104.8378&radius=10&unit=miles"
try:
    tm_response = requests.get(tm_test_url, timeout=5)
    if tm_response.status_code == 200:
        print("✅ Ticketmaster: SUCCESS! API key is valid.")
    else:
        print(f"❌ Ticketmaster Error: Received code {tm_response.status_code}")
except Exception as e:
    print(f"❌ Ticketmaster connection failed: {e}")

print("\n----------------------------------------------------\n")

print("🔄 Starting Spotify Handshake. Watch the instructions below!")

# We use open_browser=False because Colab cannot open a local browser window.
sp_oauth = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope="user-top-read",
    open_browser=False  # <--- Crucial for Google Colab!
)

try:
    # 1. This will print a URL. Click on it, log in to Spotify, and click "Agree".
    # 2. Your browser will then redirect to a blank page starting with "http://127.0.0.1:8080/?code=..."
    # 3. Copy the entire blank page URL from your address bar.
    # 4. Paste that entire URL into the input box that appears below in your Colab cell.

    sp = spotipy.Spotify(auth_manager=sp_oauth)

    # Let's test if we can pull your top artists!
    top_artists = sp.current_user_top_artists(limit=5, time_range='medium_term')

    print("\n✅ Spotify: SUCCESS! Connected to your personal account.")
    print("Here are your current top artists on Spotify:")
    for idx, artist in enumerate(top_artists['items'], 1):
         print(f" {idx}. {artist['name']}")

except Exception as e:
    print(f"\n❌ Spotify setup failed: {e}")

from datetime import datetime, timezone
from io import StringIO
import json
import os
import random
import time
from bs4 import BeautifulSoup
import feedparser
from feedgen.feed import FeedGenerator
from google import genai
from google.genai import types
from google.cloud import storage
from gtts import gTTS
import pandas as pd
import requests
import yfinance as yf

# --- CONFIGURATION ---
# Read API keys from GitHub Secrets / Environment Variables
API_KEY = os.environ.get("GEMINI_API_KEY")
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY")

# Write the GCP key from GitHub Secrets into a temporary file for storage client
gcp_key_json = os.environ.get("GCP_SA_KEY")
if gcp_key_json:
  with open("/tmp/gcp-key.json", "w") as f:
    f.write(gcp_key_json)
  os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/gcp-key.json"

# GCS & PODCAST SETTINGS
GCS_BUCKET_NAME = "my-daily-digest-podcast-123"  # Your bucket name
GCS_PUBLIC_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}"

LATITUDE = 39.6997
LONGITUDE = -104.8378

# GCS & PODCAST SETTINGS
GCS_BUCKET_NAME = "my-daily-digest-podcast-123"
GCS_CREDENTIALS_FILE = "/content/drive/MyDrive/Colab Notebooks/gcp-key.json"
GCS_PUBLIC_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}"

# Curated daily RSS feed sources
RSS_FEEDS = {
    "Financial Markets": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Accounting News": "https://www.accountingtoday.com/feed/rss.xml",
    "Aurora News 1": "https://sentinelcolorado.com/feed/rss.xml",
    "Aurora News 2": "https://www.denver7.com/news/front-range/aurora.rss",
}

# PODCAST RSS FEEDS
PODCAST_FEEDS = {
    "Gold and Black": "https://feeds.simplecast.com/AHqOg_vz",
    "All In": "https://allinchamathjason.libsyn.com/rss",
    "Next with Kyle Clark": "https://feeds.simplecast.com/aLWsA1Ol",
    "WSJ What's News": (
        "https://video-api.wsj.com/podcast/rss/wsj/whats-news"
    ),
    "Trackside": (
        "https://www.omnycontent.com/d/playlist/78a347aa-3282-4ac5-837c-a72300032082/d977cad4-a06d-47b4-bcd4-af2c0122e72c/117d83f3-2c34-441a-9b8b-af2c0122e74d/podcast.rss"
    ),
}

# FINANCIAL TICKERS WATCHLIST
STOCK_TICKERS = {
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "Verizon": "VZ",
    "Darden Restaurants": "DRI",
}


# --- 1. THE DATA GATHERERS ---
def get_aurora_weather(lat=LATITUDE, lon=LONGITUDE):
  """Gets the raw 24-hour weather forecast for Aurora, CO."""
  headers = {"User-Agent": "(daily-digest-app, user@example.com)"}
  try:
    point_url = f"https://api.weather.gov/points/{lat},{lon}"
    point_resp = requests.get(point_url, headers=headers, timeout=10)
    point_resp.raise_for_status()

    forecast_url = point_resp.json()["properties"]["forecast"]
    forecast_resp = requests.get(forecast_url, headers=headers, timeout=10)
    forecast_resp.raise_for_status()

    periods = forecast_resp.json()["properties"]["periods"]
    weather_summary = []
    for period in periods[:3]:
      weather_summary.append({
          "period": period["name"],
          "temp": f"{period['temperature']}°{period['temperatureUnit']}",
          "forecast": period["detailedForecast"],
      })
    return weather_summary
  except Exception as e:
    return f"Weather unavailable: {str(e)}"


def get_live_local_concerts():
  """Queries Ticketmaster for upcoming live music events near Aurora, CO."""
  url = "https://app.ticketmaster.com/discovery/v2/events.json"
  params = {
      "apikey": TICKETMASTER_API_KEY,
      "latlong": f"{LATITUDE},{LONGITUDE}",
      "radius": "30",
      "unit": "miles",
      "classificationName": "music",
      "size": 5,
      "sort": "date,asc",
  }
  try:
    res = requests.get(url, params=params, timeout=10).json()
    events = res.get("_embedded", {}).get("events", [])
    shows = []
    for e in events:
      venue = e.get("_embedded", {}).get("venues", [{}])[0]
      classifications = e.get("classifications", [{}])
      genre_name = (
          classifications[0].get("genre", {}).get("name", "Live Music")
          if classifications
          else "Live Music"
      )

      shows.append({
          "artist": e["name"],
          "date": e.get("dates", {})
          .get("start", {})
          .get("localDate", "TBA"),
          "venue": venue.get("name", "Unknown Venue"),
          "genre": genre_name,
      })
    return shows
  except Exception:
    return []


def clean_html(html_string):
  """Strips HTML tags to clean up RSS feeds."""
  if not html_string:
    return ""
  return BeautifulSoup(html_string, "html.parser").get_text().strip()


def parse_rss_feeds(feeds_dict, max_entries=4):
  """Gathers the latest headlines and summaries from the RSS feeds."""
  aggregated_news = {}
  for category, url in feeds_dict.items():
    try:
      feed = feedparser.parse(url)
      articles = []
      for entry in feed.entries[:max_entries]:
        raw_summary = getattr(
            entry, "summary", getattr(entry, "description", "")
        )
        clean_summary = clean_html(raw_summary)
        articles.append({
            "title": entry.title,
            "summary": (
                clean_summary[:200] + "..."
                if len(clean_summary) > 200
                else clean_summary
            ),
        })
      aggregated_news[category] = articles
    except Exception as e:
      aggregated_news[category] = [f"Failed to load: {str(e)}"]
  return aggregated_news


def get_latest_podcasts(podcast_dict):
  """Parses podcast RSS feeds and grabs the single most recent episode."""
  latest_episodes = {}
  for show_name, url in podcast_dict.items():
    try:
      feed = feedparser.parse(url)
      if feed.entries:
        latest_ep = feed.entries[0]
        raw_summary = getattr(
            latest_ep, "summary", getattr(latest_ep, "description", "")
        )
        clean_summary = clean_html(raw_summary)

        latest_episodes[show_name] = {
            "episode_title": latest_ep.title,
            "published": getattr(latest_ep, "published", "Date Unknown"),
            "summary": (
                clean_summary[:250] + "..."
                if len(clean_summary) > 250
                else clean_summary
            ),
        }
      else:
        latest_episodes[show_name] = "No episodes found."
    except Exception as e:
      latest_episodes[show_name] = f"Error loading podcast: {str(e)}"
  return latest_episodes


def get_market_data(ticker_dict):
  """Fetches market data for custom tickers."""
  market_summary = {}
  for name, symbol in ticker_dict.items():
    try:
      ticker = yf.Ticker(symbol)
      hist = ticker.history(period="2d")
      if len(hist) >= 2:
        close_today = hist["Close"].iloc[-1]
        close_yesterday = hist["Close"].iloc[-2]
        pct_change = (
            (close_today - close_yesterday) / close_yesterday
        ) * 100
        market_summary[name] = {
            "price": (
                f"${close_today:.2f}"
                if not symbol.startswith("^")
                else f"{close_today:,.2f}"
            ),
            "change": f"{pct_change:+.2f}%",
        }
      elif len(hist) == 1:
        close_today = hist["Close"].iloc[-1]
        market_summary[name] = {
            "price": (
                f"${close_today:.2f}"
                if not symbol.startswith("^")
                else f"{close_today:,.2f}"
            ),
            "change": "Data flat / flat exchange",
        }
      else:
        market_summary[name] = "No recent pricing available."
    except Exception as e:
      market_summary[name] = f"Market data error: {str(e)}"
  return market_summary


def get_sp500_tickers():
  """Scrapes Wikipedia for S&P 500 tickers."""
  url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
  headers = {"User-Agent": "Mozilla/5.0"}
  try:
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    tables = pd.read_html(
        StringIO(response.text), attrs={"id": "constituents"}
    )
    df = tables[0]
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()
  except Exception as e:
    return ["VZ", "T", "CMCSA", "CHTR", "KSS", "CBRL", "TAP", "MCD", "QSR"]


def find_sp500_recent_low_discovery():
  """Scours S&P 500 for companies near 52-week lows."""
  print("📊 Scouring the entire S&P 500 for recent 52-week lows...")
  all_tickers = get_sp500_tickers()
  closest_stock = None
  percent_from_low = float("inf")

  for ticker in all_tickers:
    try:
      stock = yf.Ticker(ticker)
      info = stock.info
      current = info.get("currentPrice") or info.get("regularMarketPrice")
      low_52 = info.get("fiftyTwoWeekLow")

      if current and low_52:
        diff_pct = ((current - low_52) / low_52) * 100
        if diff_pct < percent_from_low:
          percent_from_low = diff_pct
          closest_stock = {
              "company_name": info.get("longName", ticker),
              "ticker": ticker,
              "sector": info.get("sector", "N/A"),
              "current_price": f"${current:.2f}",
              "trailing_pe": f"{info.get('trailingPE', 'N/A')}",
              "dividend_yield": (
                  f"{round((info.get('dividendYield', 0) * 100), 2)}%"
                  if info.get("dividendYield")
                  else "N/A"
              ),
              "free_cash_flow": (
                  f"${round(info.get('freeCashflow', 0) / 1e9, 2)} Billion"
                  if info.get("freeCashflow")
                  else "N/A"
              ),
              "percent_above_52w_low": f"{round(diff_pct, 2)}%",
          }
    except Exception:
      continue

  return closest_stock or {
      "company_name": "Verizon Communications Inc.",
      "ticker": "VZ",
      "sector": "Telecommunications",
      "current_price": "$38.50",
      "trailing_pe": "9.2",
      "dividend_yield": "6.8%",
      "free_cash_flow": "$18.5 Billion",
      "percent_above_52w_low": "1.2%",
  }


def get_watchlist_premarket_news():
  """Queries Yahoo Finance for latest headlines on watchlist."""
  watch_tickers = ["CHTR", "CMCSA", "KSS", "CBRL", "TAP"]
  news_items = []
  for ticker in watch_tickers:
    try:
      stock = yf.Ticker(ticker)
      s_news = stock.news
      if s_news:
        latest_story = s_news[0]
        news_items.append({
            "ticker": ticker,
            "headline": latest_story.get("title"),
            "publisher": latest_story.get("publisher"),
        })
    except Exception:
      continue
  return news_items[:4]


# --- 2. AUDIO & GCS PIPELINE ---
def text_to_speech(text: str, output_filename: str = "today_digest.mp3"):
  """Converts text script into an MP3 file using gTTS."""
  print("🔊 Converting digest text to speech...")
  tts = gTTS(text=text, lang="en", slow=False)
  tts.save(output_filename)
  print(f"✅ Audio saved to {output_filename}")
  return output_filename


def upload_to_gcs(
    local_file_path: str, destination_blob_name: str, content_type: str = None
):
  """Uploads a file to Google Cloud Storage bucket."""
  print(f"☁️ Uploading {local_file_path} to GCS as {destination_blob_name}...")
  if os.path.exists(GCS_CREDENTIALS_FILE):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCS_CREDENTIALS_FILE

  storage_client = storage.Client()
  bucket = storage_client.bucket(GCS_BUCKET_NAME)
  blob = bucket.blob(destination_blob_name)

  if content_type:
    blob.content_type = content_type

  blob.upload_from_filename(local_file_path)
  return f"{GCS_PUBLIC_BASE_URL}/{destination_blob_name}"


def update_podcast_rss(
    latest_audio_url: str,
    audio_file_path: str,
    digest_title: str,
    digest_description: str,
):
  """Generates/updates podcast RSS feed xml and uploads to GCS."""
  print("📰 Building RSS podcast feed...")
  fg = FeedGenerator()
  fg.load_extension("podcast")

  fg.title("My Morning Daily Digest")
  fg.link(href=f"{GCS_PUBLIC_BASE_URL}/feed.xml", rel="self")
  fg.description("Personal automated morning briefing with weather and news.")
  fg.language("en")

  fg.podcast.itunes_category("News")
  fg.podcast.itunes_explicit("no")

  fe = fg.add_entry()
  fe.id(latest_audio_url)
  fe.title(digest_title)
  fe.description(digest_description)
  fe.published(datetime.now(timezone.utc))

  file_size = os.path.getsize(audio_file_path)
  fe.enclosure(latest_audio_url, str(file_size), "audio/mpeg")

  rss_local_filename = "feed.xml"
  fg.rss_file(rss_local_filename, pretty=True)

  upload_to_gcs(
      rss_local_filename, "feed.xml", content_type="application/rss+xml"
  )
  print(f"🚀 Podcast Feed updated! Subscribe using:")
  print(f"👉 {GCS_PUBLIC_BASE_URL}/feed.xml")


def process_audio_pipeline(script_text: str):
  """Wrapper function to run the full audio creation and upload flow."""
  date_str = datetime.now().strftime("%Y-%m-%d")
  mp3_filename = f"digest_{date_str}.mp3"

  # 1. Convert text to MP3
  local_mp3 = text_to_speech(script_text, output_filename=mp3_filename)

  # 2. Upload MP3 to GCS
  audio_url = upload_to_gcs(local_mp3, mp3_filename, content_type="audio/mpeg")

  # 3. Update & upload RSS feed XML
  update_podcast_rss(
      latest_audio_url=audio_url,
      audio_file_path=local_mp3,
      digest_title=f"Daily Digest - {date_str}",
      digest_description=script_text[:300] + "...",
  )


# --- 3. THE MAIN ENGINE ---
def run_daily_digest():
  print(
      "🤖 Step 1: Gathering weather, news, concerts, podcasts, and market"
      " tickers..."
  )
  raw_input_data = {
      "location": "Aurora, Colorado",
      "weather_data": get_aurora_weather(),
      "local_concerts": get_live_local_concerts(),
      "news_data": parse_rss_feeds(RSS_FEEDS),
      "latest_podcasts": get_latest_podcasts(PODCAST_FEEDS),
      "market_quotes": get_market_data(STOCK_TICKERS),
      "value_discovery": find_sp500_recent_low_discovery(),
      "watchlist_news": get_watchlist_premarket_news(),
  }

  print("🤖 Step 2: Formatting the data package...")
  data_string = json.dumps(raw_input_data, indent=2)

  system_instruction = (
      "You are an engaging morning radio host. Your goal is to write a warm,"
      " crisp up to 5 minute morning commute script. The listener rides the"
      " train to work. Start with an upbeat greeting and local Aurora, CO"
      " weather.\n\nNext, check the 'local_concerts' data. If there are upcoming"
      " events listed, naturally mention a couple of the key live music shows"
      " coming to the area (including venue and date) as a fun weekend preview"
      " line.\n\nNext, summarize local news stories using the RSS feeds for"
      " Aurora News 1 and Aurora News 2.Next, review the 'market_quotes' data."
      " Give a brief, natural summary of how the major indices (S&P 500, Dow"
      " Jones) and custom watchlist stocks are doing today (up or down).  If"
      " the time is before the market has opened then do not give  a synopsis"
      " of the market's performance because it could be outdated. Move"
      " seamlessly from the raw stock movements into the broader financial,"
      " accounting market. Avoid presenting this as a boring list; weave it"
      " into a coherent narrative.\n\nNext, introduce the 'Fresh 52-Week Low"
      " Discovery' using the data in 'value_discovery'. Explain that you ran"
      " a scan on the entire S&P 500 to pull out companies that actually"
      " bottomed out and hit a brand-new 52-week low within the last week."
      " Pitch this stock to the listener: state its name, sector, price,"
      " valuation metrics (trailing P/E, Dividend Yield, and Free Cash Flow)."
      " Then, provide a sharp, conversational deep-dive. Why is the market"
      " dumping it this week? Is it a classic value trap with declining"
      " fundamentals, or a strong, cash-generative business trading at an"
      " temporary discount? Make this segment the analytical star of the"
      " morning.\n\nThen, check 'watchlist_news'. If any tracked stocks (CHTR,"
      " CMCSA, KSS, CBRL, TAP) have active headlines, mention them as quick"
      " pre-market news alerts. If there is no related news then leave this"
      " piece out and don't mention.Transition smoothly into broader"
      " business/accounting market news.\n\nFinally, check the 'latest_podcasts'"
      " data. If there is a very recently released episode (within the last day"
      " or two), mention it enthusiastically as a listening option for the"
      " train ride."
  )

  print("🤖 Step 3: Sending to Gemini API...")
  try:
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"Here is today's raw data:\n\n{data_string}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction
        ),
    )

    script_text = response.text
    print("\n🎉 SUCCESS! HERE IS YOUR DAILY SCRIPT:\n")
    print("=========================================")
    print(script_text)
    print("=========================================")

    # 🚀 Step 4: Run Audio & RSS Pipeline
    print("\n🤖 Step 4: Generating audio and uploading RSS feed...")
    process_audio_pipeline(script_text)

  except Exception as e:
    print(f"\n❌ Error calling the Gemini API: {str(e)}")


if __name__ == "__main__":
  run_daily_digest()
