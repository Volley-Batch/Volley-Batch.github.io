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
from math import erf, sqrt
from typing import Tuple
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
        
        # Skip matches before stats last update (with 2-day buffer)
        if date_text and stats_data.get("last_update"):
            last_update_date_str = stats_data["last_update"].split("T")[0]
            last_update_date = datetime.strptime(last_update_date_str, "%Y-%m-%d")
            match_date = datetime.strptime(date_text, "%Y-%m-%d")
            days_diff = (last_update_date - match_date).days
            if days_diff > 2:
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
    # Sort new data by date
    df_new = df_new.sort_values(by="date").reset_index(drop=True)
    df_results = pd.read_csv(RESULTS_CSV)
    df_update = pd.concat([df_results, df_new]).drop_duplicates(["date", "team1", "team2"]).reset_index(drop=True)
    df_update.to_csv(RESULTS_CSV, index=False)
    print("results.csv updated.")
    
    # Save updated teams.json (in case new teams were added)
    print("Saving updated teams.json...")
    with open("teams.json", "w", encoding="utf-8") as teams_json:
        json.dump(teams_data, teams_json, indent=4, ensure_ascii=False)
    print("teams.json updated.")


# Standard normal CDF
def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))

def compute_elo(team_a_elo: float, team_b_elo: float, score_a: int, score_b: int) -> Tuple[float, float]:
    """
    Compute the new ELO (WR) ratings for two volleyball teams using the FIVB-like method.
    - team_a_elo, team_b_elo: current WR scores (floats)
    - score_a, score_b: sets won by team A and team B respectively (integers 0..3)
    
    Returns:
      (new_team_a_elo, new_team_b_elo) as floats.
    
    Notes:
      - Assumes best-of-5 match (valid set scores are integers 0..3 and one team must have 3).
      - Uses cutpoints C1..C5 = [-1.060, -0.394, 0, 0.394, 1.060] (FIVB example).
      - Standard scaling factor = 8, Match Weight Factor (MWF) = 50.
      - Avoids losing points on a win (or gaining points on a loss) by enforcing minimum point changes (+0.01 for wins, -0.01 for losses).
    """
    # Validate scores
    if not (isinstance(score_a, int) and isinstance(score_b, int)):
        raise ValueError("score_a and score_b must be integers (sets won).")
    if not (0 <= score_a <= 3 and 0 <= score_b <= 3):
        raise ValueError("score_a and score_b must be between 0 and 3.")
    if not (score_a == 3 or score_b == 3):
        raise ValueError("One team must have 3 sets (match winner).")
    if score_a == 3 and score_b == 3:
        raise ValueError("Invalid match: both teams cannot have 3 sets.")

    # Constants
    C1, C2, C3, C4, C5 = -1.060, -0.394, 0.0, 0.394, 1.060
    SCALE = 8.0          # standard scaling factor
    MWF = 50.0           # fixed Match Weight Factor

    # Strength difference △
    delta = 8.0 * (team_a_elo - team_b_elo) / 1000.0

    # Probabilities for team A to produce each specific set-score result:
    # P1 = Prob(3-0 by A), P2 = Prob(3-1 by A), P3 = Prob(3-2 by A),
    # P4 = Prob(2-3 i.e. B wins 3-2), P5 = Prob(1-3 i.e. B wins 3-1), P6 = Prob(0-3 i.e. B wins 3-0)
    phi_c1 = _phi(C1 + delta)
    phi_c2 = _phi(C2 + delta)
    phi_c3 = _phi(C3 + delta)
    phi_c4 = _phi(C4 + delta)
    phi_c5 = _phi(C5 + delta)

    P1 = phi_c1
    P2 = phi_c2 - phi_c1
    P3 = phi_c3 - phi_c2
    P4 = phi_c4 - phi_c3
    P5 = phi_c5 - phi_c4
    P6 = 1.0 - phi_c5

    # Sanity fix: force tiny negatives to zero and renormalize if necessary
    probs = [P1, P2, P3, P4, P5, P6]
    probs = [max(0.0, p) for p in probs]
    total_p = sum(probs)
    if total_p <= 0:
        # fallback to equal probabilities (should not happen)
        probs = [1.0/6.0]*6
    else:
        probs = [p/total_p for p in probs]
    P1, P2, P3, P4, P5, P6 = probs

    # Set Score Variant (SSV) values from perspective of team A:
    # 3-0 => +2, 3-1 => +1.5, 3-2 => +1, 2-3 => -1, 1-3 => -1.5, 0-3 => -2
    ssv_values = [2.0, 1.5, 1.0, -1.0, -1.5, -2.0]

    # Expected Match Result (EMR) for team A
    EMR = P1*ssv_values[0] + P2*ssv_values[1] + P3*ssv_values[2] + P4*ssv_values[3] + P5*ssv_values[4] + P6*ssv_values[5]

    # Actual SSV for the played match (from team A perspective)
    if score_a == 3 and score_b == 0:
        SSV_actual = 2.0
    elif score_a == 3 and score_b == 1:
        SSV_actual = 1.5
    elif score_a == 3 and score_b == 2:
        SSV_actual = 1.0
    elif score_b == 3 and score_a == 2:
        SSV_actual = -1.0
    elif score_b == 3 and score_a == 1:
        SSV_actual = -1.5
    elif score_b == 3 and score_a == 0:
        SSV_actual = -2.0
    else:
        # This should not happen given validation above
        raise ValueError("Unhandled set score combination.")

    # WR value and WR points
    WR_value = SSV_actual - EMR
    WR_points = WR_value * MWF / SCALE  # (WR_value * MWF) / 8

    # Avoid losing points on a win (or gaining points on a loss)
    if WR_points < 0.01 and SSV_actual > 0:
        WR_points = 0.01
        # print in yellow
        print(f"{YELLOW}Note: Adjusted WR points to minimum gain of 0.01 for winning team.{RESET}")
    elif WR_points > -0.01 and SSV_actual < 0:
        WR_points = -0.01
        print(f"{YELLOW}Note: Adjusted WR points to minimum loss of -0.01 for losing team.{RESET}")

    # Update ratings: team A gains WR_points, team B loses the same amount
    new_team_a_elo = team_a_elo + WR_points
    new_team_b_elo = team_b_elo - WR_points

    return new_team_a_elo, new_team_b_elo


def update_elo_ratings():
    """
    Recalculate ELO ratings for all teams based on the updated match results.
    Store the updated ELO ratings in the local data storage.
    """
    print("Updating ELO ratings...")

    # read teams.json
    print("Loading teams from teams.json...")
    teams_json = open("teams.json", "r", encoding="utf-8")
    teams_data = json.load(teams_json)
    teams_json.close()
    # print("Fetched teams:")
    # for team in teams_data:
    #     print(f"- {team['name']} (ID: {team['id']}) (ELO: {team['elo']}) (last_match_id: {team['last_match_id']})")

    # read results.csv
    print("Loading match results from results.csv...")
    df_results = pd.read_csv(RESULTS_CSV)
    print(f"Fetched {len(df_results)} match results.")

    # Get the last processed match ID from stats.json
    last_processed_match_id_from_stats = stats_data.get("last_match_id")
    
    # Track the last match processed in this run
    last_processed_match_id = None
    last_processed_date = None
    
    # Skip matches up to and including the last processed match
    skip_until_found = last_processed_match_id_from_stats is not None
    matches_processed = 0

    # Recalculate ELO ratings using all matches after last update
    for index, match in df_results.iterrows():
        match_id = match["match_id"]
        date = match["date"]
        team1_slug = match["team1"]
        team2_slug = match["team2"]
        team1_sets = match["team1_sets"]
        team2_sets = match["team2_sets"]

        # Skip matches up to and including the last processed match
        if skip_until_found:
            if match_id == last_processed_match_id_from_stats:
                print(f"Found last processed match: {match_id}. Starting from next match...")
                skip_until_found = False
            continue

        # Find teams in teams_data
        team1 = next((t for t in teams_data if f"{t.get('diretta_name', 'unknown')}-{t.get('diretta_id', 'unknown')}" == team1_slug), None)
        team2 = next((t for t in teams_data if f"{t.get('diretta_name', 'unknown')}-{t.get('diretta_id', 'unknown')}" == team2_slug), None)

        if not team1 or not team2:
            print(f"{RED}Warning: Could not find teams for match {match_id}. Skipping ELO update.{RESET}")
            continue

        # Current ELO ratings
        team1_elo = team1.get("elo", 200)
        team2_elo = team2.get("elo", 200)

        # Compute new ELO ratings
        new_team1_elo, new_team2_elo = compute_elo(team1_elo, team2_elo, team1_sets, team2_sets)

        # Update teams data
        team1["elo"] = new_team1_elo
        team2["elo"] = new_team2_elo
        team1["last_match_date"] = date
        team1["last_match_id"] = match_id
        team2["last_match_date"] = date
        team2["last_match_id"] = match_id

        print(f"Updated ELOs for match {match_id}: {team1['name']} ELO {team1_elo:.2f} -> {new_team1_elo:.2f}, {team2['name']} ELO {team2_elo:.2f} -> {new_team2_elo:.2f}")
        print(f"Match {match_id} processed.")

        # Track last processed match
        last_processed_match_id = match_id
        last_processed_date = date
        matches_processed += 1

    print(f"{GREEN}Processed {matches_processed} new matches.{RESET}")

    # save updated teams.json
    print("Saving updated teams.json...")
    with open("teams.json", "w", encoding="utf-8") as teams_json:
        json.dump(teams_data, teams_json, indent=4, ensure_ascii=False)
    print("teams.json updated.")

    # Update stats.json with last update info
    print("Updating stats.json...")
    stats_data["last_update"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if last_processed_match_id:
        stats_data["last_match_id"] = last_processed_match_id
    if last_processed_date:
        stats_data["last_match_date"] = last_processed_date
    
    with open(STATS_JSON, "w", encoding="utf-8") as stats_file:
        json.dump(stats_data, stats_file, indent=4, ensure_ascii=False)
    print("stats.json updated.")


if __name__ == "__main__":
    update_results()
    update_elo_ratings()
