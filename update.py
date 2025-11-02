"""
This is the main backend module.
It handles updates of new results, computation of ELO, and data storage.
"""

import pandas as pd
import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# -- CONFIG --
DIRETTA_URL = "https://www.diretta.it/squadra/{diretta_name}/{diretta_id}/risultati/"
RESULTS_CSV = "results.csv"
STATS_JSON = "stats.json"
stats_data = {}
with open(STATS_JSON, "r", encoding="utf-8") as stats_file:
    stats_data = json.load(stats_file)

# ANSI color codes
RED = '\033[91m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
RESET = '\033[0m'

def normalize_text(text):
    """Normalize text for comparison by removing accents and converting to lowercase."""
    if not text:
        return ""
    # Normalize unicode characters (NFD = decompose accents)
    normalized = unicodedata.normalize('NFD', text)
    # Remove accent marks
    without_accents = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return without_accents.lower()

def get_soup(url):
    """Fetch the HTML content of a URL and return a BeautifulSoup object."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        page.goto(url, timeout=10000)
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        browser.close()
        return soup

def get_home_away_from_match_page(match_url):
    """
    Fetch the match page and extract home/away team IDs from the HTML.
    Returns a tuple (home_id, away_id) or (None, None) if extraction fails.
    """
    try:
        soup = get_soup(match_url)
        
        # Find the home team div: <div class="duelParticipant__home ...">
        home_div = soup.select_one('div[class*="duelParticipant__home"]')
        # Find the away team div: <div class="duelParticipant__away ...">
        away_div = soup.select_one('div[class*="duelParticipant__away"]')
        
        home_id = None
        away_id = None
        
        if home_div:
            # Find the link inside: <a href="/squadra/trentino/CffxNRaH/" ...>
            home_link = home_div.select_one('a[href*="/squadra/"]')
            if home_link and home_link.get('href'):
                # Extract ID from href: /squadra/trentino/CffxNRaH/
                href_parts = home_link['href'].strip('/').split('/')
                if len(href_parts) >= 3:
                    home_id = href_parts[2]  # CffxNRaH
        
        if away_div:
            # Find the link inside: <a href="/squadra/padova/Kfbd7lGB/" ...>
            away_link = away_div.select_one('a[href*="/squadra/"]')
            if away_link and away_link.get('href'):
                # Extract ID from href: /squadra/padova/Kfbd7lGB/
                href_parts = away_link['href'].strip('/').split('/')
                if len(href_parts) >= 3:
                    away_id = href_parts[2]  # Kfbd7lGB
        
        return home_id, away_id
    except Exception as e:
        print(f"{RED}Warning: Failed to extract home/away IDs from match page: {match_url}{RESET}")
        print(f"{RED}Error details: {e}{RESET}")
        return None, None

def parse_team_results_diretta_page(soup, teams_data):
    """
    Find match containers like:
    <div id="g_12_2oxAyMp4" class="event__match--last event__match ..." ...>
    and return list of dicts with match data (id, url, date_text, home, away, home_sets, away_sets, set_scores).
    """
    results = []

    print("Parsing team results page...")

    # match containers: class contains event__match
    for div in soup.select('div[class*="event__match"]'):
        mid = div.get("id")  # e.g., g_12_2oxAyMp4
        # link to match details is in <a class="eventRowLink" href="...">
        a = div.select_one("a.eventRowLink")
        match_url = None
        if a and a.get("href"):
            match_url = a["href"]
        # date/time string element (e.g., <div class="event__time">21.10. 20:30</div>)
        date_el = div.select_one(".event__time")
        date_raw = date_el.get_text(strip=True) if date_el else None
        
        # Parse and format date
        date_text = None
        if date_raw:
            try:
                # Remove time part (everything after space or just the time)
                date_part = date_raw.split()[0] if ' ' in date_raw else date_raw
                
                # Remove trailing dots and split
                date_part = date_part.strip('.')
                parts = date_part.split('.')
                
                # Parse different date formats
                if len(parts) == 3:
                    # Format: "22.12.2024" (day.month.year)
                    day, month, year = parts
                    date_text = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                elif len(parts) == 2:
                    # Format: "06.01" (day.month, no year)
                    day, month = parts
                    # Assume the first possible day in the past with this day/month
                    today = datetime.now()
                    current_year = today.year
                    
                    # Try current year first
                    try:
                        match_date = datetime(current_year, int(month), int(day))
                        # If the date is in the future, use previous year
                        if match_date > today:
                            match_date = datetime(current_year - 1, int(month), int(day))
                        date_text = match_date.strftime("%Y-%m-%d")
                    except ValueError:
                        # Invalid date (e.g., Feb 30), skip
                        date_text = None
            except Exception as e:
                print(f"{RED}Warning: Could not parse date '{date_raw}': {e}{RESET}")
                date_text = None
        
        # Skip matches before stats last update
        if not date_text or date_text < stats_data.get("last_update", "0000-00-00").split("T")[0]:
            continue

        # teams:
        home_el = div.select_one(".event__participant--home")
        away_el = div.select_one(".event__participant--away")
        home_display = home_el.get_text(strip=True) if home_el else None
        away_display = away_el.get_text(strip=True) if away_el else None
        
        # Remove parentheses and everything between them
        if home_display:
            home_display = re.sub(r'\s*\([^)]*\)', '', home_display).strip()
        if away_display:
            away_display = re.sub(r'\s*\([^)]*\)', '', away_display).strip()
        
        # Extract team IDs from match URL
        # URL format: /partita/volley/team1-id1/team2-id2/?mid=...
        home = None
        away = None
        if match_url:
            try:
                # Fetch the match page to get home/away team IDs directly
                print(f"Fetching match page to extract home/away teams: {match_url}")
                home_id, away_id = get_home_away_from_match_page(match_url)
                
                if not home_id or not away_id:
                    print(f"{RED}Warning: Could not extract home/away IDs from match page{RESET}")
                    continue
                
                print(f"Extracted home_id: {home_id}, away_id: {away_id}")
                
                # Check if teams exist in teams_data, if not add them
                home_found = False
                away_found = False
                home_slug = None
                away_slug = None
                
                for team in teams_data:
                    if team.get("diretta_id") == home_id:
                        home_found = True
                        home_slug = f"{team.get('diretta_name', 'unknown')}-{home_id}"
                    if team.get("diretta_id") == away_id:
                        away_found = True
                        away_slug = f"{team.get('diretta_name', 'unknown')}-{away_id}"
                
                # Add missing teams to teams_data
                # Note: Automatically added teams do NOT get an "id" field, only "diretta_id"
                # This way they will be skipped when fetching matches
                if not home_found:
                    # Parse URL path to get the team slug for the home team
                    path_parts = urlparse(match_url).path.strip('/').split('/')
                    if len(path_parts) >= 4:
                        # Find which slug contains the home_id
                        team1_slug = path_parts[2]
                        team2_slug = path_parts[3]
                        
                        if team1_slug.endswith(home_id):
                            home_slug = team1_slug
                        elif team2_slug.endswith(home_id):
                            home_slug = team2_slug
                        else:
                            home_slug = f"unknown-{home_id}"
                    else:
                        home_slug = f"unknown-{home_id}"
                    
                    team_display_name = home_display if home_display else "Unknown Team"
                    print(f"Adding new team to teams.json: {team_display_name} (diretta_id: {home_id})")
                    new_team = {
                        "name": team_display_name,
                        "names": [team_display_name],
                        "diretta_id": home_id,
                        "diretta_name": '-'.join(home_slug.split('-')[:-1]),
                        "elo": 200,
                        "last_match_date": None,
                        "last_match_id": None
                    }
                    teams_data.append(new_team)
                
                if not away_found:
                    # Parse URL path to get the team slug for the away team
                    path_parts = urlparse(match_url).path.strip('/').split('/')
                    if len(path_parts) >= 4:
                        # Find which slug contains the away_id
                        team1_slug = path_parts[2]
                        team2_slug = path_parts[3]
                        
                        if team1_slug.endswith(away_id):
                            away_slug = team1_slug
                        elif team2_slug.endswith(away_id):
                            away_slug = team2_slug
                        else:
                            away_slug = f"unknown-{away_id}"
                    else:
                        away_slug = f"unknown-{away_id}"
                    
                    team_display_name = away_display if away_display else "Unknown Team"
                    print(f"Adding new team to teams.json: {team_display_name} (diretta_id: {away_id})")
                    new_team = {
                        "name": team_display_name,
                        "names": [team_display_name],
                        "diretta_id": away_id,
                        "diretta_name": '-'.join(away_slug.split('-')[:-1]),
                        "elo": 200,
                        "last_match_date": None,
                        "last_match_id": None
                    }
                    teams_data.append(new_team)
                
                # Set home and away using the slugs
                home = home_slug
                away = away_slug
                
            except Exception as e:
                # Fallback to display names if URL parsing fails
                print(f"{RED}Warning: Failed to parse team IDs from match URL: {match_url}{RESET}")
                print(f"{RED}Error details: {e}{RESET}")
                home = home_display
                away = away_display
        else:
            # No URL available, skip game
            print(f"{RED}Warning: No match URL available to parse team IDs.{RESET}")
            continue

        # final set counts
        hs_el = div.select_one("span.event__score--home")
        as_el = div.select_one("span.event__score--away")
        try:
            home_sets = int(hs_el.get_text(strip=True))
            away_sets = int(as_el.get_text(strip=True))
        except Exception:
            continue
        
        # Check if at least one team scored exactly 3 sets
        if home_sets != 3 and away_sets != 3:
            continue
        
        # Check if match date is valid and after stats last update
        if date_text and stats_data.get("last_update"):
            last_update_date = stats_data["last_update"].split("T")[0]
            if date_text < last_update_date:
                # print(f"Skipping match on {date_text} (home: {home}, away: {away}) - before stats last update {last_update_date}")
                continue

        # Generate match_id in format: <date>_<team1_diretta_id>_<team2_diretta_id>
        match_id = f"{date_text}_{home_id}_{away_id}"

        results.append({
            "match_id": match_id,
            "date": date_text,
            "home": home,
            "away": away,
            "home_sets": home_sets,
            "away_sets": away_sets,
            "winner": home if home_sets > away_sets else away if away_sets > home_sets else None,
        })
    return results

def update_results():
    """
    For each team, fetch the latest match results from the web source.
    Update the local data with any new results found.
    """
    print("Updating match results...")

    # load teams from JSON file
    print("Loading teams from teams.json...")
    teams_json = open("teams.json", "r")
    teams_data = json.load(teams_json)
    teams_json.close()

    # print("Fetched teams:")
    # for team in teams_data:
    #     print(f"- {team['name']} (ID: {team['id']}) (ELO: {team['elo']}) (last_match_id: {team['last_match_id']})")

    print("Get latest match results...")
    data = []
    for team in teams_data:
        # NOTE: If a team is missing the id, it has been added automatically, not by developer
        # We do not search for results of teams added automatically
        if not team.get("diretta_name") or not team.get("diretta_id") or not team.get("id"):
            print(f"Skipping team {team.get('name')} missing diretta_name or id")
            continue
        team_url = DIRETTA_URL.format(diretta_name=team["diretta_name"], diretta_id=team["diretta_id"])
        print(f"Fetching results for team {team['name']} from {team_url}...")
        soup = get_soup(team_url)
        parsed_results = parse_team_results_diretta_page(soup, teams_data)
        print(f"Found {len(parsed_results)} match entries on the team page.")
        for match in parsed_results:
            data.append([match["match_id"], match["date"], match["home"], match["away"], match["home_sets"], match["away_sets"], match["winner"]])
    
    print(f"Fetched {len(data)} new match results.")

   # update results.csv
    print("Updating results.csv...")
    df_new = pd.DataFrame(data, columns=["match_id", "date", "team1", "team2", "team1_sets", "team2_sets", "winner"])
    df_results = pd.read_csv(RESULTS_CSV)
    df_update = pd.concat([df_results, df_new]).drop_duplicates(["date", "team1", "team2"]).reset_index(drop=True)
    # Sort by date
    df_update = df_update.sort_values(by="date").reset_index(drop=True)
    df_update.to_csv(RESULTS_CSV, index=False)
    print("results.csv updated.")
    
    # Save updated teams.json (in case new teams were added)
    print("Saving updated teams.json...")
    with open("teams.json", "w", encoding="utf-8") as teams_json:
        json.dump(teams_data, teams_json, indent=4, ensure_ascii=False)
    print("teams.json updated.")


def compute_elo(team_a_elo, team_b_elo, score_a, score_b):
    """
    Compute the new ELO ratings for two teams based on their match result.
    """
    # TODO: Implement (these two lines are placeholders)
    new_team_a_elo = team_a_elo
    new_team_b_elo = team_b_elo

    return new_team_a_elo, new_team_b_elo


def update_elo_ratings():
    """
    Recalculate ELO ratings for all teams based on the updated match results.
    Store the updated ELO ratings in the local data storage.
    """
    print("Updating ELO ratings...")

    # read teams.json
    print("Loading teams from teams.json...")
    teams_json = open("teams.json", "r")
    teams_data = json.load(teams_json)
    teams_json.close()
    # print("Fetched teams:")
    # for team in teams_data:
    #     print(f"- {team['name']} (ID: {team['id']}) (ELO: {team['elo']}) (last_match_id: {team['last_match_id']})")

    # read results.csv
    print("Loading match results from results.csv...")
    df_results = pd.read_csv(RESULTS_CSV)
    print(f"Fetched {len(df_results)} match results.")

    # update ELO ratings for teams based on matches after their last_match_date
    for team in teams_data:
        if not team.get("diretta_name") or not team.get("diretta_id") or not team.get("id"):
            print(f"Skipping team {team.get('name')} missing diretta_name or id")
            continue
        team_id = team["id"]
        last_match_date = team.get("last_match_date")
        team_elo = team["elo"]

        # filter matches involving this team with date greater than last_match_date
        if last_match_date:
            df_team_matches = df_results[((df_results["team1"] == team_id) | (df_results["team2"] == team_id)) & (df_results["date"] > last_match_date)]
        else:
            # If no last_match_date, process all matches for this team
            df_team_matches = df_results[(df_results["team1"] == team_id) | (df_results["team2"] == team_id)]
        
        df_team_matches = df_team_matches.sort_values(by="date")

        for _, match in df_team_matches.iterrows():
            opponent_id = match["team2"] if match["team1"] == team_id else match["team1"]
            opponent_elo = 200
            for t in teams_data:
                if t["id"] == opponent_id:
                    opponent_elo = t["elo"]
                    break
            result = 1 if match["winner"] == team_id else 0

            new_team_elo, new_opponent_elo = compute_elo(team_elo, opponent_elo, result, 1 - result)
            team_elo = new_team_elo
            opponent_elo = new_opponent_elo

            print(f"Match ID: {match['match_id']}, Opponent: {opponent_id}, Result: {'Win' if result == 1 else 'Loss'}, New ELO: {team_elo:.2f}")

            # update last_match_date and last_match_id
            last_match_date = match["date"]
            last_match_id = match["match_id"]

        # update team's ELO, last_match_id, and last_match_date
        team["elo"] = team_elo
        if not df_team_matches.empty:
            team["last_match_date"] = df_team_matches["date"].max()
            team["last_match_id"] = df_team_matches.loc[df_team_matches["date"] == df_team_matches["date"].max(), "match_id"].iloc[-1]

    # save updated teams.json
    print("Saving updated teams.json...")
    with open("teams.json", "w", encoding="utf-8") as teams_json:
        json.dump(teams_data, teams_json, indent=4, ensure_ascii=False)
    print("teams.json updated.")


if __name__ == "__main__":
    update_results()
    # update_elo_ratings()
