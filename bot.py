import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
 
DATA_FILE = "/data/activity_data.json"
ARCHIVE_FILE = "/data/archive.json"
FIGYELT_RANG = "El Diablo | \U0001f479"
VEZETES_RANG = "Vezet\u0151s\u00e9g | \U0001f37a"
INAKTIV_RANG = "Inaktiv Tag | \U0001f47b"
LEADERBOARD_CHANNEL = "\u2503\u3018\U0001f4ca\u3019aktivitas-mero"
INAKTIV_CHANNEL = "\u2503\u3018\U0001f573\ufe0f\u3019inaktivitas-jelzo"
INAKTIV_NAPOK = 3
INAKTIV_MIN_ORA = 17
 
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True
 
bot = commands.Bot(command_prefix="!", intents=intents)
 
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_reset": None, "users": {}, "leaderboard_message_id": None, "personal_bests": {}}
 
def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
def load_archive():
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []
 
def save_archive(data):
    os.makedirs(os.path.dirname(ARCHIVE_FILE), exist_ok=True)
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
active_sessions = {}
db = load_data()
 
def get_user(user_id):
    if user_id not in db["users"]:
        db["users"][user_id] = {"total_seconds": {}, "last_seen": None}
    return db["users"][user_id]
 
def has_rang(member, rang):
    return any(role.name == rang for role in member.roles)
 
def fmt_time(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d:02}:{h:02}:{m:02}:{s:02}"
 
def end_session(user_id, now):
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
    user["last_seen"] = now.isoformat()
    save_data(db)
 
def get_weekly_seconds(uid, now):
    games = dict(db["users"].get(uid, {}).get("total_seconds", {}))
    if uid in active_sessions:
        elapsed = int((now - datetime.fromisoformat(active_sessions[uid]["start"])).total_seconds())
        g = active_sessions[uid]["game"]
        games[g] = games.get(g, 0) + elapsed
    return sum(games.values())
 
def get_channel(guild, name):
    for ch in guild.text_channels:
        if ch.name == name:
            return ch
    return None
 
def build_leaderboard_rows(guild, now):
    members = [m for m in guild.members if not m.bot and has_rang(m, FIGYELT_RANG)]
    rows = []
    for member in members:
        uid = str(member.id)
        games = dict(db["users"].get(uid, {}).get("total_seconds", {}))
        if uid in active_sessions:
            elapsed = int((now - datetime.fromisoformat(active_sessions[uid]["start"])).total_seconds())
            g = active_sessions[uid]["game"]
            games[g] = games.get(g, 0) + elapsed
        rows.append((member, games, sum(games.values()), uid))
    rows.sort(key=lambda x: x[2], reverse=True)
    return rows
 
def build_leaderboard_embed(guild, now):
    rows = build_leaderboard_rows(guild, now)
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    lines = []
    for i, (member, games, total, uid) in enumerate(rows):
        place = medals[i] if i < 3 else f"**{i+1}.**"
        live = " \U0001f534" if uid in active_sessions else ""
        name = member.display_name
        if games:
            parts = ", ".join(g + " `" + fmt_time(s) + "`" for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True))
            lines.append(place + " **" + name + "**" + live + " \u2014 " + parts)
        else:
            lines.append(place + " **" + name + "** \u2014 *m\u00e9g nem j\u00e1tszott*")
    last_reset = str(db.get("last_reset", "M\u00e9g nem volt"))[:10]
    embed = discord.Embed(
        title="\U0001f3c6 El Diablo Leaderboard",
        description="\n".join(lines) if lines else "*M\u00e9g nincs adat*",
        color=discord.Color.gold(),
        timestamp=now
    )
    embed.set_footer(text="\U0001f504 5 percenk\u00e9nt friss\u00fcl | Utols\u00f3 reset: " + last_reset)
    return embed
 
@tasks.loop(minutes=5)
async def auto_leaderboard():
    now = datetime.utcnow()
    for guild in bot.guilds:
        channel = get_channel(guild, LEADERBOARD_CHANNEL)
        if not channel:
            continue
        embed = build_leaderboard_embed(guild, now)
        msg_id = db.get("leaderboard_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(int(msg_id))
                await msg.edit(embed=embed)
                continue
            except:
                pass
        msg = await channel.send(embed=embed)
        db["leaderboard_message_id"] = str(msg.id)
        save_data(db)
 
@tasks.loop(hours=24)
async def inaktiv_check():
    now = datetime.utcnow()
    for guild in bot.guilds:
        inaktiv_ch = get_channel(guild, INAKTIV_CHANNEL)
        vezetes_role = discord.utils.get(guild.roles, name=VEZETES_RANG)
        inaktiv_role = discord.utils.get(guild.roles, name=INAKTIV_RANG)
        el_diablo = [m for m in guild.members if not m.bot and has_rang(m, FIGYELT_RANG)]
        MIN_SEC = INAKTIV_MIN_ORA * 3600
        inaktivak = []
        for member in el_diablo:
            uid = str(member.id)
            weekly = get_weekly_seconds(uid, now)
            last_seen_str = db["users"].get(uid, {}).get("last_seen")
            days_since = 0
            if last_seen_str:
                days_since = (now - datetime.fromisoformat(last_seen_str)).days
            if weekly < MIN_SEC and days_since >= INAKTIV_NAPOK:
                inaktivak.append((member, weekly, days_since))
        if not inaktivak:
            continue
        inaktivak.sort(key=lambda x: x[1])
        utolso_5 = inaktivak[:5]
        lines = []
        for member, weekly, days in utolso_5:
            if inaktiv_role and inaktiv_role not in member.roles:
                try:
                    await member.add_roles(inaktiv_role, reason="Heti 17 ora alatt")
                except:
                    pass
            h, m = divmod(weekly // 60, 60)
            lines.append("- **" + member.display_name + "** \u2014 ezen a h\u00e9ten `" + str(h) + "\u00f3 " + str(m) + "p` j\u00e1t\u00e9kid\u0151 (" + str(days) + " napja inakt\u00edv)")
        if inaktiv_ch:
            ping = vezetes_role.mention if vezetes_role else "@Vezet\u0151s\u00e9g"
            msg = ping + " \U0001f47b **Inaktivit\u00e1s jelent\u00e9s**\n\n"
            msg += "Az al\u00e1bbi tagok ezen a h\u00e9ten **nem \u00e9rt\u00e9k el a " + str(INAKTIV_MIN_ORA) + " \u00f3r\u00e1s minimumot** \u00e9s legal\u00e1bb " + str(INAKTIV_NAPOK) + " napja nem voltak akt\u00edvak:\n\n"
            msg += "\n".join(lines)
            msg += "\n\n\U0001f4cc Automatikusan megkaptk az **Inaktiv Tag | \U0001f47b** rangot."
            await inaktiv_ch.send(msg)
 
@tasks.loop(minutes=5)
async def scan_presences():
    now = datetime.utcnow()
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or not has_rang(member, FIGYELT_RANG):
                continue
            uid = str(member.id)
            current_game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
            active_game = active_sessions.get(uid, {}).get("game")
            if current_game and not active_game:
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
                get_user(uid)["last_seen"] = now.isoformat()
            elif current_game and active_game and current_game != active_game:
                end_session(uid, now)
                active_sessions[uid] = {"game": current_game, "start": now.isoformat()}
            elif not current_game and active_game:
                end_session(uid, now)
                await check_personal_best(guild, uid, now)
 
async def check_personal_best(guild, uid, now):
    channel = get_channel(guild, LEADERBOARD_CHANNEL)
    if not channel:
        return
    user_data = db["users"].get(uid, {})
    total = sum(user_data.get("total_seconds", {}).values())
    pb = db.get("personal_bests", {}).get(uid, 0)
    if total > pb and pb > 0:
        db.setdefault("personal_bests", {})[uid] = total
        save_data(db)
        member = guild.get_member(int(uid))
        name = member.display_name if member else uid
        await channel.send("\U0001f389 **" + name + "** megd\u00f6nt\u00f6tte a saj\u00e1t rekordj\u00e1t! \u00daj legjobb h\u00e9t: `" + fmt_time(total) + "` \U0001f3c6")
    elif total > pb:
        db.setdefault("personal_bests", {})[uid] = total
        save_data(db)
 
@bot.event
async def on_presence_update(before, after):
    if not has_rang(after, FIGYELT_RANG):
        return
    user_id = str(after.id)
    now = datetime.utcnow()
    before_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
    after_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
    if before_game and before_game != after_game:
        end_session(user_id, now)
        await check_personal_best(after.guild, user_id, now)
    if after_game and after_game != before_game:
        active_sessions[user_id] = {"game": after_game, "start": now.isoformat()}
        get_user(user_id)["last_seen"] = now.isoformat()
 
 
@bot.tree.command(name="leaderboard", description="Heti jatekido toplista")
async def leaderboard(interaction: discord.Interaction):
    now = datetime.utcnow()
    embed = build_leaderboard_embed(interaction.guild, now)
    await interaction.response.send_message(embed=embed)
 
@bot.tree.command(name="nowplaying", description="Ki mit jatszik most, es miota?")
async def nowplaying(interaction: discord.Interaction):
    if not active_sessions:
        await interaction.response.send_message("Senki sem jatszik eppen semmit.", ephemeral=True)
        return
    now = datetime.utcnow()
    embed = discord.Embed(title="\U0001f534 Aktiv jatekosok", color=discord.Color.red(), timestamp=now)
    for uid, session in active_sessions.items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else ("ID:" + uid)
        game = session["game"]
        start_time = datetime.fromisoformat(session["start"])
        elapsed = int((now - start_time).total_seconds())
        saved = db["users"].get(uid, {}).get("total_seconds", {}).get(game, 0)
        weekly_total = saved + elapsed
        local_start = start_time + timedelta(hours=2)
        value = (
            "\U0001f3ae **" + game + "**\n"
            "\u23f1\ufe0f Mostani session: `" + fmt_time(elapsed) + "`\n"
            "\U0001f550 Elkezdve: `" + local_start.strftime("%H:%M:%S") + "` (magyar ido)\n"
            "\U0001f4ca Heti osszes ebbol: `" + fmt_time(weekly_total) + "`"
        )
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed)
 
@bot.tree.command(name="lastweek", description="Elozo hetek archivuma")
@app_commands.describe(week="Hanadik elozo het? (1 = legutobbi)")
async def lastweek(interaction: discord.Interaction, week: int = 1):
    archive = load_archive()
    if not archive:
        await interaction.response.send_message("Meg nincs archivalt het.", ephemeral=True)
        return
    idx = len(archive) - week
    if idx < 0:
        await interaction.response.send_message("Nincs annyi archivalt het.", ephemeral=True)
        return
    entry = archive[idx]
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    lines = []
    for i, row in enumerate(entry["rows"]):
        place = medals[i] if i < 3 else ("**" + str(i+1) + ".**")
        parts = ", ".join(g + " `" + fmt_time(s) + "`" for g, s in row["games"])
        lines.append(place + " **" + row["name"] + "** \u2014 " + (parts if parts else "*nem jatszott*"))
    embed = discord.Embed(
        title="\U0001f4c5 Archivum \u2013 " + entry["week_start"] + " hete",
        description="\n".join(lines) if lines else "*Nincs adat*",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Legaktivabb: " + entry.get("most_active", "?"))
    await interaction.response.send_message(embed=embed)
 
@bot.tree.command(name="gamestats", description="Egy adott jatek statisztikai")
@app_commands.describe(game="Jatek neve (pl. DRP)")
async def gamestats(interaction: discord.Interaction, game: str):
    now = datetime.utcnow()
    players = []
    total_all = 0
    for uid, data in db["users"].items():
        secs = data.get("total_seconds", {}).get(game, 0)
        if uid in active_sessions and active_sessions[uid]["game"] == game:
            secs += int((now - datetime.fromisoformat(active_sessions[uid]["start"])).total_seconds())
        if secs > 0:
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else ("ID:" + uid)
            players.append((name, secs))
            total_all += secs
    if not players:
        await interaction.response.send_message("Senki sem jatszotta ezt a heten.", ephemeral=True)
        return
    players.sort(key=lambda x: x[1], reverse=True)
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    lines = []
    for i, (name, secs) in enumerate(players):
        place = medals[i] if i < 3 else ("**" + str(i+1) + ".**")
        lines.append(place + " **" + name + "**: `" + fmt_time(secs) + "`")
    embed = discord.Embed(
        title="\U0001f3ae " + game + " \u2013 statisztika",
        description="\n".join(lines),
        color=discord.Color.green(),
        timestamp=now
    )
    embed.add_field(name="Osszes jatekos", value=str(len(players)) + " fo", inline=True)
    embed.add_field(name="Osszes ido", value="`" + fmt_time(total_all) + "`", inline=True)
    await interaction.response.send_message(embed=embed)
 
@bot.tree.command(name="addtime", description="[Vezetoseg] Adj idot egy tagnak")
@app_commands.describe(member="Melyik tagnak", game="Melyik jatekhoz", hours="Hany ora", minutes="Hany perc")
async def addtime(interaction: discord.Interaction, member: discord.Member, game: str, hours: int = 0, minutes: int = 0):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    seconds = hours * 3600 + minutes * 60
    if seconds <= 0:
        await interaction.response.send_message("Adj meg legalabb 1 percet!", ephemeral=True)
        return
    uid = str(member.id)
    user = get_user(uid)
    user["total_seconds"][game] = user["total_seconds"].get(game, 0) + seconds
    save_data(db)
    await interaction.response.send_message(
        "\u2705 **" + member.display_name + "**-nak hozzaadva: **" + game + "** \u2192 +" + str(hours) + "o " + str(minutes) + "p\n"
        "\U0001f4ca Mostani osszes: `" + fmt_time(user["total_seconds"][game]) + "`"
    )
 
@bot.tree.command(name="removetime", description="[Vezetoseg] Vegyel el idot egy tagol")
@app_commands.describe(member="Melyik tagnak", game="Melyik jatekhoz", hours="Hany ora", minutes="Hany perc")
async def removetime(interaction: discord.Interaction, member: discord.Member, game: str, hours: int = 0, minutes: int = 0):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    seconds = hours * 3600 + minutes * 60
    if seconds <= 0:
        await interaction.response.send_message("Adj meg legalabb 1 percet!", ephemeral=True)
        return
    uid = str(member.id)
    user = get_user(uid)
    user["total_seconds"][game] = max(0, user["total_seconds"].get(game, 0) - seconds)
    save_data(db)
    await interaction.response.send_message(
        "\u2705 **" + member.display_name + "**-tol elveve: **" + game + "** \u2192 -" + str(hours) + "o " + str(minutes) + "p\n"
        "\U0001f4ca Mostani osszes: `" + fmt_time(user["total_seconds"][game]) + "`"
    )
 
@bot.tree.command(name="resetleaderboard", description="[Vezetoseg] Leaderboard resetelese + archivumba mentes")
async def resetleaderboard(interaction: discord.Interaction):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    now = datetime.utcnow()
    rows = build_leaderboard_rows(interaction.guild, now)
    most_active = rows[0][0].display_name if rows and rows[0][2] > 0 else "Senki"
    archive_rows = []
    for member, games, total, uid in rows:
        archive_rows.append({
            "name": member.display_name,
            "uid": uid,
            "games": [(g, s) for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True)],
            "total": total
        })
    archive = load_archive()
    archive.append({"week_start": now.strftime("%Y.%m.%d"), "most_active": most_active, "rows": archive_rows})
    if len(archive) > 12:
        archive = archive[-12:]
    save_archive(archive)
    for uid in list(active_sessions.keys()):
        end_session(uid, now)
    db["users"] = {}
    db["last_reset"] = now.isoformat()
    db["leaderboard_message_id"] = None
    save_data(db)
    channel = get_channel(interaction.guild, LEADERBOARD_CHANNEL)
    summary = "\U0001f504 **Leaderboard resetelve** (" + interaction.user.display_name + " altal)\n"
    summary += "\U0001f3c6 **Ezen a heten a legaktivabb: " + most_active + "**\n"
    summary += "Uj het, uj verseny! Hajra! \U0001f479"
    await interaction.response.send_message(summary)
    if channel and channel != interaction.channel:
        await channel.send(summary)
 
@bot.tree.command(name="debug", description="[Vezetoseg] Aktualis bot adatok")
async def debug(interaction: discord.Interaction):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    now = datetime.utcnow()
    lines = ["**Aktiv sessionok (" + str(len(active_sessions)) + "):**"]
    if active_sessions:
        for uid, session in active_sessions.items():
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else ("ID:" + uid)
            elapsed = int((now - datetime.fromisoformat(session["start"])).total_seconds())
            lines.append("- " + name + " \u2192 " + session["game"] + " (`" + fmt_time(elapsed) + "`)")
    else:
        lines.append("- Senki")
    lines.append("\n**Mentett adatok (" + str(len(db["users"])) + " fo):**")
    for uid, data in db["users"].items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else ("ID:" + uid)
        total = sum(data.get("total_seconds", {}).values())
        if total > 0:
            lines.append("- " + name + ": `" + fmt_time(total) + "`")
    lines.append("\n**Utolso reset:** " + str(db.get("last_reset", "Meg nem volt"))[:19])
    lines.append("**Archivum hetek:** " + str(len(load_archive())))
    embed = discord.Embed(title="\U0001f527 Debug Info", description="\n".join(lines), color=discord.Color.orange(), timestamp=now)
    await interaction.response.send_message(embed=embed, ephemeral=True)
 
@bot.event
async def on_ready():
    await bot.tree.sync()
    scan_presences.start()
    auto_leaderboard.start()
    inaktiv_check.start()
    print(f"Bot bejelentkezve: {bot.user}")
    now = datetime.utcnow()
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or not has_rang(member, FIGYELT_RANG):
                continue
            for activity in member.activities:
                if activity.type == discord.ActivityType.playing:
                    uid = str(member.id)
                    if uid not in active_sessions:
                        active_sessions[uid] = {"game": activity.name, "start": now.isoformat()}
                        print(f"[STARTUP] {member.display_name} jatszik: {activity.name}")
                    break
 
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("HIBA: DISCORD_TOKEN nincs beallitva!")
        exit(1)
    bot.run(TOKEN)
