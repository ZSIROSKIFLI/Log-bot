import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
 
# ─── Beállítások ───────────────────────────────────────────────────────────────
DATA_FILE = "/data/activity_data.json"
FIGYELT_RANG = "El Diablo | 👹"
VEZETES_RANG = "Vezetőség | 🍺"
 
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
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
active_sessions = {}
db = load_data()
 
def get_user(user_id: str):
    if user_id not in db["users"]:
        db["users"][user_id] = {"total_seconds": {}}
    return db["users"][user_id]
 
def has_figyelt_rang(member: discord.Member) -> bool:
    return any(role.name == FIGYELT_RANG for role in member.roles)
 
def has_vezetes_rang(member: discord.Member) -> bool:
    return any(role.name == VEZETES_RANG for role in member.roles)
 
def fmt_time(seconds: int) -> str:
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
 
            if current_game and not active_game:
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
                print(f"[SCAN] {member.display_name} elkezdte: {current_game}")
            elif current_game and active_game and current_game != active_game:
                end_session(uid, now)
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
                print(f"[SCAN] {member.display_name} valtott: {current_game}")
            elif not current_game and active_game:
                end_session(uid, now)
                print(f"[SCAN] {member.display_name} abbahagyta: {active_game}")
 
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
 
# ─── /leaderboard ─────────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Heti játékidő toplista")
async def leaderboard(interaction: discord.Interaction):
    now = datetime.utcnow()
    guild = interaction.guild
    el_diablo_members = [m for m in guild.members if not m.bot and has_figyelt_rang(m)]
 
    if not el_diablo_members:
        await interaction.response.send_message("Nincs egyetlen El Diablo rangú tag sem.", ephemeral=True)
        return
 
    rows = []
    for member in el_diablo_members:
        uid = str(member.id)
        games = dict(db["users"].get(uid, {}).get("total_seconds", {}))
        if uid in active_sessions:
            elapsed = int((now - datetime.fromisoformat(active_sessions[uid]["start"])).total_seconds())
            g = active_sessions[uid]["game"]
            games[g] = games.get(g, 0) + elapsed
        total_seconds = sum(games.values())
        rows.append((member, games, total_seconds, uid))
 
    rows.sort(key=lambda x: x[2], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, games, total_secs, uid) in enumerate(rows):
        place = medals[i] if i < 3 else ("**" + str(i+1) + ".**")
        live = " 🔴" if uid in active_sessions else ""
        name = member.display_name
        if games:
            game_parts = ", ".join(
                g + " `" + fmt_time(s) + "`"
                for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True)
            )
            lines.append(place + " **" + name + "**" + live + " — " + game_parts)
        else:
            lines.append(place + " **" + name + "** — *még nem játszott*")
 
    last_reset = db.get("last_reset", "Még nem volt")
    embed = discord.Embed(
        title="🏆 El Diablo Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
        timestamp=now
    )
    embed.set_footer(text="Reset: /resetleaderboard | Utolsó: " + str(last_reset)[:10])
    await interaction.response.send_message(embed=embed)
 
# ─── /nowplaying ──────────────────────────────────────────────────────────────
@bot.tree.command(name="nowplaying", description="Ki mit játszik most, és mióta?")
async def nowplaying(interaction: discord.Interaction):
    if not active_sessions:
        await interaction.response.send_message("Senki sem játszik éppen semmit. 😴", ephemeral=True)
        return
 
    now = datetime.utcnow()
    embed = discord.Embed(title="🔴 Aktív játékosok", color=discord.Color.red(), timestamp=now)
 
    for uid, session in active_sessions.items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else ("ID:" + uid)
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
            "🕐 Elkezdve: `" + start_str + "` (magyar idő)\n"
            "📊 Heti összes ebből: `" + fmt_time(weekly_total) + "`"
        )
        embed.add_field(name=name, value=value, inline=False)
 
    await interaction.response.send_message(embed=embed)
 
# ─── /addtime [Vezetőség] ─────────────────────────────────────────────────────
@bot.tree.command(name="addtime", description="[Vezetőség] Adj időt egy tagnak egy játékhoz")
@app_commands.describe(member="Melyik tagnak", game="Melyik játékhoz (pl. DRP)", hours="Hány óra", minutes="Hány perc")
async def addtime(interaction: discord.Interaction, member: discord.Member, game: str, hours: int = 0, minutes: int = 0):
    if not has_vezetes_rang(interaction.user):
        await interaction.response.send_message("Nincs jogosultságod! 🚫", ephemeral=True)
        return
    seconds = hours * 3600 + minutes * 60
    if seconds <= 0:
        await interaction.response.send_message("Adj meg legalább 1 percet!", ephemeral=True)
        return
    uid = str(member.id)
    user = get_user(uid)
    user["total_seconds"][game] = user["total_seconds"].get(game, 0) + seconds
    save_data(db)
    h, m = divmod(seconds // 60, 60)
    await interaction.response.send_message(
        "✅ **" + member.display_name + "**-nak hozzáadva: **" + game + "** → +" + str(h) + "ó " + str(m) + "p\n"
        "📊 Mostani összes: `" + fmt_time(user["total_seconds"][game]) + "`"
    )
 
# ─── /removetime [Vezetőség] ──────────────────────────────────────────────────
@bot.tree.command(name="removetime", description="[Vezetőség] Vegyél el időt egy tagtól")
@app_commands.describe(member="Melyik tagnak", game="Melyik játékhoz (pl. DRP)", hours="Hány óra", minutes="Hány perc")
async def removetime(interaction: discord.Interaction, member: discord.Member, game: str, hours: int = 0, minutes: int = 0):
    if not has_vezetes_rang(interaction.user):
        await interaction.response.send_message("Nincs jogosultságod! 🚫", ephemeral=True)
        return
    seconds = hours * 3600 + minutes * 60
    if seconds <= 0:
        await interaction.response.send_message("Adj meg legalább 1 percet!", ephemeral=True)
        return
    uid = str(member.id)
    user = get_user(uid)
    current = user["total_seconds"].get(game, 0)
    user["total_seconds"][game] = max(0, current - seconds)
    save_data(db)
    h, m = divmod(seconds // 60, 60)
    await interaction.response.send_message(
        "✅ **" + member.display_name + "**-tól elvéve: **" + game + "** → -" + str(h) + "ó " + str(m) + "p\n"
        "📊 Mostani összes: `" + fmt_time(user["total_seconds"][game]) + "`"
    )
 
# ─── /resetleaderboard [Vezetőség] ───────────────────────────────────────────
@bot.tree.command(name="resetleaderboard", description="[Vezetőség] Leaderboard manuális resetelése")
async def resetleaderboard(interaction: discord.Interaction):
    if not has_vezetes_rang(interaction.user):
        await interaction.response.send_message("Nincs jogosultságod! 🚫", ephemeral=True)
        return
    now = datetime.utcnow()
    for uid in list(active_sessions.keys()):
        end_session(uid, now)
    db["users"] = {}
    db["last_reset"] = now.isoformat()
    save_data(db)
    await interaction.response.send_message(
        "🔄 **Leaderboard resetelve!** (" + interaction.user.display_name + " által)\nÚj hét, új verseny! 🏆"
    )
 
# ─── /debug [Vezetőség] ───────────────────────────────────────────────────────
@bot.tree.command(name="debug", description="[Vezetőség] Aktuális bot adatok megtekintése")
async def debug(interaction: discord.Interaction):
    if not has_vezetes_rang(interaction.user):
        await interaction.response.send_message("Nincs jogosultságod! 🚫", ephemeral=True)
        return
    now = datetime.utcnow()
    lines = ["**Aktív sessionök (" + str(len(active_sessions)) + "):**"]
    if active_sessions:
        for uid, session in active_sessions.items():
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else ("ID:" + uid)
            elapsed = int((now - datetime.fromisoformat(session["start"])).total_seconds())
            lines.append("• " + name + " → " + session["game"] + " (`" + fmt_time(elapsed) + "`)")
    else:
        lines.append("• Senki")
    lines.append("\n**Mentett adatok (" + str(len(db["users"])) + " felhasználó):**")
    for uid, data in db["users"].items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else ("ID:" + uid)
        total = sum(data.get("total_seconds", {}).values())
        if total > 0:
            lines.append("• " + name + ": `" + fmt_time(total) + "` összesen")
    lines.append("\n**Utolsó reset:** " + str(db.get("last_reset", "Még nem volt"))[:19])
    embed = discord.Embed(
        title="🔧 Debug Info",
        description="\n".join(lines),
        color=discord.Color.orange(),
        timestamp=now
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
 
# ─── Bot indulás ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
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
