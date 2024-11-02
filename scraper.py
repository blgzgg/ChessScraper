import sys
import os
import requests
from bs4 import BeautifulSoup
from selenium import webdriver

# Chess piece figurines to notation mapping
piece_notation = {
    'K': 'K',  # King
    'Q': 'Q',  # Queen
    'R': 'R',  # Rook
    'B': 'B',  # Bishop
    'N': 'N',  # Knight
    'P': ''    # Pawn has no letter
}

script_dir = os.path.dirname(os.path.abspath(__file__))
filename = os.path.join(script_dir, 'htmlTestOutput.txt')

def read_strings_from_file(file__name):
    try:
        with open(file__name, 'r') as file:
            strings = file.read().splitlines()
        return strings
    except FileNotFoundError:
        return []

def write_strings_to_file(strings, batch_number=1):
    """Writes strings to a file, handling large datasets by splitting into batches."""
    batch_filename = f"htmlTestOutput_batch_{batch_number}.txt"
    with open(batch_filename, 'a') as file:
        for string in strings:
            file.write(f"{string}\n")

def extract_moves_from_game_page(game_url, batch_number=1):
    """Extract moves from a given game analysis page URL."""
    response = requests.get(game_url)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the move list element based on wc-move-list
        move_list = soup.find(class_='analysis-view-movelist move-list chessboard-pkg-move-list-component')
        
        if not move_list:
            stringWrite = read_strings_from_file(filename)
            stringWrite.append(str(response.content))
            write_strings_to_file(stringWrite, batch_number)  # Save smaller batches

            print(f"No move list found on {game_url}")
            return []

        moves = []
        move_rows = move_list.find_all('div', class_='main-line-row')

        for row in move_rows:
            white_move_div = row.find('div', class_='white-move')
            if white_move_div:
                white_move = extract_move(white_move_div)
                if white_move:
                    moves.append(white_move)
            
            black_move_div = row.find('div', class_='black-move')
            if black_move_div:
                black_move = extract_move(black_move_div)
                if black_move:
                    moves.append(black_move)
        
        return moves

    else:
        print(f"Failed to retrieve {game_url}. Status code: {response.status_code}")
        return []


def extract_move(move_div):
    """Extract a move from a specific div element."""
    # Extract the piece being moved from the data-figurine attribute
    figurine_span = move_div.find('span', class_='icon-font-chess')
    if figurine_span:
        piece = piece_notation.get(figurine_span['data-figurine'], '')  # Get piece notation or empty for pawns
    else:
        piece = ''  # Default to empty (pawn move)

    # Extract the destination square from the move text
    move_text_span = move_div.find('span', class_='node-highlight-content')
    if move_text_span:
        move_text = move_text_span.get_text(strip=True)
    else:
        move_text = ''

    # Return the move in chess notation format
    return piece + move_text

def scrape_chesscom_games(username):
    """Scrape the chess.com archive for a given username."""
    url = f"https://www.chess.com/games/archive/{username}"
    response = requests.get(url)
    
    if response.status_code == 200:
        games = []
        pageIndex = 1
        while True:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all game entries
            game_entries = soup.find_all('tr', attrs={'v-board-popover': True})
            if len(game_entries) == 0:
                break  # No more games
            
            for game_entry in game_entries:
                # Extract game result
                result_elem = game_entry.find('span', class_='archive-games-result-icon')
                result = result_elem['v-tooltip'] if result_elem else None
                
                # Extract move URLs for game analysis
                moves_urls = []
                move_links = game_entry.find_all('a', href=True)
                for link in move_links:
                    if 'chess.com/analysis/game/' in link['href']:
                        move_url = link['href'] + "?tab=analysis"  # Append ?tab=analysis to the URL
                        moves_urls.append(move_url)
                
                # Gather moves from the analysis page
                game_moves = []
                for move_url in moves_urls:
                    game_moves += extract_moves_from_game_page(move_url)
                
                games.append({'result': result, 'moves': game_moves})
            
            # Check for next page
            pageIndex += 1
            url = f"https://www.chess.com/games/archive/{username}?page={pageIndex}"
            response = requests.get(url)
        
        return games
    
    else:
        print(f"Failed to retrieve data. Status code: {response.status_code}")
        return None


# Test
username = input("Enter your chess.com username: ")
games = scrape_chesscom_games(username)

if games:
    for idx, game in enumerate(games, start=1):
        print(f"Game {idx}:")
        print(f"Result: {game['result']}")
        if game['moves']:
            print(f"Moves:")
            for move in game['moves']:
                print(move, end=" ")
            print("\n")
        else:
            print("No moves found.\n")
