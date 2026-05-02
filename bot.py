import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timezone
import zoneinfo
import uuid
import re
import csv
import io

# --- SYSTEM CONSTANTS & COLORS ---
FILE_NAME = "database.json"
TEMP_FILE = "database.json.tmp"

COLOR_SYSTEM = 0x1A1A2E
COLOR_ERROR = 0xE63946
COLOR_SUCCESS = 0x2DC653
COLOR_WARNING = 0xF4A261
COLOR_UNGRADED = 0xB0B0B0

DEFAULT_DB = {
    "config": {
        "timezone": "UTC",
        "announcement_channel": None,
        "dev_role_id": None,
        "default_multiplier": 1,
        "max_ocs_per_user": 5,
        "allow_negative_points": False,
        "reveal_color": "#8A2BE2"
    },
    "grades": {},
    "ocs": {},
    "archived_ocs": {},
    "voting": {
        "is_open": False,
        "multiplier": 1,
        "cap": 0,
        "votes": {}
    },
    "dorms": {},
    "rank_snapshots": [],
    "point_log": []
}

# --- DATABASE MANAGEMENT ---
def load_db():
    if not os.path.exists(FILE_NAME):
        save_db(DEFAULT_DB)
        return DEFAULT_DB
    try:
        with open(FILE_NAME, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Schema validation: Ensure all top-level keys exist
            for key in DEFAULT_DB:
                if key not in data:
                    data[key] = DEFAULT_DB[key]
            return data
    except json.JSONDecodeError:
        print("CRITICAL: Malformed JSON. Halting startup to prevent data corruption.")
        exit(1)

def save_db(data):
    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(TEMP_FILE, FILE_NAME)

db = load_db()

# --- HELPERS ---
def get_tz():
    try:
        return zoneinfo.ZoneInfo(db["config"]["timezone"])
    except:
        return timezone.utc

def get_now():
    return datetime.now(get_tz())

def format_ts(dt=None):
    if dt is None: dt = get_now()
    return dt.strftime("%b %d, %Y · %H:%M %Z")

def calculate_age(bday_str):
    try:
        # Accepts YYYY-MM-DD or MM/DD/YYYY
        if "-" in bday_str:
            bday = datetime.strptime(bday_str, "%Y-%m-%d").date()
        else:
            bday = datetime.strptime(bday_str, "%m/%d/%Y").date()
        today = get_now().date()
        return today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
    except:
        return "?"

def get_embed(title, desc="", color=COLOR_SYSTEM):
    embed = discord.Embed(title=title, description=desc, color=color)
    embed.set_footer(text=f"SurvivalShowSim · Korean Survival Show Sim · {format_ts()}")
    return embed

def hex_to_int(hex_str):
    return int(hex_str.lstrip('#'), 16) if hex_str else COLOR_UNGRADED

def recalculate_ranks():
    active_ocs = list(db["ocs"].values())
    # Sort: Total Points DESC, Registration Time ASC
    active_ocs.sort(key=lambda x: (-x["total_points"], x["registered_at"]))
    
    for i, oc in enumerate(active_ocs):
        db["ocs"][oc["id"]]["rank"] = i + 1
    save_db(db)

def get_snapshot_diff(oc_id, current_rank):
    if not db["rank_snapshots"]: return "🆕"
    last_snap = db["rank_snapshots"][-1]["rankings"]
    if oc_id not in last_snap: return "🆕"
    old_rank = last_snap[oc_id]["rank"]
    diff = old_rank - current_rank
    if diff > 0: return f"▲ {diff}"
    elif diff < 0: return f"▼ {abs(diff)}"
    return "—"

# --- PERMISSIONS ---
def is_dev():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.client.application.owner.id:
            return True
        dev_role = db["config"]["dev_role_id"]
        if dev_role and any(role.id == dev_role for role in interaction.user.roles):
            return True
        await interaction.response.send_message(
            embed=get_embed("Access Denied", "🔒 *This command is restricted to show staff. Please contact a Dev if you believe this is an error.*", COLOR_ERROR),
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

# --- BOT SETUP ---
class SurvivalBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Bot synced and ready. Loaded {len(db['ocs'])} OCs.")

bot = SurvivalBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure): return
    err_embed = get_embed("System Error", f"An unexpected error occurred.\n```{error}```", COLOR_ERROR)
    if interaction.response.is_done():
        await interaction.followup.send(embed=err_embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=err_embed, ephemeral=True)


# ==========================================
# 1. OC REGISTRATION & MANAGEMENT
# ==========================================
oc_group = app_commands.Group(name="oc", description="OC Management commands")

@oc_group.command(name="register", description="Register a new Trainee")
async def oc_register(interaction: discord.Interaction, name: str, birthday: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, ethnicity: str = "N/A", form_link: str = ""):
    user_ocs = [oc for oc in db["ocs"].values() if oc["owner_id"] == interaction.user.id]
    if len(user_ocs) >= db["config"]["max_ocs_per_user"]:
        return await interaction.response.send_message(embed=get_embed("Registration Failed", f"⛔ *You've already reached the maximum of {db['config']['max_ocs_per_user']} Trainees. Please retire or remove one before registering a new one.*", COLOR_ERROR), ephemeral=True)
    
    if any(oc["name"].lower() == name.lower() and oc["owner_id"] == interaction.user.id for oc in db["ocs"].values()):
        return await interaction.response.send_message(embed=get_embed("Registration Failed", f"You already have a Trainee named '{name}'. Please use a unique name.", COLOR_ERROR), ephemeral=True)

    if form_link and not form_link.startswith("http"):
        return await interaction.response.send_message(embed=get_embed("Invalid Link", "Please provide a valid URL starting with http/https.", COLOR_ERROR), ephemeral=True)

    oc_id = str(uuid.uuid4())
    new_oc = {
        "id": oc_id, "name": name, "owner_id": interaction.user.id, "owner_name": interaction.user.name,
        "birthday": birthday, "gender": gender, "pronouns": pronouns, "faceclaim": faceclaim,
        "main_skill": main_skill, "nationality": nationality, "ethnicity": ethnicity, "form_link": form_link,
        "grade": None, "voting_points": 0, "mission_points": 0, "total_points": 0, "rank": 0,
        "dorm_floor": None, "dorm_room": None, "registered_at": get_now().isoformat()
    }
    
    db["ocs"][oc_id] = new_oc
    recalculate_ranks()
    
    await interaction.response.send_message(embed=build_profile_embed(new_oc))

def build_profile_embed(oc):
    grade_emoji = "⭐"
    color = COLOR_UNGRADED
    if oc["grade"] and oc["grade"] in db["grades"]:
        color = hex_to_int(db["grades"][oc["grade"]])
        grade_emoji = oc["grade"]

    age = calculate_age(oc["birthday"])
    embed = get_embed(f"{oc['name']} {grade_emoji}", color=color)
    
    embed.add_field(name="🎂 Birthday · Age", value=f"{oc['birthday']} · {age} yrs", inline=True)
    embed.add_field(name="🪪 Gender · Pronouns", value=f"{oc['gender']} · {oc['pronouns']}", inline=True)
    embed.add_field(name="🎭 Faceclaim", value=oc["faceclaim"], inline=True)
    embed.add_field(name="🎤 Main Skill", value=oc["main_skill"], inline=True)
    embed.add_field(name="🌏 Nationality · Ethnicity", value=f"{oc['nationality']} · {oc['ethnicity']}", inline=True)
    if oc["form_link"]:
        embed.add_field(name="🔗 Profile", value=f"[View Full Profile]({oc['form_link']})", inline=True)
    
    embed.add_field(name="📊 Points & Rank", value=f"{oc['total_points']:,} pts · Rank #{oc['rank']}", inline=False)
    embed.add_field(name="🏷️ Grade", value=oc["grade"] if oc["grade"] else "Ungraded", inline=True)
    dorm_val = f"Floor {oc['dorm_floor']} · Room {oc['dorm_room']}" if oc["dorm_room"] else "Unassigned"
    embed.add_field(name="🏠 Dorm", value=dorm_val, inline=True)
    
    dt = datetime.fromisoformat(oc["registered_at"]).astimezone(get_tz())
    embed.set_footer(text=f"Registered by @{oc['owner_name']} · {format_ts(dt)}")
    return embed

@oc_group.command(name="profile", description="View a Trainee's profile")
async def oc_profile(interaction: discord.Interaction, name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == name.lower()]
    if not matches:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{name}' was found. Check spelling.", COLOR_ERROR), ephemeral=True)
    await interaction.response.send_message(embed=build_profile_embed(matches[0]))

@oc_group.command(name="remove", description="Archive your Trainee permanently")
async def oc_remove(interaction: discord.Interaction, name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == name.lower() and oc["owner_id"] == interaction.user.id]
    if not matches:
        return await interaction.response.send_message(embed=get_embed("Not Found", "You do not own a Trainee by that name.", COLOR_ERROR), ephemeral=True)
    
    oc = matches[0]
    # Remove from dorms
    if oc["dorm_floor"] and oc["dorm_room"]:
        try:
            db["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
        except ValueError: pass

    db["archived_ocs"][oc["id"]] = oc
    del db["ocs"][oc["id"]]
    recalculate_ranks()
    await interaction.response.send_message(embed=get_embed("Trainee Archived", f"*{oc['name']} has left the program.*", COLOR_SUCCESS))

bot.tree.add_command(oc_group)


# ==========================================
# 2. VOTING SYSTEM
# ==========================================
vote_group = app_commands.Group(name="voting", description="Voting System management")

@bot.tree.command(name="vote", description="Cast a vote for a Trainee")
async def vote_cmd(interaction: discord.Interaction, oc_name: str):
    if not db["voting"]["is_open"]:
        return await interaction.response.send_message(embed=get_embed("Voting Closed", "🚫 *Voting is currently closed. Stay tuned for the next evaluation period.*", COLOR_WARNING), ephemeral=True)
    
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}' found.", COLOR_ERROR), ephemeral=True)
    
    oc = matches[0]
    uid_str = str(interaction.user.id)
    
    # Cap check (simplified for tracking globally per user in this round)
    if "user_votes" not in db["voting"]: db["voting"]["user_votes"] = {}
    if db["voting"]["cap"] > 0:
        if db["voting"]["user_votes"].get(uid_str, 0) >= db["voting"]["cap"]:
            return await interaction.response.send_message(embed=get_embed("Cap Reached", "You have reached your vote limit for this round.", COLOR_ERROR), ephemeral=True)
    
    db["voting"]["user_votes"][uid_str] = db["voting"]["user_votes"].get(uid_str, 0) + 1
    db["voting"]["votes"][oc["id"]] = db["voting"]["votes"].get(oc["id"], 0) + 1
    save_db(db)
    
    await interaction.response.send_message(embed=get_embed("Vote Cast", f"Your vote for **{oc['name']}** has been recorded.", COLOR_SUCCESS), ephemeral=True)

@vote_group.command(name="open", description="[DEV] Open the voting round")
@is_dev()
async def vote_open(interaction: discord.Interaction):
    db["voting"]["is_open"] = True
    db["voting"]["votes"] = {}
    db["voting"]["user_votes"] = {}
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Voting Opened", "The voting round has officially begun.", COLOR_SUCCESS))

@vote_group.command(name="close", description="[DEV] Close the voting round and apply points")
@is_dev()
async def vote_close(interaction: discord.Interaction):
    db["voting"]["is_open"] = False
    multiplier = db["voting"]["multiplier"]
    
    for oc_id, v_count in db["voting"]["votes"].items():
        if oc_id in db["ocs"]:
            added_pts = v_count * multiplier
            db["ocs"][oc_id]["voting_points"] += added_pts
            db["ocs"][oc_id]["total_points"] += added_pts
    
    recalculate_ranks()
    save_db(db)
    
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    await channel.send(embed=get_embed("Voting Closed", f"The voting round is over. A {multiplier}x multiplier was applied. Ranks have been updated.", COLOR_SYSTEM))
    await interaction.response.send_message("Round closed.", ephemeral=True)

@vote_group.command(name="config", description="[DEV] Configure voting settings")
@is_dev()
async def vote_cfg(interaction: discord.Interaction, multiplier: int = None, cap: int = None):
    if multiplier is not None: db["voting"]["multiplier"] = multiplier
    if cap is not None: db["voting"]["cap"] = cap
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Config Updated", f"Multiplier: {db['voting']['multiplier']}x\nCap: {db['voting']['cap']} (0=unlimited)", COLOR_SUCCESS), ephemeral=True)

bot.tree.add_command(vote_group)


# ==========================================
# 3. POINT SYSTEM
# ==========================================
@bot.tree.command(name="points", description="[DEV] Modify Trainee points")
@app_commands.describe(action="add, deduct, multiply, set")
@is_dev()
async def points_cmd(interaction: discord.Interaction, oc_name: str, action: str, value: int):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches:
        return await interaction.response.send_message("OC not found.", ephemeral=True)
    
    oc = matches[0]
    pts_before = oc["total_points"]
    
    if action == "add":
        oc["mission_points"] += value
        oc["total_points"] += value
    elif action == "deduct":
        oc["total_points"] -= value
        if not db["config"]["allow_negative_points"] and oc["total_points"] < 0:
            oc["total_points"] = 0
    elif action == "multiply":
        oc["total_points"] = round(oc["total_points"] * value)
    elif action == "set":
        oc["total_points"] = value
    else:
        return await interaction.response.send_message("Invalid action.", ephemeral=True)
    
    db["point_log"].append({
        "timestamp": get_now().isoformat(), "dev_id": interaction.user.id, "dev_name": interaction.user.name,
        "oc_name": oc["name"], "action": action, "value": value,
        "points_before": pts_before, "points_after": oc["total_points"]
    })
    
    recalculate_ranks()
    await interaction.response.send_message(embed=get_embed("Points Updated", f"**{oc['name']}** points updated: {pts_before} -> {oc['total_points']}", COLOR_SUCCESS))


# ==========================================
# 4. GRADE SYSTEM
# ==========================================
grade_group = app_commands.Group(name="grade", description="[DEV] Grade System Management")

@grade_group.command(name="create", description="[DEV] Create a new grade tier")
@is_dev()
async def grade_create(interaction: discord.Interaction, label: str, hex_color: str):
    if not re.match(r"^#[0-9A-Fa-f]{6}$", hex_color):
        return await interaction.response.send_message(embed=get_embed("Invalid Color", f"'{hex_color}' is not a valid hex color code. Format: #RRGGBB", COLOR_ERROR), ephemeral=True)
    db["grades"][label] = hex_color
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Grade Created", f"Grade **{label}** mapped to {hex_color}.", hex_to_int(hex_color)))

@grade_group.command(name="assign", description="[DEV] Assign a grade to a Trainee")
@is_dev()
async def grade_assign(interaction: discord.Interaction, oc_name: str, label: str):
    if label not in db["grades"]:
        return await interaction.response.send_message("Grade not found.", ephemeral=True)
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches:
        return await interaction.response.send_message("OC not found.", ephemeral=True)
    
    matches[0]["grade"] = label
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Class Evaluation Complete", f"**{matches[0]['name']}** has been assigned to **Grade {label}**.", hex_to_int(db['grades'][label])))

bot.tree.add_command(grade_group)


# ==========================================
# 5. DORMITORY SYSTEM
# ==========================================
dorm_group = app_commands.Group(name="dorm", description="[DEV] Dormitory Management")

@dorm_group.command(name="createfloor", description="[DEV] Create a new dorm floor")
@is_dev()
async def dorm_createfloor(interaction: discord.Interaction, floor_name: str):
    if floor_name in db["dorms"]:
        return await interaction.response.send_message("Floor already exists.", ephemeral=True)
    db["dorms"][floor_name] = {"rooms": {}}
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Floor Created", f"Floor {floor_name} added.", COLOR_SUCCESS))

@dorm_group.command(name="createroom", description="[DEV] Create a room on a floor")
@is_dev()
async def dorm_createroom(interaction: discord.Interaction, floor_name: str, room_name: str, capacity: int):
    if floor_name not in db["dorms"]: return await interaction.response.send_message("Floor not found.", ephemeral=True)
    db["dorms"][floor_name]["rooms"][room_name] = {"capacity": capacity, "occupants": []}
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Room Created", f"{room_name} created on {floor_name} (Cap: {capacity}).", COLOR_SUCCESS))

@dorm_group.command(name="assign", description="[DEV] Assign a Trainee to a room")
@is_dev()
async def dorm_assign(interaction: discord.Interaction, oc_name: str, floor_name: str, room_name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message("OC not found.", ephemeral=True)
    try:
        room = db["dorms"][floor_name]["rooms"][room_name]
    except KeyError:
        return await interaction.response.send_message("Floor/Room not found.", ephemeral=True)
    
    if len(room["occupants"]) >= room["capacity"]:
        return await interaction.response.send_message(embed=get_embed("Capacity Error", f"Room {room_name} is at full capacity.", COLOR_ERROR), ephemeral=True)
    
    oc = matches[0]
    # Remove from old room
    if oc["dorm_floor"]:
        try: db["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
        except: pass
    
    room["occupants"].append(oc["id"])
    oc["dorm_floor"] = floor_name
    oc["dorm_room"] = room_name
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Dorm Assigned", f"**{oc['name']}** placed in {floor_name} - {room_name}.", COLOR_SUCCESS))

@dorm_group.command(name="view", description="Publicly view dormitory assignments")
async def dorm_view(interaction: discord.Interaction):
    embed = get_embed("Dormitory Assignments")
    for fname, fval in db["dorms"].items():
        desc = ""
        for rname, rval in fval["rooms"].items():
            occupant_names = [db["ocs"][oid]["name"] for oid in rval["occupants"] if oid in db["ocs"]]
            occ_str = ", ".join(occupant_names) if occupant_names else "Empty"
            desc += f"**{rname}** ({len(rval['occupants'])}/{rval['capacity']}): {occ_str}\n"
        embed.add_field(name=f"Floor {fname}", value=desc or "No rooms.", inline=False)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(dorm_group)


# ==========================================
# 6. RANKING SYSTEM REVEALS
# ==========================================
rank_group = app_commands.Group(name="rankings", description="Ranking Reveals")

@rank_group.command(name="private", description="[DEV] Save snapshot and view private rankings")
@is_dev()
async def rank_priv(interaction: discord.Interaction):
    recalculate_ranks()
    
    # Save Snapshot
    snap_data = {oc["id"]: {"rank": oc["rank"], "points": oc["total_points"]} for oc in db["ocs"].values()}
    db["rank_snapshots"].append({
        "timestamp": get_now().isoformat(),
        "trigger": "RANKINGS_PRIVATE_COMMAND",
        "rankings": snap_data
    })
    save_db(db)
    
    embed = get_embed("Private Evaluation Standings", "Current Live Rankings:")
    active_ocs = sorted(db["ocs"].values(), key=lambda x: x["rank"])
    
    desc = ""
    for oc in active_ocs:
        change = get_snapshot_diff(oc["id"], oc["rank"])
        grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
        desc += f"`{oc['rank']:02d}` {change} | **{oc['name']}** {grade_str} - {oc['total_points']:,} pts\n"
    
    embed.description = desc
    await interaction.response.send_message(embed=embed, ephemeral=True)

@rank_group.command(name="reveal", description="[DEV] Dramatic full ranking reveal")
@is_dev()
async def rank_reveal(interaction: discord.Interaction):
    await interaction.response.send_message(embed=get_embed("Evaluation Begins", "🎬 *The moment you've all been waiting for… The evaluation results are in.*", hex_to_int(db["config"]["reveal_color"])))
    
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    active_ocs = sorted(db["ocs"].values(), key=lambda x: x["rank"], reverse=True) # Reverse for suspense
    
    # Batches of 7
    for i in range(0, len(active_ocs), 7):
        batch = active_ocs[i:i+7]
        embed = get_embed("Rankings Reveal", color=hex_to_int(db["config"]["reveal_color"]))
        for oc in batch:
            grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
            embed.add_field(name=f"Rank #{oc['rank']} {grade_str}", value=f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}>", inline=False)
        await asyncio.sleep(3)
        await channel.send(embed=embed)
    
    await asyncio.sleep(3)
    await channel.send(embed=get_embed("Evaluation Concluded", "👑 *Congratulations to our top Trainee! Your hard work has paid off.*", COLOR_SUCCESS))

@rank_group.command(name="partialreveal", description="[DEV] Dramatic reveal for specific ranks (e.g. '1 5 10')")
@is_dev()
async def rank_partial(interaction: discord.Interaction, ranks: str):
    await interaction.response.defer()
    try:
        target_ranks = sorted([int(r) for r in ranks.split()], reverse=True)
    except:
        return await interaction.followup.send("Invalid format. Use space-separated numbers (e.g., '1 2 5').")

    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    active_ocs = {oc["rank"]: oc for oc in db["ocs"].values()}
    
    valid_ocs = [active_ocs[r] for r in target_ranks if r in active_ocs]
    
    for i in range(0, len(valid_ocs), 7):
        batch = valid_ocs[i:i+7]
        embed = get_embed("Partial Evaluation Results", color=hex_to_int(db["config"]["reveal_color"]))
        for oc in batch:
            change = get_snapshot_diff(oc["id"], oc["rank"])
            grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
            embed.add_field(name=f"Rank #{oc['rank']} {grade_str} ({change})", value=f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}>", inline=False)
        await asyncio.sleep(3)
        await channel.send(embed=embed)
    
    await interaction.followup.send("Partial reveal complete.", ephemeral=True)

bot.tree.add_command(rank_group)


# ==========================================
# 7. EXPORT SYSTEM
# ==========================================
@bot.tree.command(name="export", description="[DEV] Export bot data to TSV")
@is_dev()
async def export_data(interaction: discord.Interaction):
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    
    # SECTION 1
    writer.writerow(["=== SECTION 1: CURRENT RANKINGS SUMMARY ==="])
    writer.writerow(["rank", "oc_name", "owner_discord_id", "owner_username", "grade", "total_points", "voting_points", "mission_points", "rank_change", "dorm_floor", "dorm_room", "registered_at"])
    for oc in sorted(db["ocs"].values(), key=lambda x: x["rank"]):
        change = get_snapshot_diff(oc["id"], oc["rank"])
        writer.writerow([oc["rank"], oc["name"], oc["owner_id"], oc["owner_name"], oc["grade"] or "", oc["total_points"], oc["voting_points"], oc["mission_points"], change, oc["dorm_floor"] or "", oc["dorm_room"] or "", oc["registered_at"]])
    
    # SECTION 2
    output.write("\n")
    writer.writerow(["=== SECTION 2: RANK HISTORY ==="])
    writer.writerow(["oc_name", "snapshot_timestamp", "snapshot_trigger", "rank_at_snapshot", "points_at_snapshot"])
    for snap in db["rank_snapshots"]:
        for oc_id, stats in snap["rankings"].items():
            name = db["ocs"].get(oc_id, db["archived_ocs"].get(oc_id, {"name": "Unknown"}))["name"]
            writer.writerow([name, snap["timestamp"], snap["trigger"], stats["rank"], stats["points"]])
            
    # SECTION 3
    output.write("\n")
    writer.writerow(["=== SECTION 3: POINT MANIPULATION LOG ==="])
    writer.writerow(["timestamp", "dev_discord_id", "dev_username", "oc_name", "action", "value", "points_before", "points_after"])
    for log in db["point_log"]:
        writer.writerow([log["timestamp"], log["dev_id"], log["dev_name"], log["oc_name"], log["action"], log["value"], log["points_before"], log["points_after"]])
    
    # Send File
    output.seek(0)
    file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"rankings_export_{get_now().strftime('%Y-%m-%d_%H-%M')}.tsv")
    await interaction.response.send_message(file=file, ephemeral=True)


# ==========================================
# 8. CONFIG & SETUP
# ==========================================
@bot.tree.command(name="setup", description="[DEV] Initial bot configuration")
@is_dev()
async def bot_setup(interaction: discord.Interaction, timezone_str: str, announcement_channel: discord.TextChannel, dev_role: discord.Role):
    try:
        zoneinfo.ZoneInfo(timezone_str)
        db["config"]["timezone"] = timezone_str
    except:
        return await interaction.response.send_message("Invalid timezone string. Try 'America/New_York' or 'UTC'.", ephemeral=True)
    
    db["config"]["announcement_channel"] = announcement_channel.id
    db["config"]["dev_role_id"] = dev_role.id
    save_db(db)
    
    await interaction.response.send_message(embed=get_embed("Setup Complete", f"Timezone: {timezone_str}\nChannel: <#{announcement_channel.id}>\nRole: <@&{dev_role.id}>", COLOR_SUCCESS), ephemeral=True)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable missing.")
        exit(1)
    bot.run(TOKEN)
