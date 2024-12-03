import requests
import chess.pgn
import io
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import time


session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429])
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)

# Database setup
Base = declarative_base()

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    white_player = Column(String, nullable=False)
    black_player = Column(String, nullable=False)
    white_rating = Column(Integer, nullable=True)
    black_rating = Column(Integer, nullable=True)
    result = Column(String, nullable=False)
    date_played = Column(DateTime, nullable=False)
    pgn = Column(String, nullable=False)

# Set up the database connection
engine = create_engine('sqlite:///chess_games.db')  # Use SQLite for simplicity
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

def fetch_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {
        "User-Agent": "ChessScraper/1.0 (+https://github.com/blgzgg)"
    }
    
    print(f"Fetching archives for user {username}...")
    response = requests.get(url, headers=headers)
    
    if response.status_code == 403:
        print("Access to the user's archives is forbidden. Check if the profile is public.")
        return []
    
    response.raise_for_status()
    return response.json()["archives"]

def fetch_game_data(archive_url):
    response = requests.get(archive_url)
    response.raise_for_status()
    return response.json()["games"]

def collect_games(username):
    archives = fetch_archives(username)
    all_games = []
    
    for archive_url in archives:
        print(f"Fetching games from {archive_url}...")
        try:
            archive_data = fetch_game_data(archive_url)
            all_games.extend(archive_data.get("games", []))
            # Add a time delay to avoid hitting rate limits
            time.sleep(0.1)  # Delay of 0.1 second between requests
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from {archive_url}: {e}")
            continue

    print(f"Collected {len(all_games)} games for user {username}.")
    return all_games

# Process a single game
def process_game(game_data):
    # Parse PGN
    pgn = io.StringIO(game_data['pgn'])
    game = chess.pgn.read_game(pgn)
    metadata = game.headers
    
    # Extract metadata
    game_record = Game(
        url=game_data['url'],
        white_player=metadata["White"],
        black_player=metadata["Black"],
        white_rating=metadata.get("WhiteElo"),
        black_rating=metadata.get("BlackElo"),
        result=metadata["Result"],
        date_played=datetime.strptime(metadata["UTCDate"], "%Y.%m.%d"),
        pgn=game_data['pgn']
    )
    
    # Save to database
    session.add(game_record)
    session.commit()

username = "obodobear"
collect_games(username)

print("Data collection complete!")
