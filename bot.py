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
import copy
import aiohttp

# ==========================================
# 1. CONSTANTS & SYSTEM DEFAULTS
# ==========================================
DATA_FILE = "data.json"
TEMP_FILE = "data.tmp"

DB_LOADED  = False
DATA_DIRTY = False

_data_channel_lock = asyncio.Lock()

POINTLOG_ACTION_RESETALL = "resetall"
SNAP_TRIGGER_RESETALL = "POINTS_RESETALL_BASELINE"

COLORS = {
    "system": 0x1A1A2E,
    "error": 0xE63946,
    "success": 0x2DC653,
    "warning": 0xF4A261,
    "neutral": 0xB0B0B0
}

TIMEZONE_CHOICES = [
    app_commands.Choice(name="UTC (UTC+0)",                     value="UTC"),
    app_commands.Choice(name="Asia/Seoul — KST (UTC+9)",        value="Asia/Seoul"),
    app_commands.Choice(name="Asia/Tokyo — JST (UTC+9)",        value="Asia/Tokyo"),
    app_commands.Choice(name="Asia/Manila — PHT (UTC+8)",       value="Asia/Manila"),
    app_commands.Choice(name="Asia/Singapore — SGT (UTC+8)",    value="Asia/Singapore"),
    app_commands.Choice(name="Asia/Jakarta — WIB (UTC+7)",      value="Asia/Jakarta"),
    app_commands.Choice(name="Asia/Bangkok — ICT (UTC+7)",      value="Asia/Bangkok"),
    app_commands.Choice(name="Asia/Kolkata — IST (UTC+5:30)",   value="Asia/Kolkata"),
    app_commands.Choice(name="Asia/Dubai — GST (UTC+4)",        value="Asia/Dubai"),
    app_commands.Choice(name="Europe/London — GMT/BST",         value="Europe/London"),
    app_commands.Choice(name="Europe/Paris — CET/CEST (UTC+1/+2)", value="Europe/Paris"),
    app_commands.Choice(name="Europe/Berlin — CET/CEST (UTC+1/+2)", value="Europe/Berlin"),
    app_commands.Choice(name="America/New_York — EST/EDT",      value="America/New_York"),
    app_commands.Choice(name="America/Chicago — CST/CDT",       value="America/Chicago"),
    app_commands.Choice(name="America/Denver — MST/MDT",        value="America/Denver"),
    app_commands.Choice(name="America/Los_Angeles — PST/PDT",   value="America/Los_Angeles"),
    app_commands.Choice(name="America/Toronto — EST/EDT",       value="America/Toronto"),
    app_commands.Choice(name="America/Sao_Paulo — BRT (UTC-3)", value="America/Sao_Paulo"),
    app_commands.Choice(name="Pacific/Auckland — NZST (UTC+12)",value="Pacific/Auckland"),
    app_commands.Choice(name="Australia/Sydney — AEST/AEDT",    value="Australia/Sydney"),
]

KST = zoneinfo.ZoneInfo("Asia/Seoul")

HELP_SECTIONS = {
    "general": {
        "title": "📋 General & Registration",
        "commands": [
            ("/register", "name birthday_yyyy_mm_dd gender pronouns faceclaim main_skill nationality [form_link] [ethnicity] [profile_picture]", "Register a new Trainee OC. Each user may have up to the configured OC cap."),
            ("/profile", "oc_name", "View a Trainee's full profile card."),
            ("/oc_all", "", "Browse all currently active Trainees (paginated)."),
            ("/oc_eliminated", "", "View all eliminated Trainees."),
            ("/removeoc", "oc_name", "Permanently archive one of your own Trainees. Requires confirmation."),
            ("/editoc", "oc_name [name] [birthday_yyyy_mm_dd] [gender] [pronouns] [faceclaim] [main_skill] [nationality] [ethnicity] [form_link] [profile_picture]", "Edit any field on one of your own Trainees."),
        ],
        "dev_commands": [
            ("/deleteoc", "oc_name", "🔒 Permanently hard-delete an OC from all data (active or archived). Irreversible."),
        ]
    },
    "voting": {
        "title": "🗳️ Voting",
        "commands": [
            ("/vote", "oc_names", "Vote for one or more Trainees (comma-separated). Subject to the per-day vote cap."),
            ("/votingstatus", "", "Check whether voting is currently open and see the current tally (if permitted)."),
        ],
        "dev_commands": [
            ("/votingopen", "", "🔒 Open a new voting round immediately, or schedule it for a specific KST datetime (year/month/day hour/minute)."),
            ("/votingclose", "", "🔒 Close voting immediately or schedule it. Applies the multiplier, tallies votes, and updates rankings."),
            ("/config votingmultiplier", "value", "🔒 Set the vote-to-points multiplier."),
            ("/config votingcap", "cap", "🔒 Set max votes per user **per day** (resets 12:00 AM KST). 0 = unlimited."),
            ("/config_multivote", "enabled", "🔒 Toggle whether a single user can vote for the same OC multiple times per round (True/False)."),
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
            ("/rankings_private", "", "🔒 See all current rankings privately. Bypasses open/closed voting gate. Shows live tally with pagination."),
            ("/rankings_partial", "ranks", "🔒 Reveal specific rankings by number. Accepts space- or comma-separated integers (e.g. `1 5 9` or `3, 7, 12`)."),
            ("/export_rankings", "", "🔒 Export full state (rankings, history, logs, feeds) as a CSV file."),
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
            ("/setup", "timezone announce_channel [force]", "🔒 Initial bot setup. Dev role, #assets, #data, and #rankings channels are detected automatically if present."),
            ("/config_view", "", "🔒 View all current configuration values."),
            ("/setassetchannel", "channel", "🔒 Set the persistent asset storage channel."),
            ("/setfeedchannel", "channel", "🔒 Set the public feed channel."),
            ("/setbackupchannel", "channel", "🔒 Set the designated channel for JSON backups."),
            ("/setdatachannel", "channel", "🔒 Set the channel that receives automatic data-change notifications."),
            ("/setrankingschannel", "channel", "🔒 Set the channel that receives the live leaderboard after every voting close."),
            ("/backup", "", "🔒 Export the full data.json to the backup channel. Creates the channel automatically if it doesn't exist."),
            ("/setrevealpage", "size", "🔒 Set how many Trainees appear per reveal page (1–25)."),
            ("/config setdebutslots", "", "🔒 [DEPRECATED] This command has been retired and is now a no-op."),
            ("/config set", "key value", "🔒 Update a whitelisted config scalar."),
            ("/purgedata", "", "🔒 ⚠️ Permanently reset ALL data to factory defaults. Requires confirmation. Irreversible."),
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
        "allow_multi_vote": False,
        "reveal_color": "#FFD700",
        "asset_channel": None,
        "feed_channel": None,
        "backup_channel_id": None,
        "backup_anchor_message_id": None,
        "data_channel_id": None,
        "rankings_channel_id": None,
        "data_anchor_message_id": None,
        "setup_completed_at": None,
        "deployment_count": 0,
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
        "last_closed_at": None,
        "scheduled_open_time": None,
        "scheduled_close_time": None,
        "daily_vote_counts": {},
        "daily_vote_date": None
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
def migrate_schema(data: dict) -> bool:
    modified = False
    for key, val in DEFAULT_SCHEMA.items():
        if key not in data:
            data[key] = val
            modified = True
            
    for key, val in DEFAULT_SCHEMA["config"].items():
        if key not in data["config"]:
            data["config"][key] = val
            modified = True

    for key in ("data_anchor_message_id", "backup_anchor_message_id", "setup_completed_at"):
        if key not in data["config"]:
            data["config"][key] = None
            modified = True

    if "deployment_count" not in data["config"]:
        data["config"]["deployment_count"] = 0
        modified = True

    # v1.x → allow_multi_vote (toggleable duplicate-vote policy)
    if "allow_multi_vote" not in data["config"]:
        data["config"]["allow_multi_vote"] = False
        modified = True

    # v1.x → rankings_channel_id (auto-detected #rankings channel)
    if "rankings_channel_id" not in data["config"]:
        data["config"]["rankings_channel_id"] = None
        modified = True

    if "last_closed_at" not in data["voting"]:
        data["voting"]["last_closed_at"] = None
        modified = True
    if "user_votes" not in data["voting"]:
        data["voting"]["user_votes"] = {}
        modified = True
    if "scheduled_open_time" not in data["voting"]:
        data["voting"]["scheduled_open_time"] = None
        modified = True
    if "scheduled_close_time" not in data["voting"]:
        data["voting"]["scheduled_close_time"] = None
        modified = True
    if "daily_vote_counts" not in data["voting"]:
        data["voting"]["daily_vote_counts"] = {}
        modified = True
    if "daily_vote_date" not in data["voting"]:
        data["voting"]["daily_vote_date"] = None
        modified = True
        
    if "feeds" not in data:
        data["feeds"] = {}
        modified = True

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

    for floor_name, floor_data in data.get("dorms", {}).items():
        if "category_id" not in floor_data:
            floor_data["category_id"] = None
            modified = True
        for room_name, room_data in floor_data.get("rooms", {}).items():
            if "channel_id" not in room_data:
                room_data["channel_id"] = None
                modified = True
                
    for grade_label, grade_data in data.get("grades", {}).items():
        if "role_id" not in grade_data:
            grade_data["role_id"] = None
            modified = True

    return modified

def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SCHEMA, f, indent=4)
        print("Initialization: Created new data.json with default schema.")
        return copy.deepcopy(DEFAULT_SCHEMA)
    
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            modified = migrate_schema(data)
            if modified:
                save_data(data)
            return data
    except json.JSONDecodeError:
        print("CRITICAL ERROR: JSON is malformed. Halting to prevent data overwrite.")
        os._exit(1)

async def load_data_from_channel(bot_instance: discord.Client) -> dict:
    """
    Rehydrate data.json from the most recent JSON attachment posted to the
    designated data channel.
    PRIMARY: Finds the pinned anchor message and loads it instantly.
    FALLBACK: Scans up to 200 messages as legacy behavior.
    """
    data = load_data()
    channel_id = data["config"].get("data_channel_id")
    if not channel_id:
        print("load_data_from_channel: data_channel_id not configured; skipping hydration.")
        return data

    channel = None
    try:
        # Prefer cache lookup first (free); fall back to HTTP fetch if miss.
        channel = bot_instance.get_channel(int(channel_id))
        if channel is None:
            channel = await bot_instance.fetch_channel(int(channel_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        print(f"load_data_from_channel: could not resolve channel {channel_id}: {e}")
        return data

    # PRIMARY: Try pinned anchor first
    try:
        pins = await channel.pins()
        for pinned_msg in sorted(pins, key=lambda m: m.created_at, reverse=True):
            for attachment in pinned_msg.attachments:
                if attachment.filename.startswith("data_") and attachment.filename.endswith(".json"):
                    try:
                        json_bytes = await attachment.read()
                        fetched_data = json.loads(json_bytes)
                        migrate_schema(fetched_data)
                        with open(TEMP_FILE, "w", encoding="utf-8") as f:
                            json.dump(fetched_data, f, indent=4)
                        os.replace(TEMP_FILE, DATA_FILE)
                        oc_count = len(fetched_data.get("ocs", {}))
                        print(f"Rehydration successful (from pinned anchor): loaded '{attachment.filename}' from #{channel.name} "
                              f"(message {pinned_msg.id}). {oc_count} OC(s) restored.")
                        return fetched_data
                    except (json.JSONDecodeError, discord.HTTPException) as parse_err:
                        print(f"load_data_from_channel: skipping malformed pin attachment '{attachment.filename}': {parse_err}")
                        continue
    except Exception as e:
        print(f"load_data_from_channel: pin scan failed: {e}")

    # FALLBACK: Linear 200-msg scan
    try:
        async for message in channel.history(limit=200, oldest_first=False):
            for attachment in message.attachments:
                if not attachment.filename.endswith(".json"):
                    continue
                try:
                    json_bytes = await attachment.read()
                    fetched_data = json.loads(json_bytes)
                except (json.JSONDecodeError, discord.HTTPException) as parse_err:
                    print(f"load_data_from_channel: skipping malformed attachment '{attachment.filename}': {parse_err}")
                    continue

                migrate_schema(fetched_data)

                # Atomic write to disk so load_data() reflects the hydrated state
                with open(TEMP_FILE, "w", encoding="utf-8") as f:
                    json.dump(fetched_data, f, indent=4)
                os.replace(TEMP_FILE, DATA_FILE)

                oc_count = len(fetched_data.get("ocs", {}))
                print(f"Rehydration successful (fallback scan): loaded '{attachment.filename}' from #{channel.name} "
                      f"(message {message.id}). {oc_count} OC(s) restored.")
                return fetched_data

        print("load_data_from_channel: no valid JSON attachment found in recent history. Using local data.")
    except Exception as e:
        print(f"load_data_from_channel: unexpected error during channel scan: {e}")

    return data

def save_data(data: dict, reason: str = "routine update", actor: discord.User | discord.Member | None = None):
    global DATA_DIRTY
    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(TEMP_FILE, DATA_FILE)
    DATA_DIRTY = True
    
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_data_channel(data, reason, actor))
        loop.create_task(push_backup_to_discord(data, reason=reason))
    except RuntimeError:
        pass  # No running event loop (e.g. called during synchronous startup)

async def push_backup_to_discord(data: dict, reason: str = "mutation") -> None:
    global DATA_DIRTY
    if not DB_LOADED:
        return

    try:
        payload_bytes = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
        if len(payload_bytes) > 8_000_000:
            print("[push_backup_to_discord] Payload exceeds 8 MB limit, skipping.")
            return

        # Resolve backup channel: prefer configured backup_channel_id, fall back to name lookup
        backup_ch = None
        configured_id = data["config"].get("backup_channel_id")
        for guild in bot.guilds:
            if configured_id:
                backup_ch = guild.get_channel(int(configured_id))
                if backup_ch is None:
                    try:
                        backup_ch = await guild.fetch_channel(int(configured_id))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        backup_ch = None
            if backup_ch is None:
                backup_ch = discord.utils.get(guild.text_channels, name="bot-db-backup")
            if backup_ch:
                break

        if backup_ch is None:
            print("[push_backup_to_discord] No backup channel found. Skipping.")
            return

        # Step 1: Send the new backup file first
        timestamp_str = datetime.now(KST).strftime('%Y%m%d_%H%M%S')
        file = discord.File(
            io.BytesIO(payload_bytes),
            filename=f"data_{timestamp_str}.json"
        )
        new_msg = await backup_ch.send(
            f"[BACKUP] `{reason}` — {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}",
            file=file
        )
        DATA_DIRTY = False

        # Step 2: Delete the *previous* backup message by stored anchor ID (surgical, not bulk)
        old_anchor_id = data["config"].get("backup_anchor_message_id")
        if old_anchor_id:
            try:
                old_msg = await backup_ch.fetch_message(int(old_anchor_id))
                await old_msg.delete()
            except discord.NotFound:
                pass  # Already deleted or never existed — harmless
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"[push_backup_to_discord] Could not delete previous backup message {old_anchor_id}: {e}")

        # Step 3: Persist the new anchor ID directly (no save_data to avoid recursion)
        data["config"]["backup_anchor_message_id"] = str(new_msg.id)
        with open(TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(TEMP_FILE, DATA_FILE)

    except Exception as e:
        print(f"[push_backup_to_discord] Failed: {type(e).__name__}: {e}")

async def save_and_backup(data: dict, reason: str = "mutation") -> None:
    """
    Semantic alias retained for backward compatibility.
    save_data() now internally schedules both notify_data_channel
    and push_backup_to_discord as async tasks, so no explicit
    push_backup_to_discord call is needed here.
    """
    save_data(data, reason=reason)

async def notify_data_channel(data: dict, reason: str, actor: discord.User | discord.Member | None = None) -> discord.Message | None:
    async with _data_channel_lock:
        channel_id = data["config"].get("data_channel_id")
        
        # Live auto-resolution for data channel
        if not channel_id:
            for guild in bot.guilds:
                ch = discord.utils.get(guild.text_channels, name="data")
                if ch:
                    data["config"]["data_channel_id"] = ch.id
                    channel_id = ch.id
                    # Update local state so it's persisted, but avoid calling save_data to prevent recursion
                    with open(TEMP_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    os.replace(TEMP_FILE, DATA_FILE)
                    break
            if not channel_id:
                return None
                
        try:
            channel = bot.get_channel(int(channel_id))
            if not channel:
                return None
                
            embed = discord.Embed(title="📋 Data Updated", color=COLORS["neutral"])
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Actor", value=actor.mention if actor else "System", inline=True)
            embed.add_field(name="Time", value=now().strftime("%Y-%m-%d %H:%M:%S %Z"), inline=False)
            embed.set_footer(text="data.json written")
            
            json_bytes = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
            timestamp_str = datetime.now(KST).strftime('%Y%m%d_%H%M%S')
            filename = f"data_{timestamp_str}.json"
            data_file = discord.File(fp=io.BytesIO(json_bytes), filename=filename)
            
            new_msg = await channel.send(embed=embed, file=data_file)
            
            # Unpin previous anchor
            old_anchor_id = data["config"].get("data_anchor_message_id")
            if old_anchor_id:
                try:
                    old_msg = await channel.fetch_message(int(old_anchor_id))
                    await old_msg.unpin(reason="Superseded by newer data snapshot")
                except (discord.NotFound, discord.HTTPException):
                    pass
                    
            # Pin new anchor
            try:
                await new_msg.pin(reason="Latest bot data snapshot")
                data["config"]["data_anchor_message_id"] = str(new_msg.id)
                # Synchronously write the anchor ID to avoid re-triggering save_data
                with open(TEMP_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                os.replace(TEMP_FILE, DATA_FILE)
            except discord.HTTPException:
                pass
                
            return new_msg
        except Exception as e:
            print(f"[notify_data_channel] WARN: failed to post data snapshot: {type(e).__name__}: {e}")
            return None

async def ensure_grade_role(guild: discord.Guild, grade_label: str, hex_color: str, data: dict) -> discord.Role | None:
    color_int = hex_to_int(hex_color)
    role_id = data["grades"][grade_label].get("role_id")
    role = None
    try:
        if role_id:
            role = guild.get_role(int(role_id))
        if role:
            if role.colour.value != color_int:
                await role.edit(colour=discord.Colour(color_int), reason="Grade colour sync")
        else:
            role = await guild.create_role(name=f"[{grade_label}]", colour=discord.Colour(color_int), reason=f"Grade tier: {grade_label}")
            data["grades"][grade_label]["role_id"] = role.id
        return role
    except (discord.Forbidden, discord.HTTPException):
        return None

async def sync_grade_role_for_owner(
    guild: discord.Guild,
    owner_id: str,
    new_grade_label: str | None,
    old_grade_label: str | None,
    data: dict
) -> None:
    try:
        member = guild.get_member(int(owner_id))
        if not member:
            return

        # Remove old grade role if applicable
        if old_grade_label and old_grade_label != new_grade_label:
            has_other = any(
                oc["owner_id"] == owner_id and oc.get("grade") == old_grade_label and not oc.get("eliminated", False)
                for oc in data["ocs"].values()
            )
            if not has_other:
                old_role_id = data["grades"].get(old_grade_label, {}).get("role_id")
                if old_role_id:
                    old_role = guild.get_role(int(old_role_id))
                    if old_role and old_role in member.roles:
                        await member.remove_roles(old_role, reason="Grade reassignment")
        
        # Assign new grade role if applicable
        if new_grade_label:
            hex_color = data["grades"][new_grade_label]["color"]
            new_role = await ensure_grade_role(guild, new_grade_label, hex_color, data)
            if new_role and new_role not in member.roles:
                await member.add_roles(new_role, reason=f"Grade {new_grade_label} assigned")
                
    except (discord.Forbidden, discord.HTTPException):
        pass

# ==========================================
# 3. UTILITY FUNCTIONS & SHARED VIEWS
# ==========================================

async def upload_to_asset_channel(bot_instance: discord.Client, oc_name: str, oc_id: str, image_url: str) -> str | None:
    """
    Download image_url and re-host it in #assets. Returns the stable proxy_url.
    Returns None on any failure. Never raises.
    """
    data = load_data()
    asset_channel_id = data["config"].get("asset_channel")
    if not asset_channel_id:
        # Attempt live resolution
        for guild in bot_instance.guilds:
            ch = discord.utils.get(guild.text_channels, name="assets")
            if ch:
                asset_channel_id = ch.id
                data["config"]["asset_channel"] = ch.id
                save_data(data, reason="auto_resolved_asset_channel")
                break
    if not asset_channel_id:
        return None

    channel = bot_instance.get_channel(int(asset_channel_id))
    if not channel:
        try:
            channel = await bot_instance.fetch_channel(int(asset_channel_id))
        except Exception:
            return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                img_bytes = await resp.read()
                ext = "png"
                if "." in image_url:
                    possible_ext = image_url.split(".")[-1].split("?")[0].lower()
                    if len(possible_ext) <= 5 and possible_ext.isalnum():
                        ext = possible_ext
                filename = f"{oc_id}_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}.{ext}"
                new_file = discord.File(fp=io.BytesIO(img_bytes), filename=filename)
                msg = await channel.send(
                    content=f"[OC Asset] `{oc_name}` (id:{oc_id})",
                    file=new_file
                )
                att = msg.attachments[0]
                return att.proxy_url or att.url
    except Exception as e:
        print(f"upload_to_asset_channel: failed for {oc_name}: {e}")
        return None

async def _post_rankings_to_channel(bot_instance: discord.Client, data: dict) -> None:
    """
    Build the live leaderboard embed pages and post them sequentially to the
    configured rankings_channel_id. Silently no-ops if the channel is not set,
    not found, or if there are no active OCs.

    This function intentionally does NOT paginate interactively — it posts all
    embed pages as individual messages so the channel retains a permanent,
    scrollable record of every round's final standings.
    """
    rankings_channel_id = data["config"].get("rankings_channel_id")
    if not rankings_channel_id:
        return

    channel = bot_instance.get_channel(int(rankings_channel_id))
    if not channel:
        try:
            channel = await bot_instance.fetch_channel(int(rankings_channel_id))
        except Exception:
            return

    active_ocs = sorted(
        [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)],
        key=lambda x: x.get("current_rank", 9999)
    )
    if not active_ocs:
        return

    page_size = data["config"].get("reveal_page_size", 7)
    pages_data = [active_ocs[i:i + page_size] for i in range(0, len(active_ocs), page_size)]
    total_pages = len(pages_data)

    # Header message
    header_embed = get_embed(
        "🏆 Updated Rankings",
        f"Rankings updated after voting closed · {now().strftime('%Y/%m/%d %H:%M %Z')} · {len(active_ocs)} active trainee(s)",
        "neutral",
        show_footer=True
    )
    await channel.send(embed=header_embed)

    for page_idx, page_ocs in enumerate(pages_data, start=1):
        lines = []
        for oc in page_ocs:
            rank_change = get_rank_change(oc["id"], oc.get("current_rank", 0), data)
            lines.append(
                f"**#{oc.get('current_rank', '?')}** {oc['name']} "
                f"— `{oc['total_points']:,} pts` {rank_change}"
            )
        page_embed = get_embed(
            f"Rankings — Page {page_idx}/{total_pages}",
            "\n".join(lines),
            "neutral"
        )
        await channel.send(embed=page_embed)

async def auto_resolve_config(guild: discord.Guild | None, data: dict) -> bool:
    if not guild:
        return False
    changed = False
    
    if data["config"].get("asset_channel") is None:
        channel = discord.utils.get(guild.text_channels, name="assets")
        if not channel:
            channel = next((c for c in guild.text_channels if c.name.lower() == "assets"), None)
        if channel:
            data["config"]["asset_channel"] = channel.id
            changed = True

    if data["config"].get("data_channel_id") is None:
        channel = discord.utils.get(guild.text_channels, name="data")
        if not channel:
            channel = next((c for c in guild.text_channels if c.name.lower() == "data"), None)
        if channel:
            data["config"]["data_channel_id"] = channel.id
            changed = True

    if data["config"].get("rankings_channel_id") is None:
        channel = discord.utils.get(guild.text_channels, name="rankings")
        if not channel:
            channel = next((c for c in guild.text_channels if c.name.lower() == "rankings"), None)
        if channel:
            data["config"]["rankings_channel_id"] = channel.id
            changed = True

    if data["config"].get("dev_role_id") is None:
        role = next((r for r in guild.roles if r.permissions.administrator and not r.is_default()), None)
        if role:
            data["config"]["dev_role_id"] = role.id
            changed = True

    return changed

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

def _reset_daily_votes_if_needed(data: dict) -> bool:
    """
    Check if the current KST date differs from the stored daily_vote_date.
    If so, reset daily_vote_counts and update daily_vote_date.
    Returns True if a reset occurred (caller should save data), False otherwise.
    """
    today_str = today_kst().isoformat()
    stored_date = data["voting"].get("daily_vote_date")
    if stored_date != today_str:
        data["voting"]["daily_vote_counts"] = {}
        data["voting"]["daily_vote_date"] = today_str
        return True
    return False

def format_dt(dt_str):
    if not dt_str: return "Unknown"
    dt = datetime.fromisoformat(dt_str).astimezone(get_tz())
    return dt.strftime("%Y/%m/%d · %H:%M %Z")

def format_date_display(date_str: str) -> str:
    """Convert stored YYYY-MM-DD to long display format: Month DD, YYYY."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        return date_str or "Unknown"

def calculate_age(dob_str: str) -> int | str:
    """
    Calculate age in full years using the current calendar date in Korean Standard
    Time (KST, UTC+9, Asia/Seoul). Age increments at midnight KST on the OC's
    birthday. Input must be stored as YYYY-MM-DD. Returns an int on success, or
    the string 'Unknown' on parse failure. This function is intentionally decoupled
    from the server's configured timezone (data["config"]["timezone"]) — KST is
    always used for age calculation regardless of server settings.
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
        if await auto_resolve_config(interaction.guild, data):
            save_data(data, reason="auto_resolve_is_dev", actor=interaction.user)
            
        dev_role_id = data["config"].get("dev_role_id")
        if dev_role_id:
            role = interaction.guild.get_role(int(dev_role_id)) if interaction.guild else None
            if role and role in interaction.user.roles:
                return True
                
        # Fallback: any Administrator role
        if interaction.guild:
            for role in interaction.user.roles:
                if role.permissions.administrator:
                    return True
                    
        raise app_commands.CheckFailure("dev_only")
    return app_commands.check(predicate)

def recalculate_ranks(data):
    active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
    if not active_ocs:
        return
    active_ocs.sort(key=lambda x: (-x["total_points"], x["registered_at"]))
    for rank, oc in enumerate(active_ocs, start=1):
        data["ocs"][oc["id"]]["current_rank"] = rank

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
                embed=get_embed("Nothing to Reset", "There are no active Trainees with points to reset right now!", "warning"),
                view=self
            )

        # ── STEP 1: Snapshot PRE-RESET rankings (before any mutation) ──────────
        recalculate_ranks(data)   # ensure ranks are current right now
        pre_reset_snap = [
            {"oc_id": oc["id"], "rank": oc["current_rank"], "points": oc["total_points"]}
            for oc in data["ocs"].values()
            if not oc.get("eliminated", False)
        ]
        data["rank_snapshots"].append({
            "timestamp": now().isoformat(),
            "trigger":   "PRE_RESETALL_BASELINE",
            "rankings":  pre_reset_snap
        })

        # ── STEP 2: Zero out all points and write audit log entries ─────────────
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

        # ── STEP 3: Recalculate ranks post-reset (tiebreak = registered_at) ─────
        recalculate_ranks(data)

        # ── STEP 4: Snapshot POST-RESET state as the new forward baseline ───────
        post_reset_snap = [
            {"oc_id": oc["id"], "rank": oc["current_rank"], "points": oc["total_points"]}
            for oc in data["ocs"].values()
            if not oc.get("eliminated", False)
        ]
        data["rank_snapshots"].append({
            "timestamp": now().isoformat(),
            "trigger":   SNAP_TRIGGER_RESETALL,
            "rankings":  post_reset_snap
        })

        save_data(data, reason="points_reset_all", actor=interaction.user)

        await interaction.response.edit_message(
            embed=get_embed(
                "✅ All Points Reset",
                f"Points for **{len(active_ocs)} Trainee(s)** have been set to zero.\n"
                f"Pre-reset rankings were snapshotted for historical reference.\n"
                f"A new ranking baseline has been anchored.\n"
                f"All future rank change indicators (▲/▼) will now compare against these post-reset standings.",
                "success"
            ),
            view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        await interaction.response.edit_message(
            embed=get_embed("Cancelled", "No worries — the reset was cancelled. Everything stays the same. ✌️", "system"),
            view=self
        )

    async def on_timeout(self):
        await self._disable_all()

class ConfirmPurgeView(discord.ui.View):
    """Two-button ephemeral confirmation for the /purgedata command."""

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

    @discord.ui.button(label="⚠️ YES, WIPE EVERYTHING", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        # Perform atomic reset: overwrite data.json with DEFAULT_SCHEMA
        save_data(copy.deepcopy(DEFAULT_SCHEMA), reason="data_purged", actor=interaction.user)
        await interaction.response.edit_message(
            embed=get_embed(
                "🗑️ All Data Wiped",
                "The data file has been reset to factory defaults. All OCs, votes, points, dorms, "
                "feeds, mission groups, grades, and configuration have been permanently deleted.\n\n"
                "Run **/setup** to reconfigure the bot.",
                "error"
            ),
            view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        await interaction.response.edit_message(
            embed=get_embed("Cancelled", "Phew! The wipe was cancelled. Nothing was changed. ✌️", "system"),
            view=self
        )

    async def on_timeout(self):
        await self._disable_all()

class ConfirmDeleteOCView(discord.ui.View):
    """Two-button ephemeral confirmation for the /deleteoc command."""

    def __init__(self, oc_id: str, oc_name: str, came_from_archive: bool, actor: discord.Member):
        super().__init__(timeout=45)
        self.oc_id = oc_id
        self.oc_name = oc_name
        self.came_from_archive = came_from_archive
        self.actor = actor
        self.message: discord.Message = None

    async def _disable_all(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

    @discord.ui.button(label="🗑️ Yes, Delete Permanently", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        data = load_data()
        
        oc = data["ocs"].get(self.oc_id) or data["archived_ocs"].get(self.oc_id)
        if not oc:
            return await interaction.response.edit_message(embed=get_embed("Error", "OC not found in data anymore.", "error"), view=self)

        purged_summary = []
        
        # 1 & 2: Active or Archived OCs
        if self.oc_id in data["ocs"]:
            del data["ocs"][self.oc_id]
            purged_summary.append("Removed from active OCs")
        if self.oc_id in data["archived_ocs"]:
            del data["archived_ocs"][self.oc_id]
            purged_summary.append("Removed from archived OCs")
            
        # 3: Feeds
        if self.oc_id in data.get("feeds", {}):
            del data["feeds"][self.oc_id]
            purged_summary.append("Removed feed list")
            
        # 4: Vote tallies
        for oc_id_key, voters in list(data["voting"].get("votes", {}).items()):
            if oc_id_key == self.oc_id:
                del data["voting"]["votes"][oc_id_key]
                purged_summary.append("Removed from vote tallies")
                
        # 5: User votes
        removed_user_votes = False
        for uid, user_votes_list in data["voting"].get("user_votes", {}).items():
            if self.oc_id in user_votes_list:
                data["voting"]["user_votes"][uid] = [x for x in user_votes_list if x != self.oc_id]
                removed_user_votes = True
        if removed_user_votes:
            purged_summary.append("Removed from user vote history")
                
        # 6: Dorm occupants
        for f_name, f_data in data.get("dorms", {}).items():
            for r_name, r_data in f_data.get("rooms", {}).items():
                if self.oc_id in r_data.get("occupants", []):
                    try:
                        r_data["occupants"].remove(self.oc_id)
                        purged_summary.append(f"Removed from dorm {f_name} / Room {r_name}")
                    except ValueError:
                        pass
                        
        # 7: Mission groups
        for mg in data.get("mission_groups", {}).values():
            if self.oc_id in mg.get("members", []):
                mg["members"].remove(self.oc_id)
                purged_summary.append(f"Removed from mission group: {mg['name']}")
                
        # 8: Peer ranking sessions
        removed_from_peer = False
        for sess in data.get("peer_ranking_sessions", {}).values():
            for uid, ballot in sess.get("ballots", {}).items():
                if self.oc_id in ballot:
                    sess["ballots"][uid] = [x for x in ballot if x != self.oc_id]
                    removed_from_peer = True
            if sess.get("benefit_applied_to") == self.oc_id:
                sess["benefit_applied_to"] = None
                removed_from_peer = True
            if sess.get("penalty_applied_to") == self.oc_id:
                sess["penalty_applied_to"] = None
                removed_from_peer = True
        if removed_from_peer:
            purged_summary.append("Removed from peer ranking sessions")
                
        # 9: Point log
        original_log_len = len(data.get("point_log", []))
        data["point_log"] = [entry for entry in data.get("point_log", []) if entry.get("oc_id") != self.oc_id]
        if len(data["point_log"]) < original_log_len:
            purged_summary.append(f"Removed {original_log_len - len(data['point_log'])} point log entries")
            
        # 10: Rank snapshots
        removed_from_snaps = False
        for snap in data.get("rank_snapshots", []):
            original_snap_len = len(snap.get("rankings", []))
            snap["rankings"] = [r for r in snap.get("rankings", []) if r.get("oc_id") != self.oc_id]
            if len(snap["rankings"]) < original_snap_len:
                removed_from_snaps = True
        if removed_from_snaps:
            purged_summary.append("Removed from rank snapshots")
            
        # Cleanup Role
        if interaction.guild:
            await sync_grade_role_for_owner(
                interaction.guild,
                oc["owner_id"],
                new_grade_label=None,
                old_grade_label=oc.get("grade"),
                data=data
            )
            
        if not self.came_from_archive:
            recalculate_ranks(data)
            
        save_data(data, reason=f"OC hard-deleted: {self.oc_name}", actor=self.actor)
        
        desc = "\n".join(f"• {line}" for line in purged_summary)
        await interaction.response.edit_message(
            embed=get_embed("🗑️ OC Hard-Deleted", f"Successfully and permanently deleted **{self.oc_name}**.\n\n**Cleanup Summary:**\n{desc}", "success"), 
            view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        await interaction.response.edit_message(
            embed=get_embed("Cancelled", "Hard-delete aborted. The OC was not modified.", "system"), 
            view=self
        )
    
    async def on_timeout(self):
        await self._disable_all()

class ConfirmRemoveOCView(discord.ui.View):
    def __init__(self, oc_id: str, oc_name: str, actor: discord.Member):
        super().__init__(timeout=45)
        self.oc_id = oc_id
        self.oc_name = oc_name
        self.actor = actor
        self.message: discord.Message = None

    async def _disable_all(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

    @discord.ui.button(label="🗑️ Yes, Archive", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        data = load_data()
        
        oc = data["ocs"].get(self.oc_id)
        if not oc:
            return await interaction.response.edit_message(embed=get_embed("Error", "OC not found in active roster.", "error"), view=self)
        if oc["owner_id"] != str(interaction.user.id):
            return await interaction.response.edit_message(embed=get_embed("Permission Denied", "You don't own this OC.", "error"), view=self)
            
        if oc.get("dorm_floor") and oc.get("dorm_room"):
            try:
                data["dorms"][oc["dorm_floor"]]["rooms"][oc["dorm_room"]]["occupants"].remove(oc["id"])
            except ValueError:
                pass
        
        data["archived_ocs"][oc["id"]] = oc
        del data["ocs"][oc["id"]]
        recalculate_ranks(data)
        
        if interaction.guild:
            await sync_grade_role_for_owner(
                interaction.guild,
                oc["owner_id"],
                new_grade_label=None,
                old_grade_label=oc.get("grade"),
                data=data
            )
            
        save_data(data, reason=f"OC archived: {self.oc_name}", actor=self.actor)
        
        await interaction.response.edit_message(
            embed=get_embed("OC Archived", f"**{self.oc_name}** has been archived and removed from the active roster. Take care! 👋", "success"),
            view=self
        )

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all()
        await interaction.response.edit_message(
            embed=get_embed("Cancelled", "Archive cancelled. The OC was not modified.", "system"), 
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

        await interaction.response.send_message(embed=get_embed("Comment Posted", "💬 Your comment is posted! Head to the thread to continue the conversation.", "success"), ephemeral=True)

async def _run_sequential_reveal(channel: discord.TextChannel, ocs_ordered: list, reveal_color: int, page_size: int, data: dict, show_debut_line: bool = True, hide_points: bool = False):
    pages = []
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
            pts_str = "— pts" if hide_points else f"{oc['total_points']:,} pts"
            field_val = f"**{oc['name']}** · {pts_str}\n<@{oc['owner_id']}> · {change}"
            
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
        intents.members = True
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

        await self.tree.sync()
        print("Commands synced. Deferring data hydration until bot is fully ready.")

    async def on_ready(self):
        global DB_LOADED
        print(f"Logged in as {self.user} (ID: {self.user.id}). Running startup sequence...")

        if not DB_LOADED:
            for guild in self.guilds:
                ch = discord.utils.get(guild.text_channels, name="bot-db-backup")
                if not ch:
                    try:
                        cat = discord.utils.get(guild.categories, name="Special")
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(view_channel=False),
                            guild.me: discord.PermissionOverwrite(
                                view_channel=True, send_messages=True,
                                attach_files=True, read_message_history=True,
                                manage_messages=True
                            )
                        }
                        ch = await guild.create_text_channel(
                            "bot-db-backup",
                            category=cat,
                            overwrites=overwrites,
                            topic="automated db backup storage.",
                            slowmode_delay=21600
                        )
                        print(f"on_ready: auto-created #bot-db-backup in '{guild.name}'.")
                    except Exception as e:
                        print(f"on_ready: could not create #bot-db-backup in '{guild.name}': {type(e).__name__}: {e}")

                if ch:
                    try:
                        async for message in ch.history(limit=20):
                            if message.author == self.user and message.attachments:
                                att = message.attachments[0]
                                if att.filename.endswith(".json"):
                                    try:
                                        file_bytes = await att.read()
                                        parsed = json.loads(file_bytes)
                                        if not isinstance(parsed, dict):
                                            print("on_ready: backup failed structural validation, skipping restore.")
                                            break
                                        migrate_schema(parsed)
                                        with open(TEMP_FILE, "w", encoding="utf-8") as f:
                                            json.dump(parsed, f, indent=4)
                                        os.replace(TEMP_FILE, DATA_FILE)
                                        oc_count = len(parsed.get("ocs", {}))
                                        print(f"on_ready: hydration successful — {oc_count} OC(s) restored from #bot-db-backup.")
                                        break
                                    except (json.JSONDecodeError, ValueError) as e:
                                        print(f"on_ready: backup attachment is corrupt, skipping restore: {e}")
                                        break
                    except Exception as e:
                        print(f"on_ready: error reading #bot-db-backup history: {type(e).__name__}: {e}")

            DB_LOADED = True

        # Register persistent views for all known feed posts
        hydrated_data = load_data()
        for feed_list in hydrated_data.get("feeds", {}).values():
            for post in feed_list:
                self.add_view(FeedPostView(post["post_id"]))

        # Auto-resolve config (guild roles/channels)
        changed = False
        for guild in self.guilds:
            if await auto_resolve_config(guild, hydrated_data):
                changed = True
        if changed:
            save_data(hydrated_data, reason="auto_resolve_startup", actor=None)

        # Start background tasks
        if not voting_scheduler.is_running():
            voting_scheduler.start()
        if not asset_revalidation_task.is_running():
            asset_revalidation_task.start()
        if not auto_backup_db.is_running():
            auto_backup_db.start()

        oc_count = len(hydrated_data.get("ocs", {}))
        post_count = sum(len(v) for v in hydrated_data.get("feeds", {}).values())
        print(f"Startup complete. Loaded {oc_count} OC(s), {post_count} feed post(s).")

bot = SurvivalBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        embed = get_embed("Access Denied", "🔒 This command is for staff only! If you think you should have access, reach out to a Dev.", "error")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = get_embed("System Error", f"Oops! Something went wrong on our end. Here's the error detail in case you need it: {str(error)}", "error")
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
    @app_commands.describe(
        timezone="Your server's IANA timezone name, e.g. 'Asia/Seoul' or 'America/New_York'. Used for all timestamps.",
        announce_channel="The text channel where voting results, eliminations, and announcements will be posted.",
        force="Force a full re-setup even if already configured."
    )
    @app_commands.choices(timezone=TIMEZONE_CHOICES)
    @is_dev()
    async def setup(self, interaction: discord.Interaction, timezone: app_commands.Choice[str], announce_channel: discord.TextChannel, force: bool = False):
        data = load_data()
        await auto_resolve_config(interaction.guild, data)
        
        already_configured = (
            data["config"].get("announcement_channel_id") is not None
            and data["config"].get("timezone") not in (None, "UTC", "")
            and data["config"].get("dev_role_id") is not None
        )

        if already_configured and not force:
            current_tz    = data["config"].get("timezone")
            current_ann   = data["config"].get("announcement_channel_id")
            ann_str       = f"<#{current_ann}>" if current_ann else "Not set"
            asset_str     = f"<#{data['config'].get('asset_channel')}>" if data["config"].get("asset_channel") else "Not set"
            data_str      = f"<#{data['config'].get('data_channel_id')}>" if data["config"].get("data_channel_id") else "Not set"

            return await interaction.response.send_message(
                embed=get_embed(
                    "⚙️ Already Configured",
                    f"This bot already has a prior configuration loaded from the data channel.\n\n"
                    f"**Current Timezone:** `{current_tz}`\n"
                    f"**Announce Channel:** {ann_str}\n"
                    f"**Asset Channel:** {asset_str}\n"
                    f"**Data Channel:** {data_str}\n\n"
                    f"To update individual values, use `/config set` or the dedicated `/set*` commands.\n"
                    f"To force a full re-setup and overwrite all values, re-run `/setup` with `force: True`.",
                    "warning"
                ),
                ephemeral=True
            )

        data["config"]["timezone"] = timezone.value
        data["config"]["announcement_channel_id"] = announce_channel.id
        data["config"]["setup_completed_at"] = now().isoformat()
        save_data(data, reason="setup_completed", actor=interaction.user)

        # --- Build per-channel resolution strings for the confirmation embed ---
        def _ch_str(ch_id) -> str:
            return f"<#{ch_id}>" if ch_id else "⚠️ Not detected — set manually with the appropriate `/set*` command"

        asset_str    = _ch_str(data["config"].get("asset_channel"))
        data_str     = _ch_str(data["config"].get("data_channel_id"))
        rankings_str = _ch_str(data["config"].get("rankings_channel_id"))
        dev_role_str = f"<@&{data['config']['dev_role_id']}>" if data["config"].get("dev_role_id") else "⚠️ Not detected — no Administrator role found"
        
        await interaction.response.send_message(
            embed=get_embed(
                "✅ Setup Complete",
                f"**Timezone:** {timezone.name} (`{timezone.value}`)\n"
                f"**Announce Channel:** {announce_channel.mention}\n"
                f"**Dev Role (Auto):** {dev_role_str}\n"
                f"**Asset Channel (Auto):** {asset_str}\n"
                f"**Data Channel (Auto):** {data_str}\n"
                f"**Rankings Channel (Auto):** {rankings_str}",
                "success"
            ),
            ephemeral=True
        )

    @app_commands.command(name="config_view", description="View configuration settings (Dev only)")
    @is_dev()
    async def config_view(self, interaction: discord.Interaction):
        data = load_data()
        cfg = data["config"]
        desc = "\n".join([f"**{k}**: {v}" for k, v in cfg.items()])
        await interaction.response.send_message(embed=get_embed("System Configuration", desc), ephemeral=True)

    @app_commands.command(name="setassetchannel", description="[DEV] Set the persistent asset storage channel")
    @app_commands.describe(channel="The text channel to designate for this purpose.")
    @is_dev()
    async def set_asset_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        if await auto_resolve_config(interaction.guild, data):
            pass
        data["config"]["asset_channel"] = channel.id
        save_data(data, reason="set asset channel", actor=interaction.user)
        await interaction.response.send_message(embed=get_embed("Success", f"Asset channel updated to {channel.mention}", "success"), ephemeral=True)

    @app_commands.command(name="setfeedchannel", description="[DEV] Set the public OC feed channel")
    @app_commands.describe(channel="The text channel to designate for this purpose.")
    @is_dev()
    async def set_feed_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        data["config"]["feed_channel"] = channel.id
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Feed channel set to {channel.mention}.", "success"), ephemeral=True)

    @app_commands.command(name="setbackupchannel", description="[DEV] Set the designated channel for JSON backups.")
    @app_commands.describe(channel="The text channel to designate for this purpose.")
    @is_dev()
    async def set_backup_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        data["config"]["backup_channel_id"] = channel.id
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Backup channel updated to {channel.mention}", "success"), ephemeral=True)

    @app_commands.command(name="setdatachannel", description="[DEV] Set the channel that receives automatic data-change notifications.")
    @app_commands.describe(channel="The text channel to designate for this purpose.")
    @is_dev()
    async def set_data_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        if await auto_resolve_config(interaction.guild, data):
            pass
        data["config"]["data_channel_id"] = channel.id
        save_data(data, reason="set data channel", actor=interaction.user)
        await interaction.response.send_message(embed=get_embed("Success", f"Data channel updated to {channel.mention}", "success"), ephemeral=True)

    @app_commands.command(name="setrankingschannel", description="[DEV] Set the channel where the live rankings leaderboard is automatically posted.")
    @app_commands.describe(channel="The text channel to designate for live rankings posts.")
    @is_dev()
    async def set_rankings_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        if await auto_resolve_config(interaction.guild, data):
            pass  # keep auto-resolve side-effects
        data["config"]["rankings_channel_id"] = channel.id
        save_data(data, reason="set rankings channel", actor=interaction.user)
        await interaction.response.send_message(
            embed=get_embed(
                "Success",
                f"Rankings channel updated to {channel.mention}. The live leaderboard will be posted there automatically after every voting round closes.",
                "success"
            ),
            ephemeral=True
        )

    @app_commands.command(name="backup", description="[DEV] Export the full data.json to the backup channel")
    @is_dev()
    async def backup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        backup_channel_id = data["config"].get("backup_channel_id")
        backup_ch = None
        
        if backup_channel_id:
            backup_ch = self.bot.get_channel(int(backup_channel_id))
            
        if backup_ch is None:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            }
            dev_role_id = data["config"].get("dev_role_id")
            if dev_role_id:
                dev_role = interaction.guild.get_role(int(dev_role_id))
                if dev_role:
                    overwrites[dev_role] = discord.PermissionOverwrite(read_messages=True)

            backup_ch = await interaction.guild.create_text_channel(
                name="data-backups",
                overwrites=overwrites,
                reason="Auto-created by bot for JSON data backups"
            )
            data["config"]["backup_channel_id"] = backup_ch.id
            save_data(data)
            await interaction.followup.send(f"Backup channel was missing and has been auto-created: {backup_ch.mention}", ephemeral=True)

        json_data = json.dumps(data, indent=4, ensure_ascii=False).encode('utf-8')
        file = discord.File(fp=io.BytesIO(json_data), filename=f"backup_{now().strftime('%Y-%m-%d_%H-%M-%S')}.json")
        
        embed = get_embed(
            "📦 Data Backup",
            f"Backup generated on {now().strftime('%Y-%m-%d %H:%M:%S')} by {interaction.user.display_name}.",
            "success"
        )
        
        await backup_ch.send(embed=embed, file=file)
        await interaction.followup.send(f"Backup successfully posted to {backup_ch.mention}.", ephemeral=True)

    @app_commands.command(name="setrevealpage", description="[DEV] Set how many trainees are shown per reveal page")
    @app_commands.describe(size="Number of Trainees shown per reveal page. Must be between 1 and 25.")
    @is_dev()
    async def set_reveal_page(self, interaction: discord.Interaction, size: int):
        if size < 1 or size > 25:
            return await interaction.response.send_message(embed=get_embed("Error", "Page size must be between 1 and 25.", "error"), ephemeral=True)
        data = load_data()
        data["config"]["reveal_page_size"] = size
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"Reveal page size set to {size}.", "success"), ephemeral=True)

    @config_group.command(name="setdebutslots", description="[DEPRECATED] This command has been phased out.")
    @app_commands.describe(
        slots="(Deprecated — no longer used)",
        public="(Deprecated — no longer used)"
    )
    @is_dev()
    async def setdebutslots(self, interaction: discord.Interaction, slots: int = 0, public: bool = True):
        await interaction.response.send_message(
            embed=get_embed(
                "⚠️ Command Deprecated",
                "`/config setdebutslots` has been phased out and no longer modifies any data.\n\n"
                "Debut slot configuration is now managed directly in the data file or through future tooling.\n"
                "The existing `debut_slots` value in config remains unchanged.",
                "warning"
            ),
            ephemeral=True
        )

    @config_group.command(name="votingmultiplier", description="[DEV] Set the vote-to-points multiplier")
    @app_commands.describe(value="The multiplier applied to votes when closing a voting round. E.g. 2 means each vote is worth 2 points.")
    @is_dev()
    async def votingmultiplier(self, interaction: discord.Interaction, value: int):
        data = load_data()
        data["voting"]["multiplier"] = value
        save_data(data, reason="config_multiplier_updated", actor=interaction.user)
        await interaction.response.send_message(embed=get_embed("Success", f"Voting multiplier set to {value}.", "success"), ephemeral=True)

    @config_group.command(name="votingcap", description="[DEV] Set max votes per user **per day** (resets 12:00 AM KST). 0 = unlimited.")
    @app_commands.describe(cap="Maximum votes per user per day. Set to 0 to allow unlimited votes.")
    @is_dev()
    async def votingcap(self, interaction: discord.Interaction, cap: int):
        data = load_data()
        data["voting"]["cap"] = cap
        save_data(data, reason="config_votingcap_updated", actor=interaction.user)
        await interaction.response.send_message(embed=get_embed("Success", f"Voting cap set to {cap}.", "success"), ephemeral=True)

    # Whitelist of config keys that are safe to edit via /config set.
    # Maps key name → (type_converter, description, valid_range_hint)
    _CONFIG_SET_WHITELIST = {
        "oc_cap":                (int,   "Max OCs per user",                         "integer ≥ 1"),
        "allow_negative_points": (bool,  "Allow OC points to go below 0",            "true / false"),
        "allow_multi_vote":      (bool,  "Allow multiple votes on one OC per round",  "true / false"),
        "reveal_color":          (str,   "Hex colour for the ranking reveal embed",   "#RRGGBB"),
        "reveal_page_size":      (int,   "Trainees shown per reveal page (1–25)",     "integer 1–25"),
        "peer_ranking_enabled":  (bool,  "Enable / disable the peer ranking system",  "true / false"),
        "peer_ranking_transparent": (bool, "Post peer ranking results publicly",      "true / false"),
        "default_multiplier":    (int,   "Default vote multiplier",                   "integer ≥ 1"),
    }

    @config_group.command(name="set", description="[DEV] Update a specific config key.")
    @app_commands.describe(
        key="The config key to change. See /config_view for all keys.",
        value="The new value as a string. Booleans: 'true'/'false'. Colours: '#RRGGBB'."
    )
    @is_dev()
    async def config_set(self, interaction: discord.Interaction, key: str, value: str):
        if key not in self._CONFIG_SET_WHITELIST:
            allowed = "\n".join(
                f"• `{k}` — {desc} ({hint})"
                for k, (_, desc, hint) in self._CONFIG_SET_WHITELIST.items()
            )
            return await interaction.response.send_message(
                embed=get_embed(
                    "Invalid Key",
                    f"**`{key}`** is not an editable config key.\n\n**Editable keys:**\n{allowed}",
                    "error"
                ),
                ephemeral=True
            )

        converter, desc, hint = self._CONFIG_SET_WHITELIST[key]
        converted = None
        try:
            if converter is bool:
                if value.lower() in ("true", "1", "yes"):
                    converted = True
                elif value.lower() in ("false", "0", "no"):
                    converted = False
                else:
                    raise ValueError("not a boolean")
            elif converter is int:
                converted = int(value)
            elif converter is str:
                converted = value

            # Domain validation
            if key == "oc_cap" and converted < 1:
                raise ValueError("oc_cap must be ≥ 1")
            if key == "reveal_page_size" and not (1 <= converted <= 25):
                raise ValueError("reveal_page_size must be 1–25")
            if key == "reveal_color":
                if not (converted.startswith("#") and len(converted) == 7):
                    raise ValueError("must be #RRGGBB format")
            if key == "default_multiplier" and converted < 1:
                raise ValueError("default_multiplier must be ≥ 1")

        except ValueError as e:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Invalid Value",
                    f"Could not set `{key}` to `{value}`.\n**Expected**: {hint}\n**Error**: {e}",
                    "error"
                ),
                ephemeral=True
            )

        data = load_data()
        old_value = data["config"].get(key)
        data["config"][key] = converted
        save_data(data, reason=f"config_set: {key} = {converted}", actor=interaction.user)

        await interaction.response.send_message(
            embed=get_embed(
                "Config Updated",
                f"**`{key}`** ({desc})\n`{old_value}` → `{converted}`",
                "success"
            ),
            ephemeral=True
        )

    @app_commands.command(name="purgedata", description="[DEV] ⚠️ Permanently wipe ALL bot data and reset to defaults")
    @is_dev()
    async def purgedata(self, interaction: discord.Interaction):
        view = ConfirmPurgeView()
        msg = await interaction.response.send_message(
            embed=get_embed(
                "⚠️ CONFIRM FULL DATA WIPE",
                "**This will permanently and irreversibly delete:**\n"
                "• All registered and archived Trainees (OCs)\n"
                "• All votes, points, and ranking history\n"
                "• All dorm floors and room assignments\n"
                "• All mission groups and peer ranking sessions\n"
                "• All feed posts and grade tiers\n"
                "• All bot configuration (timezone, channels, roles)\n\n"
                "**This cannot be undone.** Are you absolutely sure?",
                "warning"
            ),
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()

class RegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register", description="Register a new Trainee OC")
    @app_commands.describe(
        name="Your Trainee OC's full name. Must be unique among your own OCs.",
        birthday_yyyy_mm_dd="Date of birth in YYYY-MM-DD format (displayed as YYYY/MM/DD), e.g. 2003-07-14.",
        gender="Your OC's gender identity, e.g. Female, Male, Non-binary.",
        pronouns="Your OC's pronouns, e.g. she/her, he/him, they/them.",
        faceclaim="The real person or character used as the OC's visual reference.",
        main_skill="Your OC's primary performance skill, e.g. Vocal, Dance, Rap.",
        nationality="Your OC's country of origin or citizenship.",
        form_link="(Optional) A link to your OC's full character sheet or application form.",
        ethnicity="(Optional) Your OC's ethnic background. Defaults to 'Unknown' if omitted.",
        profile_picture="(Optional) Upload a PNG/JPG/GIF image to use as the OC's profile picture."
    )
    async def register(self, interaction: discord.Interaction, name: str, birthday_yyyy_mm_dd: str, gender: str, pronouns: str, faceclaim: str, main_skill: str, nationality: str, form_link: str = None, ethnicity: str = "Unknown", profile_picture: discord.Attachment = None):
        data = load_data()
        if await auto_resolve_config(interaction.guild, data):
            save_data(data, reason="auto_resolve_register", actor=interaction.user)

        user_id = str(interaction.user.id)
        current_ocs = len([oc for oc in data["ocs"].values() if oc["owner_id"] == user_id])
        if current_ocs >= data["config"]["oc_cap"]:
            return await interaction.response.send_message(embed=get_embed("Limit Reached", f"⛔ Looks like you've already got {data['config']['oc_cap']} Trainees — that's the maximum allowed right now! Feel free to reach out to a staff member if you have questions.", "error"), ephemeral=True)
        
        for oc in data["ocs"].values():
            if oc["owner_id"] == user_id and oc["name"].lower() == name.lower():
                return await interaction.response.send_message(embed=get_embed("Duplicate Name", f"⛔ You've already got a Trainee named **{name}**! Each of your OCs needs a unique name — try a different one.", "error"), ephemeral=True)

        if profile_picture:
            if not profile_picture.content_type or not profile_picture.content_type.startswith("image/"):
                return await interaction.response.send_message(embed=get_embed("Invalid File", "Hmm, that file type isn't supported. Please attach an image (PNG, JPG, GIF, WEBP)!", "error"), ephemeral=True)

        await interaction.response.defer()

        oc_id = str(uuid.uuid4())
        profile_picture_url = None
        if profile_picture:
            profile_picture_url = await upload_to_asset_channel(self.bot, name, oc_id, profile_picture.url)

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
        save_data(data, reason="oc_registered", actor=interaction.user)
        
        embed = self._build_profile_embed(new_oc, data)
        await interaction.followup.send(content="🎉 Welcome to the show! Your Trainee has been registered. Here's their profile:", embed=embed)

    @app_commands.command(name="profile", description="View a Trainee's profile")
    @app_commands.describe(oc_name="The exact name of the Trainee OC to look up.")
    async def profile(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"We looked everywhere but couldn't find a Trainee named '{oc_name}'.", "error"), ephemeral=True)
        await interaction.response.send_message(embed=self._build_profile_embed(oc, data))

    @app_commands.command(name="removeoc", description="Permanently archive one of your own Trainees. Requires confirmation.")
    @app_commands.describe(oc_name="The name of your Trainee OC to permanently archive. This action cannot be undone.")
    async def removeoc(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc or oc["owner_id"] != str(interaction.user.id):
            return await interaction.response.send_message(embed=get_embed("Error", "Hmm, we couldn't find that Trainee in your roster. Double-check the name and try again!", "error"), ephemeral=True)
        
        view = ConfirmRemoveOCView(oc["id"], oc["name"], interaction.user)
        embed = get_embed(
            "⚠️ Confirm Archive",
            f"You are about to permanently archive **{oc['name']}**. They will be removed from the active roster, dorms, and rankings.\n\nThis **cannot be undone**. Click Confirm to proceed.",
            "warning"
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="editoc", description="Edit any field on one of your own Trainees.")
    @app_commands.describe(
        oc_name="The exact name of the Trainee OC to edit.",
        name="New name.",
        birthday_yyyy_mm_dd="New date of birth (YYYY-MM-DD).",
        gender="New gender identity.",
        pronouns="New pronouns.",
        faceclaim="New faceclaim.",
        main_skill="New main skill.",
        nationality="New nationality.",
        ethnicity="New ethnicity.",
        form_link="New profile/form link.",
        profile_picture="New profile picture."
    )
    async def editoc(self, interaction: discord.Interaction, oc_name: str, name: str = None, birthday_yyyy_mm_dd: str = None, gender: str = None, pronouns: str = None, faceclaim: str = None, main_skill: str = None, nationality: str = None, ethnicity: str = None, form_link: str = None, profile_picture: discord.Attachment = None):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", "Hmm, we couldn't find that Trainee in your roster. Double-check the name and try again!", "error"), ephemeral=True)
        if oc["owner_id"] != str(interaction.user.id):
            return await interaction.response.send_message(embed=get_embed("Permission Denied", "🔒 You can only edit your own Trainees!", "error"), ephemeral=True)
        
        if birthday_yyyy_mm_dd is not None:
            try:
                datetime.strptime(birthday_yyyy_mm_dd, "%Y-%m-%d")
            except ValueError:
                return await interaction.response.send_message(embed=get_embed("Invalid Date", "Birthday must be in YYYY-MM-DD format (e.g., 2003-07-14).", "error"), ephemeral=True)
                
        if name is not None and name.lower() != oc["name"].lower():
            for other_oc in data["ocs"].values():
                if other_oc["owner_id"] == str(interaction.user.id) and other_oc["id"] != oc["id"] and other_oc["name"].lower() == name.lower():
                    return await interaction.response.send_message(embed=get_embed("Duplicate Name", f"⛔ You've already got a Trainee named **{name}**! Each of your OCs needs a unique name.", "error"), ephemeral=True)

        if profile_picture is not None:
            if not profile_picture.content_type or not profile_picture.content_type.startswith("image/"):
                return await interaction.response.send_message(embed=get_embed("Invalid File", "Hmm, that file type isn't supported. Please attach an image (PNG, JPG, GIF, WEBP)!", "error"), ephemeral=True)
        
        await interaction.response.defer()
        
        if profile_picture is not None:
            new_url = await upload_to_asset_channel(self.bot, name or oc["name"], oc["id"], profile_picture.url)
            if new_url:
                oc["profile_picture_url"] = new_url

        if name is not None: oc["name"] = name
        if birthday_yyyy_mm_dd is not None: oc["birthday"] = birthday_yyyy_mm_dd
        if gender is not None: oc["gender"] = gender
        if pronouns is not None: oc["pronouns"] = pronouns
        if faceclaim is not None: oc["faceclaim"] = faceclaim
        if main_skill is not None: oc["main_skill"] = main_skill
        if nationality is not None: oc["nationality"] = nationality
        if ethnicity is not None: oc["ethnicity"] = ethnicity
        if form_link is not None: oc["form_link"] = form_link
        
        save_data(data, reason="oc_edited", actor=interaction.user)
        embed = self._build_profile_embed(oc, data)
        await interaction.followup.send(content="✅ Trainee profile updated!", embed=embed)

    @app_commands.command(name="deleteoc", description="[DEV] Permanently and irreversibly delete an OC from all data")
    @app_commands.describe(oc_name="The name of the OC to permanently purge. Searches active and archived OCs.")
    @is_dev()
    async def deleteoc(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        came_from_archive = False
        
        if not oc:
            name_lower = oc_name.lower()
            for a_oc in data["archived_ocs"].values():
                if a_oc["name"].lower() == name_lower:
                    oc = a_oc
                    came_from_archive = True
                    break
                    
        if not oc:
            return await interaction.response.send_message(
                embed=get_embed("Not Found", f"Could not find an active or archived OC named '{oc_name}'.", "error"), 
                ephemeral=True
            )
            
        status = "Archived" if came_from_archive else ("Eliminated" if oc.get("eliminated") else "Active")
        
        view = ConfirmDeleteOCView(oc["id"], oc["name"], came_from_archive, interaction.user)
        embed = get_embed(
            "⚠️ Confirm Hard-Delete",
            f"**OC:** {oc['name']}\n**Owner:** <@{oc['owner_id']}>\n**Status:** {status}\n\n**This cannot be undone. The OC will be erased from all collections.**",
            "error"
        )
        msg = await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="oc_all", description="Browse all currently registered Trainees")
    async def oc_all(self, interaction: discord.Interaction):
        data = load_data()
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        if not active_ocs:
            return await interaction.response.send_message(embed=get_embed("Empty", "The stage is empty! No Trainees have been registered yet.", "warning"))
            
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
                    f"**Birthday / Age**: {format_date_display(oc['birthday'])} · {age} yrs (KST / GMT+9)\n"
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
            return await interaction.response.send_message(embed=get_embed("None", "Nobody's been eliminated yet — everyone's still in the running! 🌟", "system"))
            
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
    @app_commands.describe(
        mode="Choose 'By Name' to eliminate a specific OC, or 'By Rank Range' to eliminate a range of rankings.",
        value="For 'By Name': the OC's exact name. For 'By Rank Range': a number (e.g. 8) or a range (e.g. 8-10)."
    )
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
                return await interaction.response.send_message(embed=get_embed("Error", f"We looked everywhere but couldn't find an active Trainee named '{value}'.", "error"), ephemeral=True)
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
        save_data(data, reason="ocs_eliminated", actor=interaction.user)
        
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
        kst_label = "KST (GMT+9)"
        embed.add_field(name="Birthday / Age", value=f"{format_date_display(oc['birthday'])} · {age} yrs ({kst_label})", inline=True)
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

    @app_commands.command(
        name="config_multivote",
        description="[DEV] Toggle whether a single user may vote for the same OC multiple times per round."
    )
    @app_commands.describe(
        enabled="True = allow repeat votes on one OC per round. False = enforce one vote per OC per user per round (default)."
    )
    @is_dev()
    async def config_multivote(self, interaction: discord.Interaction, enabled: bool):
        data = load_data()
        data["config"]["allow_multi_vote"] = enabled
        save_data(data, reason=f"allow_multi_vote set to {enabled}", actor=interaction.user)

        state_str  = "✅ **Enabled**"  if enabled else "❌ **Disabled**"
        policy_str = (
            "Users may now vote for the same Trainee more than once within the same voting round. "
            "Each repeated vote still counts toward (and is deducted from) the voter's daily vote cap."
            if enabled else
            "Standard policy restored — each user may vote for a given Trainee only once per round."
        )
        await interaction.response.send_message(
            embed=get_embed(
                "Multi-Vote Policy Updated",
                f"**Multi-Vote:** {state_str}\n\n{policy_str}",
                "success" if enabled else "warning"
            ),
            ephemeral=True
        )

    @app_commands.command(name="vote", description="Cast vote(s) for one or more Trainees (comma-separated names)")
    @app_commands.describe(oc_names="One or more Trainee names separated by commas. Example: Mira, Juno, Haeun")
    async def vote(self, interaction: discord.Interaction, oc_names: str):
        data = load_data()

        # Guard: voting must be open
        if not data["voting"]["is_open"]:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Voting Closed",
                    "Voting isn't open right now! Stay tuned for the next voting round. 🗳️",
                    "error"
                ),
                ephemeral=True
            )

        user_id = str(interaction.user.id)
        cap = data["voting"]["cap"]  # 0 = unlimited

        _reset_daily_votes_if_needed(data)

        daily_counts = data["voting"]["daily_vote_counts"]
        votes_today = daily_counts.get(user_id, 0)

        # Remaining daily quota (None = unlimited)
        remaining = (cap - votes_today) if cap > 0 else None

        if remaining is not None and remaining <= 0:
            return await interaction.response.send_message(
                embed=get_embed(
                    "Daily Cap Reached",
                    f"You've used all **{cap}** of your votes for today! "
                    f"Your votes reset at **12:00 AM KST**. Come back then! 🗓️",
                    "error"
                ),
                ephemeral=True
            )

        raw_names = [n.strip() for n in oc_names.split(",") if n.strip()]

        if not raw_names:
            return await interaction.response.send_message(
                embed=get_embed("No Input", "Please provide at least one Trainee name to vote for!", "error"),
                ephemeral=True
            )

        accepted  = []   # list of OC name strings that were successfully voted for
        rejected  = []   # list of (name_token, reason_string) tuples

        for token in raw_names:
            if remaining is not None and remaining <= 0:
                rejected.append((token, f"Vote cap of **{cap}** reached mid-batch"))
                continue

            oc = find_oc(token, data)
            if not oc:
                rejected.append((token, "Hmm, we couldn't find a Trainee with that name. Check the spelling and try again!"))
                continue

            if oc.get("eliminated", False):
                rejected.append((token, f"**{oc['name']}** has been eliminated"))
                continue

            if oc["id"] not in data["voting"]["votes"]:
                data["voting"]["votes"][oc["id"]] = []

            # --- Duplicate vote guard (per-OC, per-round) ---
            # Bypassed when allow_multi_vote is True (dev toggle).
            allow_multi_vote = data["config"].get("allow_multi_vote", False)
            existing_voters  = data["voting"]["votes"].get(oc["id"], [])
            if not allow_multi_vote and user_id in existing_voters:
                rejected.append((
                    token,
                    f"You've already voted for **{oc['name']}** this round — each OC can only receive one vote per user per round. Your vote was not counted again."
                ))
                continue

            data["voting"]["votes"][oc["id"]].append(user_id)

            daily_counts[user_id] = daily_counts.get(user_id, 0) + 1
            accepted.append(oc["name"])
            if remaining is not None:
                remaining -= 1

        if accepted:
            save_data(data, reason="votes_cast", actor=interaction.user)

        votes_today_final = daily_counts.get(user_id, 0)
        quota_line = (
            f"**Today's Quota**: {votes_today_final}/{cap} vote(s) used today (resets 12:00 AM KST)."
            if cap > 0 else
            f"**Votes cast today** (no cap): {votes_today_final}"
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

    @app_commands.command(name="votingopen", description="[DEV] Open voting now or schedule it for a KST datetime (year/month/day hour/minute).")
    @app_commands.describe(
        year="(Optional) Year to open voting. If omitted, opens immediately.",
        month="(Optional) Month (1–12).",
        day="(Optional) Day (1–31).",
        hour="(Optional) Hour in 24-hour KST (0–23). Defaults to 0 if date is given.",
        minute="(Optional) Minute (0–59). Defaults to 0 if date is given."
    )
    @is_dev()
    async def votingopen(self, interaction: discord.Interaction, year: int = None, month: int = None, day: int = None, hour: int = 0, minute: int = 0):
        data = load_data()
        
        date_args = [year, month, day]
        if any(a is None for a in date_args) and not all(a is None for a in date_args):
            return await interaction.response.send_message(embed=get_embed("Error", "Provide all of year, month, and day together, or omit all to open immediately.", "error"), ephemeral=True)
            
        if all(a is None for a in date_args):
            data["voting"]["is_open"] = True
            data["voting"]["votes"] = {}
            data["voting"]["user_votes"] = {}
            data["voting"]["daily_vote_counts"] = {}
            data["voting"]["daily_vote_date"] = today_kst().isoformat()
            data["voting"]["start_time"] = now().isoformat()
            data["voting"]["scheduled_open_time"] = None
            save_data(data, reason="voting_opened", actor=interaction.user)
            await interaction.response.send_message(embed=get_embed("Voting Opened", "🗳️ Voting is now open! Members can start casting their votes.", "success"))
        else:
            try:
                target_dt = datetime(year, month, day, hour, minute, tzinfo=KST)
            except ValueError as e:
                return await interaction.response.send_message(embed=get_embed("Error", f"Invalid date/time: {e}", "error"), ephemeral=True)
                
            if target_dt <= datetime.now(KST):
                return await interaction.response.send_message(embed=get_embed("Warning", "That time is in the past. Provide a future time or omit parameters to open immediately.", "warning"), ephemeral=True)
                
            data["voting"]["scheduled_open_time"] = target_dt.isoformat()
            save_data(data, reason="voting_open_scheduled", actor=interaction.user)
            await interaction.response.send_message(embed=get_embed("Voting Scheduled", f"✅ Voting is scheduled to open on **{target_dt.strftime('%Y/%m/%d %H:%M KST')}**.", "success"), ephemeral=True)

    @app_commands.command(name="votingclose", description="[DEV] Close voting now or schedule it. Applies the multiplier and updates rankings.")
    @app_commands.describe(
        year="(Optional) Year to close voting. If omitted, closes immediately.",
        month="(Optional) Month (1–12).",
        day="(Optional) Day (1–31).",
        hour="(Optional) Hour in 24-hour KST (0–23). Defaults to 0 if date is given.",
        minute="(Optional) Minute (0–59). Defaults to 0 if date is given."
    )
    @is_dev()
    async def votingclose(self, interaction: discord.Interaction, year: int = None, month: int = None, day: int = None, hour: int = 0, minute: int = 0):
        data = load_data()
        
        date_args = [year, month, day]
        if any(a is None for a in date_args) and not all(a is None for a in date_args):
            return await interaction.response.send_message(embed=get_embed("Error", "Provide all of year, month, and day together, or omit all to close immediately.", "error"), ephemeral=True)
            
        if all(a is None for a in date_args):
            await interaction.response.defer()
            data["voting"]["is_open"] = False
            data["voting"]["last_closed_at"] = now().isoformat()
            data["voting"]["end_time"] = now().isoformat()
            data["voting"]["scheduled_close_time"] = None
            
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
            save_data(data, reason="voting_closed", actor=interaction.user)
            
            channel_id = data["config"]["announcement_channel_id"]
            if channel_id:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    embed = get_embed("Voting Closed", "✅ Voting has closed! Results have been tallied and rankings are updated.", "system", show_footer=True)
                    await channel.send(embed=embed)
            
            await interaction.followup.send(embed=get_embed("Success", "✅ Voting has closed! Results have been tallied and rankings are updated.", "success"))
            await _post_rankings_to_channel(self.bot, data)
        else:
            try:
                target_dt = datetime(year, month, day, hour, minute, tzinfo=KST)
            except ValueError as e:
                return await interaction.response.send_message(embed=get_embed("Error", f"Invalid date/time: {e}", "error"), ephemeral=True)
                
            if target_dt <= datetime.now(KST):
                return await interaction.response.send_message(embed=get_embed("Warning", "That time is in the past. Provide a future time or omit parameters to close immediately.", "warning"), ephemeral=True)
                
            if not data["voting"]["is_open"] and data["voting"].get("scheduled_open_time") is None:
                return await interaction.response.send_message(embed=get_embed("Warning", "Voting is not open and no open is scheduled. Schedule or open voting first.", "warning"), ephemeral=True)
                
            data["voting"]["scheduled_close_time"] = target_dt.isoformat()
            save_data(data, reason="voting_close_scheduled", actor=interaction.user)
            await interaction.response.send_message(embed=get_embed("Voting Scheduled", f"✅ Voting is scheduled to close on **{target_dt.strftime('%Y/%m/%d %H:%M KST')}**.", "success"), ephemeral=True)

    @app_commands.command(name="votingstatus", description="Check whether voting is currently open and see the current tally (if permitted).")
    async def votingstatus(self, interaction: discord.Interaction):
        data = load_data()
        is_open = data["voting"]["is_open"]
        cap = data["voting"]["cap"]
        
        status_parts = []
        if is_open:
            status_parts.append("✅ **Voting is currently OPEN.**")
        else:
            status_parts.append("❌ **Voting is currently CLOSED.**")
            
        sched_open = data["voting"].get("scheduled_open_time")
        sched_close = data["voting"].get("scheduled_close_time")

        if sched_open:
            dt = datetime.fromisoformat(sched_open)
            status_parts.append(f"📅 **Scheduled to Open:** {dt.strftime('%Y/%m/%d %H:%M KST')}")
        if sched_close:
            dt = datetime.fromisoformat(sched_close)
            status_parts.append(f"📅 **Scheduled to Close:** {dt.strftime('%Y/%m/%d %H:%M KST')}")

        if is_open:
            multi_vote_on = data["config"].get("allow_multi_vote", False)
            if multi_vote_on:
                status_parts.append("♾️ **Multi-Vote Mode:** Enabled — you may vote for the same Trainee more than once this round.")
            
        if is_open and cap > 0:
            user_id = str(interaction.user.id)
            _reset_daily_votes_if_needed(data)
            votes_today = data["voting"]["daily_vote_counts"].get(user_id, 0)
            remaining = cap - votes_today
            status_parts.append(
                f"\n🗳️ **Your Daily Votes:** {votes_today}/{cap} used "
                f"(~{remaining} remaining · resets 12:00 AM KST)"
            )
            
        await interaction.response.send_message(embed=get_embed("Voting Status", "\n".join(status_parts), "neutral"), ephemeral=True)

class PointsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="points", description="Manage a Trainee's points (Dev only)")
    @app_commands.describe(
        oc_name="The name of the Trainee to modify points for.",
        action="The operation to apply: Add, Deduct, Multiply, or Set.",
        value="The numeric value for the selected action. Must be a positive number."
    )
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
            return await interaction.response.send_message("We looked everywhere but couldn't find that Trainee.", ephemeral=True)
        
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
        save_data(data, reason=f"points_{action.value}_{oc_name}", actor=interaction.user)
        
        await interaction.response.send_message(
            embed=get_embed(
                "Points Updated",
                f"**{oc['name']}** · {action.value.capitalize()}: `{value:,}`\n"
                f"Points: `{points_before:,}` → `{oc['total_points']:,}`\n"
                f"New Rank: **#{oc['current_rank']}**",
                "success"
            ),
            ephemeral=True
        )

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
    @app_commands.describe(
        label="A short display name for the grade tier, e.g. 'A', 'S+', 'Rookie'.",
        hex_color="A hex color code for this grade's display color. Format: #RRGGBB, e.g. #FFD700."
    )
    @is_dev()
    async def grade_create(self, interaction: discord.Interaction, label: str, hex_color: str):
        if not hex_color.startswith("#") or len(hex_color) != 7:
            return await interaction.response.send_message(embed=get_embed("Error", "Invalid hex. Use #RRGGBB format.", "error"), ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        
        is_update = label in data["grades"]
        
        if is_update:
            data["grades"][label]["color"] = hex_color
        else:
            data["grades"][label] = {"color": hex_color, "role_id": None}
            
        if interaction.guild:
            await ensure_grade_role(interaction.guild, label, hex_color, data)
            
        if is_update and interaction.guild:
            owners = set(oc["owner_id"] for oc in data["ocs"].values() if oc.get("grade") == label and not oc.get("eliminated", False))
            for owner_id in owners:
                await sync_grade_role_for_owner(interaction.guild, owner_id, label, label, data)
                
        save_data(
            data, 
            reason=f"grade updated: {label} → {hex_color}" if is_update else f"grade created: {label}", 
            actor=interaction.user
        )
        
        action_str = "updated" if is_update else "created"
        await interaction.followup.send(embed=get_embed("Grade Configured", f"Grade **{label}** {action_str} with color {hex_color}.", "success"))

    @app_commands.command(name="assigngrade", description="Assign a grade to an OC (Dev only)")
    @app_commands.describe(
        oc_name="The Trainee OC to assign the grade to.",
        grade_label="The exact label of the grade tier to assign."
    )
    @is_dev()
    async def assigngrade(self, interaction: discord.Interaction, oc_name: str, grade_label: str):
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc:
            return await interaction.followup.send(embed=get_embed("Not Found", "We looked everywhere but couldn't find that Trainee.", "error"))
        if grade_label not in data["grades"]:
            return await interaction.followup.send(embed=get_embed("Not Found", "We couldn't find a grade tier with that label. Use **/grade_create** to create it first!", "error"))
        
        old_grade = oc.get("grade")
        oc["grade"] = grade_label
        
        if interaction.guild:
            await ensure_grade_role(interaction.guild, grade_label, data["grades"][grade_label]["color"], data)
            await sync_grade_role_for_owner(interaction.guild, oc["owner_id"], grade_label, old_grade, data)
            
        save_data(data, reason=f"grade assigned: {oc['name']} → {grade_label}", actor=interaction.user)
        
        await interaction.followup.send(
            embed=get_embed(
                "Grade Assigned",
                f"**{oc['name']}** is now Grade **{grade_label}**.\n"
                f"Owner <@{oc['owner_id']}> has been given the "
                f"**[{grade_label}]** role with colour `{data['grades'][grade_label]['color']}`.",
                "success"
            )
        )

class DormsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dorm_createfloor", description="Create a dorm floor and its Discord category (Dev only)")
    @app_commands.describe(floor_name="A unique name for this dorm floor, e.g. 'Floor A' or 'Wing Crimson'. A matching Discord category will be created.")
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
    @app_commands.describe(
        floor_name="The name of the floor this room belongs to. Must already exist.",
        room_name="A unique name for the room within this floor, e.g. 'Room 101'.",
        capacity="Maximum number of OCs this room can hold."
    )
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
    @app_commands.describe(
        oc_name="The Trainee OC to assign to a room.",
        floor_name="The floor the target room is on.",
        room_name="The room to assign the OC to."
    )
    @is_dev()
    async def assign(self, interaction: discord.Interaction, oc_name: str, floor_name: str, room_name: str):
        data = load_data()
        oc = find_oc(oc_name, data)
        if not oc: return await interaction.response.send_message("We looked everywhere but couldn't find that Trainee.", ephemeral=True)
        
        if oc.get("eliminated", False):
            return await interaction.response.send_message(
                embed=get_embed("Ineligible", f"**{oc['name']}** is eliminated and cannot be assigned to a dorm.", "error"),
                ephemeral=True
            )
            
        try:
            room = data["dorms"][floor_name]["rooms"][room_name]
            if len(room["occupants"]) >= room["capacity"]:
                return await interaction.response.send_message(embed=get_embed("Room Full", "That room is full! Try a different room or ask a Dev to increase capacity.", "error"), ephemeral=True)
            
            if oc.get("dorm_floor") and oc.get("dorm_room"):
                return await interaction.response.send_message(
                    embed=get_embed("Already Assigned", f"**{oc['name']}** is already assigned to a room — they'll need to be moved out first.", "warning"),
                    ephemeral=True
                )
                
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
    @app_commands.describe(
        name="A unique name for this mission group.",
        oc_names="Comma-separated names of Trainees to add as founding members."
    )
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
    @app_commands.describe(
        group_name="The name of the mission group to add a member to.",
        oc_name="The Trainee OC to add."
    )
    @is_dev()
    async def addmember(self, interaction: discord.Interaction, group_name: str, oc_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"), ephemeral=True)
        
        oc = find_oc(oc_name, data)
        if not oc: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that Trainee.", "error"), ephemeral=True)
        if oc.get("eliminated"): return await interaction.response.send_message(embed=get_embed("Error", "OC is eliminated.", "error"), ephemeral=True)
        
        conflict = next((mg["name"] for mg in data["mission_groups"].values() if not mg.get("archived") and oc["id"] in mg["members"]), None)
        if conflict: return await interaction.response.send_message(embed=get_embed("Error", f"OC is already assigned to {conflict}.", "error"), ephemeral=True)
        
        group["members"].append(oc["id"])
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"{oc['name']} added to {group['name']}.", "success"), ephemeral=True)

    @missiongroup.command(name="removemember", description="[DEV] Remove an OC from a mission group")
    @app_commands.describe(
        group_name="The name of the mission group to remove a member from.",
        oc_name="The Trainee OC to remove."
    )
    @is_dev()
    async def removemember(self, interaction: discord.Interaction, group_name: str, oc_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"), ephemeral=True)
        
        oc = find_oc(oc_name, data)
        if not oc or oc["id"] not in group["members"]:
            return await interaction.response.send_message(embed=get_embed("Warning", "OC is not in this group.", "warning"), ephemeral=True)
            
        group["members"].remove(oc["id"])
        save_data(data)
        await interaction.response.send_message(embed=get_embed("Success", f"{oc['name']} removed from {group['name']}.", "success"), ephemeral=True)

    @missiongroup.command(name="provision", description="[DEV] Create a Discord practice channel for a group")
    @app_commands.describe(
        group_name="The mission group to create a practice channel for.",
        category="(Optional) The name of an existing Discord category to place the channel in."
    )
    @is_dev()
    async def provision(self, interaction: discord.Interaction, group_name: str, category: discord.CategoryChannel = None):
        await interaction.response.defer(ephemeral=True)
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.followup.send(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"))
        
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
    @app_commands.describe(group_name="The name of the mission group to deprovision.")
    @is_dev()
    async def deprovision(self, interaction: discord.Interaction, group_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if mg["name"].lower() == group_name.lower()), None)
        if not group or not group.get("channel_id"):
            return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group, or it has no channel.", "error"), ephemeral=True)
            
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
            if not group: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"))
            
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
    @app_commands.describe(group_name="The name of the mission group to archive.")
    @is_dev()
    async def archive(self, interaction: discord.Interaction, group_name: str):
        data = load_data()
        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == group_name.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"), ephemeral=True)
        
        group["archived"] = True
        save_data(data)
        
        warning = "\n⚠️ **Note**: Practice channel was not deleted. Use `/missiongroup deprovision` if needed." if group.get("channel_id") else ""
        await interaction.response.send_message(embed=get_embed("Success", f"Group '{group['name']}' archived.{warning}", "success"), ephemeral=True)

class PeerRankingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    peerranking = app_commands.Group(name="peerranking", description="Peer Ranking System")

    @peerranking.command(name="toggle", description="[DEV] Toggle Peer Ranking system on/off")
    @app_commands.describe(enabled="Set to True to enable the peer ranking system, False to disable it globally.")
    @is_dev()
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        data = load_data()
        data["config"]["peer_ranking_enabled"] = enabled
        save_data(data)
        
        unresolved = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        warning = "\n⚠️ **Warning**: There is an unresolved session that should be closed/cancelled." if not enabled and unresolved else ""
        
        await interaction.response.send_message(embed=get_embed("System Toggled", f"Peer Ranking System is now {'**ENABLED**' if enabled else '**DISABLED**'}.{warning}", "success" if enabled else "warning"), ephemeral=True)

    @peerranking.command(name="configure", description="[DEV] Configure Peer Ranking rewards/penalties")
    @app_commands.describe(
        benefit_type="Reward type for the top-ranked OC: 'multiplier' scales points, 'flat' adds a fixed amount.",
        benefit_value="The numeric value of the reward (e.g. 1.20 for a 20% bonus multiplier).",
        penalty_type="Penalty type for the bottom-ranked OC: 'multiplier' or 'flat'.",
        penalty_value="The numeric value of the penalty.",
        transparent="If True, the resolved results are posted publicly. Default: True."
    )
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
    @app_commands.describe(mission_group="The mission group whose members will be ranked against each other.")
    @is_dev()
    async def opensession(self, interaction: discord.Interaction, mission_group: str):
        data = load_data()
        if not data["config"]["peer_ranking_enabled"]:
            return await interaction.response.send_message(embed=get_embed("Error", "Peer Ranking is not enabled. Use /peerranking toggle to enable it.", "error"), ephemeral=True)
            
        if any(not s.get("resolved") for s in data["peer_ranking_sessions"].values()):
            return await interaction.response.send_message(embed=get_embed("Error", "An active peer ranking session already exists. Close it before opening a new one.", "error"), ephemeral=True)

        group = next((mg for mg in data["mission_groups"].values() if not mg.get("archived") and mg["name"].lower() == mission_group.lower()), None)
        if not group: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find that mission group.", "error"), ephemeral=True)

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
    @app_commands.describe(
        session_id="The ID of the currently open peer ranking session.",
        ranking="A comma-separated list of OC names ordered from best to worst performer in your opinion."
    )
    async def vote(self, interaction: discord.Interaction, session_id: str, ranking: str):
        data = load_data()
        if not data["config"]["peer_ranking_enabled"]:
            return await interaction.response.send_message(embed=get_embed("Disabled", "The Rivalry Protocol is not active this cycle.", "error"), ephemeral=True)
            
        session = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        if not session or session["session_id"] != session_id:
            return await interaction.response.send_message(embed=get_embed("Closed", "No peer ranking session is currently open.", "error"), ephemeral=True)
            
        user_id = str(interaction.user.id)
        if user_id not in session["eligible_voter_ids"]:
            return await interaction.response.send_message(embed=get_embed("Ineligible", "You aren't eligible to vote in this session. Only trainees who were not performing may cast peer rankings.", "error"), ephemeral=True)
            
        if user_id in session["ballots"]:
            return await interaction.response.send_message(embed=get_embed("Already Voted", "You've already submitted your ranking for this session!", "warning"), ephemeral=True)
            
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
        await interaction.response.send_message(embed=get_embed("Recorded", "Your peer ranking has been recorded. It will remain private until the session is revealed. 🤫", "success"), ephemeral=True)

    @peerranking.command(name="closesession", description="[DEV] Close session and apply multipliers")
    @is_dev()
    async def closesession(self, interaction: discord.Interaction):
        data = load_data()
        session = next((s for s in data["peer_ranking_sessions"].values() if not s.get("resolved")), None)
        if not session: return await interaction.response.send_message(embed=get_embed("Error", "We looked everywhere but couldn't find an active session to close.", "error"), ephemeral=True)

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
        save_data(data, reason="peer_ranking_closed", actor=interaction.user)
        
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
        save_data(data, reason="peer_ranking_revealed", actor=interaction.user)
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

    @app_commands.command(name="rankings_private", description="[DEV] View all rankings privately (paginated). Shows live points.")
    @is_dev()
    async def private(self, interaction: discord.Interaction):
        data = load_data()
        recalculate_ranks(data)
        
        voting_status_note = "🟢 Voting is **OPEN** — live tally shown." if data["voting"]["is_open"] else "🔴 Voting is **CLOSED**."
        
        ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False)]
        if not ocs:
            return await interaction.response.send_message(
                embed=get_embed("Empty Roster", "There are no active Trainees to display.", "warning"),
                ephemeral=True
            )
            
        ocs.sort(key=lambda x: x.get("current_rank", 9999))
        
        page_size = data["config"].get("reveal_page_size", 7)
        debut_slots = data["config"].get("debut_slots", 0)
        
        batches = [ocs[i:i+page_size] for i in range(0, len(ocs), page_size)]
        pages = []
        
        for idx, batch in enumerate(batches):
            embed = discord.Embed(title=f"Private Rankings — Page {idx+1}/{len(batches)}", color=COLORS["system"])
            
            if idx == 0:
                embed.add_field(name="📊 Status", value=voting_status_note, inline=False)
                
            for oc in batch:
                change = get_rank_change(oc["id"], oc["current_rank"], data)
                grade_str = f" [{oc['grade']}]" if oc.get('grade') else ""
                
                if debut_slots > 0 and oc["current_rank"] == debut_slots + 1:
                    embed.add_field(name="── DEBUT LINE ──", value=f"Top {debut_slots} trainee(s) debut.", inline=False)
                    
                embed.add_field(
                    name=f"#{oc['current_rank']} {change}{grade_str}",
                    value=f"**{oc['name']}** · {oc['total_points']:,} pts\n<@{oc['owner_id']}>",
                    inline=False
                )
                
            pages.append(embed)
            
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            view = RankingPaginationView(pages)
            msg = await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
            view.message = await interaction.original_response()

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

    @app_commands.command(name="rankings_partial", description="Reveal specific rankings by number — supports comma/space-separated lists.")
    @app_commands.describe(ranks="Rank numbers to reveal. Accepts space-separated or comma-separated integers, or a mix.")
    @is_dev()
    async def partial(self, interaction: discord.Interaction, ranks: str):
        data = load_data()
        recalculate_ranks(data)
        color = hex_to_int(data["config"]["reveal_color"])
        
        raw_tokens = re.split(r'[\s,]+', ranks.strip())
        rank_set = set()
        invalid_tokens = []

        for token in raw_tokens:
            if not token:
                continue
            try:
                val = int(token)
                if val < 1:
                    invalid_tokens.append(token)
                else:
                    rank_set.add(val)
            except ValueError:
                invalid_tokens.append(token)

        if not rank_set:
            return await interaction.response.send_message(
                embed=get_embed("Invalid Input", "No valid rank numbers were found. Provide integers separated by spaces or commas, e.g. `1 3 5` or `2, 8, 14`.", "error"),
                ephemeral=True
            )

        sorted_display = sorted(rank_set)
        ranks_str = ", ".join(f"#{r}" for r in sorted_display)
        
        desc = f"*Revealing ranks: {ranks_str}…*"
        if invalid_tokens:
            desc += f"\n⚠️ Skipped unrecognized tokens: `{', '.join(invalid_tokens)}`"

        await interaction.response.send_message(embed=get_embed("Evaluation Begins", desc, "reveal", show_footer=True))
        
        channel_id = data["config"].get("announcement_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else interaction.channel
        
        active_ocs = [oc for oc in data["ocs"].values() if not oc.get("eliminated", False) and oc.get("current_rank", 0) in rank_set]
        active_ocs.sort(key=lambda x: x.get("current_rank", 9999), reverse=True)
        
        if not active_ocs:
            return await interaction.followup.send(
                embed=get_embed("No Results", f"No active Trainees were found at the specified rank(s): {ranks_str}.", "warning"),
                ephemeral=True
            )
            
        page_size = data["config"].get("reveal_page_size", 7)
        page_embeds = await _run_sequential_reveal(channel, active_ocs, color, page_size, data, show_debut_line=False, hide_points=True)
        
        await interaction.followup.send(
            embed=get_embed("📖 Browse Results", f"Scroll through all {len(page_embeds)} page(s).", "reveal", show_footer=True),
            view=RankingPaginationView(page_embeds)
        )

class ExportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="export_rankings", description="[DEV] Export full rankings, history, logs, and feeds as a CSV file.")
    @is_dev()
    async def export_rankings(self, interaction: discord.Interaction):
        data = load_data()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', quoting=csv.QUOTE_ALL)
        
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
                len(s["ballots"]), len(s["eligible_voters"]),
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
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8-sig')), filename=f"rankings_export_{now().strftime('%Y-%m-%d_%H-%M')}.csv")
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
        oc_name="The name of the OC posting to their feed.",
        caption="The text caption for this post.",
        media1="URL to the first image or video attachment.",
        media2="(Optional) URL to a second media attachment.",
        media3="(Optional) URL to a third media attachment.",
        media4="(Optional) URL to a fourth media attachment.",
        media5="(Optional) URL to a fifth media attachment."
    )
    async def feed_post(self, interaction: discord.Interaction, oc_name: str, caption: str,
                        media1: discord.Attachment, media2: discord.Attachment = None, media3: discord.Attachment = None,
                        media4: discord.Attachment = None, media5: discord.Attachment = None, media6: discord.Attachment = None,
                        media7: discord.Attachment = None, media8: discord.Attachment = None, media9: discord.Attachment = None,
                        media10: discord.Attachment = None):
        
        data = load_data()
        if await auto_resolve_config(interaction.guild, data):
            save_data(data, reason="auto_resolve_feed_post", actor=interaction.user)
            
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"We looked everywhere but couldn't find an active Trainee named '{oc_name}'.", "error"), ephemeral=True)
        if oc.get("eliminated", False):
            return await interaction.response.send_message(embed=get_embed("Ineligible", "Eliminated Trainees aren't able to post to their feed right now.", "error"), ephemeral=True)
            
        is_owner = str(interaction.user.id) == oc["owner_id"]
        dev_role = data["config"].get("dev_role_id")
        
        is_dev_user = (
            interaction.user.id == interaction.client.application.owner.id
            or (dev_role and interaction.guild and interaction.guild.get_role(int(dev_role)) in interaction.user.roles)
        )
        
        if not is_owner and not is_dev_user:
            return await interaction.response.send_message(embed=get_embed("Permission Denied", f"🔒 Only **{oc['name']}**'s owner or a staff member can do that!", "error"), ephemeral=True)
            
        oc_id = oc["id"]
        if oc_id not in data["feeds"]:
            data["feeds"][oc_id] = []
            
        if len(oc.get("feed_post_ids", [])) >= 10:
            return await interaction.response.send_message(embed=get_embed("Feed Full", f"**{oc['name']}** already has 10 posts. Delete an existing post with `/feed delete` to make room.", "warning"), ephemeral=True)
            
        if len(caption) > 500:
            return await interaction.response.send_message(embed=get_embed("Caption Too Long", "Your caption is a bit too long! Please keep it under 500 characters.", "error"), ephemeral=True)
            
        raw_attachments = [a for a in [media1, media2, media3, media4, media5, media6, media7, media8, media9, media10] if a is not None]
        
        ALLOWED_TYPES = ("image/", "video/")
        for att in raw_attachments:
            if not att.content_type or not any(att.content_type.startswith(t) for t in ALLOWED_TYPES):
                return await interaction.response.send_message(embed=get_embed("Invalid File", f"Hmm, '{att.filename}' isn't a supported image or video type.", "error"), ephemeral=True)
                
        if not data["config"].get("asset_channel"):
            return await interaction.response.send_message(embed=get_embed("Not Configured", "There's no asset channel set up yet, so profile pictures can't be saved at the moment. A staff member will need to run **/setassetchannel** to enable this — try registering without a picture for now!", "warning"), ephemeral=True)
            
        if not data["config"].get("feed_channel"):
            return await interaction.response.send_message(embed=get_embed("Not Configured", "The feed channel hasn't been set up yet. A Dev needs to run `/setfeedchannel`.", "warning"), ephemeral=True)
            
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
        save_data(data, reason="feed_post_created", actor=interaction.user)
        
        await interaction.followup.send(embed=get_embed("Post Published", f"📸 **{oc['name']}**'s post is live! Head over to <#{feed_ch.id}> to check it out.", "success"), ephemeral=True)

    @feed_group.command(name="view", description="Browse an OC's social feed posts")
    @app_commands.describe(oc_name="The OC whose feed you want to browse.")
    async def feed_view(self, interaction: discord.Interaction, oc_name: str):
        data = load_data()
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"We looked everywhere but couldn't find a Trainee named '{oc_name}'.", "error"), ephemeral=True)
            
        oc_posts = data["feeds"].get(oc["id"], [])
        if not oc_posts:
            return await interaction.response.send_message(embed=get_embed(f"{oc['name']}'s Feed", f"Nothing here yet — **{oc['name']}** hasn't posted anything! 📭", "system"))
            
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
    @app_commands.describe(
        oc_name="The OC whose post you want to delete.",
        post_number="The number of the post to delete (1 = oldest post)."
    )
    async def feed_delete(self, interaction: discord.Interaction, oc_name: str, post_number: int):
        data = load_data()
        oc = next((o for o in data["ocs"].values() if o["name"].lower() == oc_name.lower()), None)
        if not oc:
            return await interaction.response.send_message(embed=get_embed("Not Found", f"We looked everywhere but couldn't find a Trainee named '{oc_name}'.", "error"), ephemeral=True)
            
        is_owner = str(interaction.user.id) == oc["owner_id"]
        dev_role = data["config"].get("dev_role_id")
        is_dev_user = (
            interaction.user.id == interaction.client.application.owner.id
            or (dev_role and interaction.guild and interaction.guild.get_role(int(dev_role)) in interaction.user.roles)
        )
        
        if not is_owner and not is_dev_user:
            return await interaction.response.send_message(embed=get_embed("Permission Denied", f"🔒 Only **{oc['name']}**'s owner or a staff member can do that!", "error"), ephemeral=True)
            
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
        save_data(data, reason="feed_post_deleted", actor=interaction.user)
        
        await interaction.response.send_message(embed=get_embed("Post Deleted", f"Post #{post_number} from **{oc['name']}**'s feed has been taken down successfully.", "success"), ephemeral=True)

# ==========================================
# 6. BACKGROUND TASKS
# ==========================================
@tasks.loop(hours=6)
async def asset_revalidation_task():
    """
    Every 6 hours, iterate all active and archived OCs that have a stored
    profile_picture_url. Issue a HEAD request to each URL. If the response
    status is not 200 (expired, 404, 403), attempt to re-fetch the image
    from the asset channel by scanning for a message whose content contains
    the OC's ID or name, then re-post the attachment to re-anchor a fresh URL.
    
    Because re-fetching from the channel is not always possible (message may
    have been pruned), this task logs a warning per OC and clears the dead URL
    so the embed degrades gracefully (no broken image icon) rather than silently.
    """
    data = load_data()
    asset_ch_id = data["config"].get("asset_channel")
    if not asset_ch_id:
        return

    asset_ch = bot.get_channel(int(asset_ch_id))
    changed = False

    async with aiohttp.ClientSession() as session:
        all_ocs = list(data["ocs"].values()) + list(data["archived_ocs"].values())
        for oc in all_ocs:
            url = oc.get("profile_picture_url")
            if not url:
                continue
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        continue  # URL still alive
            except Exception:
                pass  # Treat connection errors as expired

            # URL is dead. Attempt re-upload by scanning asset channel history.
            new_url = None
            if asset_ch:
                try:
                    async for msg in asset_ch.history(limit=500, oldest_first=False):
                        if oc["id"] in msg.content or oc["name"].lower() in msg.content.lower():
                            if msg.attachments:
                                att = msg.attachments[0]
                                new_url = await upload_to_asset_channel(bot, oc["name"], oc["id"], att.url)
                                break
                except Exception as e:
                    print(f"asset_revalidation_task: error re-fetching asset for {oc['name']}: {e}")

            # Update or clear the stored URL
            target_store = data["ocs"] if oc["id"] in data["ocs"] else data["archived_ocs"]
            if new_url:
                target_store[oc["id"]]["profile_picture_url"] = new_url
                print(f"asset_revalidation_task: re-anchored URL for {oc['name']}")
            else:
                target_store[oc["id"]]["profile_picture_url"] = None
                print(f"asset_revalidation_task: cleared dead URL for {oc['name']} (no re-upload source found)")
            changed = True

    if changed:
        save_data(data, reason="asset_revalidation_auto")

@tasks.loop(minutes=1)
async def voting_scheduler():
    data = load_data()
    now_kst = datetime.now(KST)
    changed = False

    # --- Daily vote count reset at 12:00 AM KST ---
    if data["voting"]["is_open"]:
        reset_occurred = _reset_daily_votes_if_needed(data)
        if reset_occurred:
            changed = True

    # --- Scheduled open ---
    sched_open = data["voting"].get("scheduled_open_time")
    if sched_open and not data["voting"]["is_open"]:
        target = datetime.fromisoformat(sched_open)
        if now_kst >= target:
            data["voting"]["is_open"] = True
            data["voting"]["votes"] = {}
            data["voting"]["user_votes"] = {}
            data["voting"]["daily_vote_counts"] = {}
            data["voting"]["daily_vote_date"] = today_kst().isoformat()
            data["voting"]["start_time"] = now_kst.isoformat()
            data["voting"]["scheduled_open_time"] = None
            changed = True

            ann_id = data["config"].get("announcement_channel_id")
            if ann_id:
                ch = bot.get_channel(int(ann_id))
                if ch:
                    await ch.send(embed=get_embed(
                        "🗳️ Voting Is Now Open!",
                        "The scheduled voting round has begun. Cast your votes!",
                        "success",
                        show_footer=True
                    ))

    # --- Scheduled close ---
    sched_close = data["voting"].get("scheduled_close_time")
    if sched_close and data["voting"]["is_open"]:
        target = datetime.fromisoformat(sched_close)
        if now_kst >= target:
            data["voting"]["is_open"] = False
            data["voting"]["last_closed_at"] = now_kst.isoformat()
            data["voting"]["end_time"] = now_kst.isoformat()
            data["voting"]["scheduled_close_time"] = None

            mult = data["voting"]["multiplier"]
            for oc_id, voters in data["voting"]["votes"].items():
                if oc_id in data["ocs"] and not data["ocs"][oc_id].get("eliminated", False):
                    pts = len(voters) * mult
                    points_before = data["ocs"][oc_id]["total_points"]
                    data["ocs"][oc_id]["voting_points"] += pts
                    data["ocs"][oc_id]["total_points"] += pts
                    data["point_log"].append({
                        "timestamp": now_kst.isoformat(),
                        "dev_id":    "SYSTEM_SCHEDULER",
                        "dev_name":  "AutoScheduler",
                        "oc_id":     oc_id,
                        "oc_name":   data["ocs"][oc_id]["name"],
                        "action":    "vote_close",
                        "value":     pts,
                        "points_before": points_before,
                        "points_after":  data["ocs"][oc_id]["total_points"]
                    })

            recalculate_ranks(data)

            active_ocs = [o for o in data["ocs"].values() if not o.get("eliminated", False)]
            data["rank_snapshots"].append({
                "timestamp": now_kst.isoformat(),
                "trigger":   "SCHEDULED_VOTING_ROUND_CLOSE",
                "rankings":  [{"oc_id": o["id"], "rank": o["current_rank"], "points": o["total_points"]} for o in active_ocs]
            })
            changed = True

            ann_id = data["config"].get("announcement_channel_id")
            if ann_id:
                ch = bot.get_channel(int(ann_id))
                if ch:
                    await ch.send(embed=get_embed(
                        "Voting Closed",
                        "✅ The scheduled voting round has closed. Results have been tallied and rankings updated.",
                        "system",
                        show_footer=True
                    ))
            await _post_rankings_to_channel(bot, data)

    if changed:
        save_data(data, reason="scheduler_auto_action")

@tasks.loop(minutes=5)
async def auto_backup_db():
    global DATA_DIRTY
    if not DATA_DIRTY or not DB_LOADED:
        return
    if not os.path.exists(DATA_FILE):
        return
    try:
        data = load_data()
        print(f"[auto_backup_db] DATA_DIRTY=True — triggering watchdog backup.")
        await push_backup_to_discord(data, reason="auto-watchdog")
    except Exception as e:
        print(f"[auto_backup_db] Watchdog backup failed: {type(e).__name__}: {e}")

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
    """
    Required env vars:
      BOT_TOKEN          — Discord bot token

    Strongly recommended env vars (prevent cold-start data loss):
      DATA_CHANNEL_ID    — Numeric Discord channel ID of #data
                           Seeds data.json on fresh container before hydration.
      ASSET_CHANNEL_ID   — Numeric Discord channel ID of #assets
                           Seeds asset_channel config on fresh container.

    Optional:
      PORT               — HTTP health-check port (default: 8080)
    """
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable missing.")
        exit(1)

    # Note: DATA_CHANNEL_ID and ASSET_CHANNEL_ID are now fetched and loaded directly
    # within the on_ready() block (Step 1) so we log those actions dynamically at runtime.
    if not os.getenv("DATA_CHANNEL_ID"):
        print("WARNING: DATA_CHANNEL_ID env var is not set. On a fresh container, "
              "data hydration from Discord will be skipped (no channel ID to read from). "
              "Set DATA_CHANNEL_ID to your data channel's numeric ID to enable full persistence.")
    else:
        print(f"DATA_CHANNEL_ID is set to: {os.getenv('DATA_CHANNEL_ID')}")

    if not os.getenv("ASSET_CHANNEL_ID"):
        print("WARNING: ASSET_CHANNEL_ID env var is not set. Setup will rely on auto-resolution.")

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print(f"Health server started on port {os.getenv('PORT', 8080)}.")

    bot.run(TOKEN)