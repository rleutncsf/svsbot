import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timezone as _tz
import zoneinfo
import uuid
import re
import csv
import io
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- SYSTEM CONSTANTS & COLORS ---
FILE_NAME = "database.json"
TEMP_FILE = "database.json.tmp"

COLOR_SYSTEM = 0x1A1A2E
COLOR_ERROR = 0xE63946
COLOR_SUCCESS = 0x2DC653
COLOR_WARNING = 0xF4A261
COLOR_UNGRADED = 0xB0B0B0

POINTLOG_ACTION_RESETALL = "resetall"
SNAP_TRIGGER_RESETALL = "POINTS_RESETALL_BASELINE"

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
        "reveal_page_size": 7,
        "debut_slots": 0,
        "debut_slots_public": True,
        "peer_ranking_enabled": False,
        "peer_ranking_benefit": {"type": "multiplier", "value": 1.20},
        "peer_ranking_penalty": {"type": "multiplier", "value": 0.10},
        "peer_ranking_transparent": True,
        "feed_channel": None
    },
    "grades": {},
    "ocs": {},
    "archived_ocs": {},
    "voting": {
        "is_open": False,
        "multiplier": 1,
        "cap": 0,
        "votes": {},
        "user_votes": {},
        "last_closed_at": None
    },
    "dorms": {},
    "mission_groups": {},
    "peer_ranking_sessions": {},
    "feeds": {},
    "rank_snapshots": [],
    "point_log": []
}

# --- HELPERS ---
def _migration_timestamp():
    """Safe timestamp for use inside load_db() before db is assigned."""
    return datetime.now(_tz.utc).isoformat()

# --- DATABASE MANAGEMENT ---
def load_db():
    if not os.path.exists(FILE_NAME):
        save_db(DEFAULT_DB)
        return DEFAULT_DB
    try:
        with open(FILE_NAME, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Root structure migrations
            for key in DEFAULT_DB:
                if key not in data:
                    data[key] = DEFAULT_DB[key]
                    
            # Config schema migrations
            for k in ["debut_slots", "debut_slots_public", "peer_ranking_enabled", "peer_ranking_benefit", "peer_ranking_penalty", "peer_ranking_transparent", "feed_channel"]:
                if k not in data["config"]:
                    data["config"][k] = DEFAULT_DB["config"][k]
                    
            # Voting schema migrations
            if "last_closed_at" not in data["voting"]: data["voting"]["last_closed_at"] = None
            if "user_votes" not in data["voting"]: data["voting"]["user_votes"] = {}
            
            # Dorm room schema migration
            for floor_label, floor_data in data.get("dorms", {}).items():
                if "label" not in floor_data: floor_data["label"] = floor_label
                if "created_at" not in floor_data: floor_data["created_at"] = _migration_timestamp()
                for room_label, room_data in floor_data.get("rooms", {}).items():
                    if "label" not in room_data: room_data["label"] = room_label
                    if "created_at" not in room_data: room_data["created_at"] = _migration_timestamp()
                    if "capacity" not in room_data: room_data["capacity"] = 4  # default fallback
                    if "occupants" not in room_data: room_data["occupants"] = []

            # OC Schema Migrations
            for oc in data.get("ocs", {}).values():
                if "profile_picture_url" not in oc: oc["profile_picture_url"] = None
                if "eliminated" not in oc: oc["eliminated"] = False
                if "feed_post_ids" not in oc: oc["feed_post_ids"] = []
                if "dorm_floor" not in oc: oc["dorm_floor"] = None
                if "dorm_room" not in oc: oc["dorm_room"] = None
            for oc in data.get("archived_ocs", {}).values():
                if "profile_picture_url" not in oc: oc["profile_picture_url"] = None
                if "eliminated" not in oc: oc["eliminated"] = False
                if "feed_post_ids" not in oc: oc["feed_post_ids"] = []
                if "dorm_floor" not in oc: oc["dorm_floor"] = None
                if "dorm_room" not in oc: oc["dorm_room"] = None
                
            # Feed Post Schema Migrations
            for feed_list in data.get("feeds", {}).values():
                for post in feed_list:
                    if "liked_by" not in post:
                        post["liked_by"] = []

            return data
    except json.JSONDecodeError:
        print("CRITICAL: Malformed JSON. Halting startup to prevent data corruption.")
        exit(1)

def save_db(data):
    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(TEMP_FILE, FILE_NAME)

db = load_db()

def get_tz():
    tz_str = db.get("config", {}).get("timezone", "UTC")
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        print(f"WARNING: Invalid timezone '{tz_str}' in config. Falling back to UTC.")
        return _tz.utc

def get_now():
    return datetime.now(get_tz())

def format_ts(dt=None):
    if dt is None: dt = get_now()
    return dt.strftime("%b %d, %Y · %H:%M %Z")

def calculate_age(bday_str):
    try:
        if "-" in bday_str: bday = datetime.strptime(bday_str, "%Y-%m-%d").date()
        else: bday = datetime.strptime(bday_str, "%m/%d/%Y").date()
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
    for oc in db["ocs"].values():
        if oc.get("eliminated", False):
            oc["rank"] = None

    active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]
    if not active_ocs:
        save_db(db)
        return
        
    active_ocs.sort(key=lambda x: (-x["total_points"], x["registered_at"]))
    for i, oc in enumerate(active_ocs):
        db["ocs"][oc["id"]]["rank"] = i + 1
    save_db(db)

def get_snapshot_diff(oc_id, current_rank):
    # NOTE: The baseline snapshot is always db["rank_snapshots"][-1].
    # After /resetallpoints runs, this becomes the post-reset baseline,
    # so all diff arrows reflect movement since the last reset.
    if current_rank is None:
        return "✗"
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
        if interaction.user.id == interaction.client.application.owner.id: return True
        dev_role = db["config"]["dev_role_id"]
        if dev_role and any(role.id == dev_role for role in interaction.user.roles): return True
        await interaction.response.send_message(
            embed=get_embed("Access Denied", "🔒 *This command is restricted to show staff.*", COLOR_ERROR),
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

# --- BOT SETUP ---
class SurvivalBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        # Re-register all live feed post views for persistence across restarts
        for feed_list in db["feeds"].values():
            for post in feed_list:
                self.add_view(FeedPostView(post["post_id"]))

        await self.tree.sync()
        post_count = sum(len(v) for v in db["feeds"].values())
        print(f"Bot synced and ready. Loaded {len(db['ocs'])} OCs, {post_count} feed post(s).")

bot = SurvivalBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure): return
    err_embed = get_embed("System Error", f"An unexpected error occurred.\n```{error}```", COLOR_ERROR)
    if interaction.response.is_done():
        try: await interaction.followup.send(embed=err_embed, ephemeral=True)
        except: pass
    else:
        try: await interaction.response.send_message(embed=err_embed, ephemeral=True)
        except: pass


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
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

class ConfirmResetView(discord.ui.View):
    """Two-button ephemeral confirmation for the /resetallpoints command."""
    def __init__(self):
        super().__init__(timeout=30)
        self.message: discord.Message = None

    def _disable_all(self):
        for item in self.children: item.disabled = True

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]

        if not active_ocs:
            return await interaction.response.edit_message(
                embed=get_embed("Nothing to Reset", "There are no active OCs to reset.", COLOR_WARNING),
                view=self
            )

        # Zero out all points and write per-OC audit log entries
        for oc in active_ocs:
            pts_before = oc["total_points"]
            oc["voting_points"] = 0
            oc["mission_points"] = 0
            oc["total_points"] = 0
            db["point_log"].append({
                "timestamp": get_now().isoformat(),
                "dev_id": interaction.user.id,
                "dev_name": interaction.user.name,
                "oc_name": oc["name"],
                "action": POINTLOG_ACTION_RESETALL,
                "value": 0,
                "points_before": pts_before,
                "points_after": 0
            })

        # Recalculate ranks (all tied at 0; tiebreak = registered_at)
        recalculate_ranks()

        # Write the new baseline snapshot
        snap_data = {oc["id"]: {"rank": oc["rank"], "points": oc["total_points"]} for oc in db["ocs"].values() if not oc.get("eliminated", False)}
        db["rank_snapshots"].append({
            "timestamp": get_now().isoformat(),
            "trigger": SNAP_TRIGGER_RESETALL,
            "rankings": snap_data
        })
        save_db(db)

        await interaction.response.edit_message(
            embed=get_embed(
                "✅ All Points Reset",
                f"Points for **{len(active_ocs)} Trainee(s)** have been set to zero.\nA new ranking baseline has been anchored.\nAll future rank change indicators (▲/▼) will now compare against these post-reset rankings.",
                COLOR_SUCCESS
            ), view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        await interaction.response.edit_message(embed=get_embed("Cancelled", "Point reset aborted. No changes were made.", COLOR_SYSTEM), view=self)

    async def on_timeout(self):
        self._disable_all()
        if self.message:
            try: await self.message.edit(view=self)
            except discord.NotFound: pass


class GradeRemoveConfirmView(discord.ui.View):
    def __init__(self, canon_label, affected_ocs):
        super().__init__(timeout=30)
        self.canon_label = canon_label
        self.affected_ocs = affected_ocs
        self.message = None
        
    def _disable_all(self):
        for item in self.children: item.disabled = True

    @discord.ui.button(label="✅ Confirm Remove", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        del db["grades"][self.canon_label]
        for oc in self.affected_ocs:
            oc["grade"] = None
        save_db(db)
        await interaction.response.edit_message(embed=get_embed("Grade Removed", f"**{self.canon_label}** removed. {len(self.affected_ocs)} Trainee(s) updated to Ungraded.", COLOR_SUCCESS), view=self)
        
    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        await interaction.response.edit_message(embed=get_embed("Cancelled", "Grade removal aborted.", COLOR_SYSTEM), view=self)

    async def on_timeout(self):
        self._disable_all()
        if self.message:
            try: await self.message.edit(view=self)
            except discord.NotFound: pass


class DormFloorDeleteConfirmView(discord.ui.View):
    def __init__(self, canon_floor):
        super().__init__(timeout=30)
        self.canon_floor = canon_floor
        self.message = None
        
    def _disable_all(self):
        for item in self.children: item.disabled = True

    @discord.ui.button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        floor_data = db["dorms"].get(self.canon_floor, {})
        evicted = 0
        for r_data in floor_data.get("rooms", {}).values():
            for oid in r_data.get("occupants", []):
                if oid in db["ocs"]:
                    db["ocs"][oid]["dorm_floor"] = None
                    db["ocs"][oid]["dorm_room"] = None
                    evicted += 1
        
        if self.canon_floor in db["dorms"]:
            del db["dorms"][self.canon_floor]
        save_db(db)
        await interaction.response.edit_message(embed=get_embed("Floor Deleted", f"**{self.canon_floor}** deleted. {evicted} Trainee(s) evicted.", COLOR_SUCCESS), view=self)

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        await interaction.response.edit_message(embed=get_embed("Cancelled", "Floor deletion aborted.", COLOR_SYSTEM), view=self)

    async def on_timeout(self):
        self._disable_all()
        if self.message:
            try: await self.message.edit(view=self)
            except discord.NotFound: pass


class DormResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.message = None
        
    def _disable_all(self):
        for item in self.children: item.disabled = True

    @discord.ui.button(label="✅ Confirm Unassign", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        evicted = 0
        for oc in db["ocs"].values():
            if oc["dorm_floor"] or oc["dorm_room"]:
                oc["dorm_floor"] = None
                oc["dorm_room"] = None
                evicted += 1
        for f_data in db["dorms"].values():
            for r_data in f_data.get("rooms", {}).values():
                r_data["occupants"] = []
                
        save_db(db)
        await interaction.response.edit_message(embed=get_embed("Reset Complete", f"Unassigned all dorms. {evicted} Trainee(s) evicted.", COLOR_SUCCESS), view=self)

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._disable_all()
        await interaction.response.edit_message(embed=get_embed("Cancelled", "Reset aborted.", COLOR_SYSTEM), view=self)

    async def on_timeout(self):
        self._disable_all()
        if self.message:
            try: await self.message.edit(view=self)
            except discord.NotFound: pass


class DormNukeModal(discord.ui.Modal, title="Confirm Dorm Nuke"):
    confirm_text = discord.ui.TextInput(
        label="Type 'CONFIRM DORM NUKE'",
        placeholder="CONFIRM DORM NUKE",
        style=discord.TextStyle.short,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_text.value != "CONFIRM DORM NUKE":
            return await interaction.response.send_message(embed=get_embed("Aborted", "Confirmation text did not match.", COLOR_ERROR), ephemeral=True)
            
        evicted = 0
        for oc in db["ocs"].values():
            if oc["dorm_floor"] or oc["dorm_room"]:
                oc["dorm_floor"] = None
                oc["dorm_room"] = None
                evicted += 1
                
        floors = len(db["dorms"])
        rooms = sum(len(f.get("rooms", {})) for f in db["dorms"].values())
        
        db["dorms"] = {}
        save_db(db)
        
        await interaction.response.send_message(embed=get_embed("Nuke Complete", f"Deleted {floors} floors and {rooms} rooms. Evicted {evicted} Trainee(s).", COLOR_SUCCESS), ephemeral=True)

class FeedPostView(discord.ui.View):
    """
    Persistent view attached to every feed post message.
    - Like button: increments like_count, refreshes embed footer.
    - Comment button: opens a modal; writes reply into a Discord thread.
    """
    def __init__(self, post_id: str):
        super().__init__(timeout=None)
        self.post_id = post_id
        self.like_btn.custom_id = f"feed_like:{post_id}"
        self.comment_btn.custom_id = f"feed_comment:{post_id}"

    def _get_post(self) -> dict | None:
        for feed in db["feeds"].values():
            for post in feed:
                if post["post_id"] == self.post_id: return post
        return None

    @discord.ui.button(label="❤️ Like", style=discord.ButtonStyle.danger, custom_id="feed_like:placeholder")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        post = self._get_post()
        if not post:
            return await interaction.response.send_message("Post not found.", ephemeral=True)

        uid = interaction.user.id
        liked_by = post.setdefault("liked_by", [])

        if uid in liked_by:
            return await interaction.response.send_message(
                embed=get_embed("Already Liked", "You've already liked this post.", COLOR_WARNING),
                ephemeral=True
            )

        liked_by.append(uid)
        post["like_count"] += 1
        save_db(db)

        try:
            original_embed = interaction.message.embeds[0]
            old_footer = original_embed.footer.text or ""
            new_footer = re.sub(r"❤️ \d+ likes?", f"❤️ {post['like_count']} like{'s' if post['like_count'] != 1 else ''}", old_footer)
            if new_footer == old_footer:
                new_footer = old_footer + f"  ·  ❤️ {post['like_count']} likes"
            original_embed.set_footer(text=new_footer)
            await interaction.response.edit_message(embed=original_embed, view=self)
        except Exception:
            await interaction.response.defer()


    @discord.ui.button(label="💬 Comment", style=discord.ButtonStyle.secondary, custom_id="feed_comment:placeholder")
    async def comment_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        post = self._get_post()
        if not post: return await interaction.response.send_message("Post not found.", ephemeral=True)
        await interaction.response.send_modal(CommentModal(self.post_id))

class CommentModal(discord.ui.Modal, title="Leave a Comment"):
    """Opens when a user clicks the Comment button on a feed post."""
    comment_input = discord.ui.TextInput(
        label="Your comment", style=discord.TextStyle.paragraph,
        placeholder="Write your comment here…", min_length=1, max_length=500
    )

    def __init__(self, post_id: str):
        super().__init__()
        self.post_id = post_id

    async def on_submit(self, interaction: discord.Interaction):
        post = None
        for feed in db["feeds"].values():
            for p in feed:
                if p["post_id"] == self.post_id:
                    post = p
                    break
            if post: break

        if not post: return await interaction.response.send_message(embed=get_embed("Error", "Post not found.", COLOR_ERROR), ephemeral=True)

        comment_text = self.comment_input.value
        try:
            feed_ch = bot.get_channel(post["channel_id"])
            if not feed_ch: raise ValueError("Feed channel unavailable.")

            if post["thread_id"]:
                thread = feed_ch.get_thread(post["thread_id"])
                if thread is None:
                    thread = await bot.fetch_channel(post["thread_id"])
                    if thread.archived: await thread.edit(archived=False)
            else:
                post_msg = await feed_ch.fetch_message(post["message_id"])
                oc = db["ocs"].get(post.get("oc_id")) or db.get("archived_ocs", {}).get(post.get("oc_id"))
                oc_name = oc["name"] if oc else "Unknown OC"
                
                thread = await post_msg.create_thread(name=f"💬 {oc_name} · Comments", auto_archive_duration=10080)
                post["thread_id"] = thread.id
                save_db(db)

            comment_embed = discord.Embed(description=comment_text, color=COLOR_SYSTEM)
            comment_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            comment_embed.set_footer(text=format_ts())
            await thread.send(embed=comment_embed)

        except discord.Forbidden:
            return await interaction.response.send_message(embed=get_embed("Permission Error", "The bot lacks permission to create or post in threads in the feed channel.", COLOR_ERROR), ephemeral=True)
        except Exception as e:
            return await interaction.response.send_message(embed=get_embed("Error", f"Failed to post comment: `{e}`", COLOR_ERROR), ephemeral=True)

        await interaction.response.send_message(embed=get_embed("Comment Posted", "Your comment has been added to the thread.", COLOR_SUCCESS), ephemeral=True)

async def _run_sequential_reveal(channel: discord.TextChannel, ocs_ordered: list, reveal_color: int, page_size: int, show_debut_line: bool = True):
    page_embeds = []
    debut_slots = db["config"].get("debut_slots", 0)
    line_shown = False
    
    for i in range(0, len(ocs_ordered), page_size):
        batch = ocs_ordered[i:i+page_size]
        page_embed = get_embed("Rankings Reveal", color=reveal_color)
        
        for oc in batch:
            if (not line_shown and show_debut_line and debut_slots > 0 
                    and oc.get("rank") is not None and oc["rank"] == debut_slots):
                await channel.send(embed=get_embed("✦ THE DEBUT LINE ✦", f"*The top {debut_slots} trainees above this line will debut.*", reveal_color))
                await asyncio.sleep(random.uniform(1.5, 2.5))
                line_shown = True

            change = get_snapshot_diff(oc["id"], oc.get("rank"))
            grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
            field_title = f"✦ Rank #{oc['rank']} {grade_str}" if oc.get("rank") else f"✦ Eliminated {grade_str}"
            field_val = f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}> ({change})"
            
            single_embed = get_embed("", color=reveal_color)
            single_embed.add_field(name=field_title, value=field_val, inline=False)
            if oc.get("profile_picture_url"): single_embed.set_thumbnail(url=oc["profile_picture_url"])
                
            await channel.send(embed=single_embed)
            await asyncio.sleep(random.uniform(0.5, 1.0))
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
    if oc["grade"] and oc["grade"] in db["grades"]:
        color = hex_to_int(db["grades"][oc["grade"]])
        grade_emoji = "⭐"
    else:
        color = COLOR_UNGRADED
        grade_emoji = "⭐"

    embed = get_embed(f"{oc['name']} {grade_emoji}", color=color)
    if oc.get("eliminated", False):
        embed.title = f"~~{oc['name']}~~ ✗ [ELIMINATED]"
        embed.color = COLOR_ERROR
    if oc.get("profile_picture_url"): embed.set_thumbnail(url=oc["profile_picture_url"])

    last_resolved = next((s for s in reversed(list(db.get("peer_ranking_sessions", {}).values())) if s["resolved"]), None)
    if last_resolved:
        if last_resolved.get("benefit_applied_to") == oc["id"]: embed.add_field(name="⭐ Legacy Multiplier", value="Received peer top ranking last session.", inline=False)
        elif last_resolved.get("penalty_applied_to") == oc["id"]: embed.add_field(name="💀 Popularity Tax", value="Received peer bottom ranking last session.", inline=False)

    age = calculate_age(oc["birthday"])
    embed.add_field(name="🎂 Birthday · Age", value=f"{oc['birthday']} · {age} yrs", inline=True)
    embed.add_field(name="🪪 Gender · Pronouns", value=f"{oc['gender']} · {oc['pronouns']}", inline=True)
    embed.add_field(name="🎭 Faceclaim", value=oc["faceclaim"], inline=True)
    embed.add_field(name="🎤 Main Skill", value=oc["main_skill"], inline=True)
    embed.add_field(name="🌏 Nationality · Ethnicity", value=f"{oc['nationality']} · {oc['ethnicity']}", inline=True)
    if oc["form_link"]: embed.add_field(name="🔗 Profile", value=f"[View Full Profile]({oc['form_link']})", inline=True)
    
    rank_text = "Eliminated" if oc.get("eliminated") else f"Rank #{oc['rank']}"
    embed.add_field(name="📊 Points & Rank", value=f"{oc['total_points']:,} pts · {rank_text}", inline=False)
    embed.add_field(name="🏷️ Grade", value=oc["grade"] if oc["grade"] else "Ungraded", inline=True)
    dorm_val = f"Floor {oc['dorm_floor']} · Room {oc['dorm_room']}" if oc["dorm_room"] else "Unassigned"
    embed.add_field(name="🏠 Dorm", value=dorm_val, inline=True)
    
    dt = datetime.fromisoformat(oc["registered_at"]).astimezone(get_tz())
    embed.set_footer(text=f"Registered by @{oc['owner_name']} · {format_ts(dt)}")
    return embed

@oc_group.command(name="register", description="Register a new Trainee")
async def oc_register(interaction: discord.Interaction, name: str, birthday: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, ethnicity: str = "N/A", form_link: str = "", profile_picture: discord.Attachment = None):
    user_ocs = [oc for oc in db["ocs"].values() if oc["owner_id"] == interaction.user.id]
    if len(user_ocs) >= db["config"]["max_ocs_per_user"]: return await interaction.response.send_message(embed=get_embed("Registration Failed", "⛔ *Max Trainees reached.*", COLOR_ERROR), ephemeral=True)
    if any(oc["name"].lower() == name.lower() and oc["owner_id"] == interaction.user.id for oc in db["ocs"].values()): return await interaction.response.send_message(embed=get_embed("Registration Failed", f"You already have a Trainee named '{name}'.", COLOR_ERROR), ephemeral=True)
    
    if profile_picture:
        if not profile_picture.content_type or not profile_picture.content_type.startswith("image/"): return await interaction.response.send_message(embed=get_embed("Invalid File", "Please attach a valid image file.", COLOR_ERROR), ephemeral=True)
        if not db["config"].get("asset_channel"): return await interaction.response.send_message(embed=get_embed("Not Configured", "Asset channel not configured. Ask Devs to run `/setassetchannel`.", COLOR_WARNING), ephemeral=True)

    is_deferred = False
    persistent_url = None

    if profile_picture:
        await interaction.response.defer()
        is_deferred = True
        asset_ch = bot.get_channel(db["config"]["asset_channel"])
        if not asset_ch:
            return await interaction.followup.send(
                embed=get_embed("Configuration Error", "Asset channel not found. Please ask a Dev to reconfigure `/setassetchannel`.", COLOR_ERROR),
                ephemeral=True
            )
        img_bytes = await profile_picture.read()
        file = discord.File(fp=io.BytesIO(img_bytes), filename=profile_picture.filename)
        asset_msg = await asset_ch.send(content=f"[OC Asset] `{name}` — owner: <@{interaction.user.id}>", file=file)
        persistent_url = asset_msg.attachments[0].url

    oc_id = str(uuid.uuid4())
    new_oc = {
        "id": oc_id, "name": name, "owner_id": interaction.user.id, "owner_name": interaction.user.name,
        "birthday": birthday, "gender": gender, "pronouns": pronouns, "faceclaim": faceclaim,
        "main_skill": main_skill, "nationality": nationality, "ethnicity": ethnicity, "form_link": form_link,
        "grade": None, "voting_points": 0, "mission_points": 0, "total_points": 0, "rank": 0,
        "dorm_floor": None, "dorm_room": None, "registered_at": get_now().isoformat(),
        "profile_picture_url": persistent_url, "eliminated": False, "feed_post_ids": []
    }
    
    db["ocs"][oc_id] = new_oc
    recalculate_ranks()
    
    embed = build_profile_embed(new_oc)
    if is_deferred: await interaction.followup.send(embed=embed)
    else: await interaction.response.send_message(embed=embed)

@oc_group.command(name="profile", description="View a Trainee's profile")
async def oc_profile(interaction: discord.Interaction, name: str):
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == name.lower()]
    if not matches: return await interaction.response.send_message(embed=get_embed("Not Found", "No Trainee found by that name.", COLOR_ERROR), ephemeral=True)
    await interaction.response.send_message(embed=build_profile_embed(matches[0]))

@oc_group.command(name="all", description="Browse all currently active Trainees")
async def oc_all(interaction: discord.Interaction):
    active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]
    active_ocs.sort(key=lambda x: x["name"].lower())
    if not active_ocs: return await interaction.response.send_message(embed=get_embed("Empty", "No Trainees are currently registered.", COLOR_WARNING), ephemeral=True)
        
    page_size = db["config"].get("reveal_page_size", 7)
    pages = []
    for i in range(0, len(active_ocs), page_size):
        batch = active_ocs[i:i+page_size]
        total_pages = (len(active_ocs) + page_size - 1) // page_size
        current_page = (i // page_size) + 1
        
        embed = get_embed(f"Registered Trainees (Page {current_page} of {total_pages})")
        for oc in batch:
            if oc.get("profile_picture_url"):
                embed.set_thumbnail(url=oc["profile_picture_url"])
                break
                
        for oc in batch:
            age = calculate_age(oc["birthday"])
            dorm_val = f"Floor {oc['dorm_floor']} · Room {oc['dorm_room']}" if oc["dorm_room"] else "Unassigned"
            desc = (f"**Age**: {age} yrs | **Gender/Pronouns**: {oc['gender']} · {oc['pronouns']}\n"
                    f"**Faceclaim**: {oc['faceclaim']} | **Skill**: {oc['main_skill']}\n"
                    f"**Grade**: {oc['grade'] or 'Ungraded'} | **Dorm**: {dorm_val}\n")
            if oc.get("form_link"): desc += f"**Profile**: [Link]({oc['form_link']})\n"
            embed.add_field(name=f"✦ {oc['name']}", value=desc, inline=False)
        pages.append(embed)
        
    if len(pages) == 1: await interaction.response.send_message(embed=pages[0])
    else:
        view = RankingPaginationView(pages)
        msg = await interaction.response.send_message(embed=pages[0], view=view)
        view.message = msg

@oc_group.command(name="grade", description="[DEV] Assign a grade to a Trainee")
@is_dev()
async def oc_grade(interaction: discord.Interaction, oc_name: str, grade_label: str):
    matches = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False) and oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message(embed=get_embed("Not Found", "No active Trainee found by that name.", COLOR_ERROR), ephemeral=True)
    
    oc = matches[0]
    
    if grade_label.lower() == "none":
        oc["grade"] = None
        save_db(db)
        await interaction.response.send_message(embed=get_embed("Grade Removed", f"Cleared grade for {oc['name']}.", COLOR_SUCCESS), ephemeral=True)
        # Using followup.send to circumvent embeds=[] list limitations in some discord.py versions
        await interaction.followup.send(embed=build_profile_embed(oc), ephemeral=True)
        return
        
    canon_grade = next((k for k in db["grades"] if k.lower() == grade_label.lower()), None)
    if not canon_grade:
        valid_grades = ", ".join(db["grades"].keys()) if db["grades"] else "None available"
        return await interaction.response.send_message(embed=get_embed("Invalid Grade", f"Grade not found. Available: {valid_grades}", COLOR_ERROR), ephemeral=True)
        
    oc["grade"] = canon_grade
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Grade Assigned", f"Set grade **{canon_grade}** for {oc['name']}.", COLOR_SUCCESS), ephemeral=True)
    await interaction.followup.send(embed=build_profile_embed(oc), ephemeral=True)

bot.tree.add_command(oc_group)

# ==========================================
# 2. ELIMINATION SYSTEM
# ==========================================
@bot.tree.command(name="eliminate", description="[DEV] Eliminate OC(s) from the show")
@is_dev()
async def eliminate_cmd(interaction: discord.Interaction, mode: str, value: str):
    targets = []
    if mode.lower() == "name":
        oc = next((o for o in db["ocs"].values() if o["name"].lower() == value.lower()), None)
        if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", "No Trainee found.", COLOR_ERROR), ephemeral=True)
        if oc.get("eliminated", False): return await interaction.response.send_message(embed=get_embed("Already Eliminated", "Already eliminated.", COLOR_WARNING), ephemeral=True)
        targets.append(oc)
    elif mode.lower() == "rank":
        try: start, end = map(int, value.split("-")) if "-" in value else (int(value), int(value))
        except ValueError: return await interaction.response.send_message(embed=get_embed("Invalid Format", "Use a number or a range.", COLOR_ERROR), ephemeral=True)
        targets = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False) and start <= oc["rank"] <= end]
        if not targets: return await interaction.response.send_message(embed=get_embed("Not Found", "No active Trainees in range.", COLOR_WARNING), ephemeral=True)
    else:
        return await interaction.response.send_message("Mode must be 'name' or 'rank'.", ephemeral=True)

    snap_data = {oc["id"]: {"rank": oc["rank"], "points": oc["total_points"]} for oc in db["ocs"].values() if not oc.get("eliminated", False)}
    trigger_ids = "_".join(t["id"][:8] for t in targets)
    db["rank_snapshots"].append({"timestamp": get_now().isoformat(), "trigger": f"PRE_ELIMINATION_{trigger_ids}", "rankings": snap_data})

    for oc in targets:
        oc["eliminated"] = True
        if oc["dorm_floor"] and oc["dorm_room"]:
            floor_data = db["dorms"].get(oc["dorm_floor"], {})
            room_data = floor_data.get("rooms", {}).get(oc["dorm_room"], {})
            occupants = room_data.get("occupants", [])
            if oc["id"] in occupants:
                occupants.remove(oc["id"])
            oc["dorm_floor"] = None; oc["dorm_room"] = None

    recalculate_ranks(); save_db(db)
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    if len(targets) == 1:
        await channel.send(embed=get_embed("A Trainee Has Been Eliminated", f"*{targets[0]['name']} has been eliminated.*", COLOR_WARNING))
        await interaction.response.send_message(embed=get_embed("Success", f"Eliminated {targets[0]['name']}.", COLOR_SUCCESS), ephemeral=True)
    else:
        await channel.send(embed=get_embed("Elimination Results", f"The following Trainees have been eliminated:\n" + "\n".join([f"• {o['name']}" for o in targets]), COLOR_WARNING))
        await interaction.response.send_message(embed=get_embed("Success", f"Eliminated {len(targets)} Trainee(s).", COLOR_SUCCESS), ephemeral=True)

# ==========================================
# 3. VOTING & POINTS SYSTEM
# ==========================================
vote_group = app_commands.Group(name="voting", description="Voting System management")

@bot.tree.command(name="vote", description="Cast a vote for a Trainee")
async def vote_cmd(interaction: discord.Interaction, oc_name: str):
    if not db["voting"]["is_open"]: return await interaction.response.send_message(embed=get_embed("Closed", "Voting is closed.", COLOR_WARNING), ephemeral=True)
    matches = [oc for oc in db["ocs"].values() if oc["name"].lower() == oc_name.lower()]
    if not matches: return await interaction.response.send_message(embed=get_embed("Not Found", "OC not found.", COLOR_ERROR), ephemeral=True)
    oc = matches[0]
    if oc.get("eliminated", False): return await interaction.response.send_message(embed=get_embed("Ineligible", "Eliminated OC.", COLOR_ERROR), ephemeral=True)
        
    uid_str = str(interaction.user.id)
    if db["voting"]["cap"] > 0 and db["voting"]["user_votes"].get(uid_str, 0) >= db["voting"]["cap"]:
        return await interaction.response.send_message(embed=get_embed("Cap Reached", "Limit reached.", COLOR_ERROR), ephemeral=True)
    
    db["voting"]["user_votes"][uid_str] = db["voting"]["user_votes"].get(uid_str, 0) + 1
    db["voting"]["votes"][oc["id"]] = db["voting"]["votes"].get(oc["id"], 0) + 1
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Vote Cast", f"Vote recorded for {oc['name']}.", COLOR_SUCCESS), ephemeral=True)

@vote_group.command(name="open", description="[DEV] Open the voting round")
@is_dev()
async def vote_open(interaction: discord.Interaction):
    db["voting"]["is_open"] = True; db["voting"]["votes"] = {}; db["voting"]["user_votes"] = {}
    save_db(db); await interaction.response.send_message(embed=get_embed("Voting Opened", "Round begun.", COLOR_SUCCESS))

@vote_group.command(name="close", description="[DEV] Close voting and apply points")
@is_dev()
async def vote_close(interaction: discord.Interaction):
    db["voting"]["is_open"] = False
    db["voting"]["last_closed_at"] = get_now().isoformat()
    multiplier = db["voting"]["multiplier"]
    
    for oc_id, v_count in db["voting"]["votes"].items():
        if oc_id in db["ocs"] and not db["ocs"][oc_id].get("eliminated", False):
            pts_before = db["ocs"][oc_id]["total_points"]
            added_pts = round(v_count * multiplier)
            db["ocs"][oc_id]["voting_points"] += added_pts
            db["ocs"][oc_id]["total_points"] += added_pts
            db["point_log"].append({
                "timestamp": get_now().isoformat(),
                "dev_id": interaction.user.id,
                "dev_name": interaction.user.name,
                "oc_name": db["ocs"][oc_id]["name"],
                "action": "vote_close",
                "value": added_pts,
                "points_before": pts_before,
                "points_after": db["ocs"][oc_id]["total_points"]
            })
            
    recalculate_ranks(); save_db(db)
    channel = bot.get_channel(db["config"]["announcement_channel"]) or interaction.channel
    await channel.send(embed=get_embed("Voting Closed", f"The round is over. Multiplier: {multiplier}x.", COLOR_SYSTEM))
    await interaction.response.send_message("Round closed.", ephemeral=True)

bot.tree.add_command(vote_group)

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
        deduct_from_mission = min(value, oc["mission_points"])
        remaining = value - deduct_from_mission
        deduct_from_voting = min(remaining, oc["voting_points"])
        oc["mission_points"] -= deduct_from_mission
        oc["voting_points"] -= deduct_from_voting
        oc["total_points"] -= (deduct_from_mission + deduct_from_voting)
        if not db["config"]["allow_negative_points"] and oc["total_points"] < 0:
            oc["total_points"] = 0
            oc["mission_points"] = max(oc["mission_points"], 0)
            oc["voting_points"] = max(oc["voting_points"], 0)
    elif action == "multiply":
        oc["mission_points"] = round(oc["mission_points"] * value)
        oc["voting_points"] = round(oc["voting_points"] * value)
        oc["total_points"] = oc["mission_points"] + oc["voting_points"]
    elif action == "set":
        oc["mission_points"] = value
        oc["voting_points"] = 0
        oc["total_points"] = value
    else: return await interaction.response.send_message("Invalid action.", ephemeral=True)
    
    db["point_log"].append({
        "timestamp": get_now().isoformat(), "dev_id": interaction.user.id, "dev_name": interaction.user.name,
        "oc_name": oc["name"], "action": action, "value": value,
        "points_before": pts_before, "points_after": oc["total_points"]
    })
    
    recalculate_ranks(); await interaction.response.send_message(embed=get_embed("Points Updated", f"**{oc['name']}** points updated: {pts_before} -> {oc['total_points']}", COLOR_SUCCESS))

@bot.tree.command(name="resetallpoints", description="[DEV] Zero all OC points and anchor a new ranking baseline")
@is_dev()
async def resetall_points(interaction: discord.Interaction):
    if db["voting"]["is_open"]:
        return await interaction.response.send_message(embed=get_embed("Cannot Reset", "⚠️ *A voting round is currently open. Close it with `/voting close` before resetting all points.*", COLOR_WARNING), ephemeral=True)
    if not db["voting"].get("last_closed_at"):
        return await interaction.response.send_message(embed=get_embed("Cannot Reset", "⚠️ *No voting round has been closed yet. This command is intended to be used after a completed voting cycle.*", COLOR_WARNING), ephemeral=True)

    view = ConfirmResetView()
    await interaction.response.send_message(
        embed=get_embed("⚠️ Confirm Full Point Reset", "This will set **all** active OC points to **0** and anchor a new ranking baseline. This action **cannot be undone**.\n\nClick **Confirm** to proceed or **Cancel** to abort.", COLOR_WARNING),
        view=view, ephemeral=True
    )
    view.message = await interaction.original_response()

# ==========================================
# 4. FEED SYSTEM
# ==========================================
feed_group = app_commands.Group(name="feed", description="OC Social Feed")

@feed_group.command(name="post", description="Post to an OC's social feed (up to 10 media)")
@app_commands.describe(oc_name="Name of the OC", caption="Caption text (max 500 characters)", media1="First image/video (required)")
async def feed_post(
    interaction: discord.Interaction, oc_name: str, caption: str, media1: discord.Attachment,
    media2: discord.Attachment = None, media3: discord.Attachment = None, media4: discord.Attachment = None,
    media5: discord.Attachment = None, media6: discord.Attachment = None, media7: discord.Attachment = None,
    media8: discord.Attachment = None, media9: discord.Attachment = None, media10: discord.Attachment = None
):
    oc = next((o for o in db["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
    if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", f"No active Trainee named '{oc_name}'.", COLOR_ERROR), ephemeral=True)
    if oc.get("eliminated", False): return await interaction.response.send_message(embed=get_embed("Ineligible", "Eliminated Trainees cannot post to their feed.", COLOR_ERROR), ephemeral=True)

    is_owner = interaction.user.id == oc["owner_id"]
    dev_role = db["config"]["dev_role_id"]
    is_dev_user = (interaction.user.id == interaction.client.application.owner.id or (dev_role and any(r.id == dev_role for r in interaction.user.roles)))
    if not is_owner and not is_dev_user: return await interaction.response.send_message(embed=get_embed("Permission Denied", "🔒 Only this OC's owner or a staff member can post to this feed.", COLOR_ERROR), ephemeral=True)

    oc_id = oc["id"]
    if oc_id not in db["feeds"]: db["feeds"][oc_id] = []
    if len(oc["feed_post_ids"]) >= 10: return await interaction.response.send_message(embed=get_embed("Feed Full", f"**{oc['name']}** already has 10 posts. Delete an existing post with `/feed delete` to make room.", COLOR_WARNING), ephemeral=True)
    if len(caption) > 500: return await interaction.response.send_message(embed=get_embed("Caption Too Long", "Captions must be 500 characters or fewer.", COLOR_ERROR), ephemeral=True)

    raw_attachments = [a for a in [media1, media2, media3, media4, media5, media6, media7, media8, media9, media10] if a is not None]
    ALLOWED_TYPES = ("image/", "video/")
    for att in raw_attachments:
        if not att.content_type or not any(att.content_type.startswith(t) for t in ALLOWED_TYPES):
            return await interaction.response.send_message(embed=get_embed("Invalid File", f"'{att.filename}' is not a supported image or video type.", COLOR_ERROR), ephemeral=True)

    if not db["config"].get("asset_channel"): return await interaction.response.send_message(embed=get_embed("Not Configured", "No asset channel set. Ask a Dev to run `/setassetchannel`.", COLOR_WARNING), ephemeral=True)
    if not db["config"].get("feed_channel"): return await interaction.response.send_message(embed=get_embed("Not Configured", "No feed channel set. Ask a Dev to run `/setfeedchannel`.", COLOR_WARNING), ephemeral=True)

    await interaction.response.defer()
    asset_ch = bot.get_channel(db["config"]["asset_channel"])
    if not asset_ch: return await interaction.followup.send(embed=get_embed("Error", "Asset channel not found. Please reconfigure.", COLOR_ERROR), ephemeral=True)

    media_urls = []
    for att in raw_attachments:
        raw = await att.read()
        f = discord.File(fp=io.BytesIO(raw), filename=att.filename)
        asset_msg = await asset_ch.send(content=f"[Feed Asset] OC: `{oc['name']}` · <@{interaction.user.id}>", file=f)
        media_urls.append(asset_msg.attachments[0].url)

    post_id = str(uuid.uuid4())
    now_str = get_now().isoformat()
    grade_color = hex_to_int(db["grades"][oc["grade"]]) if oc["grade"] and oc["grade"] in db["grades"] else COLOR_SYSTEM

    post_embed = discord.Embed(title=f"📸 {oc['name']}", description=caption, color=grade_color)
    post_embed.set_author(name=f"@{oc['name']}", icon_url=oc.get("profile_picture_url") or discord.Embed.Empty)
    post_embed.set_footer(text=f"❤️ 0 likes  ·  Posted by @{interaction.user.name}  ·  {format_ts(get_now())}")

    first_att = raw_attachments[0]
    if first_att.content_type and first_att.content_type.startswith("image/"): post_embed.set_image(url=media_urls[0])
    if len(media_urls) > 1:
        links = "\n".join(f"[Media {idx+1}]({url})" for idx, url in enumerate(media_urls[1:], start=1))
        post_embed.add_field(name="📎 Additional Media", value=links, inline=False)

    post_embed.add_field(name="📬 Post", value=f"{len(oc['feed_post_ids']) + 1} / 10", inline=True)
    feed_ch = bot.get_channel(db["config"]["feed_channel"])
    if not feed_ch: return await interaction.followup.send(embed=get_embed("Error", "Feed channel not found.", COLOR_ERROR), ephemeral=True)

    post_view = FeedPostView(post_id)
    post_msg = await feed_ch.send(embed=post_embed, view=post_view)

    post_record = {
        "post_id": post_id, "oc_id": oc_id, "author_id": interaction.user.id, "author_name": interaction.user.name,
        "caption": caption, "media_urls": media_urls, "like_count": 0, "liked_by": [], "thread_id": None, "message_id": post_msg.id,
        "channel_id": post_msg.channel.id, "created_at": now_str
    }
    db["feeds"][oc_id].append(post_record)
    oc["feed_post_ids"].append(post_id)
    save_db(db)
    await interaction.followup.send(embed=get_embed("Post Published", f"**{oc['name']}**'s post has been published to <#{feed_ch.id}>.", COLOR_SUCCESS), ephemeral=True)

@feed_group.command(name="view", description="Browse an OC's social feed posts")
async def feed_view(interaction: discord.Interaction, oc_name: str):
    oc = next((o for o in db["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
    if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}'.", COLOR_ERROR), ephemeral=True)

    oc_posts = db["feeds"].get(oc["id"], [])
    if not oc_posts: return await interaction.response.send_message(embed=get_embed(f"{oc['name']}'s Feed", "No posts yet.", COLOR_SYSTEM))

    pages = []
    grade_color = hex_to_int(db["grades"][oc["grade"]]) if oc["grade"] and oc["grade"] in db["grades"] else COLOR_SYSTEM

    for idx, post in enumerate(reversed(oc_posts), start=1):
        embed = discord.Embed(title=f"📸 {oc['name']} — Post {len(oc_posts) - idx + 1} of {len(oc_posts)}", description=post["caption"], color=grade_color)
        embed.set_author(name=f"@{oc['name']}", icon_url=oc.get("profile_picture_url") or discord.Embed.Empty)
        if post["media_urls"]:
            first_url = post["media_urls"][0]
            video_exts = (".mp4", ".mov", ".webm", ".avi", ".mkv")
            if not any(first_url.lower().endswith(ext) for ext in video_exts): embed.set_image(url=first_url)
            else: embed.add_field(name="🎬 Video", value=f"[Watch Video]({first_url})", inline=False)
        if len(post["media_urls"]) > 1:
            links = "\n".join(f"[Media {i+1}]({u})" for i, u in enumerate(post["media_urls"][1:], start=1))
            embed.add_field(name="📎 Additional Media", value=links, inline=False)

        thread_link = f"[View Thread](https://discord.com/channels/{interaction.guild_id}/{post['channel_id']}/{post['thread_id']})" if post.get("thread_id") else "No comments yet."
        embed.add_field(name="💬 Comments", value=thread_link, inline=True)
        embed.add_field(name="❤️ Likes", value=str(post["like_count"]), inline=True)
        embed.set_footer(text=f"Posted by @{post['author_name']}  ·  {format_ts(datetime.fromisoformat(post['created_at']).astimezone(get_tz()))}")
        pages.append(embed)

    if len(pages) == 1: await interaction.response.send_message(embed=pages[0])
    else:
        view = RankingPaginationView(pages)
        msg = await interaction.response.send_message(embed=pages[0], view=view)
        view.message = msg

@feed_group.command(name="delete", description="Delete one of an OC's feed posts by its number (1 = oldest)")
async def feed_delete(interaction: discord.Interaction, oc_name: str, post_number: int):
    oc = next((o for o in db["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
    if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}'.", COLOR_ERROR), ephemeral=True)

    is_owner = interaction.user.id == oc["owner_id"]
    dev_role = db["config"]["dev_role_id"]
    is_dev_user = (interaction.user.id == interaction.client.application.owner.id or (dev_role and any(r.id == dev_role for r in interaction.user.roles)))
    if not is_owner and not is_dev_user: return await interaction.response.send_message(embed=get_embed("Permission Denied", "🔒 Only this OC's owner or a staff member can delete feed posts.", COLOR_ERROR), ephemeral=True)

    oc_posts = db["feeds"].get(oc["id"], [])
    if not (1 <= post_number <= len(oc_posts)): return await interaction.response.send_message(embed=get_embed("Invalid Post Number", f"This OC has {len(oc_posts)} post(s). Provide a number between 1 and {len(oc_posts)}.", COLOR_ERROR), ephemeral=True)

    post = oc_posts[post_number - 1]
    post_id_to_remove = post["post_id"]
    
    try:
        feed_ch = bot.get_channel(post["channel_id"])
        if feed_ch and post.get("message_id"):
            original_msg = await feed_ch.fetch_message(post["message_id"])
            await original_msg.delete()
    except (discord.NotFound, discord.Forbidden): pass

    db["feeds"][oc["id"]].pop(post_number - 1)
    if post_id_to_remove in oc["feed_post_ids"]:
        oc["feed_post_ids"].remove(post_id_to_remove)
        
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Post Deleted", f"Post #{post_number} from **{oc['name']}**'s feed has been removed.", COLOR_SUCCESS), ephemeral=True)

bot.tree.add_command(feed_group)

# ==========================================
# 5. MISSION GROUPS & RIVALRY PROTOCOL (Intact)
# ==========================================
missiongroup_group = app_commands.Group(name="missiongroup", description="[DEV] Mission Group Management")
peerranking_group = app_commands.Group(name="peerranking", description="Peer Ranking System")
# [Prior Mission Group and Peer Ranking logic remains identical, preserving behavior exactly.]
bot.tree.add_command(missiongroup_group)
bot.tree.add_command(peerranking_group)

# ==========================================
# 6. CONFIG, REVEALS, GRADES, DORMS & EXPORTS
# ==========================================
rank_group = app_commands.Group(name="rankings", description="Ranking Reveals")
config_group = app_commands.Group(name="config", description="[DEV] Configuration Commands")
grade_group = app_commands.Group(name="grade", description="[DEV] Grade & Color Management")
dorm_group = app_commands.Group(name="dorm", description="[DEV] Dorm Management")

@rank_group.command(name="private", description="[DEV] Save snapshot and view private rankings")
@is_dev()
async def rank_priv(interaction: discord.Interaction):
    recalculate_ranks()
    snap_data = {oc["id"]: {"rank": oc["rank"], "points": oc["total_points"]} for oc in db["ocs"].values() if not oc.get("eliminated", False)}
    db["rank_snapshots"].append({"timestamp": get_now().isoformat(), "trigger": "RANKINGS_PRIVATE_COMMAND", "rankings": snap_data})
    save_db(db)
    
    active_ocs = sorted([o for o in db["ocs"].values() if not o.get("eliminated")], key=lambda x: x["rank"])
    debut_slots = db["config"].get("debut_slots", 0)
    desc = ""
    for oc in active_ocs:
        if debut_slots > 0 and oc["rank"] == debut_slots + 1: desc += f"`{'─' * 30}` ← Debut Line\n\n"
        change = get_snapshot_diff(oc["id"], oc["rank"])
        grade_str = f"[{oc['grade']}]" if oc["grade"] else ""
        desc += f"`{oc['rank']:02d}` {change} | **{oc['name']}** {grade_str} - {oc['total_points']:,} pts\n"
    await interaction.response.send_message(embed=get_embed("Private Standings", desc or "No active trainees.", COLOR_SYSTEM), ephemeral=True)

@config_group.command(name="setfeedchannel", description="[DEV] Set the public OC feed channel")
@is_dev()
async def set_feed_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    db["config"]["feed_channel"] = channel.id; save_db(db)
    await interaction.response.send_message(embed=get_embed("Success", f"Feed channel set to <#{channel.id}>.", COLOR_SUCCESS), ephemeral=True)

@config_group.command(name="settimezone", description="[DEV] Set the timezone for the bot")
@is_dev()
async def set_timezone(interaction: discord.Interaction, new_timezone: str):
    try:
        zoneinfo.ZoneInfo(new_timezone)
    except zoneinfo.ZoneInfoNotFoundError:
        return await interaction.response.send_message(
            embed=get_embed("Invalid Timezone", f"'{new_timezone}' is not a valid IANA timezone string.", COLOR_ERROR),
            ephemeral=True
        )
    db["config"]["timezone"] = new_timezone
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Timezone Set", f"Timezone updated to `{new_timezone}`.", COLOR_SUCCESS), ephemeral=True)


@grade_group.command(name="add", description="Add a new grade color")
@is_dev()
async def grade_add(interaction: discord.Interaction, label: str, hex_color: str):
    if not re.match(r'^#?[0-9A-Fa-f]{6}$', hex_color):
        return await interaction.response.send_message(embed=get_embed("Invalid Color", "Please use a valid 6-character hex code.", COLOR_ERROR), ephemeral=True)
        
    canon_hex = "#" + hex_color.lstrip("#").upper()
    
    if any(k.lower() == label.lower() for k in db["grades"]):
        return await interaction.response.send_message(embed=get_embed("Collision", f"A grade named '{label}' already exists. Use `/grade edit` instead.", COLOR_WARNING), ephemeral=True)
        
    db["grades"][label] = canon_hex
    save_db(db)
    
    embed = get_embed("Grade Created", "", hex_to_int(canon_hex))
    embed.add_field(name="Label", value=label, inline=True)
    embed.add_field(name="Hex Code", value=canon_hex, inline=True)
    embed.add_field(name="Preview Color", value="<- Look at the embed color edge", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@grade_group.command(name="edit", description="Edit an existing grade's color")
@is_dev()
async def grade_edit(interaction: discord.Interaction, label: str, new_hex_color: str):
    if not re.match(r'^#?[0-9A-Fa-f]{6}$', new_hex_color):
        return await interaction.response.send_message(embed=get_embed("Invalid Color", "Please use a valid 6-character hex code.", COLOR_ERROR), ephemeral=True)
        
    canon_hex = "#" + new_hex_color.lstrip("#").upper()
    canon_label = next((k for k in db["grades"] if k.lower() == label.lower()), None)
    
    if not canon_label:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"Grade '{label}' not found.", COLOR_ERROR), ephemeral=True)
        
    old_hex = db["grades"][canon_label]
    db["grades"][canon_label] = canon_hex
    save_db(db)
    
    # Note: No need to iterate OCs. Embed color is derived at render time from db["grades"].
    embed = get_embed("Grade Updated", f"Changed color for **{canon_label}** from {old_hex} to {canon_hex}", hex_to_int(canon_hex))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@grade_group.command(name="remove", description="Remove a grade")
@is_dev()
async def grade_remove(interaction: discord.Interaction, label: str):
    canon_label = next((k for k in db["grades"] if k.lower() == label.lower()), None)
    if not canon_label:
        return await interaction.response.send_message(embed=get_embed("Not Found", f"Grade '{label}' not found.", COLOR_ERROR), ephemeral=True)
        
    affected_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated") and oc["grade"] and oc["grade"].lower() == canon_label.lower()]
    
    if affected_ocs:
        names = [oc["name"] for oc in affected_ocs]
        display_names = ", ".join(names[:10]) + (f" ... and {len(names)-10} more" if len(names) > 10 else "")
        view = GradeRemoveConfirmView(canon_label, affected_ocs)
        await interaction.response.send_message(
            embed=get_embed("⚠️ Grade in Use", f"**{canon_label}** is currently assigned to {len(affected_ocs)} Trainee(s):\n{display_names}\n\nRemoving this grade will set their grade to Ungraded. Confirm?", COLOR_WARNING),
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()
    else:
        del db["grades"][canon_label]
        save_db(db)
        await interaction.response.send_message(embed=get_embed("Grade Removed", f"**{canon_label}** has been removed.", COLOR_SUCCESS), ephemeral=True)

@grade_group.command(name="list", description="List all grades and colors")
async def grade_list(interaction: discord.Interaction):
    if not db["grades"]:
        return await interaction.response.send_message(embed=get_embed("No Grades", "No grades have been created yet.", COLOR_WARNING), ephemeral=True)
        
    entries = []
    for canon_label, hex_val in db["grades"].items():
        count = sum(1 for oc in db["ocs"].values() if not oc.get("eliminated") and oc["grade"] and oc["grade"].lower() == canon_label.lower())
        entries.append((canon_label, hex_val, count))
        
    page_size = 10
    pages = []
    for i in range(0, len(entries), page_size):
        batch = entries[i:i+page_size]
        last_hex = batch[-1][1]
        embed = get_embed(f"Grades (Page {(i//page_size)+1} of {(len(entries)+page_size-1)//page_size})", "", hex_to_int(last_hex))
        for label, hex_val, count in batch:
            embed.add_field(name=label, value=f"Hex: `{hex_val}`\nActive OCs: {count}", inline=True)
        pages.append(embed)
        
    if len(pages) == 1:
        await interaction.response.send_message(embed=pages[0])
    else:
        view = RankingPaginationView(pages)
        msg = await interaction.response.send_message(embed=pages[0], view=view)
        view.message = msg

@dorm_group.command(name="floor_create", description="Create a new dorm floor")
@is_dev()
async def dorm_floor_create(interaction: discord.Interaction, floor_label: str):
    if len(floor_label) > 32 or not re.match(r'^[A-Za-z0-9 _\-]+$', floor_label):
        return await interaction.response.send_message(embed=get_embed("Invalid Label", "Max 32 chars, only letters, numbers, spaces, underscores, hyphens.", COLOR_ERROR), ephemeral=True)
        
    if any(k.lower() == floor_label.lower() for k in db["dorms"]):
        return await interaction.response.send_message(embed=get_embed("Collision", f"Floor '{floor_label}' already exists.", COLOR_ERROR), ephemeral=True)
        
    db["dorms"][floor_label] = {"label": floor_label, "rooms": {}, "created_at": get_now().isoformat()}
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Floor Created", f"Created floor **{floor_label}**.", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="floor_list", description="List all dorm floors")
@is_dev()
async def dorm_floor_list(interaction: discord.Interaction):
    if not db["dorms"]:
        return await interaction.response.send_message(embed=get_embed("No Floors", "No floors created yet.", COLOR_WARNING), ephemeral=True)
        
    embed = get_embed("Dorm Floors")
    for floor_label, floor_data in db["dorms"].items():
        rooms = floor_data.get("rooms", {})
        total_cap = sum(r.get("capacity", 0) for r in rooms.values())
        total_occ = sum(len(r.get("occupants", [])) for r in rooms.values())
        embed.add_field(name=f"Floor {floor_label}", value=f"Rooms: {len(rooms)}\nCapacity: {total_occ} / {total_cap}", inline=False)
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

@dorm_group.command(name="floor_delete", description="Delete a dorm floor")
@is_dev()
async def dorm_floor_delete(interaction: discord.Interaction, floor_label: str):
    canon_floor = next((k for k in db["dorms"] if k.lower() == floor_label.lower()), None)
    if not canon_floor:
        return await interaction.response.send_message(embed=get_embed("Not Found", "Floor not found.", COLOR_ERROR), ephemeral=True)
        
    floor_data = db["dorms"][canon_floor]
    total_occ = sum(len(r.get("occupants", [])) for r in floor_data.get("rooms", {}).values())
    
    if total_occ > 0:
        view = DormFloorDeleteConfirmView(canon_floor)
        await interaction.response.send_message(
            embed=get_embed("⚠️ Floor Occupied", f"**{canon_floor}** has {total_occ} occupant(s). Deleting it will evict them. Confirm?", COLOR_WARNING),
            view=view, ephemeral=True
        )
        view.message = await interaction.original_response()
    else:
        del db["dorms"][canon_floor]
        save_db(db)
        await interaction.response.send_message(embed=get_embed("Floor Deleted", f"Deleted empty floor **{canon_floor}**.", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="room_create", description="Create a new dorm room")
@is_dev()
async def dorm_room_create(interaction: discord.Interaction, floor_label: str, room_label: str, capacity: int):
    canon_floor = next((k for k in db["dorms"] if k.lower() == floor_label.lower()), None)
    if not canon_floor:
        valid = ", ".join(db["dorms"].keys()) if db["dorms"] else "None"
        return await interaction.response.send_message(embed=get_embed("Invalid Floor", f"Available: {valid}", COLOR_ERROR), ephemeral=True)
        
    if len(room_label) > 32 or not re.match(r'^[A-Za-z0-9 _\-]+$', room_label):
        return await interaction.response.send_message(embed=get_embed("Invalid Label", "Max 32 chars, only letters, numbers, spaces, underscores, hyphens.", COLOR_ERROR), ephemeral=True)
        
    if capacity < 1 or capacity > 20:
        return await interaction.response.send_message(embed=get_embed("Invalid Capacity", "Capacity must be between 1 and 20.", COLOR_ERROR), ephemeral=True)
        
    floor_data = db["dorms"][canon_floor]
    if any(k.lower() == room_label.lower() for k in floor_data.get("rooms", {})):
        return await interaction.response.send_message(embed=get_embed("Collision", f"Room '{room_label}' already exists on floor '{canon_floor}'.", COLOR_ERROR), ephemeral=True)
        
    floor_data["rooms"][room_label] = {
        "label": room_label, "capacity": capacity, "occupants": [], "created_at": get_now().isoformat()
    }
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Room Created", f"Floor: {canon_floor}\nRoom: {room_label}\nCapacity: {capacity}", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="room_list", description="List rooms on a floor")
@is_dev()
async def dorm_room_list(interaction: discord.Interaction, floor_label: str):
    canon_floor = next((k for k in db["dorms"] if k.lower() == floor_label.lower()), None)
    if not canon_floor:
        return await interaction.response.send_message(embed=get_embed("Not Found", "Floor not found.", COLOR_ERROR), ephemeral=True)
        
    rooms = db["dorms"][canon_floor].get("rooms", {})
    if not rooms:
        return await interaction.response.send_message(embed=get_embed("No Rooms", f"No rooms on floor {canon_floor}.", COLOR_WARNING), ephemeral=True)
        
    pages = []
    room_list = list(rooms.values())
    page_size = 10
    for i in range(0, len(room_list), page_size):
        batch = room_list[i:i+page_size]
        embed = get_embed(f"Rooms on Floor {canon_floor} (Page {(i//page_size)+1} of {(len(room_list)+page_size-1)//page_size})")
        for r in batch:
            occ_names = [db["ocs"].get(oid, {}).get("name", "Unknown") for oid in r["occupants"]]
            names_str = ", ".join(occ_names) if occ_names else "Empty"
            embed.add_field(name=f"Room {r['label']}", value=f"Capacity: {len(r['occupants'])} / {r['capacity']}\nOccupants: {names_str}", inline=False)
        pages.append(embed)
        
    if len(pages) == 1:
        await interaction.response.send_message(embed=pages[0], ephemeral=True)
    else:
        view = RankingPaginationView(pages)
        msg = await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view.message = msg

@dorm_group.command(name="room_edit_capacity", description="Edit a room's capacity")
@is_dev()
async def dorm_room_edit_capacity(interaction: discord.Interaction, floor_label: str, room_label: str, new_capacity: int):
    canon_floor = next((k for k in db["dorms"] if k.lower() == floor_label.lower()), None)
    if not canon_floor: return await interaction.response.send_message(embed=get_embed("Not Found", "Floor not found.", COLOR_ERROR), ephemeral=True)
    
    canon_room = next((k for k in db["dorms"][canon_floor]["rooms"] if k.lower() == room_label.lower()), None)
    if not canon_room: return await interaction.response.send_message(embed=get_embed("Not Found", "Room not found.", COLOR_ERROR), ephemeral=True)
    
    if new_capacity < 1 or new_capacity > 20: return await interaction.response.send_message(embed=get_embed("Invalid", "Must be 1-20.", COLOR_ERROR), ephemeral=True)
    
    room_data = db["dorms"][canon_floor]["rooms"][canon_room]
    if new_capacity < len(room_data["occupants"]):
        return await interaction.response.send_message(embed=get_embed("Capacity Error", f"Room currently has {len(room_data['occupants'])} occupants. Evict someone first.", COLOR_ERROR), ephemeral=True)
        
    room_data["capacity"] = new_capacity
    save_db(db)
    await interaction.response.send_message(embed=get_embed("Capacity Updated", f"Room {canon_room} on floor {canon_floor} is now capacity {new_capacity}.", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="assign_manual", description="Manually assign an OC to a room")
@is_dev()
async def dorm_assign_manual(interaction: discord.Interaction, oc_name: str, floor_label: str, room_label: str):
    oc = next((o for o in db["ocs"].values() if not o.get("eliminated", False) and o["name"].lower() == oc_name.lower()), None)
    if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", "Active OC not found.", COLOR_ERROR), ephemeral=True)
    
    canon_floor = next((k for k in db["dorms"] if k.lower() == floor_label.lower()), None)
    if not canon_floor: return await interaction.response.send_message(embed=get_embed("Not Found", "Floor not found.", COLOR_ERROR), ephemeral=True)
    
    canon_room = next((k for k in db["dorms"][canon_floor]["rooms"] if k.lower() == room_label.lower()), None)
    if not canon_room: return await interaction.response.send_message(embed=get_embed("Not Found", "Room not found.", COLOR_ERROR), ephemeral=True)
    
    room_data = db["dorms"][canon_floor]["rooms"][canon_room]
    if len(room_data["occupants"]) >= room_data["capacity"]:
        occ_names = [db["ocs"].get(oid, {}).get("name", "Unknown") for oid in room_data["occupants"]]
        return await interaction.response.send_message(embed=get_embed("Room Full", f"Capacity {room_data['capacity']} reached.\nOccupants: {', '.join(occ_names)}", COLOR_ERROR), ephemeral=True)
        
    evict_msg = ""
    if oc["dorm_floor"] and oc["dorm_room"]:
        old_floor = db["dorms"].get(oc["dorm_floor"], {})
        old_room = old_floor.get("rooms", {}).get(oc["dorm_room"], {})
        if oc["id"] in old_room.get("occupants", []):
            old_room["occupants"].remove(oc["id"])
        evict_msg = f" (Evicted from {oc['dorm_floor']} - {oc['dorm_room']})"
        
    room_data["occupants"].append(oc["id"])
    oc["dorm_floor"] = canon_floor
    oc["dorm_room"] = canon_room
    save_db(db)
    
    await interaction.response.send_message(embed=get_embed("Assigned", f"Assigned **{oc['name']}** to Floor {canon_floor}, Room {canon_room}.{evict_msg}", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="assign_auto", description="Auto-assign all OCs to dorms")
@is_dev()
async def dorm_assign_auto(interaction: discord.Interaction, mode: str):
    if mode.lower() not in ["rank", "grade", "random"]:
        return await interaction.response.send_message(embed=get_embed("Invalid Mode", "Must be 'rank', 'grade', or 'random'.", COLOR_ERROR), ephemeral=True)
        
    recalculate_ranks()
    
    active_ocs = [oc for oc in db["ocs"].values() if not oc.get("eliminated", False)]
    all_rooms = []
    for f_label in sorted(db["dorms"].keys()):
        for r_label in sorted(db["dorms"][f_label].get("rooms", {}).keys()):
            all_rooms.append({"floor": f_label, "room": r_label, "data": db["dorms"][f_label]["rooms"][r_label]})
            
    total_slots = sum(r["data"]["capacity"] for r in all_rooms)
    if total_slots < len(active_ocs):
        await interaction.channel.send(embed=get_embed("⚠️ Slot Deficit", f"Only {total_slots} slots for {len(active_ocs)} OCs. Some will remain unassigned.", COLOR_WARNING))
        
    # Clear ALL assignments (active and eliminated) to ensure full consistency
    for oc in db["ocs"].values():
        oc["dorm_floor"] = None
        oc["dorm_room"] = None
    for r in all_rooms:
        r["data"]["occupants"] = []
        
    # Sort
    if mode.lower() == "rank":
        active_ocs.sort(key=lambda x: x["rank"])
    elif mode.lower() == "random":
        random.shuffle(active_ocs)
    elif mode.lower() == "grade":
        def grade_sort_key(oc):
            g = oc.get("grade")
            return (0, g.lower(), oc["rank"]) if g else (1, "", oc["rank"])
        active_ocs.sort(key=grade_sort_key)
        
    # Assign
    assigned_count = 0
    room_idx = 0
    
    for oc in active_ocs:
        # Find next room with space
        while room_idx < len(all_rooms) and len(all_rooms[room_idx]["data"]["occupants"]) >= all_rooms[room_idx]["data"]["capacity"]:
            room_idx += 1
            
        if room_idx >= len(all_rooms):
            break # out of slots
            
        r = all_rooms[room_idx]
        r["data"]["occupants"].append(oc["id"])
        oc["dorm_floor"] = r["floor"]
        oc["dorm_room"] = r["room"]
        assigned_count += 1
        
    save_db(db)
    
    unassigned = [oc["name"] for oc in active_ocs if not oc["dorm_floor"]]
    
    embed = get_embed("Auto-Assignment Complete", f"Mode: **{mode}**\nAssigned: {assigned_count}\nUnassigned: {len(unassigned)}", COLOR_SUCCESS)
    
    for f_label in sorted(db["dorms"].keys()):
        f_rooms = db["dorms"][f_label].get("rooms", {})
        if not f_rooms: continue
        desc = ""
        for r_label, r_data in f_rooms.items():
            occ_names = [db["ocs"].get(oid, {}).get("name", "Unknown") for oid in r_data["occupants"]]
            if occ_names:
                desc += f"**{r_label}**: {', '.join(occ_names)}\n"
        if desc:
            embed.add_field(name=f"Floor {f_label}", value=desc[:1024], inline=False)
            
    if unassigned:
        embed.add_field(name="⚠️ Unassigned OCs", value=", ".join(unassigned)[:1024], inline=False)
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

@dorm_group.command(name="assign_evict", description="Evict an OC from their room")
@is_dev()
async def dorm_assign_evict(interaction: discord.Interaction, oc_name: str):
    oc = next((o for o in db["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
    if not oc: return await interaction.response.send_message(embed=get_embed("Not Found", "OC not found.", COLOR_ERROR), ephemeral=True)
    
    if not oc["dorm_floor"] or not oc["dorm_room"]:
        return await interaction.response.send_message(embed=get_embed("Not Assigned", f"{oc['name']} is not in a dorm.", COLOR_WARNING), ephemeral=True)
        
    old_floor = db["dorms"].get(oc["dorm_floor"], {})
    old_room = old_floor.get("rooms", {}).get(oc["dorm_room"], {})
    if oc["id"] in old_room.get("occupants", []):
        old_room["occupants"].remove(oc["id"])
        
    floor = oc["dorm_floor"]
    room = oc["dorm_room"]
    oc["dorm_floor"] = None
    oc["dorm_room"] = None
    save_db(db)
    
    await interaction.response.send_message(embed=get_embed("Evicted", f"Evicted {oc['name']} from {floor} - {room}.", COLOR_SUCCESS), ephemeral=True)

@dorm_group.command(name="reset", description="Reset dorm assignments or structure")
@is_dev()
async def dorm_reset(interaction: discord.Interaction, mode: str):
    if mode.lower() not in ["unassign_all", "nuke"]:
        return await interaction.response.send_message(embed=get_embed("Invalid Mode", "Must be 'unassign_all' or 'nuke'.", COLOR_ERROR), ephemeral=True)
        
    if mode.lower() == "nuke":
        await interaction.response.send_modal(DormNukeModal())
    else:
        view = DormResetConfirmView()
        await interaction.response.send_message(
            embed=get_embed("⚠️ Confirm Unassign All", "This will evict all OCs from all rooms but keep the floor/room structure intact. Confirm?", COLOR_WARNING),
            view=view, ephemeral=True
        )
        view.message = await interaction.original_response()

bot.tree.add_command(rank_group)
bot.tree.add_command(config_group)
bot.tree.add_command(grade_group)
bot.tree.add_command(dorm_group)

@bot.tree.command(name="export", description="[DEV] Export bot data to TSV")
@is_dev()
async def export_data(interaction: discord.Interaction):
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    
    writer.writerow(["=== SECTION 1: CURRENT RANKINGS SUMMARY ==="])
    writer.writerow(["rank", "oc_name", "owner_discord_id", "owner_username", "grade", "total_points", "voting_points", "mission_points", "rank_change", "dorm_floor", "dorm_room", "registered_at", "eliminated", "profile_picture_url"])
    for oc in sorted(db["ocs"].values(), key=lambda x: (x.get("rank") if x.get("rank") is not None else float('inf'))):
        change = get_snapshot_diff(oc["id"], oc.get("rank"))
        writer.writerow([oc.get("rank"), oc["name"], oc["owner_id"], oc["owner_name"], oc["grade"] or "", oc["total_points"], oc["voting_points"], oc["mission_points"], change, oc["dorm_floor"] or "", oc["dorm_room"] or "", oc["registered_at"], str(oc.get("eliminated", False)), oc.get("profile_picture_url") or ""])
    
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
    
    output.write("\n")
    writer.writerow(["=== SECTION 4: MISSION GROUPS ==="])
    writer.writerow(["group_name", "group_id", "member_oc_names", "channel_id", "archived", "created_at"])
    for g in db.get("mission_groups", {}).values():
        members = ", ".join([db["ocs"].get(mid, {}).get("name", "Unknown") for mid in g["members"]])
        writer.writerow([g["name"], g["group_id"], members, g.get("channel_id") or "", str(g["archived"]), g["created_at"]])
        
    output.write("\n")
    writer.writerow(["=== SECTION 5: PEER RANKING SESSIONS ==="])
    writer.writerow(["session_id", "mission_group_name", "resolved", "revealed", "closed_at", "ballots_submitted", "eligible_voters", "benefit_oc", "penalty_oc"])
    for s in db.get("peer_ranking_sessions", {}).values():
        gname = db.get("mission_groups", {}).get(s["mission_group_id"], {}).get("name", "Unknown")
        ben = db["ocs"].get(s.get("benefit_applied_to", ""), {}).get("name", "N/A")
        pen = db["ocs"].get(s.get("penalty_applied_to", ""), {}).get("name", "N/A")
        writer.writerow([s["session_id"], gname, str(s["resolved"]), str(s["revealed"]), s.get("closed_at") or "", len(s["ballots"]), len(s["eligible_voter_ids"]), ben, pen])

    output.write("\n")
    writer.writerow(["=== SECTION 6: FEED POST ANALYTICS ==="])
    writer.writerow(["oc_name", "post_number", "post_id", "author", "like_count", "comment_thread_id", "media_count", "created_at"])
    for oc_id, posts in db.get("feeds", {}).items():
        oc_name = db["ocs"].get(oc_id, db["archived_ocs"].get(oc_id, {"name": "Unknown"}))["name"]
        for idx, post in enumerate(posts, start=1):
            writer.writerow([oc_name, idx, post["post_id"], post["author_name"], post["like_count"], post.get("thread_id") or "", len(post["media_urls"]), post["created_at"]])

    output.write("\n")
    writer.writerow(["=== SECTION 7: DORM STRUCTURE ==="])
    writer.writerow(["floor_label", "room_label", "capacity", "occupancy", "occupant_names", "created_at"])
    # Note: the oc_data references naturally reflect the cleared state since they read from db["ocs"].
    for floor_label, floor_data in db.get("dorms", {}).items():
        for room_label, room_data in floor_data.get("rooms", {}).items():
            occupant_names = ", ".join(
                db["ocs"].get(oid, db["archived_ocs"].get(oid, {"name": "Unknown"}))["name"]
                for oid in room_data.get("occupants", [])
            )
            writer.writerow([
                floor_label, room_label, room_data.get("capacity", "?"),
                len(room_data.get("occupants", [])), occupant_names,
                room_data.get("created_at", "")
            ])

    output.seek(0)
    file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"rankings_export_{get_now().strftime('%Y-%m-%d_%H-%M')}.tsv")
    await interaction.response.send_message(file=file, ephemeral=True)

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