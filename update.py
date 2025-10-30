"""
This is the main backend module.
It handles updates of new results, computation of ELO, and data storage.
"""

import pandas as pd
import random
import json
from datetime import datetime, timedelta


# -- CONFIG --
API_URL = "https://api.example.com/volleyball/matches/latest"
API_KEY = "YOUR_API_KEY_HERE"
RESULTS_CSV = "results.csv"

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
    teams = [team["id"] for team in teams_data]

    print("Fetched teams:")
    for team in teams_data:
        print(f"- {team['name']} (ID: {team['id']}) (ELO: {team['elo']}) (last_match_id: {team['last_match_id']})")

    print("Get latest match results from API...")
    # create 10 random matches
    data = []
    for _ in range(10):
        date = (datetime.now() - timedelta(days=random.randint(0,350))).strftime("%Y-%m-%d")
        match_id = current_match_id + 1
        current_match_id += 1
        team1, team2 = random.sample(teams, 2)
        team1_sets = 0
        team2_sets = 0

        # set 1
        team1_set1 = 0
        team2_set1 = 0
        winner_set = random.choices([1,2])[0]
        if winner_set == 1:
            team1_sets += 1
            team1_set1 = 25
            team2_set1 = random.randint(0,24)
        else:
            team2_sets += 1
            team2_set1 = 25
            team1_set1 = random.randint(0,24)
            
        # set 2
        team1_set2 = 0
        team2_set2 = 0
        winner_set = random.choices([1,2])[0]
        if winner_set == 1:
            team1_sets += 1
            team1_set2 = 25
            team2_set2 = random.randint(0,24)
        else:
            team2_sets += 1
            team2_set2 = 25
            team1_set2 = random.randint(0,24)
        
        # set 3
        team1_set3 = 0
        team2_set3 = 0
        winner_set = random.choices([1,2])[0]
        if winner_set == 1:
            team1_sets += 1
            team1_set3 = 25
            team2_set3 = random.randint(0,24)
        else:
            team2_sets += 1
            team2_set3 = 25
            team1_set3 = random.randint(0,24)
        
        team1_set4 = 0
        team2_set4 = 0
        team1_set5 = 0
        team2_set5 = 0
        if team1_sets == 3:
            winner = team1
        elif team2_sets == 3:
            winner = team2
        else:
            # set 4
            winner_set = random.choices([1,2])[0]
            if winner_set == 1:
                team1_sets += 1
                team1_set4 = 25
                team2_set4 = random.randint(0,24)
            else:
                team2_sets += 1
                team2_set4 = 25
                team1_set4 = random.randint(0,24)
            
            if team1_sets == 3:
                winner = team1
            elif team2_sets == 3:
                winner = team2
            else:
                # set 5
                winner_set = random.choices([1,2])[0]
                if winner_set == 1:
                    team1_sets += 1
                    team1_set5 = 15
                    team2_set5 = random.randint(0,14)
                else:
                    team2_sets += 1
                    team2_set5 = 15
                    team1_set5 = random.randint(0,14)
                
                if team1_sets == 3:
                    winner = team1
                else:
                    winner = team2

        data.append([match_id, date, "Superlega", team1, team2, team1_sets, team2_sets, team1_set1, team2_set1, team1_set2, team2_set2, team1_set3, team2_set3, team1_set4, team2_set4, team1_set5, team2_set5, winner])
    
    print(f"Fetched {len(data)} new match results.")
    for match in data:
        print(f"- Match ID: {match[0]}, Date: {match[1]}, {match[3]} vs {match[4]}, Score: {match[5]}-{match[6]}, Winner: {match[17]}")
    
    # update results.csv
    print("Updating results.csv...")
    df_new = pd.DataFrame(data, columns=["match_id", "date", "league", "team1", "team2", "team1_sets", "team2_sets", "team1_set1", "team2_set1", "team1_set2", "team2_set2", "team1_set3", "team2_set3", "team1_set4", "team2_set4", "team1_set5", "team2_set5", "winner"])
    df_results = pd.read_csv(RESULTS_CSV)
    df_update = pd.concat([df_results, df_new]).drop_duplicates().reset_index(drop=True)
    df_update.to_csv(RESULTS_CSV, index=False)
    print("results.csv updated.")


def compute_elo(team_a_elo, team_b_elo, score_a, score_b):
    """
    Compute the new ELO ratings for two teams based on their match result.
    """
    # TODO: Implement
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
    print("Fetched teams:")
    for team in teams_data:
        print(f"- {team['name']} (ID: {team['id']}) (ELO: {team['elo']}) (last_match_id: {team['last_match_id']})")

    # read results.csv
    print("Loading match results from results.csv...")
    df_results = pd.read_csv(RESULTS_CSV)
    print(f"Fetched {len(df_results)} match results.")

    # update ELO ratings for teams whose last_match_id is less than the latest match_id in results.csv
    for team in teams_data:
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

            # ELO calculation
            K = 30
            expected_score = 1 / (1 + 10 ** ((opponent_elo - team_elo) / 400))
            team_elo += K * (result - expected_score)

            print(f"Match ID: {match['match_id']}, Opponent: {opponent_id}, Result: {'Win' if result == 1 else 'Loss'}, New ELO: {team_elo:.2f}")

            # update last_match_id
            last_match_id = match["match_id"]

        # update team's ELO and last_match_id
        team["elo"] = round(team_elo)
        team["last_match_id"] = last_match_id

    # save updated teams.json
    print("Saving updated teams.json...")
    with open("teams.json", "w") as teams_json:
        json.dump(teams_data, teams_json, indent=4)
    print("teams.json updated.")


if __name__ == "__main__":
    update_results()
    update_elo_ratings()
