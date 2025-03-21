import requests
import json
import time
import random
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Setting up the session with retries and backoff
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[429])  # Only retry on 429 (Too Many Requests)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)

# Define the headers
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
}

def fetch_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    print(f"Fetching archives for user {username}...")
    response = session.get(url, headers=headers)

    if response.status_code == 403:
        print("Access to the user's archives is forbidden. Check if the profile is public.")
        return []
    
    response.raise_for_status()  # Raise an exception for any HTTP error (non-2xx status)
    return response.json().get("archives", [])

def fetch_game_data(archive_url):
    response = session.get(archive_url, headers=headers)
    if response.status_code == 403:
        print(f"Forbidden access to archive URL: {archive_url}")
        return []
    response.raise_for_status()  # Raise an exception for any HTTP error (non-2xx status)
    return response.json().get("games", [])

def save_full_game_data(username):
    archives = fetch_archives(username)
    if not archives:
        print("No archives found.")
        return

    all_game_data = []

    # Fetch the game data from each archive URL
    for archive_url in archives:
        print(f"Fetching game data from {archive_url}...")
        try:
            game_data = fetch_game_data(archive_url)
            all_game_data.extend(game_data)
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from {archive_url}: {e}")
            continue

    if all_game_data:
        # Save the collected game data to a JSON file
        with open(f"{username}_game_data.json", "w") as f:
            json.dump({"games": all_game_data}, f, indent=4)

        print(f"Saved full game data to {username}_game_data.json")
    else:
        print(f"No game data collected for user {username}.")

# Example usage
username = "akirenosleep"  # Replace with the Chess.com username you want to fetch
save_full_game_data(username)
