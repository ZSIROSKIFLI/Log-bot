import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta

# ─── Beállítások ───────────────────────────────────────────────────────────────
DATA_FILE = "/data/activity_data.json"
FIGYELT_RANG = "El Diablo | 👹"

# ─── Bot inicializálás ─────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Adatok betöltése/mentése ──────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_reset": None, "users": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

active_sessions = {}  # {user_id: {"game": "...", "start": "ISO"}}
db = load_data()

def get_user(user_id: str):
    if user_id not in db["users"]:
        db["users"][user_id] = {"total_seconds": {}}
    return db["users"][user_id]

def has_figyelt_rang(member: discord.Member) -> bool:
    return any(role.name == FIGYELT_RANG for role in member.roles)

def fmt_time(seconds: int) -> str:
    """Másodperceket DD:HH:MM:SS formátumra alakít."""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d:02}:{h:02}:{m:02}:{s:02}"

def end_session(user_id: str, now: datetime):
    if user_id not in active_sessions:
        return
    session = active_sessions.pop(user_id)
    start_time = datetime.fromisoformat(session["start"])
    duration = int((now - start_time).total_seconds())
    if duration < 10:
        return
    game = session["game"]
    user = get_user(user_id)
    user["total_seconds"][game] = user["total_seconds"].get(game, 0) + duration
    save_data(db)

# ─── Heti reset vasárnaponként ─────────────────────────────────────────────────
@tasks.loop(minutes=10)
async def weekly_reset_check():
    now = datetime.utcnow()
    last = db.get("last_reset")
    if now.weekday() == 6:
        if last is None or (now - datetime.fromisoformat(last)).days >= 7:
            for uid in list(active_sessions.keys()):
                end_session(uid, now)
            db["users"] = {}
            db["last_reset"] = now.isoformat()
            save_data(db)
            print(f"[RESET] Heti leaderboard resetelve: {now}")
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send("🔄 **Heti leaderboard resetelve!** Új hét, új verseny! 🏆")
                        break

# ─── Esemény: Aktivitás változás ───────────────────────────────────────────────
@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    if not has_figyelt_rang(after):
        return

    user_id = str(after.id)
    now = datetime.utcnow()

    before_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
    after_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)

    if before_game and before_game != after_game:
        end_session(user_id, now)

    if after_game and after_game != before_game:
        active_sessions[user_id] = {"game": after_game, "start": now.isoformat()}
        print(f"[LOG] {after.display_name} elkezdte: {after_game}")

# ─── Slash parancs: /leaderboard ──────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Heti játékidő toplista")
async def leaderboard(interaction: discord.Interaction):
    now = datetime.utcnow()
    guild = interaction.guild

    # Összegyűjtjük az összes "El Diablo | 👹" rangú tagot
    el_diablo_members = [m for m in guild.members if not m.bot and has_figyelt_rang(m)]

    if not el_diablo_members:
        await interaction.response.send_message("Nincs egyetlen El Diablo rangú tag sem.", ephemeral=True)
        return

    rows = []
    for member in el_diablo_members:
        uid = str(member.id)
        games = dict(db["users"].get(uid, {}).get("total_seconds", {}))

        # Aktív session hozzáadása
        if uid in active_sessions:
            elapsed = int((now - datetime.fromisoformat(active_sessions[uid]["start"])).total_seconds())
            g = active_sessions[uid]["game"]
            games[g] = games.get(g, 0) + elapsed

        total_seconds = sum(games.values())
        rows.append((member, games, total_seconds, uid))

    # Rendezés összes játékidő szerint (csökkenő)
    rows.sort(key=lambda x: x[2], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, games, total_secs, uid) in enumerate(rows):
        place = medals[i] if i < 3 else f"**{i+1}.**"
        live = " 🔴" if uid in active_sessions else ""
        name = member.display_name

        if games:
            # Játékok listája: "DRP 00:01:22:11, Minecraft 00:00:45:30"
            game_parts = ", ".join(
                f"{g} `{fmt_time(s)}`"
                for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True)
            )
            lines.append(f"{place} **{name}**{live} — {game_parts}")
        else:
            lines.append(f"{place} **{name}** — *még nem játszott*")

    # Reset dátuma
    days_until_sunday = (6 - now.weekday()) % 7 or 7
    next_reset = now + timedelta(days=days_until_sunday)

    embed = discord.Embed(
        title="🏆 Heti El Diablo Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
        timestamp=now
    )
    embed.set_footer(text=f"Reset: {next_reset.strftime('%Y.%m.%d')} vasárnap")

    await interaction.response.send_message(embed=embed)

# ─── Slash parancs: /nowplaying ───────────────────────────────────────────────
@bot.tree.command(name="nowplaying", description="Ki mit játszik most, és mióta?")
async def nowplaying(interaction: discord.Interaction):
    if not active_sessions:
        await interaction.response.send_message("Senki sem játszik éppen semmit. 😴", ephemeral=True)
        return

    now = datetime.utcnow()
    embed = discord.Embed(title="🔴 Aktív játékosok", color=discord.Color.red(), timestamp=now)

    for uid, session in active_sessions.items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ID:{uid}"
        game = session["game"]
        start_time = datetime.fromisoformat(session["start"])
        elapsed = int((now - start_time).total_seconds())

        saved = db["users"].get(uid, {}).get("total_seconds", {}).get(game, 0)
        weekly_total = saved + elapsed

        local_start = start_time + timedelta(hours=2)
        start_str = local_start.strftime("%H:%M:%S")

        value = (
            "🎮 **" + game + "**\n"
            "⏱️ Mostani session: `" + fmt_time(elapsed) + "`\n"
            "🕐 Elkezdve: `" + start_str + "` (magyar ido)\n"
            "📊 Heti osszes ebbol: `" + fmt_time(weekly_total) + "`"
        )
        embed.add_field(name=name, value=value, inline=False)

    await interaction.response.send_message(embed=embed)

# ─── Aktív scan minden 5 percben ──────────────────────────────────────────────
@tasks.loop(minutes=5)
async def scan_presences():
    now = datetime.utcnow()
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or not has_figyelt_rang(member):
                continue
            uid = str(member.id)
            current_game = next(
                (a.name for a in member.activities if a.type == discord.ActivityType.playing),
                None
            )
            active_game = active_sessions.get(uid, {}).get("game")

            # Ha most játszik de nincs session -> kezdés
            if current_game and not active_game:
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
                print(f"[SCAN] {member.display_name} elkezdte: {current_game}")

            # Ha más játékra váltott
            elif current_game and active_game and current_game != active_game:
                end_session(uid, now)
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
                print(f"[SCAN] {member.display_name} valtott: {current_game}")

            # Ha abbahagyta
            elif not current_game and active_game:
                end_session(uid, now)
                print(f"[SCAN] {member.display_name} abbahagyta: {active_game}")

# ─── Bot indulás ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    weekly_reset_check.start()
    scan_presences.start()
    print(f"Bot bejelentkezve: {bot.user}")

    now = datetime.utcnow()
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or not has_figyelt_rang(member):
                continue
            for activity in member.activities:
                if activity.type == discord.ActivityType.playing:
                    uid = str(member.id)
                    if uid not in active_sessions:
                        active_sessions[uid] = {"game": activity.name, "start": now.isoformat()}
                        print(f"[STARTUP] {member.display_name} jatszik: {activity.name}")
                    break

# ─── Indítás ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("HIBA: DISCORD_TOKEN nincs beallitva!")
        exit(1)
    bot.run(TOKEN)
