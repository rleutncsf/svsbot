import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import uuid
import re
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

POINTLOG_ACTION_RESETALL = "resetall"
SNAP_TRIGGER_RESETALL = "POINTS_RESETALL_BASELINE"

COLORS = {
    "system": 0x1A1A2E,
    "error": 0xE63946,
    "success": 0x2DC653,
    "warning": 0xF4A261,
    "neutral": 0xB0B0B0
}

KST = zoneinfo.ZoneInfo("Asia/Seoul")

HELP_SECTIONS = {
    "general": {
        "title": "📋 General & Registration",
        "commands": [
            ("/register", "name birthday_yyyy_mm_dd gender pronouns faceclaim main_skill nationality [form_link] [ethnicity] [profile_picture]", "Register a new Trainee OC. Each user may have up to the configured OC cap."),
            ("/profile", "oc_name", "View a Trainee's full profile card."),
            ("/oc_all", "", "Browse all currently active Trainees (paginated)."),
            ("/oc_eliminated", "", "View all eliminated Trainees."),
            ("/removeoc", "oc_name", "Permanently archive one of your own Trainees."),
        ],
        "dev_commands": []
    },
    "voting": {
        "title": "🗳️ Voting",
        "commands": [
            ("/vote", "oc_names", "Vote for one or more Trainees (comma-separated). Subject to the per-round vote cap."),
            ("/votingstatus", "", "Check whether voting is currently open and see the current tally (if permitted)."),
        ],
        "dev_commands": [
            ("/votingopen", "", "🔒 Open a new voting round and clear the previous vote ledger."),
            ("/votingclose", "", "🔒 Close voting, apply the multiplier, tally votes, update rankings, and post to the announcement channel."),
            ("/config votingmultiplier", "value", "🔒 Set the vote-to-points multiplier."),
            ("/config votingcap", "cap", "🔒 Set the maximum number of votes per user per round (0 = unlimited)."),
        ]
    },
    "points": {
        "title": "🏆 Points & Rankings",
        "commands": [
            ("/rankings", "", "View the current live leaderboard (paginated)."),
            ("/reveal", "", "Trigger a sequential cinematic ranking reveal in the announcement channel."),
        ],
        "dev_commands": [
            ("/points", "oc_name action value", "🔒 Add, Deduct, Multiply, or Set a Trainee's mission points."),
            ("/resetallpoints", "", "🔒 Zero all OC points and anchor a new ranking baseline snapshot. Requires voting to be closed first."),
            ("/export_rankings", "", "🔒 Export full state (rankings, history, logs, feeds) as a TSV file."),
        ]
    },
    "dorms": {
        "title": "🏠 Dorms",
        "commands": [
            ("/dorm_view", "", "View all dorm floor and room assignments."),
        ],
        "dev_commands": [
            ("/dorm_createfloor", "floor_name", "🔒 Create a new dorm floor. Automatically creates a matching Discord category."),
            ("/dorm_createroom", "floor_name room_name capacity", "🔒 Create a room under a floor. Automatically creates a text channel inside the floor's category."),
            ("/dorm_assign", "oc_name floor_name room_name", "🔒 Manually assign an OC to a room."),
        ]
    },
    "grades": {
        "title": "🎓 Grades",
        "commands": [],
        "dev_commands": [
            ("/grade_create", "label hex_color", "🔒 Create a new grade tier with a display colour (#RRGGBB)."),
            ("/assigngrade", "oc_name grade_label", "🔒 Assign a grade tier to an OC."),
        ]
    },
    "missions": {
        "title": "🎯 Mission Groups",
        "commands": [
            ("/missiongroup view", "[group_name]", "View all active mission groups or details of a single group."),
        ],
        "dev_commands": [
            ("/missiongroup create", "name oc_names", "🔒 Create a new mission group (comma-separated OC names)."),
            ("/missiongroup addmember", "group_name oc_name", "🔒 Add a Trainee to an existing group."),
            ("/missiongroup removemember", "group_name oc_name", "🔒 Remove a Trainee from a group."),
            ("/missiongroup provision", "group_name [category]", "🔒 Create a Discord practice channel for the group."),
            ("/missiongroup deprovision", "group_name", "🔒 Delete the group's practice channel."),
            ("/missiongroup archive", "group_name", "🔒 Archive a mission group."),
        ]
    },
    "peerranking": {
        "title": "⚖️ Peer Ranking",
        "commands": [
            ("/peerranking vote", "session_id ranking", "Submit your ballot for an open peer ranking session. Ranking is a comma-separated list of OC names from best to worst performer."),
            ("/peerranking mystatus", "", "Check whether you have submitted a ballot in the current session."),
        ],
        "dev_commands": [
            ("/peerranking toggle", "enabled", "🔒 Enable or disable the peer ranking system globally."),
            ("/peerranking configure", "benefit_type benefit_value penalty_type penalty_value [transparent]", "🔒 Set reward/penalty parameters."),
            ("/peerranking opensession", "mission_group", "🔒 Open a new peer ranking session for a group."),
            ("/peerranking closesession", "", "🔒 Close the active session and lock in ballots."),
            ("/peerranking resolve", "", "🔒 Tally ballots, apply benefit/penalty, update points."),
            ("/peerranking reveal", "", "🔒 Post the peer ranking results to the announcement channel."),
        ]
    },
    "feeds": {
        "title": "📸 OC Feed",
        "commands": [
            ("/feed post", "oc_name caption [media_url_1..5]", "Post to your OC's public feed. Supports up to 5 media URLs."),
            ("/feed view", "oc_name", "Browse an OC's feed posts (paginated)."),
        ],
        "dev_commands": [
            ("/feed delete", "oc_name post_number", "🔒 Delete a specific feed post (owners may also delete their own)."),
        ]
    },
    "config": {
        "title": "⚙️ Configuration",
        "commands": [],
        "dev_commands": [
            ("/setup", "timezone announce_channel dev_role [asset_channel]", "🔒 Initial bot setup."),
            ("/config_view", "", "🔒 View all current configuration values."),
            ("/setassetchannel", "channel", "🔒 Set the persistent asset storage channel."),
            ("/setfeedchannel", "channel", "🔒 Set the public feed channel."),
            ("/setrevealpage", "size", "🔒 Set how many Trainees appear per reveal page (1–25)."),
            ("/config setdebutslots", "slots [public]", "🔒 Mark the top N ranking positions as the debut line."),
        ]
    },
}

DEFAULT_SCHEMA = {
    "config": {
        "timezone": "UTC",
        "announcement_channel_id": None,
        "dev_role_id": None,
        "default_multiplier": 1,
        "oc_cap": 5,
        "allow_negative_points": False,
        "reveal_color": "#FFD700",
        "asset_channel": None,
        "feed_channel": None,
        "reveal_page_size": 7,
        "debut_slots": 0,
        "debut_slots_public": True,
        "peer_ranking_enabled": False,
        "peer_ranking_benefit": {
            "type": "multiplier",
            "value": 1.20
        },
        "peer_ranking_penalty": {
            "type": "multiplier",
            "value": 0.10
        },
        "peer_ranking_transparent": True
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
        "votes": {},
        "user_votes": {},
        "last_closed_at": None
    },
    "feeds": {},
    "dorms": {},
    "mission_groups": {},
    "peer_ranking_sessions": {},
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
            modified = False
            
            # Auto-initialize missing top-level keys
            for key, val in DEFAULT_SCHEMA.items():
                if key not in data:
                    data[key] = val
                    modified = True
            
            # Auto-initialize missing config sub-keys
            for key, val in DEFAULT_SCHEMA["config"].items():
                if key not in data["config"]:
                    data["config"][key] = val
                    modified = True

            # Voting schema migration
            if "last_closed_at" not in data["voting"]:
                data["voting"]["last_closed_at"] = None
                modified = True
            if "user_votes" not in data["voting"]:
                data["voting"]["user_votes"] = {}
                modified = True
            
            # Feeds initialization
            if "feeds" not in data:
                data["feeds"] = {}
                modified = True

            # Schema Migration Guard for OCs
            for oc in data.get("ocs", {}).values():
                if "profile_picture_url" not in oc:
                    oc["profile_picture_url"] = None
                    modified = True
                if "eliminated" not in oc:
                    oc["eliminated"] = False
                    modified = True
                if "feed_post_ids" not in oc:
                    oc["feed_post_ids"] = []
                    modified = True
                if "birthday" not in oc:
                    oc["birthday"] = "Unknown"
                    modified = True
                if "form_link" not in oc:
                    oc["form_link"] = None
                    modified = True
            
            # Schema Migration Guard for Archived OCs
            for oc in data.get("archived_ocs", {}).values():
                if "profile_picture_url" not in oc:
                    oc["profile_picture_url"] = None
                    modified = True
                if "eliminated" not in oc:
                    oc["eliminated"] = False
                    modified = True
                if "feed_post_ids" not in oc:
                    oc["feed_post_ids"] = []
                    modified = True
                if "birthday" not in oc:
                    oc["birthday"] = "Unknown"
                    modified = True
                if "form_link" not in oc:
                    oc["form_link"] = None
                    modified = True

            # Schema Migration Guard for Dorms: add category_id and room channel_id
            for floor_name, floor_data in data.get("dorms", {}).items():
                if "category_id" not in floor_data:
                    floor_data["category_id"] = None
                    modified = True
                for room_name, room_data in floor_data.get("rooms", {}).items():
                    if "channel_id" not in room_data:
                        room_data["channel_id"] = None
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
# 3. UTILITY FUNCTIONS & SHARED VIEWS
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

def today_kst() -> datetime.date:
    """Return the current calendar date in Korean Standard Time (UTC+9)."""
    return datetime.now(KST).date()

def format_dt(dt_str):
    if not dt_str: return "Unknown"
    dt = datetime.fromisoformat(dt_str).astimezone(get_tz())
    return dt.strftime("%b %d, %Y · %H:%M %Z")

def calculate_age(dob_str: str) -> int | str:
    """
    Calculate age in full years using the current date in KST (UTC+9).
    Returns an int on success, or the string "Unknown" on parse failure.
    """
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        today = today_kst()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except (ValueError, TypeError):
        return "Unknown"

def get_embed(title: str, description: str = "", color_type: str = "system", show_footer: bool = False) -> discord.Embed:
    data = load_data()
    color_val = COLORS.get(color_type, COLORS["system"])
    if color_type == "reveal":
        try:
            color_val = int(data["config"]["reveal_color"].lstrip("#"), 16)
        except:
            color_val = COLORS["system"]

    embed = discord.Embed(title=title, description=description, color=color_val)
    embed.timestamp = now()
    if show_footer:
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
    active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
    if not active_ocs:
        save_data(data)
        return
    active_ocs.sort(key=lambda x: (-x["total_points"], x["registered_at"]))
    for rank, oc in enumerate(active_ocs, start=1):
        data["ocs"][oc["id"]]["current_rank"] = rank
    save_data(data)

def find_oc(name: str, data: dict):
    name_lower = name.lower()
    for oc in data["ocs"].values():
        if oc["name"].lower() == name_lower:
            return oc
    return None

def get_rank_change(oc_id, current_rank, data):
    # NOTE: The baseline snapshot is always data["rank_snapshots"][-1].
    # After /resetallpoints runs, this becomes the post-reset baseline,
    # so all diff arrows reflect movement since the last reset.
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

class RankingPaginationView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.pages = pages
        self.current = 0
        self.message = None
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
            try:
                await self.message.edit(view=self)
            except:
                pass

class ConfirmResetView(discord.ui.View):
    """Two-button ephemeral confirmation for the /resetallpoints command."""

    def __init__(self):
        super().__init__(timeout=30)
        self.message: discord.Message = None

    async def _disable_all(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()

        data = load_data()
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]

        if not active_ocs:
            return await interaction.response.edit_message(
                embed=get_embed("Nothing to Reset", "There are no active OCs to reset.", "warning"),
                view=self
            )

        # Zero out all points and write per-OC audit log entries
        for oc in active_ocs:
            pts_before = oc["total_points"]
            oc["voting_points"]  = 0
            oc["mission_points"] = 0
            oc["total_points"]   = 0
            data["point_log"].append({
                "timestamp":     now().isoformat(),
                "dev_id":        str(interaction.user.id),
                "dev_name":      interaction.user.name,
                "oc_id":         oc["id"],
                "oc_name":       oc["name"],
                "action":        POINTLOG_ACTION_RESETALL,
                "value":         0,
                "points_before": pts_before,
                "points_after":  0
            })

        # Recalculate ranks (all tied at 0; tiebreak = registered_at)
        recalculate_ranks(data)

        # Write the new baseline snapshot
        snap_data = [{"oc_id": oc["id"], "rank": oc["current_rank"], "points": oc["total_points"]} for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        data["rank_snapshots"].append({
            "timestamp": now().isoformat(),
            "trigger":   SNAP_TRIGGER_RESETALL,
            "rankings":  snap_data
        })

        save_data(data)

        await interaction.response.edit_message(
            embed=get_embed(
                "✅ All Points Reset",
                f"Points for **{len(active_ocs)} Trainee(s)** have been set to zero.\n"
                f"A new ranking baseline has been anchored.\n"
                f"All future rank change indicators (▲/▼) will now compare against these post-reset rankings.",
                "success"
            ),
            view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        await interaction.response.edit_message(
            embed=get_embed("Cancelled", "Point reset aborted. No changes were made.", "system"),
            view=self
        )

    async def on_timeout(self):
        await self._disable_all()

class FeedPostView(discord.ui.View):
    """
    Persistent view attached to every feed post message.
    - Like button: increments like_count, refreshes embed footer.
    - Comment button: opens a modal; writes reply into a Discord thread.
    """

    def __init__(self, post_id: str):
        super().__init__(timeout=None)
        self.post_id = post_id
        for child in self.children:
            if child.custom_id == "feed_like:placeholder":
                child.custom_id = f"feed_like:{post_id}"
            elif child.custom_id == "feed_comment:placeholder":
                child.custom_id = f"feed_comment:{post_id}"

    def _get_post(self) -> dict | None:
        data = load_data()
        for feed in data["feeds"].values():
            for post in feed:
                if post["post_id"] == self.post_id:
                    return post
        return None

    @discord.ui.button(label="❤️ Like", style=discord.ButtonStyle.danger, custom_id="feed_like:placeholder")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        post = self._get_post()
        if not post:
            return await interaction.response.send_message("Post not found.", ephemeral=True)

        data = load_data()
        found = False
        for feed in data["feeds"].values():
            for p in feed:
                if p["post_id"] == self.post_id:
                    p["like_count"] += 1
                    found = True
                    break
            if found: break

        if not found:
            return await interaction.response.send_message("Post not found in DB.", ephemeral=True)

        save_data(data)

        try:
            original_embed = interaction.message.embeds[0]
            old_footer = original_embed.footer.text or ""
            # Calculate updated like count based on post retrieved right after incrementing
            updated_likes = next((p["like_count"] for feed in data["feeds"].values() for p in feed if p["post_id"] == self.post_id), 0)
            new_footer = re.sub(r"❤️ \d+ likes", f"❤️ {updated_likes} likes", old_footer)
            original_embed.set_footer(text=new_footer)
            await interaction.response.edit_message(embed=original_embed, view=self)
        except Exception:
            await interaction.response.defer()

    @discord.ui.button(label="💬 Comment", style=discord.ButtonStyle.secondary, custom_id="feed_comment:placeholder")
    async def comment_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        post = self._get_post()
        if not post:
            return await interaction.response.send_message("Post not found.", ephemeral=True)
        await interaction.response.send_modal(CommentModal(self.post_id))

class CommentModal(discord.ui.Modal, title="Leave a Comment"):
    """
    Opens when a user clicks the Comment button on a feed post.
    The submitted text is posted as a reply inside the post's Discord thread.
    The thread is created lazily on the first comment.
    """

    comment_input = discord.ui.TextInput(
        label="Your comment",
        style=discord.TextStyle.paragraph,
        placeholder="Write your comment here…",
        min_length=1,
        max_length=500
    )

    def __init__(self, post_id: str):
        super().__init__()
        self.post_id = post_id

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        post = None
        for feed in data["feeds"].values():
            for p in feed:
                if p["post_id"] == self.post_id:
                    post = p
                    break
            if post: break

        if not post:
            return await interaction.response.send_message(embed=get_embed("Error", "Post not found.", "error"), ephemeral=True)

        comment_text = self.comment_input.value

        try:
            feed_ch = interaction.client.get_channel(int(post["channel_id"]))
            if not feed_ch:
                raise ValueError("Feed channel unavailable.")

            if post.get("thread_id"):
                thread = feed_ch.get_thread(int(post["thread_id"]))
                if thread is None:
                    thread = await interaction.client.fetch_channel(int(post["thread_id"]))
                    if thread.archived:
                        await thread.edit(archived=False)
            else:
                post_msg = await feed_ch.fetch_message(int(post["message_id"]))
                oc_name = "Unknown OC"
                for feed_list in data["feeds"].values():
                    for p in feed_list:
                        if p["post_id"] == post["post_id"]:
                            oc = data["ocs"].get(p["oc_id"])
                            if oc:
                                oc_name = oc["name"]
                            break

                thread = await post_msg.create_thread(
                    name=f"💬 {oc_name} · Comments",
                    auto_archive_duration=10080
                )
                post["thread_id"] = thread.id
                save_data(data)

            comment_embed = discord.Embed(description=comment_text, color=COLORS["system"])
            comment_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            await thread.send(embed=comment_embed)

        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=get_embed("Permission Error", "The bot lacks permission to create or post in threads in the feed channel.", "error"),
                ephemeral=True
            )
        except Exception as e:
            return await interaction.response.send_message(
                embed=get_embed("Error", f"Failed to post comment: `{e}`", "error"),
                ephemeral=True
            )

        await interaction.response.send_message(embed=get_embed("Comment Posted", "Your comment has been added to the thread.", "success"), ephemeral=True)

async def _run_sequential_reveal(channel: discord.TextChannel, ocs_ordered: list, reveal_color: int, page_size: int, data: dict, show_debut_line: bool = True):
    pages = []
    # ocs_ordered is sorted from worst to best (highest rank number first)
    batches = [ocs_ordered[i:i + page_size] for i in range(0, len(ocs_ordered), page_size)]
    
    debut_slots = data["config"].get("debut_slots", 0)
    show_line = data["config"].get("debut_slots_public", True) and show_debut_line
    global_idx = 0
    total_active = len(ocs_ordered)
    
    for idx, batch in enumerate(batches):
        page_embed = discord.Embed(title=f"Page {idx+1} of {len(batches)}", color=reveal_color)
        
        for oc in batch:
            if debut_slots > 0 and show_line and global_idx == (total_active - debut_slots):
                sep_embed = get_embed(
                    "✦ THE DEBUT LINE ✦", 
                    f"*The top {debut_slots} trainees above this line will debut.*", 
                    "reveal",
                    show_footer=True
                )
                await channel.send(embed=sep_embed)
                await asyncio.sleep(random.uniform(1.5, 2.5))

            change = get_rank_change(oc["id"], oc.get("current_rank", 0), data)
            grade_str = f" [{oc['grade']}]" if oc.get('grade') else ""
            field_name = f"✦ Rank #{oc.get('current_rank', 0)}{grade_str}"
            field_val = f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}> · {change}"
            
            single_embed = discord.Embed(color=reveal_color)
            single_embed.add_field(name=field_name, value=field_val, inline=False)
            if oc.get("profile_picture_url"):
                single_embed.set_thumbnail(url=oc["profile_picture_url"])
                
            await channel.send(embed=single_embed)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            page_embed.add_field(name=field_name, value=field_val, inline=False)
            global_idx += 1
            
        pages.append(page_embed)
        
        sep_embed = discord.Embed(description=f"— Page {idx+1} of {len(batches)} Complete —", color=COLORS["neutral"])
        await channel.send(embed=sep_embed)
        await asyncio.sleep(random.uniform(2.0, 3.0))
        
    final_embed = get_embed("Reveal Complete", "All rankings have been revealed.", "reveal", show_footer=True)
    await channel.send(embed=final_embed)
    
    return pages

# ==========================================
# 4. BOT CORE & ERROR HANDLING
# ==========================================
class SurvivalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # Enable only the privileged intents you actually read.
        # members: required if you call guild.get_member(), guild.members, or
        #          use Member objects in interactions beyond interaction.user.
        # message_content: NOT needed — no on_message / prefix command logic is live.
        # presences: NOT needed — no status/activity reads anywhere.
        intents.members = True   # Enable ONLY this privileged intent.
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.add_cog(ConfigCog(self))
        await self.add_cog(RegistrationCog(self))
        await self.add_cog(VotingCog(self))
        await self.add_cog(PointsCog(self))
        await self.add_cog(GradesCog(self))
        await self.add_cog(DormsCog(self))
        await self.add_cog(RankingsCog(self))
        await self.add_cog(MissionGroupCog(self))
        await self.add_cog(PeerRankingCog(self))
        await self.add_cog(ExportCog(self))
        await self.add_cog(HelpCog(self))
        await self.add_cog(FeedCog(self))

        # Re-register all live feed post views for persistence across restarts
        data = load_data()
        for feed_list in data.get("feeds", {}).values():
            for post in feed_list:
                self.add_view(FeedPostView(post["post_id"]))

        await self.tree.sync()
        post_count = sum(len(v) for v in data.get("feeds", {}).values())
        print(f"Bot Started & Commands Synced. Loaded {len(data.get('ocs', {}))} OCs, {post_count} feed post(s).")
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

    config_group = app_commands.Group(name="config", description="[DEV] Additional Configuration Commands")

    @app_commands.command(name="setup", description="Initial bot configuration (Dev only)")
    @is_dev()
    async def setup(self, interaction: discord.Interaction, timezone: str, announce_channel: discord.TextChannel, dev_role: discord.Role, asset_channel: discord.TextChannel = None):
        data = load_data()
        data["config"]["timezone"] = timezone
        data["config"]["announcement_channel_id"] = announce_channel.id
        data["config"]["dev_role_id"] = dev_role.id
        if asset_channel:
            data["config"]["asset_channel"] = asset_channel.id
        save_data(data)
        
        asset_msg = f"\nAsset Channel: {asset_channel.mention}" if asset_channel else ""
        await interaction.response.send_message(embed=get_embed("Setup Complete", f"Timezone: {timezone}\nAnnounce Channel: {announce_channel.mention}\nDev Role: {dev_role.mention}{asset_msg}", "success"), ephemeral=True)

    @app_commands.command(name="config_view", description="View configuration settings (Dev only)")
    @is_dev()
    async def config_view(self, interaction: discord.Interaction):
        data = load_data()
        cfg = data["config"]
        desc = "\n".join([f"**{k}**: {v}" for k, v in cfg.items()])
        await interaction.response.send_message(embed=get_embed("System Configuration", desc), ephemeral=True)

    @app_commands.command(name="setassetchannel", description="[DEV] Set the persistent asset storage channel")
    @is_dev()
    async def set_asset_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        data["config"]["asset_channel"] = channel.id
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Asset channel updated to {channel.mention}", "success"), ephemeral=True)

    @app_commands.command(name="setfeedchannel", description="[DEV] Set the public OC feed channel")
    @is_dev()
    async def set_feed_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        data["config"]["feed_channel"] = channel.id
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Feed channel set to {channel.mention}.", "success"), ephemeral=True)

    @app_commands.command(name="setrevealpage", description="[DEV] Set how many trainees are shown per reveal page")
    @is_dev()
    async def set_reveal_page(self, interaction: discord.Interaction, size: int):
        if size < 1 or size > 25:
            return await interaction.response.send_message(embed=get_embed("Error", "Page size must be between 1 and 25.", "error"), ephemeral=True)
        data = load_data()
        data["config"]["reveal_page_size"] = size
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Reveal page size set to {size}.", "success"), ephemeral=True)

    @config_group.command(name="setdebutslots", description="[DEV] Set the number of trainees slated to debut")
    @is_dev()
    async def setdebutslots(self, interaction: discord.Interaction, slots: int, public: bool = True):
        data = load_data()
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        if slots < 1 or slots > len(active_ocs):
            return await interaction.response.send_message(embed=get_embed("Error", f"Slots must be between 1 and {len(active_ocs)}.", "error"), ephemeral=True)
        
        data["config"]["debut_slots"] = slots
        data["config"]["debut_slots_public"] = public
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Debut line set to top {slots} trainee(s).\nDebut line visibility on public reveals: {public}.", "success"), ephemeral=True)

class RegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register", description="Register a new Trainee OC")
    async def register(self, interaction: discord.Interaction, name: str, birthday_yyyy_mm_dd: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, form_link: str = None, ethnicity: str = "Unknown", profile_picture: discord.Attachment = None):
        data = load_data()
        user_id = str(interaction.user.id)
        current_ocs = len([oc for oc in data["ocs"].values() if oc["owner_id"] == user_id])
        if current_ocs >= data["config"]["oc_cap"]:
            return await interaction.response.send_message(embed=get_embed("Limit Reached", f"⛔ You've already reached the maximum of {data['config']['oc_cap']} Trainees.", "error"), ephemeral=True)
        
        for oc in data["ocs"].values():
            if oc["owner_id"] == user_id and oc["name"].lower() == name.lower():
                return await interaction.response.send_message(embed=get_embed("Duplicate Name", f"⛔ You already have a Trainee named '{name}'. Please use a unique name.", "error"), ephemeral=True)

        if profile_picture:
            if not profile_picture.content_type or not profile_picture.content_type.startswith("image/"):
                return await interaction.response.send_message(embed=get_embed("Invalid File", "Please attach an image (PNG, JPG, GIF, WEBP).", "error"), ephemeral=True)
            if not data["config"].get("asset_channel"):
                return await interaction.response.send_message(embed=get_embed("Warning", "No asset channel has been configured. Ask a Dev to run /setassetchannel first.", "warning"), ephemeral=True)

        await interaction.response.defer()

        profile_picture_url = None
        if profile_picture:
            asset_ch = self.bot.get_channel(int(data["config"]["asset_channel"]))
            if asset_ch:
                img_bytes = await profile_picture.read()
                file = discord.File(fp=io.BytesIO(img_bytes), filename=profile_picture.filename)
                asset_msg = await asset_ch.send(
                    content=f"[OC Asset] `{name}` — owner: <@{interaction.user.id}>",
                    file=file
                )
                profile_picture_url = asset_msg.attachments[0].url

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
            "form_link": form_link or None,
            "profile_picture_url": profile_picture_url,
            "eliminated": False,
            "grade": None,
            "dorm_floor": None,
            "dorm_room": None,
            "voting_points": 0,
            "mission_points": 0,
            "total_points": 0,
            "current_rank": 0,
            "feed_post_ids": [],
            "registered_at": now().isoformat()
        }
        data["ocs"][oc_id] = new_oc
        recalculate_ranks(data)
        
        embed = self._build_profile_embed(new_oc, data)
        await interaction.followup.send(content="Your Trainee has been registered.", embed=embed)

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
        
        if oc.get("dorm_floor") and oc.get("dorm_room"):
            try:
                data["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
            except ValueError:
                pass
        
        data["archived_ocs"][oc["id"]] = oc
        del data["ocs"][oc["id"]]
        recalculate_ranks(data)
        await interaction.response.send_message(embed=get_embed("OC Archived", f"Trainee '{oc_name}' has been successfully removed.", "success"))

    @app_commands.command(name="oc_all", description="Browse all currently registered Trainees")
    async def oc_all(self, interaction: discord.Interaction):
        data = load_data()
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        if not active_ocs:
            return await interaction.response.send_message(embed=get_embed("Empty", "No Trainees are currently registered.", "warning"))
            
        active_ocs.sort(key=lambda x: x["name"].lower())
        page_size = data["config"].get("reveal_page_size", 7)
        batches = [active_ocs[i:i + page_size] for i in range(0, len(active_ocs), page_size)]
        
        pages = []
        for idx, batch in enumerate(batches):
            embed = discord.Embed(title=f"All Trainees (Page {idx+1}/{len(batches)})", color=COLORS["neutral"])
            for i, oc in enumerate(batch):
                age = calculate_age(oc["birthday"])
                grade_str = f" [{oc['grade']}]" if oc.get('grade') else ""
                dorm_str = f"{oc['dorm_floor']} · {oc['dorm_room']}" if oc.get('dorm_floor') else "Unassigned"
                
                desc = (
                    f"**Birthday / Age**: {oc['birthday']} · {age} yrs (KST)\n"
                    f"**Gender / Pronouns**: {oc['gender']} · {oc['pronouns']}\n"
                    f"**Faceclaim**: {oc['faceclaim']}\n"
                    f"**Skill**: {oc['main_skill']}\n"
                    f"**Origin**: {oc['nationality']} · {oc['ethnicity']}\n"
                    f"**Grade**: {oc.get('grade', 'Ungraded')}\n"
                    f"**Dorm**: {dorm_str}\n"
                )
                if oc.get('form_link'):
                    desc += f"[Profile Link]({oc['form_link']})"
                    
                embed.add_field(name=f"{oc['name']}{grade_str}", value=desc, inline=False)
                
                if i == 0 and oc.get("profile_picture_url"):
                    embed.set_thumbnail(url=oc["profile_picture_url"])
                    
            pages.append(embed)
            
        if len(pages) > 1:
            await interaction.response.send_message(embed=pages[0], view=RankingPaginationView(pages))
        else:
            await interaction.response.send_message(embed=pages[0])

    @app_commands.command(name="oc_eliminated", description="View all eliminated Trainees")
    async def oc_eliminated(self, interaction: discord.Interaction):
        data = load_data()
        eliminated_ocs = [oc for oc in data["ocs"].values() if oc.get("eliminated", False)]
        if not eliminated_ocs:
            return await interaction.response.send_message(embed=get_embed("None", "No Trainees have been eliminated yet.", "system"))
            
        eliminated_ocs.sort(key=lambda x: x["name"].lower())
        page_size = 25 
        batches = [eliminated_ocs[i:i + page_size] for i in range(0, len(eliminated_ocs), page_size)]
        
        pages = []
        for idx, batch in enumerate(batches):
            embed = discord.Embed(title="Eliminated Trainees", color=COLORS["system"])
            for oc in batch:
                embed.add_field(name=f"~~{oc['name']}~~", value=f"Faceclaim: {oc['faceclaim']}\nOwner: <@{oc['owner_id']}>", inline=False)
            pages.append(embed)
            
        if len(pages) > 1:
            await interaction.response.send_message(embed=pages[0], view=RankingPaginationView(pages))
        else:
            await interaction.response.send_message(embed=pages[0])

    @app_commands.command(name="eliminate", description="[DEV] Eliminate OC(s) from the show")
    @app_commands.choices(mode=[
        app_commands.Choice(name="By Name", value="name"),
        app_commands.Choice(name="By Rank Range", value="rank")
    ])
    @is_dev()
    async def eliminate_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str], value: str):
        data = load_data()
        channel_id = data["config"].get("announcement_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else interaction.channel
        
        target_ocs_list = []

        if mode.value == "name":
            oc = find_oc(value, data)
            if not oc:
                return await interaction.response.send_message(embed=get_embed("Error", f"No active Trainee named '{value}' found.", "error"), ephemeral=True)
            if oc.get("eliminated", False):
                return await interaction.response.send_message(embed=get_embed("Warning", f"{oc['name']} is already eliminated.", "warning"), ephemeral=True)
            target_ocs_list = [oc]

        elif mode.value == "rank":
            try:
                if "-" in value:
                    start_str, end_str = value.split("-")
                    start, end = int(start_str.strip()), int(end_str.strip())
                else:
                    start = end = int(value.strip())
            except ValueError:
                return await interaction.response.send_message(embed=get_embed("Error", "Invalid rank format. Use a number (e.g., '8') or a range (e.g., '8-10').", "error"), ephemeral=True)
                
            target_ocs_list = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False) and start <= oc.get("current_rank", 0) <= end]
            if not target_ocs_list:
                return await interaction.response.send_message(embed=get_embed("Warning", f"No active Trainees found in rank range {start}–{end}.", "warning"), ephemeral=True)
        
        # Pre-elimination Snapshot
        recalculate_ranks(data)
        snap_data = [{"oc_id": o["id"], "rank": o["current_rank"], "points": o["total_points"]} for o in data["ocs"].values() if not o.get("eliminated", False)]
        trigger_name = f"PRE_ELIMINATION_{','.join([t['name'] for t in target_ocs_list])}"
        data["rank_snapshots"].append({
            "timestamp": now().isoformat(),
            "trigger": trigger_name[:100],
            "rankings": snap_data
        })

        names = []
        for oc in target_ocs_list:
            oc["eliminated"] = True
            names.append(oc["name"])
            if oc.get("dorm_floor") and oc.get("dorm_room"):
                try:
                    data["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
                except ValueError:
                    pass
                oc["dorm_floor"] = None
                oc["dorm_room"] = None
                
        recalculate_ranks(data)
        
        if mode.value == "name":
            embed_announce = get_embed("A Trainee Has Been Eliminated", f"*{names[0]} has been eliminated from the competition.*", "warning")
            if channel: await channel.send(embed=embed_announce)
            await interaction.response.send_message(embed=get_embed("Success", f"Done. {names[0]} has been eliminated.", "success"), ephemeral=True)
        else:
            bullet_list = "\n".join([f"• {name}" for name in names])
            embed_announce = get_embed("Elimination Results", f"The following Trainees have been eliminated:\n{bullet_list}", "warning")
            if channel: await channel.send(embed=embed_announce)
            await interaction.response.send_message(embed=get_embed("Success", f"Eliminated {len(names)} Trainee(s): {', '.join(names)}", "success"), ephemeral=True)

    def _build_profile_embed(self, oc, data):
        grade = oc.get("grade")
        grade_data = data["grades"].get(grade, {"color": "#B0B0B0"}) if grade else {"color": "#B0B0B0"}
        
        embed = discord.Embed(title=f"{oc['name']} {'⭐' if not grade else f'[{grade}]'}", color=hex_to_int(grade_data["color"]))
        
        if oc.get("eliminated", False):
            embed.title = f"~~{oc['name']}~~ ✗ [ELIMINATED]"
            embed.color = COLORS["error"]

        age = calculate_age(oc["birthday"])
        embed.add_field(name="Birthday / Age", value=f"{oc['birthday']} · {age} yrs (KST)", inline=True)
        embed.add_field(name="Gender / Pronouns", value=f"{oc['gender']} · {oc['pronouns']}", inline=True)
        embed.add_field(name="Faceclaim", value=oc["faceclaim"], inline=True)
        embed.add_field(name="Main Skill", value=oc["main_skill"], inline=True)
        embed.add_field(name="Nationality / Ethnicity", value=f"{oc['nationality']} · {oc['ethnicity']}", inline=True)
        if oc.get("form_link"):
            embed.add_field(name="Profile", value=f"[View Full Form]({oc['form_link']})", inline=True)
        
        rank_str = "Eliminated" if oc.get("eliminated", False) else f"Rank #{oc.get('current_rank', 0)}"
        embed.add_field(name="Points / Rank", value=f"{oc['total_points']:,} pts · {rank_str}", inline=True)
        embed.add_field(name="Grade", value=grade if grade else "Ungraded", inline=True)
        embed.add_field(name="Dorm", value=f"{oc['dorm_floor']} · {oc['dorm_room']}" if oc.get('dorm_floor') else "Unassigned", inline=True)
        
        if data["config"].get("peer_ranking_enabled"):
            last_resolved = next(
                (s for s in reversed(list(data.get("peer_ranking_sessions", {}).values())) if s.get("resolved")),
                None
            )
            if last_resolved:
                if last_resolved.get("benefit_applied_to") == oc["id"]:
                    embed.add_field(name="Legacy Multiplier", value="Received peer top ranking last session.", inline=False)
                elif last_resolved.get("penalty_applied_to") == oc["id"]:
                    embed.add_field(name="Popularity Tax", value="Received peer bottom ranking last session.", inline=False)

        if oc.get("profile_picture_url"):
            embed.set_thumbnail(url=oc["profile_picture_url"])

        return embed

class VotingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vote", description="Cast vote(s) for one or more Trainees (comma-separated names)")
    @app_commands.describe(oc_names="One or more Trainee names separated by commas, e.g. 'Mira, Juno, Haeun'")
    async def vote(self, interaction: discord.Interaction, oc_names: str):
        data = load_data()

        # Guard: voting must be open
        if not data["voting"]["is_open"]:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Voting Closed",
                    "Voting is currently closed. Stay tuned for the next evaluation period.",
                    "error"
                ),
                ephemeral=True
            )

        user_id   = str(interaction.user.id)
        cap       = data["voting"]["cap"]           # 0 = unlimited

        # Count how many votes this user has already cast this round
        votes_already_cast = sum(
            v_list.count(user_id)
            for v_list in data["voting"]["votes"].values()
        )

        # Remaining quota (None = unlimited)
        remaining = (cap - votes_already_cast) if cap > 0 else None

        # If cap is set and already exhausted, short-circuit immediately
        if remaining is not None and remaining <= 0:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Cap Reached",
                    f"You have already used all **{cap}** vote(s) for this round.",
                    "error"
                ),
                ephemeral=True
            )

        # Parse the input into individual name tokens
        raw_names = [n.strip() for n in oc_names.split(",") if n.strip()]

        if not raw_names:
            return await interaction.response.send_message(
                embed=get_embed("No Input", "Please provide at least one Trainee name.", "error"),
                ephemeral=True
            )

        accepted  = []   # list of OC name strings that were successfully voted for
        rejected  = []   # list of (name_token, reason_string) tuples

        for token in raw_names:
            # Check remaining quota before processing each token
            if remaining is not None and remaining <= 0:
                rejected.append((token, f"Vote cap of **{cap}** reached mid-batch"))
                continue

            # OC resolution
            oc = find_oc(token, data)
            if not oc:
                rejected.append((token, "Trainee not found"))
                continue

            # Eligibility check
            if oc.get("eliminated", False):
                rejected.append((token, f"**{oc['name']}** has been eliminated"))
                continue

            # Record the vote
            if oc["id"] not in data["voting"]["votes"]:
                data["voting"]["votes"][oc["id"]] = []
            data["voting"]["votes"][oc["id"]].append(user_id)

            accepted.append(oc["name"])
            if remaining is not None:
                remaining -= 1

        # Persist only if at least one vote was accepted
        if accepted:
            save_data(data)

        # Build response embed
        votes_now_cast = votes_already_cast + len(accepted)
        quota_line = (
            f"**Quota**: {votes_now_cast}/{cap} vote(s) used this round."
            if cap > 0 else
            f"**Votes cast this round** (no cap): {votes_now_cast}"
        )

        if accepted and not rejected:
            color = "success"
            title = "✅ Vote(s) Recorded"
        elif accepted and rejected:
            color = "warning"
            title = "⚠️ Partial Vote(s) Recorded"
        else:
            color = "error"
            title = "❌ No Votes Recorded"

        desc_parts = []
        if accepted:
            desc_parts.append("**Accepted**:\n" + "\n".join(f"• {n}" for n in accepted))
        if rejected:
            desc_parts.append("**Rejected**:\n" + "\n".join(f"• `{n}` — {reason}" for n, reason in rejected))
        desc_parts.append(quota_line)

        await interaction.response.send_message(
            embed=get_embed(title, "\n\n".join(desc_parts), color),
            ephemeral=True
        )

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
        data["voting"]["last_closed_at"] = now().isoformat()
        data["voting"]["end_time"] = now().isoformat()
        
        mult = data["voting"]["multiplier"]
        for oc_id, voters in data["voting"]["votes"].items():
            if oc_id in data["ocs"] and not data["ocs"][oc_id].get("eliminated", False):
                pts = len(voters) * mult
                points_before = data["ocs"][oc_id]["total_points"]
                
                data["ocs"][oc_id]["voting_points"] += pts
                data["ocs"][oc_id]["total_points"] += pts
                
                data["point_log"].append({
                    "timestamp": now().isoformat(),
                    "dev_id": str(interaction.user.id),
                    "dev_name": interaction.user.name,
                    "oc_id": oc_id,
                    "oc_name": data["ocs"][oc_id]["name"],
                    "action": "vote_close",
                    "value": pts,
                    "points_before": points_before,
                    "points_after": data["ocs"][oc_id]["total_points"]
                })
        
        recalculate_ranks(data)
        
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        snapshot = {
            "timestamp": now().isoformat(),
            "trigger": "VOTING_ROUND_CLOSE",
            "rankings": [{"oc_id": oc["id"], "rank": oc["current_rank"], "points": oc["total_points"]} for oc in active_ocs]
        }
        data["rank_snapshots"].append(snapshot)
        save_data(data)
        
        channel_id = data["config"]["announcement_channel_id"]
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            embed = get_embed("Voting Closed", "The evaluation period has ended. The votes have been tallied and rankings updated.", "system", show_footer=True)
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
                oc["mission_points"] = 0 - oc["voting_points"]
        elif action.value == "multiply":
            oc["total_points"] = int(oc["total_points"] * value)
            oc["mission_points"] = oc["total_points"] - oc["voting_points"]
        elif action.value == "set":
            oc["total_points"] = value
            oc["mission_points"] = value - oc["voting_points"]

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
        
        active_ocs = [o for o in data["ocs"].values() if not o.get("eliminated", False)]
        snapshot = {
            "timestamp": now().isoformat(),
            "trigger": "MANUAL_POINTS",
            "rankings": [{"oc_id": o["id"], "rank": o["current_rank"], "points": o["total_points"]} for o in active_ocs]
        }
        data["rank_snapshots"].append(snapshot)
        save_data(data)
        
        await interaction.response.send_message(embed=get_embed("Points Updated", f"OC **{oc['name']}** total points updated from {points_before:,} to {oc['total_points']:,}.", "success"))

    @app_commands.command(name="resetallpoints", description="[DEV] Zero all OC points and anchor a new ranking baseline")
    @is_dev()
    async def resetall_points(self, interaction: discord.Interaction):
        data = load_data()
        
        # Guard: voting must not be open
        if data["voting"]["is_open"]:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Cannot Reset",
                    "⚠️ *A voting round is currently open. Close it with `/voting close` before resetting all points.*",
                    "warning"
                ),
                ephemeral=True
            )

        # Guard: at least one voting round must have been closed
        if not data["voting"].get("last_closed_at"):
            return await interaction.response.send_message(
                embed=get_embed(
                    "Cannot Reset",
                    "⚠️ *No voting round has been closed yet. This command is intended to be used after a completed voting cycle.*",
                    "warning"
                ),
                ephemeral=True
            )

        # Confirmation gate via ephemeral button UI
        view = ConfirmResetView()
        await interaction.response.send_message(
            embed=get_embed(
                "⚠️ Confirm Full Point Reset",
                "This will set **all** active OC points to **0** and anchor a new ranking baseline. This action **cannot be undone**.\n\n"
                "Click **Confirm** to proceed or **Cancel** to abort.",
                "warning"
            ),
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()


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

    @app_commands.command(name="dorm_createfloor", description="Create a dorm floor and its Discord category (Dev only)")
    @is_dev()
    async def createfloor(self, interaction: discord.Interaction, floor_name: str):
        await interaction.response.defer(ephemeral=True)
        data = load_data()

        if floor_name in data["dorms"]:
            return await interaction.followup.send(
                embed=get_embed("Already Exists", f"Floor **{floor_name}** already exists.", "warning")
            )

        if not interaction.guild:
            return await interaction.followup.send(
                embed=get_embed("Error", "This command must be used inside a server.", "error")
            )

        # Create the Discord category
        try:
            category = await interaction.guild.create_category(name=floor_name)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=get_embed("Permission Error", "Bot lacks `Manage Channels` permission.", "error")
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=get_embed("Discord Error", f"Category creation failed: `{e}`", "error")
            )

        # Persist the record with the new category_id field
        data["dorms"][floor_name] = {
            "rooms": {},
            "category_id": category.id   # NEW FIELD
        }
        save_data(data)

        await interaction.followup.send(
            embed=get_embed(
                "Floor Created",
                f"Floor **{floor_name}** has been set up.\n"
                f"Discord category: **{category.name}** (`{category.id}`)\n"
                f"Rooms added via `/dorm_createroom` will auto-populate under this category.",
                "success"
            )
        )

    @app_commands.command(name="dorm_createroom", description="Create a room on a floor and its Discord channel (Dev only)")
    @is_dev()
    async def createroom(
        self,
        interaction: discord.Interaction,
        floor_name: str,
        room_name: str,
        capacity: int
    ):
        await interaction.response.defer(ephemeral=True)
        data = load_data()

        if floor_name not in data["dorms"]:
            return await interaction.followup.send(
                embed=get_embed("Not Found", f"Floor **{floor_name}** does not exist. Create it first with `/dorm_createfloor`.", "error")
            )

        if room_name in data["dorms"][floor_name]["rooms"]:
            return await interaction.followup.send(
                embed=get_embed("Already Exists", f"Room **{room_name}** already exists on floor **{floor_name}**.", "warning")
            )

        if capacity < 1:
            return await interaction.followup.send(
                embed=get_embed("Invalid Capacity", "Capacity must be at least 1.", "error")
            )

        if not interaction.guild:
            return await interaction.followup.send(
                embed=get_embed("Error", "This command must be used inside a server.", "error")
            )

        # Resolve the parent category (may be None if floor was created before this patch)
        category = None
        category_id = data["dorms"][floor_name].get("category_id")
        if category_id:
            category = interaction.guild.get_channel(int(category_id))
            # If the category was manually deleted in Discord, proceed without it
            # and log a warning in the response so the dev is aware.

        # Sanitise the room name for a Discord channel slug
        safe_name = re.sub(r'[^a-z0-9\-]', '', room_name.lower().replace(' ', '-'))[:100]
        if not safe_name:
            safe_name = f"room-{str(uuid.uuid4())[:8]}"

        # Create the text channel, nested under the floor's category if available
        try:
            channel = await interaction.guild.create_text_channel(
                name=safe_name,
                category=category,
                topic=f"Dorm room {room_name} on floor {floor_name}. Capacity: {capacity}."
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=get_embed("Permission Error", "Bot lacks `Manage Channels` permission.", "error")
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=get_embed("Discord Error", f"Channel creation failed: `{e}`", "error")
            )

        # Persist the room record, including the new channel_id field
        data["dorms"][floor_name]["rooms"][room_name] = {
            "capacity": capacity,
            "occupants": [],
            "channel_id": channel.id   # NEW FIELD
        }
        save_data(data)

        orphan_warning = (
            "\n⚠️ **Note**: The floor's Discord category was not found; the channel was created without a parent category."
            if category_id and category is None else ""
        )

        await interaction.followup.send(
            embed=get_embed(
                "Room Created",
                f"Room **{room_name}** on floor **{floor_name}** is ready.\n"
                f"Discord channel: <#{channel.id}>\n"
                f"Capacity: **{capacity}** occupant(s).{orphan_warning}",
                "success"
            )
        )

    @app_commands.command(name="dorm_assign", description="Manually assign an OC to a room (Dev only)")
    @is_dev()
    async def assign(self, interaction: discord.Interaction, oc_name: str, floor_name: str, room_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc: return await interaction.response.send_message("OC not found.", ephemeral=True)
        
        if oc.get("eliminated", False):
            return await interaction.response.send_message(
                embed=get_embed("Ineligible", f"**{oc['name']}** is eliminated and cannot be assigned to a dorm.", "error"),
                ephemeral=True
            )
            
        try:
            room = data["dorms"][floor_name]["rooms"][room_name]
            if len(room["occupants"]) >= room["capacity"]:
                return await interaction.response.send_message(embed=get_embed("Room Full", f"Room {room_name} is at capacity ({room['capacity']}).", "error"), ephemeral=True)
            
            if oc.get("dorm_floor") and oc.get("dorm_room"):
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
        if not data["dorms"]:
            return await interaction.response.send_message(
                embed=get_embed("No Dorms", "No dorm floors have been created yet.", "system")
            )

        embed = get_embed("🏠 Dormitory Assignments", "Current resident listings by floor.")
        for floor, f_data in data["dorms"].items():
            cat_id = f_data.get("category_id")
            cat_mention = f" *(Category `{cat_id}`)*" if cat_id else ""
            desc = ""
            for r_name, r_data in f_data["rooms"].items():
                occ_names = [
                    data["ocs"][oid]["name"]
                    for oid in r_data["occupants"]
                    if oid in data["ocs"] and not data["ocs"][oid].get("eliminated", False)
                ]
                names_str  = ", ".join(occ_names) if occ_names else "*Empty*"
                ch_mention = f" · <#{r_data['channel_id']}>" if r_data.get("channel_id") else ""
                desc += (
                    f"**Room {r_name}**{ch_mention} "
                    f"({len(occ_names)}/{r_data['capacity']}): {names_str}\n"
                )
            if not desc:
                desc = "*No rooms yet.*"
            embed.add_field(name=f"Floor: {floor}{cat_mention}", value=desc, inline=False)

        await interaction.response.send_message(embed=embed)

class MissionGroupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    missiongroup = app_commands.Group(name="missiongroup", description="[DEV] Mission Group Management")

    @missiongroup.command(name="create", description="[DEV] Create a new mission group")
    @is_dev()
    async def create(self, interaction: discord.Interaction, name: str, oc_names: str):
        data = load_data()
        for mg in data["mission_groups"].values():
            if not mg.get("archived", False) and mg["name"].lower() == name.lower():
                return await interaction.response.send_message(embed=get_embed("Error", f"A mission group named '{name}' already exists.", "error"), ephemeral=True)
                
        raw_names = [n.strip() for n in re.split(r'[,\s]+', oc_names) if n.strip()]
        valid_ocs = []
        not_found = []
        ineligible = []
        already_assigned = []
        
        for n in raw_names:
            oc = find_oc(n, data)
            if not oc:
                not_found.append(n)
                continue
            if oc.get("eliminated", False):
                ineligible.append(n)
                continue
            
            conflict = next((mg["name"] for mg in data["mission_groups"].values() if not mg.get("archived") and oc["id"] in mg["members"]), None)
            if conflict:
                already_assigned.append(f"{n} (in {conflict})")
            else:
                valid_ocs.append(oc["id"])
                
        if not valid_ocs:
            err_desc = "No valid trainees could be added.\n"
            if not_found: err_desc += f"**Not Found**: {', '.join(not_found)}\n"
            if ineligible: err_desc += f"**Eliminated**: {', '.join(ineligible)}\n"
            if already_assigned: err_desc += f"**Already Assigned**: {', '.join(already_assigned)}"
            return await interaction.response.send_message(embed=get_embed("Creation Failed", err_desc, "error"), ephemeral=True)
            
        new_id = str(uuid.uuid4())
        data["mission_groups"][new_id] = {
            "group_id": new_id,
            "name": name,
            "members": valid_ocs,
            "channel_id": None,
            "category_id": None,
            "created_at": now().isoformat(),
            "archived": False
        }
        save_data(data)
        
        desc = f"**Members**: {', '.join([data['ocs'][oid]['name'] for oid in valid_ocs])}\n"
        if not_found or ineligible or already_assigned:
            desc += "\n**⚠️ Warnings (Skipped):**\n"
            if not_found: desc += f"• Not Found: {', '.join(not_found)}\n"
            if ineligible: desc += f"• Eliminated: {', '.join(ineligible)}\n"
            if already_assigned: desc += f"• Conflict: {', '.join(already_assigned)}"
            
        await interaction.response.send_message(embed=get_embed(f"Group '{name}' Created", desc, "success"), ephemeral=True)

    @missiongroup.command(name="addmember", description="[DEV] Add an OC to a mission group")
    @is_dev()
    async def addmember(self, interaction: discord.Interaction, group_name: str, oc_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "Mission group not found or archived.", "error"), ephemeral=True)
        
        oc = find_oc(oc_name, data)
        if not oc: return await interaction.response.send_message(embed=get_embed("Error", "OC not found.", "error"), ephemeral=True)
        if oc.get("eliminated"): return await interaction.response.send_message(embed=get_embed("Error", "OC is eliminated.", "error"), ephemeral=True)
        
        conflict = next((mg["name"] for mg in data["mission_groups"].values() if not mg.get("archived") and oc["id"] in mg["members"]), None)
        if conflict: return await interaction.response.send_message(embed=get_embed("Error", f"OC is already assigned to {conflict}.", "error"), ephemeral=True)
        
        group["members"].append(oc["id"])
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"{oc['name']} added to {group['name']}.", "success"), ephemeral=True)

    @missiongroup.command(name="removemember", description="[DEV] Remove an OC from a mission group")
    @is_dev()
    async def removemember(self, interaction: discord.Interaction, group_name: str, oc_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "Mission group not found.", "error"), ephemeral=True)
        
        oc = find_oc(oc_name, data)
        if not oc or oc["id"] not in group["members"]:
            return await interaction.response.send_message(embed=get_embed("Warning", "OC is not in this group.", "warning"), ephemeral=True)
            
        group["members"].remove(oc["id"])
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"{oc['name']} removed from {group['name']}.", "success"), ephemeral=True)

    @missiongroup.command(name="provision", description="[DEV] Create a Discord practice channel for a group")
    @is_dev()
    async def provision(self, interaction: discord.Interaction, group_name: str, category: discord.CategoryChannel = None):
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.followup.send(embed=get_embed("Error", "Mission group not found or archived.", "error"))
        
        if group.get("channel_id"):
            ch = self.bot.get_channel(int(group["channel_id"]))
            if ch: return await interaction.followup.send(embed=get_embed("Warning", f"A practice room channel already exists: <#{ch.id}>.", "warning"))
            
        safe_name = "practice-" + re.sub(r'[^a-zA-Z0-9\-]', '', group['name'].lower().replace(' ', '-'))
        try:
            channel = await interaction.guild.create_text_channel(
                name=safe_name,
                topic=f"Practice room for {group['name']} mission group.",
                category=category
            )
        except discord.Forbidden:
            return await interaction.followup.send(embed=get_embed("Permission Error", "The bot lacks the `Manage Channels` permission in this server.", "error"))
            
        group["channel_id"] = channel.id
        group["category_id"] = category.id if category else None
        save_data(data)
        await interaction.followup.send(embed=get_embed("Success", f"Practice room created: <#{channel.id}>.", "success"))

    @missiongroup.command(name="deprovision", description="[DEV] Delete the practice channel for a group")
    @is_dev()
    async def deprovision(self, interaction: discord.Interaction, group_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if mg["name"].lower() == group_name.lower()), None)
        if not group or not group.get("channel_id"):
            return await interaction.response.send_message(embed=get_embed("Error", "Group not found or has no channel.", "error"), ephemeral=True)
            
        ch = self.bot.get_channel(int(group["channel_id"]))
        if ch:
            try:
                await ch.delete(reason=f"Mission group {group['name']} deprovisioned.")
            except discord.Forbidden:
                return await interaction.response.send_message(embed=get_embed("Error", "Missing permissions to delete channel.", "error"), ephemeral=True)
                
        group["channel_id"] = None
        group["category_id"] = None
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", "Channel deprovisioned.", "success"), ephemeral=True)

    @missiongroup.command(name="view", description="Publicly view mission group assignments")
    async def view(self, interaction: discord.Interaction, group_name: str = None):
        data = load_data()
        if group_name:
            group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
            if not group: return await interaction.response.send_message(embed=get_embed("Error", "Group not found.", "error"))
            
            embed = get_embed(f"Mission Group: {group['name']}", f"**Created**: {format_dt(group['created_at'])}")
            embed.add_field(name="Practice Room", value=f"<#{group['channel_id']}>" if group.get("channel_id") else "No practice room", inline=False)
            members = [data["ocs"].get(oid, {}).get("name", "[Unknown OC]") for oid in group["members"]]
            embed.add_field(name=f"Members ({len(members)})", value=", ".join(members) if members else "None", inline=False)
            return await interaction.response.send_message(embed=embed)
            
        active_groups = [mg for mg in data["mission_groups"].values() if not mg.get("archived")]
        if not active_groups: return await interaction.response.send_message(embed=get_embed("No Groups", "No active mission groups.", "neutral"))
        
        embeds = []
        page_size = 5
        batches = [active_groups[i:i + page_size] for i in range(0, len(active_groups), page_size)]
        
        for idx, batch in enumerate(batches):
            embed = get_embed(f"Mission Groups (Page {idx+1}/{len(batches)})")
            for group in batch:
                ch_str = f" · Room: <#{group['channel_id']}>" if group.get("channel_id") else ""
                members = [data["ocs"].get(oid, {}).get("name", "[Unknown]") for oid in group["members"]]
                embed.add_field(name=group["name"], value=f"Members ({len(members)}): {', '.join(members) if members else 'None'}{ch_str}", inline=False)
            embeds.append(embed)
            
        if len(embeds) > 1:
            await interaction.response.send_message(embed=embeds[0], view=RankingPaginationView(embeds))
        else:
            await interaction.response.send_message(embed=embeds[0])

    @missiongroup.command(name="archive", description="[DEV] Archive a mission group")
    @is_dev()
    async def archive(self, interaction: discord.Interaction, group_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "Group not found.", "error"), ephemeral=True)
        
        group["archived"] = True
        save_data(data)
        
        warning = "\n⚠️ **Note**: Practice channel was not deleted. Use `/missiongroup deprovision` if needed." if group.get("channel_id") else ""
        await interaction.response.send_message(embed=get_embed("Success", f"Group '{group['name']}' archived.{warning}", "success"), ephemeral=True)

class PeerRankingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    peerranking = app_commands.Group(name="peerranking", description="Peer Ranking System")

    @peerranking.command(name="toggle", description="[DEV] Toggle Peer Ranking system on/off")
    @is_dev()
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        data = load_data()
        data["config"]["peer_ranking_enabled"] = enabled
        save_data(data)
        
        unresolved = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        warning = "\n⚠️ **Warning**: There is an unresolved session that should be closed/cancelled." if not enabled and unresolved else ""
        
        await interaction.response.send_message(embed=get_embed("System Toggled", f"Peer Ranking System is now {'**ENABLED**' if enabled else '**DISABLED**'}.{warning}", "success" if enabled else "warning"), ephemeral=True)

    @peerranking.command(name="configure", description="[DEV] Configure Peer Ranking rewards/penalties")
    @app_commands.choices(benefit_type=[app_commands.Choice(name="Multiplier", value="multiplier"), app_commands.Choice(name="Flat Points", value="flat")],
                          penalty_type=[app_commands.Choice(name="Multiplier", value="multiplier"), app_commands.Choice(name="Flat Points", value="flat")])
    @is_dev()
    async def configure(self, interaction: discord.Interaction, benefit_type: app_commands.Choice[str], benefit_value: float, penalty_type: app_commands.Choice[str], penalty_value: float, transparent: bool = None):
        data = load_data()
        if benefit_type.value == "multiplier" and benefit_value < 1.0:
            return await interaction.response.send_message(embed=get_embed("Error", "Benefit multiplier must be >= 1.0", "error"), ephemeral=True)
        if benefit_type.value == "flat" and benefit_value <= 0:
            return await interaction.response.send_message(embed=get_embed("Error", "Benefit flat value must be > 0", "error"), ephemeral=True)
        
        if penalty_type.value == "multiplier" and (penalty_value <= 0.0 or penalty_value >= 1.0):
            return await interaction.response.send_message(embed=get_embed("Error", "Penalty multiplier must be between 0.0 and 1.0 exclusive", "error"), ephemeral=True)
        if penalty_type.value == "flat" and penalty_value <= 0:
            return await interaction.response.send_message(embed=get_embed("Error", "Penalty flat value must be > 0", "error"), ephemeral=True)

        data["config"]["peer_ranking_benefit"] = {"type": benefit_type.value, "value": benefit_value}
        data["config"]["peer_ranking_penalty"] = {"type": penalty_type.value, "value": penalty_value}
        if transparent != None: data["config"]["peer_ranking_transparent"] = transparent
        save_data(data)
        
        desc = (f"**Benefit**: {benefit_type.name} ({benefit_value})\n"
                f"**Penalty**: {penalty_type.name} ({penalty_value})\n"
                f"**Transparent Reveal**: {data['config']['peer_ranking_transparent']}")
        await interaction.response.send_message(embed=get_embed("Configuration Updated", desc, "success"), ephemeral=True)

    @peerranking.command(name="opensession", description="[DEV] Open a new peer ranking session")
    @is_dev()
    async def opensession(self, interaction: discord.Interaction, mission_group: str):
        data = load_data()
        if not data["config"]["peer_ranking_enabled"]:
            return await interaction.response.send_message(embed=get_embed("Error", "Peer Ranking is not enabled. Use /peerranking toggle to enable it.", "error"), ephemeral=True)
            
        if any(not s.get("resolved") for s in data["peer_ranking_sessions"].values()):
            return await interaction.response.send_message(embed=get_embed("Error", "An active peer ranking session already exists. Close it before opening a new one.", "error"), ephemeral=True)

        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == mission_group.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "Mission group not found.", "error"), ephemeral=True)

        perf_oc_ids = [oid for oid in group["members"] if oid in data["ocs"] and not data["ocs"][oid].get("eliminated")]
        if not perf_oc_ids: return await interaction.response.send_message(embed=get_embed("Error", "No active trainees in this group.", "error"), ephemeral=True)

        eligible = set(oc["owner_id"] for oc in data["ocs"].values() if not oc.get("eliminated") and oc["id"] not in perf_oc_ids)
        
        sess_id = str(uuid.uuid4())
        data["peer_ranking_sessions"][sess_id] = {
            "session_id": sess_id,
            "mission_group_id": group["group_id"],
            "performing_oc_ids": perf_oc_ids,
            "eligible_voter_ids": list(eligible),
            "ballots": {},
            "tally": {},
            "resolved": False,
            "revealed": False,
            "created_at": now().isoformat(),
            "closed_at": None,
            "benefit_applied_to": None,
            "penalty_applied_to": None
        }
        save_data(data)
        
        announce_ch = self.bot.get_channel(int(data["config"]["announcement_channel_id"])) if data["config"].get("announcement_channel_id") else interaction.channel
        if announce_ch:
            perf_names = ", ".join([data["ocs"][oid]["name"] for oid in perf_oc_ids])
            embed = get_embed("⚖️ Peer Ranking Now Open", f"**Group**: {group['name']}\n**Performers**: {perf_names}\n\nAll non-performing trainees must cast their ranking from best to worst using `/peerranking vote ranking: ...`.")
            await announce_ch.send(embed=embed)
            
        await interaction.response.send_message(embed=get_embed("Success", f"Session opened. {len(eligible)} eligible voters.", "success"), ephemeral=True)

    @peerranking.command(name="vote", description="Cast your peer ranking vote (best to worst)")
    async def vote(self, interaction: discord.Interaction, ranking: str):
        data = load_data()
        if not data["config"]["peer_ranking_enabled"]:
            return await interaction.response.send_message(embed=get_embed("Disabled", "Peer Ranking is currently disabled.", "error"), ephemeral=True)
            
        session = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        if not session:
            return await interaction.response.send_message(embed=get_embed("Closed", "No peer ranking session is currently open.", "error"), ephemeral=True)
            
        user_id = str(interaction.user.id)
        if user_id not in session["eligible_voter_ids"]:
            return await interaction.response.send_message(embed=get_embed("Ineligible", "You are not eligible to vote in this session. Only trainees who were not performing may cast peer rankings.", "error"), ephemeral=True)
            
        if user_id in session["ballots"]:
            return await interaction.response.send_message(embed=get_embed("Already Voted", "You have already submitted your ranking for this session.", "warning"), ephemeral=True)
            
        raw_names = [n.strip() for n in re.split(r'[,\s]+', ranking) if n.strip()]
        perf_lower_map = {data["ocs"][oid]["name"].lower(): oid for oid in session["performing_oc_ids"]}
        
        ballot_ids = []
        errors = []
        for n in raw_names:
            if n.lower() in perf_lower_map: ballot_ids.append(perf_lower_map[n.lower()])
            else: errors.append(n)
            
        if errors or len(ballot_ids) != len(session["performing_oc_ids"]) or len(set(ballot_ids)) != len(ballot_ids):
            valid_names = [data["ocs"][oid]["name"] for oid in session["performing_oc_ids"]]
            return await interaction.response.send_message(embed=get_embed("Invalid Ranking", f"Issues found: unrecognized or missing/duplicate names.\n\nValid performing OCs to rank:\n{', '.join(valid_names)}", "error"), ephemeral=True)
            
        session["ballots"][user_id] = ballot_ids
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Recorded", "Your peer ranking has been recorded. It will remain private until the session is revealed.", "success"), ephemeral=True)

    @peerranking.command(name="closesession", description="[DEV] Close session and apply multipliers")
    @is_dev()
    async def closesession(self, interaction: discord.Interaction):
        data = load_data()
        session = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        if not session: return await interaction.response.send_message(embed=get_embed("Error", "No active session to close.", "error"), ephemeral=True)

        perf_oc_ids = session["performing_oc_ids"]
        tally = {oid: 0 for oid in perf_oc_ids}
        rank_counts = {oid: {i: 0 for i in range(len(perf_oc_ids))} for oid in perf_oc_ids}
        
        warning_msg = ""
        if len(session["ballots"]) == 0:
            warning_msg = "\n⚠️ **Warning**: No ballots were submitted. Benefit/Penalty applied alphabetically."
            sorted_ocs = sorted(perf_oc_ids, key=lambda oid: data["ocs"][oid]["name"].lower())
            benefit_oc_id = sorted_ocs[0]
            penalty_oc_id = sorted_ocs[-1]
        else:
            for ballot in session["ballots"].values():
                for i, oid in enumerate(ballot):
                    tally[oid] += (i + 1)
                    rank_counts[oid][i] += 1
            
            def sort_for_benefit(oid):
                return (tally[oid], -rank_counts[oid][0], rank_counts[oid].get(len(perf_oc_ids)-1, 0), random.random())
            def sort_for_penalty(oid):
                return (tally[oid], rank_counts[oid].get(len(perf_oc_ids)-1, 0), -rank_counts[oid][0], random.random())
                
            benefit_oc_id = min(perf_oc_ids, key=sort_for_benefit)
            penalty_oc_id = max(perf_oc_ids, key=sort_for_penalty)

        session["tally"] = tally

        # Apply Benefit
        ben_cfg = data["config"]["peer_ranking_benefit"]
        if ben_cfg["type"] == "multiplier":
            bonus = round(data["ocs"][benefit_oc_id]["voting_points"] * (ben_cfg["value"] - 1.0))
            data["ocs"][benefit_oc_id]["total_points"] += bonus
        else:
            bonus = int(ben_cfg["value"])
            data["ocs"][benefit_oc_id]["mission_points"] += bonus
            data["ocs"][benefit_oc_id]["total_points"] += bonus
            
        data["point_log"].append({
            "timestamp": now().isoformat(), "dev_id": str(interaction.user.id), "dev_name": interaction.user.name,
            "oc_id": benefit_oc_id, "oc_name": data["ocs"][benefit_oc_id]["name"],
            "action": "peer_benefit", "value": bonus,
            "points_before": data["ocs"][benefit_oc_id]["total_points"] - bonus, "points_after": data["ocs"][benefit_oc_id]["total_points"]
        })

        # Apply Penalty
        pen_cfg = data["config"]["peer_ranking_penalty"]
        if pen_cfg["type"] == "multiplier":
            deduction = round(data["ocs"][penalty_oc_id]["voting_points"] * pen_cfg["value"])
            data["ocs"][penalty_oc_id]["total_points"] -= deduction
        else:
            deduction = int(pen_cfg["value"])
            data["ocs"][penalty_oc_id]["total_points"] -= deduction
            
        if data["ocs"][penalty_oc_id]["total_points"] < 0 and not data["config"]["allow_negative_points"]:
            data["ocs"][penalty_oc_id]["total_points"] = 0
            
        data["point_log"].append({
            "timestamp": now().isoformat(), "dev_id": str(interaction.user.id), "dev_name": interaction.user.name,
            "oc_id": penalty_oc_id, "oc_name": data["ocs"][penalty_oc_id]["name"],
            "action": "peer_penalty", "value": -deduction,
            "points_before": data["ocs"][penalty_oc_id]["total_points"] + deduction, "points_after": data["ocs"][penalty_oc_id]["total_points"]
        })

        session["resolved"] = True
        session["closed_at"] = now().isoformat()
        session["benefit_applied_to"] = benefit_oc_id
        session["penalty_applied_to"] = penalty_oc_id
        
        recalculate_ranks(data)
        
        desc = (f"Ballots: {len(session['ballots'])} / {len(session['eligible_voter_ids'])}\n"
                f"**⭐ Benefit**: {data['ocs'][benefit_oc_id]['name']} (+{bonus})\n"
                f"**💀 Penalty**: {data['ocs'][penalty_oc_id]['name']} (-{deduction})\n"
                f"{warning_msg}\n"
                f"{'*Use `/peerranking reveal` to disclose ballots.*' if data['config']['peer_ranking_transparent'] else ''}")
        await interaction.response.send_message(embed=get_embed("Session Closed", desc, "success"), ephemeral=True)

    @peerranking.command(name="reveal", description="[DEV] Publicly reveal peer ranking ballots")
    @is_dev()
    async def reveal(self, interaction: discord.Interaction, session_id: str = None):
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        
        if not data["config"]["peer_ranking_transparent"]:
            return await interaction.followup.send(embed=get_embed("Warning", "Transparent ballot reveal is currently disabled in config. Enable it with /peerranking configure.", "warning"))

        if session_id:
            session = data["peer_ranking_sessions"].get(session_id)
        else:
            session = next((s for s in reversed(list(data["peer_ranking_sessions"].values())) if s.get("resolved") and not s.get("revealed")), None)
            
        if not session or not session.get("resolved") or session.get("revealed"):
            return await interaction.followup.send(embed=get_embed("Error", "No valid unresolved/unrevealed session found.", "error"))

        group = data["mission_groups"].get(session["mission_group_id"], {"name": "Unknown Group"})
        announce_ch = self.bot.get_channel(int(data["config"]["announcement_channel_id"])) if data["config"].get("announcement_channel_id") else interaction.channel

        sorted_tally = sorted(session["tally"].items(), key=lambda x: x[1])
        tally_desc = "\n".join([f"**{data['ocs'][oid]['name']}**: {score} pts" for oid, score in sorted_tally])
        await announce_ch.send(embed=get_embed("⚖️ The Peer Ranking Ballots Are Now Public", f"**Group**: {group['name']}\n\n**Final Tally** (Lower is better):\n{tally_desc}"))
        await asyncio.sleep(2.0)

        for voter_id, ballot in session["ballots"].items():
            try:
                user = await self.bot.fetch_user(int(voter_id))
                username = user.name
            except:
                username = f"Unknown User (ID: {voter_id})"
                
            ranks_str = "\n".join([f"{i+1}. {data['ocs'][oid]['name']}" for i, oid in enumerate(ballot)])
            embed = discord.Embed(title=f"Ballot · @{username}", description=ranks_str, color=COLORS["neutral"])
            await announce_ch.send(embed=embed)
            await asyncio.sleep(random.uniform(1.0, 2.0))

        res_embed = discord.Embed(title="Resolution", color=COLORS["system"])
        ben_name = data["ocs"].get(session["benefit_applied_to"], {}).get("name", "Unknown")
        pen_name = data["ocs"].get(session["penalty_applied_to"], {}).get("name", "Unknown")
        res_embed.add_field(name="⭐ Legacy Multiplier", value=ben_name, inline=True)
        res_embed.add_field(name="💀 Popularity Tax", value=pen_name, inline=True)
        await announce_ch.send(embed=res_embed)

        session["revealed"] = True
        save_data(data)
        await interaction.followup.send(embed=get_embed("Success", "All ballots have been publicly revealed.", "success"))

    @peerranking.command(name="status", description="Check current peer ranking status")
    async def status(self, interaction: discord.Interaction):
        data = load_data()
        if not data["config"]["peer_ranking_enabled"]:
            return await interaction.response.send_message(embed=get_embed("Inactive", "The Rivalry Protocol is not active this cycle.", "system"), ephemeral=True)
            
        session = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        if session:
            group = data["mission_groups"].get(session["mission_group_id"], {"name": "Unknown"})
            desc = (f"**Group Under Evaluation**: {group['name']}\n"
                    f"**Performers**: {len(session['performing_oc_ids'])}\n"
                    f"**Eligible Voters**: {len(session['eligible_voter_ids'])}\n"
                    f"**Ballots Submitted**: {len(session['ballots'])}\n"
                    "Status: **OPEN**")
            return await interaction.response.send_message(embed=get_embed("Peer Ranking Status", desc, "neutral"))
            
        last_resolved = next((s for s in reversed(list(data["peer_ranking_sessions"].values())) if s.get("resolved") and s.get("revealed")), None)
        if last_resolved:
            group = data["mission_groups"].get(last_resolved["mission_group_id"], {"name": "Unknown"})
            desc = f"Last evaluated group: **{group['name']}**\nSession closed."
            return await interaction.response.send_message(embed=get_embed("Peer Ranking Status", desc, "neutral"))

        await interaction.response.send_message(embed=get_embed("Status", "No peer ranking session has been opened yet.", "neutral"))

class RankingsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rankings_private", description="View full rankings privately and save snapshot (Dev only)")
    @is_dev()
    async def private(self, interaction: discord.Interaction):
        data = load_data()
        ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        ocs.sort(key=lambda x: x.get("current_rank", 9999))
        
        debut_slots = data["config"].get("debut_slots", 0)
        desc = ""
        prev_rank = 0
        
        for oc in ocs:
            if debut_slots > 0 and prev_rank <= debut_slots and oc["current_rank"] > debut_slots:
                desc += f"`{'─' * 30}` ← Debut Line\n\n"
            
            change = get_rank_change(oc["id"], oc["current_rank"], data)
            grade_str = f" [{oc['grade']}]" if oc.get('grade') else ""
            desc += f"**#{oc['current_rank']}** {change} · {oc['name']}{grade_str} · {oc['total_points']:,} pts\n"
            prev_rank = oc["current_rank"]
            
        embed = get_embed("Live Internal Rankings", desc, show_footer=True)
        
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
        data = load_data()
        color = hex_to_int(data["config"]["reveal_color"])
        await interaction.response.send_message(embed=get_embed("Evaluation Begins", "*The moment you've all been waiting for…*", "reveal", show_footer=True))
        
        channel_id = data["config"].get("announcement_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else interaction.channel
        
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        active_ocs.sort(key=lambda x: x.get("current_rank", 9999), reverse=True)
        
        page_size = data["config"].get("reveal_page_size", 7)
        page_embeds = await _run_sequential_reveal(channel, active_ocs, color, page_size, data, show_debut_line=True)
        
        await interaction.followup.send(
            embed=get_embed("📖 Browse Results", f"Scroll through all {len(page_embeds)} page(s).", "reveal", show_footer=True),
            view=RankingPaginationView(page_embeds)
        )

    @app_commands.command(name="rankings_partial", description="Dramatically reveal a partial range of rankings (Dev only)")
    @is_dev()
    async def partial(self, interaction: discord.Interaction, start_rank: int, end_rank: int):
        data = load_data()
        color = hex_to_int(data["config"]["reveal_color"])
        await interaction.response.send_message(embed=get_embed("Evaluation Begins", f"*Revealing ranks {start_rank} to {end_rank}…*", "reveal", show_footer=True))
        
        channel_id = data["config"].get("announcement_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else interaction.channel
        
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False) and start_rank <= oc.get("current_rank", 0) <= end_rank]
        active_ocs.sort(key=lambda x: x.get("current_rank", 9999), reverse=True)
        
        if not active_ocs:
            return await channel.send(embed=get_embed("No Results", "No trainees found in that rank range.", "warning"))
            
        page_size = data["config"].get("reveal_page_size", 7)
        # We set show_debut_line to False for partial reveals since ordinal counting might misalign with partial lists
        page_embeds = await _run_sequential_reveal(channel, active_ocs, color, page_size, data, show_debut_line=False)
        
        await interaction.followup.send(
            embed=get_embed("📖 Browse Results", f"Scroll through all {len(page_embeds)} page(s).", "reveal", show_footer=True),
            view=RankingPaginationView(page_embeds)
        )

class ExportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="export_rankings", description="Export full state to TSV (Dev only)")
    @is_dev()
    async def export_rankings(self, interaction: discord.Interaction):
        data = load_data()
        output = io.StringIO()
        writer = csv.writer(output, delimiter='\t')
        
        writer.writerow(["--- SECTION 1: CURRENT RANKINGS ---"])
        writer.writerow(["rank", "oc_name", "owner_discord_id", "owner_username", "grade", "total_points", "voting_points", "mission_points", "rank_change", "dorm_floor", "dorm_room", "registered_at", "eliminated", "profile_picture_url"])
        
        ocs = sorted(list(data["ocs"].values()), key=lambda x: (x.get("eliminated", False), x.get("current_rank", 999999)))
        for oc in ocs:
            change = get_rank_change(oc["id"], oc.get("current_rank", 0), data)
            writer.writerow([
                oc.get("current_rank", ""), oc["name"], oc["owner_id"], oc["owner_name"], 
                oc.get("grade",""), oc["total_points"], oc["voting_points"], oc["mission_points"], 
                change, oc.get("dorm_floor",""), oc.get("dorm_room",""), oc["registered_at"], 
                str(oc.get("eliminated", False)), oc.get("profile_picture_url", "")
            ])
        
        writer.writerow([])
        writer.writerow(["--- SECTION 2: RANK HISTORY ---"])
        writer.writerow(["oc_name", "snapshot_timestamp", "snapshot_trigger", "rank_at_snapshot", "points_at_snapshot"])
        for snap in data["rank_snapshots"]:
            for r in snap["rankings"]:
                oc_name = data["ocs"].get(r["oc_id"], {}).get("name", "Unknown/Archived")
                writer.writerow([oc_name, snap["timestamp"], snap["trigger"], r["rank"], r["points"]])
                
        writer.writerow([])
        writer.writerow(["--- SECTION 3: POINT MANIPULATION LOG ---"])
        writer.writerow(["timestamp", "dev_discord_id", "dev_username", "oc_name", "action", "value", "points_before", "points_after"])
        for log in data["point_log"]:
            writer.writerow([log["timestamp"], log["dev_id"], log["dev_name"], log["oc_name"], log["action"], log["value"], log["points_before"], log["points_after"]])

        writer.writerow([])
        writer.writerow(["--- SECTION 4: MISSION GROUPS ---"])
        writer.writerow(["group_name", "group_id", "member_oc_names", "channel_id", "archived", "created_at"])
        for g in data.get("mission_groups", {}).values():
            member_names = ", ".join([data["ocs"].get(mid, {}).get("name", "Unknown") for mid in g["members"]])
            writer.writerow([g["name"], g["group_id"], member_names, g.get("channel_id") or "", str(g.get("archived", False)), g["created_at"]])

        writer.writerow([])
        writer.writerow(["--- SECTION 5: PEER RANKING SESSIONS ---"])
        writer.writerow(["session_id", "mission_group_name", "resolved", "revealed", "closed_at", "ballots_submitted", "eligible_voters", "benefit_oc", "penalty_oc"])
        for s in data.get("peer_ranking_sessions", {}).values():
            group = data.get("mission_groups", {}).get(s["mission_group_id"], {})
            benefit_name = data["ocs"].get(s.get("benefit_applied_to", ""), {}).get("name", "N/A")
            penalty_name = data["ocs"].get(s.get("penalty_applied_to", ""), {}).get("name", "N/A")
            writer.writerow([
                s["session_id"], group.get("name", "Unknown"), str(s["resolved"]),
                str(s["revealed"]), s.get("closed_at") or "",
                len(s["ballots"]), len(s["eligible_voter_ids"]),
                benefit_name, penalty_name
            ])

        writer.writerow([])
        writer.writerow(["--- SECTION 6: FEED POST ANALYTICS ---"])
        writer.writerow(["oc_name", "post_number", "post_id", "author", "like_count", "comment_thread_id", "media_count", "created_at"])
        for oc_id, posts in data.get("feeds", {}).items():
            oc_name = data["ocs"].get(oc_id, data["archived_ocs"].get(oc_id, {"name": "Unknown"}))["name"]
            for idx, post in enumerate(posts, start=1):
                writer.writerow([
                    oc_name, idx, post["post_id"], post["author_name"],
                    post["like_count"], post.get("thread_id") or "",
                    len(post["media_urls"]), post["created_at"]
                ])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"rankings_export_{now().strftime('%Y-%m-%d_%H-%M')}.tsv")
        await interaction.response.send_message("Here is the requested data export.", file=file, ephemeral=True)

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="guide", description="Display a guide to all bot commands")
    @app_commands.describe(section="Jump to a specific topic (optional)")
    @app_commands.choices(section=[
        app_commands.Choice(name="General & Registration", value="general"),
        app_commands.Choice(name="Voting",                 value="voting"),
        app_commands.Choice(name="Points & Rankings",      value="points"),
        app_commands.Choice(name="Dorms",                  value="dorms"),
        app_commands.Choice(name="Grades",                 value="grades"),
        app_commands.Choice(name="Mission Groups",         value="missions"),
        app_commands.Choice(name="Peer Ranking",           value="peerranking"),
        app_commands.Choice(name="OC Feed",                value="feeds"),
        app_commands.Choice(name="Configuration",          value="config"),
    ])
    async def help_cmd(self, interaction: discord.Interaction, section: app_commands.Choice[str] = None):
        try:
            if section is None:
                # Build the index overview page
                embed = get_embed(
                    "Survival Show Sim — Command Guide",
                    "Use `/guide section:<name>` to drill into any topic.\n\u200b",
                    "system"
                )
                for key, sec in HELP_SECTIONS.items():
                    public_count = len(sec["commands"])
                    dev_count    = len(sec["dev_commands"])
                    embed.add_field(
                        name=sec["title"],
                        value=(
                            f"{public_count} public command(s)"
                            + (f" · {dev_count} staff command(s) 🔒" if dev_count else "")
                            + f"\n`/guide section:{key}`"
                        ),
                        inline=True
                    )
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            # Specific section page
            sec = HELP_SECTIONS[section.value]
            
            if not sec["commands"] and not sec["dev_commands"]:
                embed = get_embed(sec["title"], "This section has no commands listed yet.", "system")
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            embed = get_embed(sec["title"], "", "system")

            all_entries = [(cmd, params, desc, False) for cmd, params, desc in sec["commands"]] + \
                          [(cmd, params, desc, True)  for cmd, params, desc in sec["dev_commands"]]

            for cmd, params, desc, is_dev_cmd in all_entries:
                usage = f"`{cmd}`" + (f" `{params}`" if params else "")
                embed.add_field(
                    name=usage,
                    value=desc,
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            err_embed = get_embed("Error", f"Failed to load the guide: `{e}`", "error")
            if interaction.response.is_done():
                await interaction.followup.send(embed=err_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=err_embed, ephemeral=True)

class FeedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    feed_group = app_commands.Group(name="feed", description="OC Social Feed")

    @feed_group.command(name="post", description="Post to an OC's social feed (up to 10 media)")
    @app_commands.describe(
        oc_name="Name of the OC",
        caption="Caption text (max 500 characters)",
        media1="First image or video attachment (required)"
    )
    async def feed_post(self, interaction: discord.Interaction, oc_name: str, caption: str,
                        media1: discord.Attachment, media2: discord.Attachment = None, media3: discord.Attachment = None,
                        media4: discord.Attachment = None, media5: discord.Attachment = None, media6: discord.Attachment = None,
                        media7: discord.Attachment = None, media8: discord.Attachment = None, media9: discord.Attachment = None,
                        media10: discord.Attachment = None):
        
        data = load_data()
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No active Trainee named '{oc_name}'.", "error"), ephemeral=True)
        if oc.get("eliminated", False):
            return await interaction.response.send_message(embed=get_embed("Ineligible", "Eliminated Trainees cannot post to their feed.", "error"), ephemeral=True)
            
        is_owner = str(interaction.user.id) == oc["owner_id"]
        dev_role = data["config"].get("dev_role_id")
        
        is_dev_user = (
            interaction.user.id == interaction.client.application.owner.id
            or (dev_role and interaction.guild and interaction.guild.get_role(int(dev_role)) in interaction.user.roles)
        )
        
        if not is_owner and not is_dev_user:
            return await interaction.response.send_message(embed=get_embed("Permission Denied", "🔒 Only this OC's owner or a staff member can post to this feed.", "error"), ephemeral=True)
            
        oc_id = oc["id"]
        if oc_id not in data["feeds"]:
            data["feeds"][oc_id] = []
            
        if len(oc.get("feed_post_ids", [])) >= 10:
            return await interaction.response.send_message(embed=get_embed("Feed Full", f"**{oc['name']}** already has 10 posts. Delete an existing post with `/feed delete` to make room.", "warning"), ephemeral=True)
            
        if len(caption) > 500:
            return await interaction.response.send_message(embed=get_embed("Caption Too Long", "Captions must be 500 characters or fewer.", "error"), ephemeral=True)
            
        raw_attachments = [a for a in [media1, media2, media3, media4, media5, media6, media7, media8, media9, media10] if a is not None]
        
        ALLOWED_TYPES = ("image/", "video/")
        for att in raw_attachments:
            if not att.content_type or not any(att.content_type.startswith(t) for t in ALLOWED_TYPES):
                return await interaction.response.send_message(embed=get_embed("Invalid File", f"'{att.filename}' is not a supported image or video type.", "error"), ephemeral=True)
                
        if not data["config"].get("asset_channel"):
            return await interaction.response.send_message(embed=get_embed("Not Configured", "No asset channel set. Ask a Dev to run `/setassetchannel`.", "warning"), ephemeral=True)
            
        if not data["config"].get("feed_channel"):
            return await interaction.response.send_message(embed=get_embed("Not Configured", "No feed channel set. Ask a Dev to run `/setfeedchannel`.", "warning"), ephemeral=True)
            
        await interaction.response.defer()
        
        asset_ch = self.bot.get_channel(int(data["config"]["asset_channel"]))
        if not asset_ch:
            return await interaction.followup.send(embed=get_embed("Error", "Asset channel not found. Please reconfigure.", "error"), ephemeral=True)
            
        media_urls = []
        for att in raw_attachments:
            raw = await att.read()
            f = discord.File(fp=io.BytesIO(raw), filename=att.filename)
            asset_msg = await asset_ch.send(content=f"[Feed Asset] OC: `{oc['name']}` · <@{interaction.user.id}>", file=f)
            media_urls.append(asset_msg.attachments[0].url)
            
        post_id = str(uuid.uuid4())
        now_str = now().isoformat()
        
        grade_color = COLORS["system"]
        if oc.get("grade") and oc["grade"] in data["grades"]:
            grade_color = hex_to_int(data["grades"][oc["grade"]]["color"])
            
        post_embed = discord.Embed(title=f"📸 {oc['name']}", description=caption, color=grade_color)
        post_embed.set_author(name=f"@{oc['name']}", icon_url=oc.get("profile_picture_url") or discord.Embed.Empty)
        post_embed.set_footer(text=f"❤️ 0 likes  ·  Posted by @{interaction.user.name}  ·  {format_dt(now_str)}")
        
        first_att = raw_attachments[0]
        if first_att.content_type and first_att.content_type.startswith("image/"):
            post_embed.set_image(url=media_urls[0])
            
        if len(media_urls) > 1:
            links = "\n".join(f"[Media {idx+1}]({url})" for idx, url in enumerate(media_urls[1:], start=1))
            post_embed.add_field(name="Additional Media", value=links, inline=False)
            
        post_num = len(oc.get("feed_post_ids", [])) + 1
        post_embed.add_field(name="Post", value=f"{post_num} / 10", inline=True)
        
        feed_ch = self.bot.get_channel(int(data["config"]["feed_channel"]))
        if not feed_ch:
            return await interaction.followup.send(embed=get_embed("Error", "Feed channel not found. Please reconfigure.", "error"), ephemeral=True)
            
        post_view = FeedPostView(post_id)
        post_msg = await feed_ch.send(embed=post_embed, view=post_view)
        
        post_record = {
            "post_id": post_id,
            "oc_id": oc_id,
            "author_id": str(interaction.user.id),
            "author_name": interaction.user.name,
            "caption": caption,
            "media_urls": media_urls,
            "like_count": 0,
            "thread_id": None,
            "message_id": post_msg.id,
            "channel_id": post_msg.channel.id,
            "created_at": now_str
        }
        
        data["feeds"][oc_id].append(post_record)
        oc.setdefault("feed_post_ids", []).append(post_id)
        save_data(data)
        
        await interaction.followup.send(embed=get_embed("Post Published", f"**{oc['name']}**'s post has been published to <#{feed_ch.id}>.", "success"), ephemeral=True)

    @feed_group.command(name="view", description="Browse an OC's social feed posts")
    async def feed_view(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}'.", "error"), ephemeral=True)
            
        oc_posts = data["feeds"].get(oc["id"], [])
        if not oc_posts:
            return await interaction.response.send_message(embed=get_embed(f"{oc['name']}'s Feed", "No posts yet.", "system"))
            
        pages = []
        grade_color = COLORS["system"]
        if oc.get("grade") and oc["grade"] in data["grades"]:
            grade_color = hex_to_int(data["grades"][oc["grade"]]["color"])
            
        for idx, post in enumerate(reversed(oc_posts), start=1):
            embed = discord.Embed(
                title=f"📸 {oc['name']} — Post {len(oc_posts) - idx + 1} of {len(oc_posts)}",
                description=post["caption"],
                color=grade_color
            )
            embed.set_author(name=f"@{oc['name']}", icon_url=oc.get("profile_picture_url") or discord.Embed.Empty)
            
            if post["media_urls"]:
                first_url = post["media_urls"][0]
                video_exts = (".mp4", ".mov", ".webm", ".avi", ".mkv")
                if not any(first_url.lower().endswith(ext) for ext in video_exts):
                    embed.set_image(url=first_url)
                else:
                    embed.add_field(name="🎬 Video", value=f"[Watch Video]({first_url})", inline=False)
                    
            if len(post["media_urls"]) > 1:
                links = "\n".join(f"[Media {i+1}]({u})" for i, u in enumerate(post["media_urls"][1:], start=1))
                embed.add_field(name="Additional Media", value=links, inline=False)
                
            thread_link = f"[View Thread](https://discord.com/channels/{interaction.guild_id}/{post['channel_id']}/{post['thread_id']})" if post.get("thread_id") else "No comments yet."
            embed.add_field(name="Comments", value=thread_link, inline=True)
            embed.add_field(name="❤️ Likes", value=str(post["like_count"]), inline=True)
            pages.append(embed)
            
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0])
        else:
            view = RankingPaginationView(pages)
            msg = await interaction.response.send_message(embed=pages[0], view=view)
            view.message = msg
            
    @feed_group.command(name="delete", description="Delete one of an OC's feed posts by its number (1 = oldest)")
    async def feed_delete(self, interaction: discord.Interaction, oc_name: str, post_number: int):
        data = load_data()
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"No Trainee named '{oc_name}'.", "error"), ephemeral=True)
            
        is_owner = str(interaction.user.id) == oc["owner_id"]
        dev_role = data["config"].get("dev_role_id")
        is_dev_user = (
            interaction.user.id == interaction.client.application.owner.id
            or (dev_role and interaction.guild and interaction.guild.get_role(int(dev_role)) in interaction.user.roles)
        )
        
        if not is_owner and not is_dev_user:
            return await interaction.response.send_message(embed=get_embed("Permission Denied", "🔒 Only this OC's owner or a staff member can delete feed posts.", "error"), ephemeral=True)
            
        oc_posts = data["feeds"].get(oc["id"], [])
        if not (1 <= post_number <= len(oc_posts)):
            return await interaction.response.send_message(embed=get_embed("Invalid Post Number", f"This OC has {len(oc_posts)} post(s). Provide a number between 1 and {len(oc_posts)}.", "error"), ephemeral=True)
            
        post = oc_posts[post_number - 1]
        
        try:
            feed_ch = self.bot.get_channel(int(post["channel_id"]))
            if feed_ch and post.get("message_id"):
                original_msg = await feed_ch.fetch_message(int(post["message_id"]))
                await original_msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
            
        data["feeds"][oc["id"]].pop(post_number - 1)
        oc["feed_post_ids"].pop(post_number - 1)
        save_data(data)
        
        await interaction.response.send_message(embed=get_embed("Post Deleted", f"Post #{post_number} from **{oc['name']}**'s feed has been removed.", "success"), ephemeral=True)

# ==========================================
# 6. BACKGROUND TASKS
# ==========================================
@tasks.loop(minutes=1)
async def voting_scheduler():
    pass

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable missing.")
        exit(1)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print(f"Health server started on port {os.getenv('PORT', 8080)}.")

    bot.run(TOKEN)