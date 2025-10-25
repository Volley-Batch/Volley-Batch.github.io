"""
This is the main backend module.
It handles updates of new results, computation of ELO, and data storage.
"""

def update_results():
    """
    For each team, fetch the latest match results from the web source.
    Update the local data with any new results found.
    """
    # TODO: Implement


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
    # TODO: Implement


if __name__ == "__main__":
    
    update_results()
    update_elo_ratings()
