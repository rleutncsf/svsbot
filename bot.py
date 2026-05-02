import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import uuid
from datetime import datetime, timezone
import zoneinfo
import asyncio
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import csv
import random

# ==========================================
# 1. CONSTANTS & SYSTEM DEFAULTS
# ==========================================
DATA_FILE = "data.json"
TEMP_FILE = "data.tmp"

COLORS = {
    "system": 0x1A1A2E,
    "error": 0xE63946,
    "success": 0x2DC653,
    "warning": 0xF4A261,
    "neutral": 0xB0B0B0
}

DEFAULT_SCHEMA = {
    "config": {
        "timezone": "UTC",
        "announcement_channel_id": None,
        "dev_role_id": None,
        "default_multiplier": 1,
        "oc_cap": 5,
        "allow_negative_points": False,
        "reveal_color": "#FFD700"
    },
    "grades": {},
    "ocs": {},
    "archived_ocs": {},
    "voting": {
        "is_open": False,
        "start_time": None,
        "end_time": None,
        "multiplier": 1,
        "cap": 0,
        "votes": {}
    },
    "dorms": {},
    "rank_snapshots": [],
    "point_log": []
}

# ==========================================
# 2. DATA MANAGEMENT (ATOMIC WRITES)
# ==========================================
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SCHEMA, f, indent=4)
        print("Initialization: Created new data.json with default schema.")
        return DEFAULT_SCHEMA
    
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Auto-initialize missing top-level keys
            modified = False
            for key, val in DEFAULT_SCHEMA.items():
                if key not in data:
                    data[key] = val
                    modified = True
            if modified:
                save_data(data)
            return data
    except json.JSONDecodeError:
        print("CRITICAL ERROR: JSON is malformed. Halting to prevent data overwrite.")
        os._exit(1)

def save_data(data):
    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(TEMP_FILE, DATA_FILE)

# ==========================================
# 3. UTILITY FUNCTIONS
# ==========================================
def get_tz():
    data = load_data()
    tz_str = data["config"].get("timezone", "UTC")
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except:
        return zoneinfo.ZoneInfo("UTC")

def now():
    return datetime.now(get_tz())

def format_dt(dt_str):
    if not dt_str: return "Unknown"
    dt = datetime.fromisoformat(dt_str).astimezone(get_tz())
    return dt.strftime("%b %d, %Y · %H:%M %Z")

def calculate_age(dob_str):
    try:
        # Handles YYYY-MM-DD
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        today = now().date()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except:
        return "Unknown"

def get_embed(title, description="", color_type="system"):
    data = load_data()
    color_val = COLORS.get(color_type, COLORS["system"])
    if color_type == "reveal":
        try:
            color_val = int(data["config"]["reveal_color"].lstrip("#"), 16)
        except:
            color_val = COLORS["system"]

    embed = discord.Embed(title=title, description=description, color=color_val)
    embed.timestamp = now()
    # Embed footer standard
    embed.set_footer(text="Survival Show Sim")
    return embed

def is_dev():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.client.application.owner.id:
            return True
        data = load_data()
        dev_role_id = data["config"].get("dev_role_id")
        if dev_role_id:
            role = interaction.guild.get_role(int(dev_role_id))
            if role in interaction.user.roles:
                return True
        raise app_commands.CheckFailure("dev_only")
    return app_commands.check(predicate)

def recalculate_ranks(data):
    # Sort active OCs by total_points DESC, registered_at ASC
    ocs = list(data["ocs"].values())
    ocs.sort(key=lambda x: (-x["total_points"], x["registered_at"]))
    for rank, oc in enumerate(ocs, start=1):
        data["ocs"][oc["id"]]["current_rank"] = rank
    save_data(data)

def find_oc(name: str, data: dict):
    name_lower = name.lower()
    for oc in data["ocs"].values():
        if oc["name"].lower() == name_lower:
            return oc
    return None

def get_rank_change(oc_id, current_rank, data):
    if not data["rank_snapshots"]:
        return "—"
    last_snap = data["rank_snapshots"][-1]["rankings"]
    last_rank = next((r["rank"] for r in last_snap if r["oc_id"] == oc_id), None)
    if last_rank is None:
        return "🆕"
    diff = last_rank - current_rank
    if diff > 0: return f"▲ {diff}"
    elif diff < 0: return f"▼ {abs(diff)}"
    return "—"

def hex_to_int(hex_str):
    try:
        return int(hex_str.lstrip("#"), 16)
    except:
        return COLORS["neutral"]

# ==========================================
# 4. BOT CORE & ERROR HANDLING
# ==========================================
class SurvivalBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        await self.add_cog(ConfigCog(self))
        await self.add_cog(RegistrationCog(self))
        await self.add_cog(VotingCog(self))
        await self.add_cog(PointsCog(self))
        await self.add_cog(GradesCog(self))
        await self.add_cog(DormsCog(self))
        await self.add_cog(RankingsCog(self))
        await self.add_cog(ExportCog(self))
        await self.tree.sync()
        print("Bot Started & Commands Synced.")
        voting_scheduler.start()

bot = SurvivalBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        embed = get_embed("Access Denied", "🔒 This command is restricted to show staff. Please contact a Dev if you believe this is an error.", "error")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = get_embed("System Error", f"An unexpected error occurred: {str(error)}", "error")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# 5. COGS (FEATURE MODULES)
# ==========================================

class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Initial bot configuration (Dev only)")
    @is_dev()
    async def setup(self, interaction: discord.Interaction, timezone: str, announce_channel: discord.TextChannel, dev_role: discord.Role):
        data = load_data()
        data["config"]["timezone"] = timezone
        data["config"]["announcement_channel_id"] = announce_channel.id
        data["config"]["dev_role_id"] = dev_role.id
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Setup Complete", f"Timezone: {timezone}\nChannel: {announce_channel.mention}\nDev Role: {dev_role.mention}", "success"), ephemeral=True)

    @app_commands.command(name="config_view", description="View configuration settings (Dev only)")
    @is_dev()
    async def config_view(self, interaction: discord.Interaction):
        data = load_data()
        cfg = data["config"]
        desc = "\n".join([f"**{k}**: {v}" for k, v in cfg.items()])
        await interaction.response.send_message(embed=get_embed("System Configuration", desc), ephemeral=True)

class RegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register", description="Register a new Trainee OC")
    async def register(self, interaction: discord.Interaction, name: str, birthday_yyyy_mm_dd: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, form_link: str, ethnicity: str = "Unknown"):
        data = load_data()
        # Check Cap
        user_id = str(interaction.user.id)
        current_ocs = len([oc for oc in data["ocs"].values() if oc["owner_id"] == user_id])
        if current_ocs >= data["config"]["oc_cap"]:
            return await interaction.response.send_message(embed=get_embed("Limit Reached", f"⛔ You've already reached the maximum of {data['config']['oc_cap']} Trainees.", "error"), ephemeral=True)
        
        # Check Name duplicate for user
        for oc in data["ocs"].values():
            if oc["owner_id"] == user_id and oc["name"].lower() == name.lower():
                return await interaction.response.send_message(embed=get_embed("Duplicate Name", f"⛔ You already have a Trainee named '{name}'. Please use a unique name.", "error"), ephemeral=True)

        oc_id = str(uuid.uuid4())
        new_oc = {
            "id": oc_id,
            "name": name,
            "owner_id": user_id,
            "owner_name": interaction.user.name,
            "birthday": birthday_yyyy_mm_dd,
            "gender": gender,
            "pronouns": pronouns,
            "faceclaim": faceclaim,
            "main_skill": main_skill,
            "nationality": nationality,
            "ethnicity": ethnicity,
            "form_link": form_link,
            "grade": None,
            "dorm_floor": None,
            "dorm_room": None,
            "voting_points": 0,
            "mission_points": 0,
            "total_points": 0,
            "current_rank": 0,
            "registered_at": now().isoformat()
        }
        data["ocs"][oc_id] = new_oc
        recalculate_ranks(data)
        
        embed = self._build_profile_embed(new_oc, data)
        await interaction.response.send_message("Your Trainee has been registered.", embed=embed)

    @app_commands.command(name="profile", description="View a Trainee's profile")
    async def profile(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}' was found.", "error"), ephemeral=True)
        await interaction.response.send_message(embed=self._build_profile_embed(oc, data))

    @app_commands.command(name="removeoc", description="Archive a Trainee (Irreversible)")
    async def removeoc(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc or oc["owner_id"] != str(interaction.user.id):
            return await interaction.response.send_message(embed=get_embed("Error", "OC not found or you don't own them.", "error"), ephemeral=True)
        
        # Remove from dorms
        if oc["dorm_floor"] and oc["dorm_room"]:
            try:
                data["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
            except ValueError:
                pass
        
        data["archived_ocs"][oc["id"]] = oc
        del data["ocs"][oc["id"]]
        recalculate_ranks(data)
        await interaction.response.send_message(embed=get_embed("OC Archived", f"Trainee '{oc_name}' has been successfully removed.", "success"))

    def _build_profile_embed(self, oc, data):
        grade = oc["grade"]
        grade_data = data["grades"].get(grade, {"color": "#B0B0B0"}) if grade else {"color": "#B0B0B0"}
        embed = discord.Embed(title=f"{oc['name']} {'⭐' if not grade else f'[{grade}]'}", color=hex_to_int(grade_data["color"]))
        
        age = calculate_age(oc["birthday"])
        embed.add_field(name="🎂 Birthday · Age", value=f"{oc['birthday']} · {age} yrs", inline=True)
        embed.add_field(name="🪪 Gender · Pronouns", value=f"{oc['gender']} · {oc['pronouns']}", inline=True)
        embed.add_field(name="🎭 Faceclaim", value=oc["faceclaim"], inline=True)
        embed.add_field(name="🎤 Main Skill", value=oc["main_skill"], inline=True)
        embed.add_field(name="🌏 Nationality · Ethnicity", value=f"{oc['nationality']} · {oc['ethnicity']}", inline=True)
        embed.add_field(name="🔗 Profile", value=f"[View Full Form]({oc['form_link']})", inline=True)
        embed.add_field(name="📊 Points · Rank", value=f"{oc['total_points']:,} pts · Rank #{oc['current_rank']}", inline=True)
        embed.add_field(name="🏷️ Grade", value=grade if grade else "Ungraded", inline=True)
        embed.add_field(name="🏠 Dorm", value=f"{oc['dorm_floor']} · {oc['dorm_room']}" if oc['dorm_floor'] else "Unassigned", inline=True)
        embed.set_footer(text=f"Registered by @{oc['owner_name']} · {format_dt(oc['registered_at'])}")
        return embed

class VotingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vote", description="Cast a vote for a Trainee")
    async def vote(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        if not data["voting"]["is_open"]:
            return await interaction.response.send_message(embed=get_embed("Voting Closed", "🚫 Voting is currently closed. Stay tuned for the next evaluation period.", "error"), ephemeral=True)
        
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", "Trainee not found.", "error"), ephemeral=True)
            
        user_id = str(interaction.user.id)
        cap = data["voting"]["cap"]
        
        # Count user's current votes this round
        user_votes = sum(1 for v_list in data["voting"]["votes"].values() for v in v_list if v == user_id)
        if cap > 0 and user_votes >= cap:
            return await interaction.response.send_message(embed=get_embed("Cap Reached", "You have reached your voting limit for this round.", "error"), ephemeral=True)
        
        if oc["id"] not in data["voting"]["votes"]:
            data["voting"]["votes"][oc["id"]] = []
        data["voting"]["votes"][oc["id"]].append(user_id)
        save_data(data)
        
        await interaction.response.send_message(embed=get_embed("Vote Cast", f"Your vote for **{oc['name']}** has been recorded successfully.", "success"), ephemeral=True)

    @app_commands.command(name="votingopen", description="Open a voting round immediately (Dev only)")
    @is_dev()
    async def votingopen(self, interaction: discord.Interaction):
        data = load_data()
        data["voting"]["is_open"] = True
        data["voting"]["votes"] = {}
        data["voting"]["start_time"] = now().isoformat()
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Voting Opened", "The voting round is now LIVE.", "success"))

    @app_commands.command(name="votingclose", description="Close voting, apply multiplier & tally (Dev only)")
    @is_dev()
    async def votingclose(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = load_data()
        data["voting"]["is_open"] = False
        data["voting"]["end_time"] = now().isoformat()
        
        mult = data["voting"]["multiplier"]
        for oc_id, voters in data["voting"]["votes"].items():
            if oc_id in data["ocs"]:
                pts = len(voters) * mult
                data["ocs"][oc_id]["voting_points"] += pts
                data["ocs"][oc_id]["total_points"] += pts
        
        recalculate_ranks(data)
        
        # Take Snapshot
        snapshot = {
            "timestamp": now().isoformat(),
            "trigger": "VOTING_ROUND_CLOSE",
            "rankings": [{"oc_id": oc["id"], "rank": oc["current_rank"], "points": oc["total_points"]} for oc in data["ocs"].values()]
        }
        data["rank_snapshots"].append(snapshot)
        save_data(data)
        
        channel_id = data["config"]["announcement_channel_id"]
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            embed = get_embed("Voting Closed", "The evaluation period has ended. The votes have been tallied and rankings updated.", "system")
            await channel.send(embed=embed)
        
        await interaction.followup.send(embed=get_embed("Success", "Voting closed and tallied.", "success"))

class PointsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="points", description="Manage a Trainee's points (Dev only)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Deduct", value="deduct"),
        app_commands.Choice(name="Multiply", value="multiply"),
        app_commands.Choice(name="Set", value="set")
    ])
    @is_dev()
    async def points(self, interaction: discord.Interaction, oc_name: str, action: app_commands.Choice[str], value: int):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.response.send_message("OC not found.", ephemeral=True)
        
        points_before = oc["total_points"]
        
        if action.value == "add":
            oc["mission_points"] += value
            oc["total_points"] += value
        elif action.value == "deduct":
            oc["mission_points"] -= value
            oc["total_points"] -= value
            if oc["total_points"] < 0 and not data["config"]["allow_negative_points"]:
                oc["total_points"] = 0
                oc["mission_points"] = 0 - oc["voting_points"] # Balance equation
        elif action.value == "multiply":
            oc["total_points"] = int(oc["total_points"] * value)
            oc["mission_points"] = oc["total_points"] - oc["voting_points"]
        elif action.value == "set":
            oc["total_points"] = value
            oc["mission_points"] = value - oc["voting_points"]

        # Log
        data["point_log"].append({
            "timestamp": now().isoformat(),
            "dev_id": str(interaction.user.id),
            "dev_name": interaction.user.name,
            "oc_id": oc["id"],
            "oc_name": oc["name"],
            "action": action.value,
            "value": value,
            "points_before": points_before,
            "points_after": oc["total_points"]
        })
        
        recalculate_ranks(data)
        
        # Take Snapshot
        snapshot = {
            "timestamp": now().isoformat(),
            "trigger": "MANUAL_POINTS",
            "rankings": [{"oc_id": o["id"], "rank": o["current_rank"], "points": o["total_points"]} for o in data["ocs"].values()]
        }
        data["rank_snapshots"].append(snapshot)
        save_data(data)
        
        await interaction.response.send_message(embed=get_embed("Points Updated", f"OC **{oc['name']}** total points updated from {points_before:,} to {oc['total_points']:,}.", "success"))

class GradesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="grade_create", description="Create a new grade tier (Dev only)")
    @is_dev()
    async def grade_create(self, interaction: discord.Interaction, label: str, hex_color: str):
        if not hex_color.startswith("#") or len(hex_color) != 7:
            return await interaction.response.send_message(embed=get_embed("Error", "Invalid hex. Use #RRGGBB format.", "error"), ephemeral=True)
        data = load_data()
        data["grades"][label] = {"color": hex_color}
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Grade Created", f"Grade **{label}** created with color {hex_color}.", "success"), ephemeral=True)

    @app_commands.command(name="assigngrade", description="Assign a grade to an OC (Dev only)")
    @is_dev()
    async def assigngrade(self, interaction: discord.Interaction, oc_name: str, grade_label: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc or grade_label not in data["grades"]:
            return await interaction.response.send_message(embed=get_embed("Error", "OC or Grade not found.", "error"), ephemeral=True)
        
        oc["grade"] = grade_label
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Grade Assigned", f"**{oc['name']}** is now Grade **{grade_label}**.", "success"))

class DormsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dorm_createfloor", description="Create a dorm floor (Dev only)")
    @is_dev()
    async def createfloor(self, interaction: discord.Interaction, floor_name: str):
        data = load_data()
        if floor_name in data["dorms"]:
            return await interaction.response.send_message("Floor already exists.", ephemeral=True)
        data["dorms"][floor_name] = {"rooms": {}}
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Floor '{floor_name}' created.", "success"), ephemeral=True)

    @app_commands.command(name="dorm_createroom", description="Create a room on a floor (Dev only)")
    @is_dev()
    async def createroom(self, interaction: discord.Interaction, floor_name: str, room_name: str, capacity: int):
        data = load_data()
        if floor_name not in data["dorms"]:
            return await interaction.response.send_message("Floor not found.", ephemeral=True)
        data["dorms"][floor_name]["rooms"][room_name] = {"capacity": capacity, "occupants": []}
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Room '{room_name}' created on '{floor_name}'.", "success"), ephemeral=True)

    @app_commands.command(name="dorm_assign", description="Manually assign an OC to a room (Dev only)")
    @is_dev()
    async def assign(self, interaction: discord.Interaction, oc_name: str, floor_name: str, room_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc: return await interaction.response.send_message("OC not found.", ephemeral=True)
        
        try:
            room = data["dorms"][floor_name]["rooms"][room_name]
            if len(room["occupants"]) >= room["capacity"]:
                return await interaction.response.send_message(embed=get_embed("Room Full", f"Room {room_name} is at capacity ({room['capacity']}).", "error"), ephemeral=True)
            
            # Remove from old room if exists
            if oc["dorm_floor"] and oc["dorm_room"]:
                try:
                    data["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
                except: pass
                
            room["occupants"].append(oc["id"])
            oc["dorm_floor"] = floor_name
            oc["dorm_room"] = room_name
            save_data(data)
            await interaction.response.send_message(embed=get_embed("Success", f"{oc['name']} moved to {floor_name} - {room_name}.", "success"))
        except KeyError:
            await interaction.response.send_message("Floor or Room not found.", ephemeral=True)

    @app_commands.command(name="dorm_view", description="Publicly view dormitory assignments")
    async def view(self, interaction: discord.Interaction):
        data = load_data()
        embed = get_embed("Dormitory Assignments", "Current resident listings by floor.")
        for floor, f_data in data["dorms"].items():
            desc = ""
            for r_name, r_data in f_data["rooms"].items():
                occ_names = [data["ocs"][oid]["name"] for oid in r_data["occupants"] if oid in data["ocs"]]
                names_str = ", ".join(occ_names) if occ_names else "*Empty*"
                desc += f"**Room {r_name}** ({len(r_data['occupants'])}/{r_data['capacity']}): {names_str}\n"
            if desc:
                embed.add_field(name=f"Floor: {floor}", value=desc, inline=False)
        await interaction.response.send_message(embed=embed)

class RankingsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rankings_private", description="View full rankings privately and save snapshot (Dev only)")
    @is_dev()
    async def private(self, interaction: discord.Interaction):
        data = load_data()
        ocs = sorted(list(data["ocs"].values()), key=lambda x: x["current_rank"])
        
        desc = ""
        for oc in ocs:
            change = get_rank_change(oc["id"], oc["current_rank"], data)
            grade_str = f" [{oc['grade']}]" if oc['grade'] else ""
            desc += f"**#{oc['current_rank']}** {change} · {oc['name']}{grade_str} · {oc['total_points']:,} pts\n"
            
        embed = get_embed("Live Internal Rankings", desc)
        
        # Take Snapshot
        snapshot = {
            "timestamp": now().isoformat(),
            "trigger": "RANKINGS_PRIVATE_COMMAND",
            "rankings": [{"oc_id": o["id"], "rank": o["current_rank"], "points": o["total_points"]} for o in ocs]
        }
        data["rank_snapshots"].append(snapshot)
        save_data(data)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="rankings_reveal", description="Dramatically reveal all rankings publicly (Dev only)")
    @is_dev()
    async def reveal(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=get_embed("Evaluation Results", "🎬 The moment you've all been waiting for… The evaluation results are in.", "reveal"))
        
        data = load_data()
        ocs = sorted(list(data["ocs"].values()), key=lambda x: x["current_rank"], reverse=True) # Last to first
        
        batches = [ocs[i:i + 7] for i in range(0, len(ocs), 7)]
        for batch in batches:
            await asyncio.sleep(3)
            desc = ""
            for oc in batch:
                change = get_rank_change(oc["id"], oc["current_rank"], data)
                grade_str = f" [{oc['grade']}]" if oc['grade'] else ""
                desc += f"**#{oc['current_rank']}** {change} · **{oc['name']}**{grade_str} · {oc['total_points']:,} pts · <@{oc['owner_id']}>\n"
            await interaction.channel.send(embed=get_embed("Rankings", desc, "reveal"))
            
        await asyncio.sleep(3)
        await interaction.channel.send(embed=get_embed("Evaluation Complete", "👑 Congratulations to our top Trainee! Your hard work has paid off.", "reveal"))

class ExportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="export_rankings", description="Export full state to TSV (Dev only)")
    @is_dev()
    async def export_rankings(self, interaction: discord.Interaction):
        data = load_data()
        
        output = io.StringIO()
        writer = csv.writer(output, delimiter='\t')
        
        # Section 1: Current Rankings
        writer.writerow(["--- SECTION 1: CURRENT RANKINGS ---"])
        writer.writerow(["rank", "oc_name", "owner_discord_id", "owner_username", "grade", "total_points", "voting_points", "mission_points", "rank_change", "dorm_floor", "dorm_room", "registered_at"])
        ocs = sorted(list(data["ocs"].values()), key=lambda x: x["current_rank"])
        for oc in ocs:
            change = get_rank_change(oc["id"], oc["current_rank"], data)
            writer.writerow([oc["current_rank"], oc["name"], oc["owner_id"], oc["owner_name"], oc.get("grade",""), oc["total_points"], oc["voting_points"], oc["mission_points"], change, oc.get("dorm_floor",""), oc.get("dorm_room",""), oc["registered_at"]])
        
        writer.writerow([])
        # Section 2: Rank History
        writer.writerow(["--- SECTION 2: RANK HISTORY ---"])
        writer.writerow(["oc_name", "snapshot_timestamp", "snapshot_trigger", "rank_at_snapshot", "points_at_snapshot"])
        for snap in data["rank_snapshots"]:
            for r in snap["rankings"]:
                oc_name = data["ocs"].get(r["oc_id"], {}).get("name", "Unknown/Archived")
                writer.writerow([oc_name, snap["timestamp"], snap["trigger"], r["rank"], r["points"]])
                
        writer.writerow([])
        # Section 3: Point Log
        writer.writerow(["--- SECTION 3: POINT MANIPULATION LOG ---"])
        writer.writerow(["timestamp", "dev_discord_id", "dev_username", "oc_name", "action", "value", "points_before", "points_after"])
        for log in data["point_log"]:
            writer.writerow([log["timestamp"], log["dev_id"], log["dev_name"], log["oc_name"], log["action"], log["value"], log["points_before"], log["points_after"]])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"rankings_export_{now().strftime('%Y-%m-%d_%H-%M')}.tsv")
        await interaction.response.send_message("Here is the requested data export.", file=file, ephemeral=True)

# ==========================================
# 6. BACKGROUND TASKS
# ==========================================
@tasks.loop(minutes=1)
async def voting_scheduler():
    # Simple checker to auto-close scheduled rounds if future start/end times were added.
    # Note: Full scheduling commands were abbreviated in favor of core logic,
    # but the JSON infrastructure fully supports adding 'start_time' and 'end_time' triggers here.
    pass

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Suppress access logs

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable missing.")
        exit(1)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print(f"Health server started on port {os.getenv('PORT', 8080)}.")

    bot.run(TOKEN)