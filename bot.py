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
import random

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
        "reveal_color": "#8A2BE2",
        "asset_channel": None,
        "reveal_page_size": 7
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
            
            # OC Schema Migrations
            for oc in data.get("ocs", {}).values():
                if "profile_picture_url" not in oc: oc["profile_picture_url"] = None
                if "eliminated" not in oc: oc["eliminated"] = False
            for oc in data.get("archived_ocs", {}).values():
                if "profile_picture_url" not in oc: oc["profile_picture_url"] = None
                if "eliminated" not in oc: oc["eliminated"] = False

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
    active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]
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

# --- UI COMPONENTS ---
class RankingPaginationView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.pages = pages
        self.current = 0
        self.message: discord.Message = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(self.pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

async def _run_sequential_reveal(channel: discord.TextChannel, ocs_ordered: list, reveal_color: int, page_size: int):
    page_embeds = []
    
    for i in range(0, len(ocs_ordered), page_size):
        batch = ocs_ordered[i:i+page_size]
        page_embed = get_embed("Rankings Reveal", color=reveal_color)
        
        for oc in batch:
            change = get_snapshot_diff(oc["id"], oc["rank"])
            grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
            field_title = f"✦ Rank #{oc['rank']} {grade_str}"
            field_val = f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}> ({change})"
            
            # Send single individual dramatic reveal
            single_embed = get_embed("", color=reveal_color)
            single_embed.add_field(name=field_title, value=field_val, inline=False)
            if oc.get("profile_picture_url"):
                single_embed.set_thumbnail(url=oc["profile_picture_url"])
                
            await channel.send(embed=single_embed)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            # Add to the reconstructed page view
            page_embed.add_field(name=field_title, value=field_val, inline=False)
        
        page_embeds.append(page_embed)
        
        if i + page_size < len(ocs_ordered):
            total_pages = (len(ocs_ordered) + page_size - 1) // page_size
            current_page = (i // page_size) + 1
            await channel.send(embed=get_embed("", f"— Page {current_page} of {total_pages} —", COLOR_SYSTEM))
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
    await channel.send(embed=get_embed("Reveal Complete", "All rankings have been revealed.", COLOR_SUCCESS))
    return page_embeds

# ==========================================
# 1. OC REGISTRATION & MANAGEMENT
# ==========================================
oc_group = app_commands.Group(name="oc", description="OC Management commands")

def build_profile_embed(oc):
    grade_emoji = "⭐"
    color = COLOR_UNGRADED
    if oc["grade"] and oc["grade"] in db["grades"]:
        color = hex_to_int(db["grades"][oc["grade"]])
        grade_emoji = oc["grade"]

    embed = get_embed(f"{oc['name']} {grade_emoji}", color=color)
    
    if oc.get("eliminated", False):
        embed.title = f"~~{oc['name']}~~ ✗ [ELIMINATED]"
        embed.color = COLOR_ERROR

    if oc.get("profile_picture_url"):
        embed.set_thumbnail(url=oc["profile_picture_url"])

    age = calculate_age(oc["birthday"])
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

@oc_group.command(name="register", description="Register a new Trainee")
async def oc_register(interaction: discord.Interaction, name: str, birthday: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, ethnicity: str = "N/A", form_link: str = "", profile_picture: discord.Attachment = None):
    user_ocs = [oc for oc in db["ocs"].values() if oc["owner_id"] == interaction.user.id]
    if len(user_ocs) >= db["config"]["max_ocs_per_user"]:
        return await interaction.response.send_message(embed=get_embed("Registration Failed", f"⛔ *You've already reached the maximum of {db['config']['max_ocs_per_user']} Trainees.*", COLOR_ERROR), ephemeral=True)
    
    if any(oc["name"].lower() == name.lower() and oc["owner_id"] == interaction.user.id for oc in db["ocs"].values()):
        return await interaction.response.send_message(embed=get_embed("Registration Failed", f"You already have a Trainee named '{name}'.", COLOR_ERROR), ephemeral=True)

    if form_link and not form_link.startswith("http"):
        return await interaction.response.send_message(embed=get_embed("Invalid Link", "Please provide a valid URL starting with http/https.", COLOR_ERROR), ephemeral=True)

    # Pre-flight checks for profile picture
    if profile_picture:
        if not profile_picture.content_type or not profile_picture.content_type.startswith("image/"):
            return await interaction.response.send_message(embed=get_embed("Invalid File", "Invalid file type. Please attach an image (PNG, JPG, GIF, WEBP).", COLOR_ERROR), ephemeral=True)
        if not db["config"].get("asset_channel"):
            return await interaction.response.send_message(embed=get_embed("Not Configured", "No asset channel has been configured. Ask a Dev to run `/setassetchannel` first.", COLOR_WARNING), ephemeral=True)

    is_deferred = False
    persistent_url = None

    if profile_picture:
        await interaction.response.defer()
        is_deferred = True
        asset_ch = bot.get_channel(db["config"]["asset_channel"])
        if not asset_ch:
            return await interaction.followup.send(embed=get_embed("Error", "Asset channel not found. Please reconfigure.", COLOR_ERROR), ephemeral=True)
        
        img_bytes = await profile_picture.read()
        file = discord.File(fp=io.BytesIO(img_bytes), filename=profile_picture.filename)
        asset_msg = await asset_ch.send(
            content=f"[OC Asset] `{name}` — owner: <@{interaction.user.id}>",
            file=file
        )
        persistent_url = asset_msg.attachments[0].url

    oc_id = str(uuid.uuid4())
    new_oc = {
        "id": oc_id, "name": name, "owner_id": interaction.user.id, "owner_name": interaction.user.name,
        "birthday": birthday, "gender": gender, "pronouns": pronouns, "faceclaim": faceclaim,
        "main_skill": main_skill, "nationality": nationality, "ethnicity": ethnicity, "form_link": form_link,
        "grade": None, "voting_points": 0, "mission_points": 0, "total_points": 0, "rank": 0,
        "dorm_floor": None, "dorm_room": None, "registered_at": get_now().isoformat(),
        "profile_picture_url": persistent_url, "eliminated": False
    }
    
    db["ocs"][oc_id] = new_oc
    recalculate_ranks()
    
    embed = build_profile_embed(new_oc)
    if is_deferred: await interaction.followup.send(embed=embed)
    else: await interaction.response.send_message(embed=embed)

@oc_group.command(name="profile", description="View a Trainee's profile")
async def oc_profile(interaction: discord.Interaction, name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == name.lower()]
    if not matches:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{name}' was found.", COLOR_ERROR), ephemeral=True)
    await interaction.response.send_message(embed=build_profile_embed(matches[0]))

@oc_group.command(name="all", description="Browse all currently active Trainees")
async def oc_all(interaction: discord.Interaction):
    active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]
    active_ocs.sort(key=lambda x: x["name"].lower())
    
    if not active_ocs:
        return await interaction.response.send_message(embed=get_embed("Empty", "No Trainees are currently registered.", COLOR_WARNING), ephemeral=True)
        
    page_size = db["config"].get("reveal_page_size", 7)
    pages = []
    
    for i in range(0, len(active_ocs), page_size):
        batch = active_ocs[i:i+page_size]
        total_pages = (len(active_ocs) + page_size - 1) // page_size
        current_page = (i // page_size) + 1
        
        embed = get_embed(f"Registered Trainees (Page {current_page} of {total_pages})")
        
        # Thumbnail for first OC on page that has one
        for oc in batch:
            if oc.get("profile_picture_url"):
                embed.set_thumbnail(url=oc["profile_picture_url"])
                break
                
        for oc in batch:
            age = calculate_age(oc["birthday"])
            dorm_val = f"Floor {oc['dorm_floor']} · Room {oc['dorm_room']}" if oc["dorm_room"] else "Unassigned"
            desc = (
                f"**Birthday/Age**: {oc['birthday']} · {age} yrs\n"
                f"**Gender/Pronouns**: {oc['gender']} · {oc['pronouns']}\n"
                f"**Faceclaim**: {oc['faceclaim']}\n"
                f"**Main Skill**: {oc['main_skill']}\n"
                f"**Nationality/Ethnicity**: {oc['nationality']} · {oc['ethnicity']}\n"
                f"**Grade**: {oc['grade'] if oc['grade'] else 'Ungraded'}\n"
                f"**Dorm**: {dorm_val}\n"
            )
            if oc.get("form_link"):
                desc += f"**Profile**: [View Full Profile]({oc['form_link']})\n"
                
            embed.add_field(name=f"✦ {oc['name']}", value=desc, inline=False)
        pages.append(embed)
        
    if len(pages) == 1:
        await interaction.response.send_message(embed=pages[0])
    else:
        view = RankingPaginationView(pages)
        msg = await interaction.response.send_message(embed=pages[0], view=view)
        view.message = msg

@oc_group.command(name="eliminated", description="View all eliminated Trainees")
async def oc_eliminated(interaction: discord.Interaction):
    eliminated_ocs = [oc for oc in db["ocs"].values() if oc.get("eliminated", False)]
    if not eliminated_ocs:
        return await interaction.response.send_message(embed=get_embed("Empty", "No Trainees have been eliminated yet.", COLOR_SYSTEM))
    
    embed = get_embed("Eliminated Trainees")
    desc = ""
    for oc in eliminated_ocs:
        desc += f"• **{oc['name']}** (Faceclaim: {oc['faceclaim']}) - <@{oc['owner_id']}>\n"
    
    embed.description = desc
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(oc_group)

# ==========================================
# 1.5 DEV ELIMINATION SYSTEM
# ==========================================
@bot.tree.command(name="eliminate", description="[DEV] Eliminate OC(s) from the show")
@app_commands.describe(mode="Choose 'name' or 'rank'", value="OC name OR rank number (e.g., '8') OR range (e.g., '8-10')")
@is_dev()
async def eliminate_cmd(interaction: discord.Interaction, mode: str, value: str):
    targets = []
    
    if mode.lower() == "name":
        oc = next((o for o in db["ocs"].values() if o["name"].lower() == value.lower()), None)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{value}' found.", COLOR_ERROR), ephemeral=True)
        if oc.get("eliminated", False):
            return await interaction.response.send_message(embed=get_embed("Already Eliminated", f"{oc['name']} is already eliminated.", COLOR_WARNING), ephemeral=True)
        targets.append(oc)
        
    elif mode.lower() == "rank":
        try:
            if "-" in value:
                start, end = map(int, value.split("-"))
            else:
                start = end = int(value)
        except ValueError:
            return await interaction.response.send_message(embed=get_embed("Invalid Format", "Use a number (e.g., '8') or a range (e.g., '8-10').", COLOR_ERROR), ephemeral=True)
            
        targets = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False) and start <= oc["rank"] <= end]
        if not targets:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No active Trainees found in rank range {start}–{end}.", COLOR_WARNING), ephemeral=True)
    else:
        return await interaction.response.send_message("Mode must be 'name' or 'rank'.", ephemeral=True)

    for oc in targets:
        oc["eliminated"] = True
        if oc["dorm_floor"] and oc["dorm_room"]:
            try:
                db["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
            except ValueError: pass
            oc["dorm_floor"] = None
            oc["dorm_room"] = None

    recalculate_ranks()
    save_db(db)
    
    # Announcements
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    if len(targets) == 1:
        await channel.send(embed=get_embed("A Trainee Has Been Eliminated", f"*{targets[0]['name']} has been eliminated from the competition.*", COLOR_WARNING))
        await interaction.response.send_message(embed=get_embed("Success", f"Done. {targets[0]['name']} has been eliminated.", COLOR_SUCCESS), ephemeral=True)
    else:
        bullet_list = "\n".join([f"• {oc['name']}" for oc in targets])
        await channel.send(embed=get_embed("Elimination Results", f"The following Trainees have been eliminated:\n{bullet_list}", COLOR_WARNING))
        await interaction.response.send_message(embed=get_embed("Success", f"Eliminated {len(targets)} Trainee(s).", COLOR_SUCCESS), ephemeral=True)


# ==========================================
# 2. VOTING SYSTEM
# ==========================================
vote_group = app_commands.Group(name="voting", description="Voting System management")

@bot.tree.command(name="vote", description="Cast a vote for a Trainee")
async def vote_cmd(interaction: discord.Interaction, oc_name: str):
    if not db["voting"]["is_open"]:
        return await interaction.response.send_message(embed=get_embed("Voting Closed", "🚫 *Voting is currently closed.*", COLOR_WARNING), ephemeral=True)
    
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}' found.", COLOR_ERROR), ephemeral=True)
    
    oc = matches[0]
    if oc.get("eliminated", False):
        return await interaction.response.send_message(embed=get_embed("Ineligible", f"**{oc['name']}** has been eliminated from the show and cannot receive votes.", COLOR_ERROR), ephemeral=True)
        
    uid_str = str(interaction.user.id)
    if "user_votes" not in db["voting"]: db["voting"]["user_votes"] = {}
    if db["voting"]["cap"] > 0 and db["voting"]["user_votes"].get(uid_str, 0) >= db["voting"]["cap"]:
        return await interaction.response.send_message(embed=get_embed("Cap Reached", "You have reached your vote limit.", COLOR_ERROR), ephemeral=True)
    
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

@vote_group.command(name="close", description="[DEV] Close voting and apply points")
@is_dev()
async def vote_close(interaction: discord.Interaction):
    db["voting"]["is_open"] = False
    multiplier = db["voting"]["multiplier"]
    
    for oc_id, v_count in db["voting"]["votes"].items():
        if oc_id in db["ocs"] and not db["ocs"][oc_id].get("eliminated", False):
            added_pts = v_count * multiplier
            db["ocs"][oc_id]["voting_points"] += added_pts
            db["ocs"][oc_id]["total_points"] += added_pts
    
    recalculate_ranks()
    save_db(db)
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    await channel.send(embed=get_embed("Voting Closed", f"The voting round is over. A {multiplier}x multiplier was applied.", COLOR_SYSTEM))
    await interaction.response.send_message("Round closed.", ephemeral=True)

bot.tree.add_command(vote_group)

# ==========================================
# 3. POINT SYSTEM
# ==========================================
@bot.tree.command(name="points", description="[DEV] Modify Trainee points")
@is_dev()
async def points_cmd(interaction: discord.Interaction, oc_name: str, action: str, value: int):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message("OC not found.", ephemeral=True)
    
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
# 4. GRADE SYSTEM (Omitted redundant standard commands for brevity, kept essential ones)
# ==========================================
grade_group = app_commands.Group(name="grade", description="[DEV] Grade System Management")

@grade_group.command(name="create", description="[DEV] Create a new grade tier")
@is_dev()
async def grade_create(interaction: discord.Interaction, label: str, hex_color: str):
    if not re.match(r"^#[0-9A-Fa-f]{6}$", hex_color): return await interaction.response.send_message("Invalid color format.", ephemeral=True)
    db["grades"][label] = hex_color
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Grade Created", f"Grade **{label}** mapped to {hex_color}.", hex_to_int(hex_color)))

@grade_group.command(name="assign", description="[DEV] Assign a grade")
@is_dev()
async def grade_assign(interaction: discord.Interaction, oc_name: str, label: str):
    if label not in db["grades"]: return await interaction.response.send_message("Grade not found.", ephemeral=True)
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message("OC not found.", ephemeral=True)
    matches[0]["grade"] = label
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Class Evaluation Complete", f"**{matches[0]['name']}** assigned to **Grade {label}**.", hex_to_int(db['grades'][label])))

bot.tree.add_command(grade_group)

# ==========================================
# 5. DORMITORY SYSTEM
# ==========================================
dorm_group = app_commands.Group(name="dorm", description="[DEV] Dormitory Management")

@dorm_group.command(name="createroom", description="[DEV] Create a room")
@is_dev()
async def dorm_createroom(interaction: discord.Interaction, floor_name: str, room_name: str, capacity: int):
    if floor_name not in db["dorms"]: db["dorms"][floor_name] = {"rooms": {}}
    db["dorms"][floor_name]["rooms"][room_name] = {"capacity": capacity, "occupants": []}
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Room Created", f"{room_name} created on {floor_name}.", COLOR_SUCCESS))

@dorm_group.command(name="assign", description="[DEV] Assign Trainee to room")
@is_dev()
async def dorm_assign(interaction: discord.Interaction, oc_name: str, floor_name: str, room_name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message("OC not found.", ephemeral=True)
    
    oc = matches[0]
    if oc.get("eliminated", False):
        return await interaction.response.send_message(embed=get_embed("Ineligible", f"**{oc['name']}** is eliminated and cannot be assigned to a dorm.", COLOR_ERROR), ephemeral=True)
        
    try: room = db["dorms"][floor_name]["rooms"][room_name]
    except KeyError: return await interaction.response.send_message("Floor/Room not found.", ephemeral=True)
    
    if len(room["occupants"]) >= room["capacity"]:
        return await interaction.response.send_message("Room at capacity.", ephemeral=True)
    
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
            occupant_names = [db["ocs"][oid]["name"] for oid in rval["occupants"] if oid in db["ocs"] and not db["ocs"][oid].get("eliminated", False)]
            occ_str = ", ".join(occupant_names) if occupant_names else "Empty"
            desc += f"**{rname}** ({len(occupant_names)}/{rval['capacity']}): {occ_str}\n"
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
    snap_data = {oc["id"]: {"rank": oc["rank"], "points": oc["total_points"]} for oc in db["ocs"].values() if not oc.get("eliminated", False)}
    db["rank_snapshots"].append({
        "timestamp": get_now().isoformat(), "trigger": "RANKINGS_PRIVATE_COMMAND", "rankings": snap_data
    })
    save_db(db)
    
    embed = get_embed("Private Evaluation Standings", "Current Live Rankings:")
    active_ocs = sorted([o for o in db["ocs"].values() if not o.get("eliminated")], key=lambda x: x["rank"])
    
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
    await interaction.response.send_message(
        embed=get_embed("Evaluation Begins", "🎬 *The moment you've all been waiting for…*", hex_to_int(db["config"]["reveal_color"]))
    )
    
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    active_ocs = sorted([o for o in db["ocs"].values() if not o.get("eliminated")], key=lambda x: x["rank"], reverse=True)
    page_size = db["config"].get("reveal_page_size", 7)
    
    page_embeds = await _run_sequential_reveal(channel, active_ocs, hex_to_int(db["config"]["reveal_color"]), page_size)
    
    view = RankingPaginationView(page_embeds)
    msg = await interaction.followup.send(
        embed=get_embed("📖 Browse Results", f"Scroll through all {len(page_embeds)} page(s)."),
        view=view,
        wait=True
    )
    view.message = msg

@rank_group.command(name="partialreveal", description="[DEV] Reveal specific ranks")
@is_dev()
async def rank_partial(interaction: discord.Interaction, ranks: str):
    await interaction.response.defer()
    try: target_ranks = sorted([int(r) for r in ranks.split()], reverse=True)
    except ValueError: return await interaction.followup.send("Invalid format. Use numbers like '1 5 10'.", ephemeral=True)

    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    active_ocs = {oc["rank"]: oc for oc in db["ocs"].values() if not oc.get("eliminated")}
    valid_ocs = [active_ocs[r] for r in target_ranks if r in active_ocs]
    
    if not valid_ocs: return await interaction.followup.send("No valid OCs found for the given ranks.", ephemeral=True)

    page_size = db["config"].get("reveal_page_size", 7)
    page_embeds = await _run_sequential_reveal(channel, valid_ocs, hex_to_int(db["config"]["reveal_color"]), page_size)
    
    view = RankingPaginationView(page_embeds)
    msg = await interaction.followup.send(
        embed=get_embed("📖 Browse Results", f"Scroll through all {len(page_embeds)} page(s)."),
        view=view,
        wait=True
    )
    view.message = msg

bot.tree.add_command(rank_group)

# ==========================================
# 7. EXPORT SYSTEM
# ==========================================
@bot.tree.command(name="export", description="[DEV] Export bot data to TSV")
@is_dev()
async def export_data(interaction: discord.Interaction):
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    
    writer.writerow(["=== SECTION 1: CURRENT RANKINGS SUMMARY ==="])
    writer.writerow(["rank", "oc_name", "owner_discord_id", "owner_username", "grade", "total_points", "voting_points", "mission_points", "rank_change", "dorm_floor", "dorm_room", "registered_at", "eliminated", "profile_picture_url"])
    for oc in sorted(db["ocs"].values(), key=lambda x: x["rank"]):
        change = get_snapshot_diff(oc["id"], oc["rank"])
        writer.writerow([oc["rank"], oc["name"], oc["owner_id"], oc["owner_name"], oc["grade"] or "", oc["total_points"], oc["voting_points"], oc["mission_points"], change, oc["dorm_floor"] or "", oc["dorm_room"] or "", oc["registered_at"], str(oc.get("eliminated", False)), oc.get("profile_picture_url") or ""])
    
    output.write("\n")
    writer.writerow(["=== SECTION 2: RANK HISTORY ==="])
    writer.writerow(["oc_name", "snapshot_timestamp", "snapshot_trigger", "rank_at_snapshot", "points_at_snapshot"])
    for snap in db["rank_snapshots"]:
        for oc_id, stats in snap["rankings"].items():
            name = db["ocs"].get(oc_id, db["archived_ocs"].get(oc_id, {"name": "Unknown"}))["name"]
            writer.writerow([name, snap["timestamp"], snap["trigger"], stats["rank"], stats["points"]])
            
    output.write("\n")
    writer.writerow(["=== SECTION 3: POINT MANIPULATION LOG ==="])
    writer.writerow(["timestamp", "dev_discord_id", "dev_username", "oc_name", "action", "value", "points_before", "points_after"])
    for log in db["point_log"]:
        writer.writerow([log["timestamp"], log["dev_id"], log["dev_name"], log["oc_name"], log["action"], log["value"], log["points_before"], log["points_after"]])
    
    output.seek(0)
    file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"rankings_export_{get_now().strftime('%Y-%m-%d_%H-%M')}.tsv")
    await interaction.response.send_message(file=file, ephemeral=True)

# ==========================================
# 8. CONFIG & SETUP
# ==========================================
@bot.tree.command(name="setup", description="[DEV] Initial bot configuration")
@is_dev()
async def bot_setup(interaction: discord.Interaction, timezone_str: str, announcement_channel: discord.TextChannel, dev_role: discord.Role, asset_channel: discord.TextChannel = None):
    try: zoneinfo.ZoneInfo(timezone_str)
    except: return await interaction.response.send_message("Invalid timezone string.", ephemeral=True)
    
    db["config"]["timezone"] = timezone_str
    db["config"]["announcement_channel"] = announcement_channel.id
    db["config"]["dev_role_id"] = dev_role.id
    if asset_channel: db["config"]["asset_channel"] = asset_channel.id
    save_db(db)
    
    asset_text = f"\nAsset Channel: <#{asset_channel.id}>" if asset_channel else ""
    await interaction.response.send_message(embed=get_embed("Setup Complete", f"Timezone: {timezone_str}\nChannel: <#{announcement_channel.id}>\nRole: <@&{dev_role.id}>{asset_text}", COLOR_SUCCESS), ephemeral=True)

@bot.tree.command(name="setassetchannel", description="[DEV] Set the persistent asset storage channel")
@is_dev()
async def set_asset_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    db["config"]["asset_channel"] = channel.id
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Success", f"Asset storage channel set to <#{channel.id}>.", COLOR_SUCCESS), ephemeral=True)

@bot.tree.command(name="setrevealpage", description="[DEV] Set how many trainees are shown per reveal page")
@is_dev()
async def set_reveal_page(interaction: discord.Interaction, size: int):
    if not (1 <= size <= 25):
        return await interaction.response.send_message(embed=get_embed("Invalid Size", "Page size must be between 1 and 25.", COLOR_ERROR), ephemeral=True)
    db["config"]["reveal_page_size"] = size
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Success", f"Reveal page size updated to {size} Trainees per page.", COLOR_SUCCESS), ephemeral=True)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable missing.")
        exit(1)
    bot.run(TOKEN)