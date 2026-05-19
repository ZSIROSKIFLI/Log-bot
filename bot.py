# -*- coding: utf-8 -*-
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
FIGYELT_JATEKOK = ["DRP", "FiveM", "Aeris ▸ PvP"]
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

def get_week_label(dt):
    # Hét eleje = hétfő, vége = vasárnap
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%m.%d") + "-" + sunday.strftime("%m.%d")

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
        drp_secs = games.get("DRP", 0)
        rows.append((member, games, drp_secs, sum(games.values()), uid))
    rows.sort(key=lambda x: (x[2], x[3]), reverse=True)
    return rows

def build_leaderboard_embed(guild, now):
    rows = build_leaderboard_rows(guild, now)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (member, games, drp_secs, total, uid) in enumerate(rows):
        place = medals[i] if i < 3 else f"**{i+1}.**"
        live = " 🔴" if uid in active_sessions else ""
        name = member.display_name
        if games:
            ordered = []
            if "DRP" in games:
                ordered.append(("DRP", games["DRP"]))
            for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True):
                if g != "DRP":
                    ordered.append((g, s))
            parts = ", ".join(g + " `" + fmt_time(s) + "`" for g, s in ordered)
            lines.append(place + " **" + name + "**" + live + " — " + parts)
        else:
            lines.append(place + " **" + name + "** — *még nem játszott*")
    last_reset = str(db.get("last_reset", "Még nem volt"))[:10]
    embed = discord.Embed(
        title="🏆 El Diablo Leaderboard",
        description="\n".join(lines) if lines else "*Még nincs adat*",
        color=discord.Color.red(),
        timestamp=now
    )
    embed.set_footer(text="🔄 30 másodpercenként frissül | Utolsó reset: " + last_reset)
    return embed

@tasks.loop(seconds=30)
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
            except Exception:
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
                except Exception:
                    pass
            h, m2 = divmod(weekly // 60, 60)
            lines.append(
                "- **" + member.display_name + "** \u2014 ezen a h\u00e9ten `" +
                str(h) + "\u00f3 " + str(m2) + "p` j\u00e1t\u00e9kid\u0151 (" + str(days) + " napja inakt\u00edv)"
            )
        if inaktiv_ch:
            ping = vezetes_role.mention if vezetes_role else "@Vezet\u0151s\u00e9g"
            lines_str = "\n".join(lines)
            msg = (
                ping + " \U0001f47b **Inaktivit\u00e1s jelent\u00e9s**\n\n"
                "Az al\u00e1bbi tagok ezen a h\u00e9ten **nem \u00e9rt\u00e9k el a " + str(INAKTIV_MIN_ORA) + " \u00f3r\u00e1s minimumot** "
                "\u00e9s legal\u00e1bb " + str(INAKTIV_NAPOK) + " napja nem voltak akt\u00edvak:\n\n" +
                lines_str +
                "\n\n\U0001f4cc Automatikusan megkaptk az **Inaktiv Tag | \U0001f47b** rangot."
            )
            await inaktiv_ch.send(msg)

@tasks.loop(minutes=5)
async def scan_presences():
    now = datetime.utcnow()
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or not has_rang(member, FIGYELT_RANG):
                continue
            uid = str(member.id)
            current_game = next(
                (a.name for a in member.activities
                 if a.type == discord.ActivityType.playing and a.name in FIGYELT_JATEKOK), None
            )
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
    pass

@bot.event
async def on_presence_update(before, after):
    if not has_rang(after, FIGYELT_RANG):
        return
    user_id = str(after.id)
    now = datetime.utcnow()
    before_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing and a.name in FIGYELT_JATEKOK), None)
    after_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing and a.name in FIGYELT_JATEKOK), None)
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

@bot.tree.command(name="resetleaderboard", description="[Vezetoseg] Leaderboard resetelese")
async def resetleaderboard(interaction: discord.Interaction):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    now = datetime.utcnow()
    rows = build_leaderboard_rows(interaction.guild, now)
    most_active = rows[0][0].display_name if rows and rows[0][2] > 0 else "Senki"
    archive_rows = []
    for member, games, drp_secs, total, uid in rows:
        archive_rows.append({
            "name": member.display_name,
            "uid": uid,
            "games": [(g, s) for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True)],
            "total": total
        })
    archive = load_archive()
    archive.append({"week_start": get_week_label(now), "most_active": most_active, "rows": archive_rows})
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
    summary = (
        "\U0001f504 **Leaderboard resetelve** (" + interaction.user.display_name + " altal)\n"
        "\U0001f3c6 **Ezen a heten a legaktivabb: " + most_active + "**\n"
        "Uj het, uj verseny! Hajra! \U0001f479"
    )
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
    embed = discord.Embed(
        title="\U0001f527 Debug Info",
        description="\n".join(lines),
        color=discord.Color.orange(),
        timestamp=now
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="archivum", description="Előző hetek megtekintése és letöltése")
async def archivum(interaction: discord.Interaction):
    archive = load_archive()
    if not archive:
        await interaction.response.send_message("Még nincs archivált hét.", ephemeral=True)
        return

    options = []
    for i, entry in enumerate(reversed(archive)):
        most_active = entry.get("most_active", "?")
        is_mentes = entry.get("type") == "mentes"
        prefix = "💾 " if is_mentes else "📅 "
        suffix = "" if is_mentes else " hete"
        saved_by = " (mentette: " + entry.get("saved_by", "?") + ")" if is_mentes else ""
        options.append(discord.SelectOption(
            label=prefix + entry["week_start"] + suffix,
            description="Legaktivabb: " + most_active + saved_by,
            value=str(len(archive) - 1 - i)
        ))

    class ArchivumSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(placeholder="Válassz egy hetet...", options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            idx = int(self.values[0])
            entry = archive[idx]
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, row in enumerate(entry["rows"]):
                place = medals[i] if i < 3 else str(i+1) + "."
                parts = ", ".join(g + " " + fmt_time(s) for g, s in row["games"])
                lines.append(place + " " + row["name"] + " — " + (parts if parts else "nem játszott"))

            embed = discord.Embed(
                title="📅 " + entry["week_start"] + " hete",
                description="\n".join(lines) if lines else "*Nincs adat*",
                color=discord.Color.blurple()
            )
            embed.set_footer(text="Legaktívabb: " + entry.get("most_active", "?"))

            view = DownloadCloseView(idx, entry)
            await interaction.response.edit_message(embed=embed, view=view)

    class DownloadCloseView(discord.ui.View):
        def __init__(self, idx, entry):
            super().__init__(timeout=120)
            self.idx = idx
            self.entry = entry

        @discord.ui.button(label="⬇️ Letöltés", style=discord.ButtonStyle.primary)
        async def download(self, interaction: discord.Interaction, button: discord.ui.Button):
            entry = self.entry
            lines = ["El Diablo Leaderboard - " + entry["week_start"] + " hete"]
            lines.append("Legaktivabb: " + entry.get("most_active", "?"))
            lines.append("=" * 40)
            for i, row in enumerate(entry["rows"]):
                place = str(i+1) + "."
                parts = ", ".join(g + " " + fmt_time(s) for g, s in row["games"])
                total = fmt_time(row.get("total", 0))
                lines.append(place + " " + row["name"] + " | Osszes: " + total + " | " + (parts if parts else "nem jatszott"))
            content_str = "\n".join(lines)
            file_bytes = content_str.encode("utf-8")
            import io
            file = discord.File(io.BytesIO(file_bytes), filename="leaderboard_" + entry["week_start"].replace(".", "-") + ".txt")
            await interaction.response.send_message(file=file, ephemeral=True)

        @discord.ui.button(label="✖️ Bezárás", style=discord.ButtonStyle.danger)
        async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="*Bezárva.*", embed=None, view=None)

    class ArchivumView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(ArchivumSelect())

    embed = discord.Embed(
        title="📚 Archívum",
        description="Válassz egy hetet az alábbi listából:",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=ArchivumView(), ephemeral=True)

@bot.tree.command(name="torleslog", description="[Vezetoseg] Egy mentesi log torlese")
async def torleslog(interaction: discord.Interaction):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    archive = load_archive()
    if not archive:
        await interaction.response.send_message("Nincs torolheto log.", ephemeral=True)
        return
    options = []
    for i, entry in enumerate(reversed(archive)):
        is_mentes = entry.get("type") == "mentes"
        prefix = "\U0001f4be " if is_mentes else "\U0001f4c5 "
        options.append(discord.SelectOption(
            label=prefix + entry["week_start"],
            description=("Mentette: " + entry.get("saved_by", "?")) if is_mentes else "Heti reset",
            value=str(len(archive) - 1 - i)
        ))

    class TorlesSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(placeholder="Melyiket torold?", options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            idx = int(self.values[0])
            entry = archive[idx]
            label = entry["week_start"]

            class ConfirmView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=30)

                @discord.ui.button(label="\U0001f5d1\ufe0f Torles megerositese", style=discord.ButtonStyle.danger)
                async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                    archive.pop(idx)
                    save_archive(archive)
                    await interaction.response.edit_message(
                        content="\u2705 **`" + label + "`** log torolve.",
                        embed=None, view=None
                    )

                @discord.ui.button(label="\u2716\ufe0f Megse", style=discord.ButtonStyle.secondary)
                async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await interaction.response.edit_message(content="Torles megszakitva.", embed=None, view=None)

            await interaction.response.edit_message(
                content="Biztosan torled: **`" + label + "`**?",
                embed=None, view=ConfirmView()
            )

    class TorlesView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(TorlesSelect())

    await interaction.response.send_message("Valassz egy logot a torleshez:", view=TorlesView(), ephemeral=True)

@bot.tree.command(name="mentes", description="[Vezetoseg] Aktualis allapat mentese a logba")
@app_commands.describe(nev="A mentes neve (pl. szerda-este)")
async def mentes(interaction: discord.Interaction, nev: str = ""):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    now = datetime.utcnow()
    rows = build_leaderboard_rows(interaction.guild, now)
    snapshot_rows = []
    for member, games, drp_secs, total, uid in rows:
        snapshot_rows.append({
            "name": member.display_name,
            "uid": uid,
            "games": [(g, s) for g, s in sorted(games.items(), key=lambda x: x[1], reverse=True)],
            "total": total
        })
    week_key = get_week_label(now)
    label = nev if nev else week_key
    most_active = rows[0][0].display_name if rows and rows[0][2] > 0 else "Senki"
    snapshot = {
        "week_start": label,
        "week_key": week_key,
        "most_active": most_active,
        "rows": snapshot_rows,
        "type": "mentes",
        "saved_by": interaction.user.display_name,
        "saved_at": now.isoformat()
    }
    archive = load_archive()
    # Ha már van ugyanolyan week_key, frissítse azt
    updated = False
    for i, entry in enumerate(archive):
        if entry.get("week_key") == week_key or entry.get("week_start") == label:
            archive[i] = snapshot
            updated = True
            break
    if not updated:
        archive.append(snapshot)
    if len(archive) > 24:
        archive = archive[-24:]
    save_archive(archive)
    status = "frissitve" if updated else "mentve"
    await interaction.response.send_message(
        "\u2705 **" + status.capitalize() + ":** `" + label + "` (" + str(len(snapshot_rows)) + " tag adatai elmentve)\n"
        "Visszanezni: `/archivum`",
        ephemeral=True
    )

@bot.tree.command(name="frissleaderboard", description="[Vezetoseg] Leaderboard azonnali frissitese")
async def frissleaderboard(interaction: discord.Interaction):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    now = datetime.utcnow()
    channel = get_channel(interaction.guild, LEADERBOARD_CHANNEL)
    if not channel:
        await interaction.followup.send("Nem talalom a leaderboard csatornat!", ephemeral=True)
        return
    embed = build_leaderboard_embed(interaction.guild, now)
    msg_id = db.get("leaderboard_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
            await interaction.followup.send("\u2705 Leaderboard frissitve!", ephemeral=True)
            return
        except Exception:
            pass
    msg = await channel.send(embed=embed)
    db["leaderboard_message_id"] = str(msg.id)
    save_data(db)
    await interaction.followup.send("\u2705 Leaderboard frissitve!", ephemeral=True)

@bot.tree.command(name="removenemmegfigy", description="[Vezetoseg] Torli a nem figyelt jatekok adatait")
@app_commands.describe(member="Melyik tagnak (elhagyhatho = mindenki)")
async def removenemmegfigy(interaction: discord.Interaction, member: discord.Member = None):
    if not has_rang(interaction.user, VEZETES_RANG):
        await interaction.response.send_message("Nincs jogosultsagod! \U0001f6ab", ephemeral=True)
        return

    removed_count = 0
    if member:
        # Csak egy embernél
        uid = str(member.id)
        user_data = db["users"].get(uid, {})
        to_delete = [g for g in list(user_data.get("total_seconds", {}).keys()) if g not in FIGYELT_JATEKOK]
        for g in to_delete:
            del user_data["total_seconds"][g]
            removed_count += 1
        save_data(db)
        await interaction.response.send_message(
            "\u2705 **" + member.display_name + "**-tol **" + str(removed_count) + "** nem figyelt jatek torolve."
        )
    else:
        # Mindenkinél
        for uid, user_data in db["users"].items():
            to_delete = [g for g in list(user_data.get("total_seconds", {}).keys()) if g not in FIGYELT_JATEKOK]
            for g in to_delete:
                del user_data["total_seconds"][g]
                removed_count += 1
        save_data(db)
        await interaction.response.send_message(
            "\u2705 Mindenkit\u0151l osszesen **" + str(removed_count) + "** nem figyelt jatek torolve."
        )

@bot.tree.command(name="sugo", description="Osszes parancs leirasa")
async def sugo(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 El Diablo Activity Track – Parancsok",
        color=discord.Color.blurple()
    )

    embed.add_field(name="👥 Mindenki hasznalatja", value="​", inline=False)

    embed.add_field(
        name="/leaderboard",
        value="Megjeleníti a heti El Diablo toplistát. Mindenki látható aki rendelkezik az El Diablo ranggal, mellettük a DRP/FiveM/Aeris játékidők.",
        inline=False
    )
    embed.add_field(
        name="/nowplaying",
        value="Megmutatja ki játszik éppen, mivel, mióta, mikor kezdte (magyar idő), és mennyi az összes heti ideje abból a játékból.",
        inline=False
    )
    embed.add_field(
        name="/gamestats [jatek]",
        value="Egy adott játék statisztikái ezen a héten. Pl: `/gamestats DRP` – ki mennyit játszotta, hányan összesen, összes eltöltött idő.",
        inline=False
    )
    embed.add_field(
        name="/archivum",
        value="Előző hetek és kézi mentések megtekintése. Legördülő menüből választhatsz hetet, majd letöltheted `.txt` formátumban vagy bezárhatod.",
        inline=False
    )

    embed.add_field(name="🍺 Csak Vezetőség használhatja", value="​", inline=False)

    embed.add_field(
        name="/addtime [@tag] [jatek] [hours] [minutes]",
        value="Kézzel adsz hozzá játékidőt valakinek. Pl: `/addtime @Lompos DRP 2 30` = +2 óra 30 perc DRP.",
        inline=False
    )
    embed.add_field(
        name="/removetime [@tag] [jatek] [hours] [minutes]",
        value="Elveszel játékidőt valakitől. Ugyanúgy működik mint az addtime, csak kivon.",
        inline=False
    )
    embed.add_field(
        name="/resetleaderboard",
        value="Elmenti az aktuális hetet az archívumba, majd nulláz mindent. Kiírja ki volt a legaktívabb, és küld üzenetet a leaderboard csatornába.",
        inline=False
    )
    embed.add_field(
        name="/mentes [nev]",
        value="Pillanatkép mentése az aktuális állásról. Ha már van mentés ezen a héten, frissíti azt. A név opcionális – ha nem adsz meg, `05.18-05.24 20:47` formátumú lesz. Visszanézni: `/archivum`.",
        inline=False
    )
    embed.add_field(
        name="/torleslog",
        value="Egy archivált log törlése. Legördülő menüből kiválasztod melyiket, majd megerősítéssel törli – a Volume-ból is eltűnik véglegesen.",
        inline=False
    )
    embed.add_field(
        name="/frissleaderboard",
        value="Azonnal frissíti a leaderboard üzenetet a `aktivitas-mero` csatornában. Hasznos ha valamiért nem frissült automatikusan.",
        inline=False
    )
    embed.add_field(
        name="/removenemmegfigy [@tag]",
        value="Törli a nem figyelt játékok adatait (csak DRP, FiveM, Aeris marad). Ha megadsz egy tagot, csak annál törli. Ha nem adsz meg senkit, mindenkinél.",
        inline=False
    )
    embed.add_field(
        name="/debug",
        value="Megmutatja mi van a bot memóriájában: ki van aktív sessionben, ki mennyi időt gyűjtött, mikor volt az utolsó reset, hány archivált hét van.",
        inline=False
    )

    embed.set_footer(text="Bot csak az El Diablo | 👹 rangú tagokat figyeli | Méri: DRP, FiveM, Aeris ▸ PvP")
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
                if activity.type == discord.ActivityType.playing and activity.name in FIGYELT_JATEKOK:
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
