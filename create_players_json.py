from nba_api.stats.static import players
import json

# שליפת כל השחקנים הפעילים
all_players = players.get_active_players()

# שמירת JSON
with open("nba_540_players.json", "w", encoding="utf-8") as f:
    json.dump(all_players, f, ensure_ascii=False, indent=4)

print(f"נשמרו {len(all_players)} שחקנים בקובץ nba_540_players.json")
