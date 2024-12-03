import requests
import chess.pgn
import io
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

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

# Fetch game archives for a user
def fetch_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()["archives"]

# Fetch games for a specific archive
def fetch_games(archive_url):
    response = requests.get(archive_url)
    response.raise_for_status()
    return response.json()["games"]

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

# Main script to collect data
def collect_games(username):
    print(f"Fetching archives for user {username}...")
    archives = fetch_archives(username)
    for archive_url in archives:
        print(f"Fetching games from archive: {archive_url}")
        games = fetch_games(archive_url)
        for game_data in games:
            if not session.query(Game).filter_by(url=game_data['url']).first():
                process_game(game_data)
                print(f"Processed game: {game_data['url']}")

username = "obodobear"
collect_games(username)

print("Data collection complete!")
