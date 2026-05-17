import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
 
# ─── Beállítások ───────────────────────────────────────────────────────────────
DATA_FILE = "activity_data.json"
FIGYELT_RANG = "El Diablo | 👹"   # Csak ezt a rangot figyelje
 
# ─── Bot inicializálás ─────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.presences = True        # Szükséges: Activity figyeléshez
intents.members = True          # Szükséges: Tagok figyeléséhez
intents.message_content = True
 
bot = commands.Bot(command_prefix="!", intents=intents)
 
# ─── Adatok betöltése/mentése ──────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
 
def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
# Aktív sessionök: {user_id: {"game": "...", "start": "ISO időbélyeg"}}
active_sessions = {}
activity_data = load_data()
 
def get_user_data(user_id: str):
    if user_id not in activity_data:
        activity_data[user_id] = {"sessions": [], "total_seconds": defaultdict(int)}
    return activity_data[user_id]
 
# ─── Esemény: Aktivitás változás ───────────────────────────────────────────────
def has_figyelt_rang(member: discord.Member) -> bool:
    """Ellenőrzi, hogy a tagnak megvan-e a figyelt rang."""
    return any(role.name == FIGYELT_RANG for role in member.roles)
 
@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    # Csak az "El Diablo | 👹" rangú tagokat figyeljük
    if not has_figyelt_rang(after):
        return
 
    user_id = str(after.id)
    now = datetime.utcnow()
 
    # Előző játék lekérése
    before_game = None
    for activity in before.activities:
        if activity.type == discord.ActivityType.playing:
            before_game = activity.name
            break
 
    # Jelenlegi játék lekérése
    after_game = None
    for activity in after.activities:
        if activity.type == discord.ActivityType.playing:
            after_game = activity.name
            break
 
    # Ha volt aktív session és változott / leállt
    if user_id in active_sessions and active_sessions[user_id]["game"] != after_game:
        session = active_sessions.pop(user_id)
        start_time = datetime.fromisoformat(session["start"])
        duration_seconds = int((now - start_time).total_seconds())
        game_name = session["game"]
 
        user_data = get_user_data(user_id)
        user_data["sessions"].append({
            "game": game_name,
            "start": session["start"],
            "end": now.isoformat(),
            "duration_seconds": duration_seconds
        })
 
        if "total_seconds" not in user_data:
            user_data["total_seconds"] = {}
        user_data["total_seconds"][game_name] = (
            user_data["total_seconds"].get(game_name, 0) + duration_seconds
        )
 
        save_data(activity_data)
        print(f"[LOG] {after.display_name} abbahagyta: {game_name} ({duration_seconds}s)")
 
    # Ha új játék kezdődött
    if after_game and after_game != before_game:
        active_sessions[user_id] = {
            "game": after_game,
            "start": now.isoformat()
        }
        print(f"[LOG] {after.display_name} elkezdte: {after_game}")
 
# ─── Slash parancs: /stats ─────────────────────────────────────────────────────
@bot.tree.command(name="stats", description="Megmutatja a játékidő statisztikákat")
@app_commands.describe(member="Melyik tag statisztikáját nézd? (alapértelmezett: saját)")
async def stats(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    user_id = str(target.id)
    user_data = activity_data.get(user_id, {})
 
    if not user_data or not user_data.get("total_seconds"):
        await interaction.response.send_message(
            f"**{target.display_name}** még nem játszott semmit amit mértem volna. 🎮",
            ephemeral=True
        )
        return
 
    totals = user_data["total_seconds"]
    sorted_games = sorted(totals.items(), key=lambda x: x[1], reverse=True)
 
    embed = discord.Embed(
        title=f"🎮 {target.display_name} játékidő statisztikái",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
 
    lines = []
    for game, seconds in sorted_games[:15]:  # max 15 játék
        h, m = divmod(seconds // 60, 60)
        s = seconds % 60
        # Jelölje ha éppen most játssza
        live = ""
        if user_id in active_sessions and active_sessions[user_id]["game"] == game:
            live = " 🔴 *most játszik*"
        lines.append(f"**{game}**: {h}ó {m}p {s}s{live}")
 
    embed.description = "\n".join(lines)
    embed.set_footer(text="Csak azokat méri, amit Discord-on keresztül látok")
 
    await interaction.response.send_message(embed=embed)
 
# ─── Slash parancs: /nowplaying ───────────────────────────────────────────────
@bot.tree.command(name="nowplaying", description="Ki mit játszik most a szerveren?")
async def nowplaying(interaction: discord.Interaction):
    if not active_sessions:
        await interaction.response.send_message("Senki sem játszik éppen semmit. 😴", ephemeral=True)
        return
 
    embed = discord.Embed(
        title="🎮 Aktív játékosok",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
 
    now = datetime.utcnow()
    lines = []
    for uid, session in active_sessions.items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ID:{uid}"
        start = datetime.fromisoformat(session["start"])
        elapsed = int((now - start).total_seconds())
        h, m = divmod(elapsed // 60, 60)
        s = elapsed % 60
        lines.append(f"**{name}** → {session['game']} (óta: {h}ó {m}p {s}s)")
 
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)
 
# ─── Slash parancs: /toprpg ───────────────────────────────────────────────────
@bot.tree.command(name="toprpg", description="Ki játszotta legtöbbet a Droxen RP-t?")
@app_commands.describe(game="Játék neve (alapértelmezett: Droxen RP)")
async def toprpg(interaction: discord.Interaction, game: str = "Droxen RP"):
    results = []
    for uid, data in activity_data.items():
        total = data.get("total_seconds", {}).get(game, 0)
        if total > 0:
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            results.append((name, total))
 
    if not results:
        await interaction.response.send_message(f"Még senki sem játszott **{game}**-t.", ephemeral=True)
        return
 
    results.sort(key=lambda x: x[1], reverse=True)
 
    embed = discord.Embed(
        title=f"🏆 {game} toplista",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
 
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, seconds) in enumerate(results[:10]):
        h, m = divmod(seconds // 60, 60)
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} **{name}**: {h}ó {m}p")
 
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)
 
# ─── Bot indulás ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot bejelentkezve: {bot.user} (ID: {bot.user.id})")
    print(f"📊 {len(activity_data)} felhasználó adata betöltve")
 
# ─── Indítás ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ HIBA: DISCORD_TOKEN környezeti változó nincs beállítva!")
        print("   Futtasd így: DISCORD_TOKEN=your_token python bot.py")
        exit(1)
    bot.run(TOKEN)
