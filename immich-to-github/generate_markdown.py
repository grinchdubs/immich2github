"""Generate markdown for synced photos."""
import json
from pathlib import Path

# Load sync state
state_file = Path(".sync_state.json")
if not state_file.exists():
    print("No sync state file found!")
    exit(1)

with open(state_file, "r") as f:
    state = json.load(f)

# Group assets by folder
folders = {}
for asset_id, asset_data in state["synced_assets"].items():
    github_path = asset_data["github_path"]
    folder = github_path.split("/")[0]
    
    if folder not in folders:
        folders[folder] = []
    folders[folder].append(github_path)

# Generate markdown for Zines, Prints, and Risograph
repo = "grinchdubs/grnch.xyz_photos"
base_url = f"https://raw.githubusercontent.com/{repo}/main"

albums_to_process = ["zines", "prints", "risograph"]

output_file = Path("photo_markdown.txt")
with open(output_file, "w", encoding="utf-8") as out:
    for album in albums_to_process:
        if album not in folders:
            continue
        
        out.write(f"\n## {album.capitalize()}\n\n")
        
        # Sort files alphabetically
        files = sorted(folders[album])
        
        for file_path in files:
            # Skip videos
            if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
                continue
            
            url = f"{base_url}/{file_path}"
            out.write(f"![{file_path}]({url})\n\n")

print(f"Markdown saved to {output_file}")
