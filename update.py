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
                # Parse URL path to extract team identifiers
                path_parts = urlparse(match_url).path.strip('/').split('/')
                if len(path_parts) >= 4:
                    team1_slug = path_parts[2]  # e.g., "shahdab-yazd-4vVpW8mC"
                    team2_slug = path_parts[3]  # e.g., "trentino-CffxNRaH"
                    
                    team1_id = team1_slug.split('-')[-1]
                    team2_id = team2_slug.split('-')[-1]
                    
                    # Match display names with names in team data of team id
                    team1_names = []
                    team2_names = []
                    team1_obj = None
                    team2_obj = None
                    for team in teams_data:
                        if team.get("diretta_id") == team1_id:
                            team1_names = team.get("names", [])
                            team1_obj = team
                        if team.get("diretta_id") == team2_id:
                            team2_names = team.get("names", [])
                            team2_obj = team
                    
                    # Check if teams are in teams_data, if not add them
                    team1_found = False
                    team2_found = False
                    for team in teams_data:
                        if team.get("diretta_id") == team1_id:
                            team1_found = True
                        if team.get("diretta_id") == team2_id:
                            team2_found = True
                    
                    # First, match display names to determine which team is which
                    # This must be done BEFORE adding missing teams
                    home_is_team1 = None
                    if home_display and away_display:
                        # Normalize names for comparison
                        home_norm = normalize_text(home_display)
                        away_norm = normalize_text(away_display)
                        
                        if team1_names and any(normalize_text(name) in home_norm for name in team1_names):
                            home_is_team1 = True
                        elif team2_names and any(normalize_text(name) in home_norm for name in team2_names):
                            home_is_team1 = False
                        elif team1_names and any(normalize_text(name) in away_norm for name in team1_names):
                            home_is_team1 = False
                        elif team2_names and any(normalize_text(name) in away_norm for name in team2_names):
                            home_is_team1 = True
                    
                    # Update existing team names if they have encoding issues
                    # (if the display name normalizes better than the stored name)
                    if team1_obj and home_is_team1 is not None:
                        team1_display = home_display if home_is_team1 else away_display
                        if team1_display and team1_names:
                            # Check if any stored name has encoding issues (contains unicode escape sequences when printed)
                            if any('\u00c3' in name or '\u0192' in name or '\u00c2' in name for name in team1_names):
                                print(f"Updating team name from '{team1_obj['name']}' to '{team1_display}' (fixing encoding)")
                                team1_obj['name'] = team1_display
                                team1_obj['names'] = [team1_display]
                                team1_names = [team1_display]
                    
                    if team2_obj and home_is_team1 is not None:
                        team2_display = away_display if home_is_team1 else home_display
                        if team2_display and team2_names:
                            # Check if any stored name has encoding issues
                            if any('\u00c3' in name or '\u0192' in name or '\u00c2' in name for name in team2_names):
                                print(f"Updating team name from '{team2_obj['name']}' to '{team2_display}' (fixing encoding)")
                                team2_obj['name'] = team2_display
                                team2_obj['names'] = [team2_display]
                                team2_names = [team2_display]
                    
                    # Add missing teams to teams_data with correct names
                    # Note: Automatically added teams do NOT get an "id" field, only "diretta_id"
                    # This way they will be skipped when fetching matches
                    if not team1_found:
                        # Determine which display name corresponds to team1
                        team1_display_name = home_display if home_is_team1 else away_display if home_is_team1 is not None else home_display
                        print(f"Adding new team to teams.json: {team1_display_name} (diretta_id: {team1_id})")
                        new_team = {
                            "name": team1_display_name,
                            "names": [team1_display_name],
                            "diretta_id": team1_id,
                            "diretta_name": '-'.join(team1_slug.split('-')[:-1]),
                            "elo": 500,
                            "last_match_date": None,
                            "last_match_id": None
                        }
                        teams_data.append(new_team)
                        team1_names = [team1_display_name]
                    
                    if not team2_found:
                        # Determine which display name corresponds to team2
                        team2_display_name = away_display if home_is_team1 else home_display if home_is_team1 is not None else away_display
                        print(f"Adding new team to teams.json: {team2_display_name} (diretta_id: {team2_id})")
                        new_team = {
                            "name": team2_display_name,
                            "names": [team2_display_name],
                            "diretta_id": team2_id,
                            "diretta_name": '-'.join(team2_slug.split('-')[:-1]),
                            "elo": 500,
                            "last_match_date": None,
                            "last_match_id": None
                        }
                        teams_data.append(new_team)
                        team2_names = [team2_display_name]
                    
                    # Now match display names to determine home/away slugs
                    # Use normalized text for comparison
                    home_norm = normalize_text(home_display) if home_display else ""
                    away_norm = normalize_text(away_display) if away_display else ""
                    team1_names_norm = [normalize_text(name) for name in team1_names]
                    team2_names_norm = [normalize_text(name) for name in team2_names]
                    
                    if home_display and team1_names_norm and any(name in home_norm for name in team1_names_norm) and away_display and team2_names_norm and any(name in away_norm for name in team2_names_norm):
                        home = team1_slug
                        away = team2_slug
                    elif home_display and team2_names_norm and any(name in home_norm for name in team2_names_norm) and away_display and team1_names_norm and any(name in away_norm for name in team1_names_norm):
                        home = team2_slug
                        away = team1_slug
                    else:
                        # Fallback: use the slugs anyway since we now have the teams in teams_data
                        print(f"{RED}Warning: Could not match team names from URL to display names: {team1_slug}, {team2_slug} vs {home_display}, {away_display}{RESET}")
                        home = team1_slug
                        away = team2_slug
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

        results.append({
            "match_id": mid or None,
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

    # get current match ids from results.csv. If no results, start from 0
    df_results = pd.read_csv(RESULTS_CSV)
    current_match_id = df_results["match_id"].max() if not df_results.empty else 0
    print(f"Current max match_id in results.csv: {current_match_id}")

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
            match_id = current_match_id + 1
            current_match_id += 1
            data.append([match_id, match["date"], match["home"], match["away"], match["home_sets"], match["away_sets"], match["winner"]])
    
    print(f"Fetched {len(data)} new match results.")

   # update results.csv
    print("Updating results.csv...")
    df_new = pd.DataFrame(data, columns=["match_id", "date", "team1", "team2", "team1_sets", "team2_sets", "winner"])
    df_results = pd.read_csv(RESULTS_CSV)
    df_update = pd.concat([df_results, df_new]).drop_duplicates(["date", "team1", "team2"]).reset_index(drop=True)
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

    # update ELO ratings for teams whose last_match_id is less than the latest match_id in results.csv
    for team in teams_data:
        if not team.get("diretta_name") or not team.get("diretta_id") or not team.get("id"):
            print(f"Skipping team {team.get('name')} missing diretta_name or id")
            continue
        team_id = team["id"]
        last_match_id = team["last_match_id"]
        team_elo = team["elo"]

        # filter matches involving this team with match_id greater than last_match_id
        df_team_matches = df_results[((df_results["team1"] == team_id) | (df_results["team2"] == team_id)) & (df_results["match_id"] > last_match_id)]
        df_team_matches = df_team_matches.sort_values(by="match_id")

        for _, match in df_team_matches.iterrows():
            opponent_id = match["team2"] if match["team1"] == team_id else match["team1"]
            opponent_elo = 500
            for t in teams_data:
                if t["id"] == opponent_id:
                    opponent_elo = t["elo"]
                    break
            result = 1 if match["winner"] == team_id else 0

            new_team_elo, new_opponent_elo = compute_elo(team_elo, opponent_elo, result, 1 - result)
            team_elo = new_team_elo
            opponent_elo = new_opponent_elo

            print(f"Match ID: {match['match_id']}, Opponent: {opponent_id}, Result: {'Win' if result == 1 else 'Loss'}, New ELO: {team_elo:.2f}")

            # update last_match_id
            last_match_id = match["match_id"]

        # update team's ELO, last_match_id, and last_match_date
        team["elo"] = round(team_elo)
        team["last_match_id"] = last_match_id
        if not df_team_matches.empty:
            last_match_date = df_team_matches["last_match_date"].max()
            team["last_match_date"] = last_match_date

    # save updated teams.json
    print("Saving updated teams.json...")
    with open("teams.json", "w") as teams_json:
        json.dump(teams_data, teams_json, indent=4)
    print("teams.json updated.")


if __name__ == "__main__":
    update_results()
    update_elo_ratings()
