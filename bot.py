"""Pepcebo, a lift tracker Discord bot: log PRs, see totals and IPF GL points, rep set estimates, progress charts, leaderboards, and rank tiers."""

import asyncio
import os
import re
from typing import Literal, Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

import charts
import db
import ipf_data
import scoring
from scoring import epley, from_kg, gl_points, tier, to_kg, total_for_gl

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # set this while developing for instant command updates

LIFTS = ("squat", "bench", "deadlift")

# "225 x 5", "225x5", "100.5 * 3"
SET_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+)\s*$", re.IGNORECASE)


def fmt(kg: float, unit: str) -> str:
    return f"{from_kg(kg, unit):.1f} {unit}"


def best_total(bests: dict):
    """Returns (total kg, bodyweight kg), or None if a lift is missing.

    Bests can be from different days, so use the heaviest bodyweight out of the three.
    """
    if not all(lift in bests for lift in LIFTS):
        return None
    return sum(bests[l].weight_kg for l in LIFTS), max(bests[l].bodyweight_kg for l in LIFTS)


class LiftBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        db.init()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()  # global sync can take a while to show up

    async def on_ready(self):
        print(f"Logged in as {self.user}")


bot = LiftBot()


@bot.tree.command(name="setup", description="Set your sex, bodyweight, and preferred unit")
@app_commands.guild_only()
@app_commands.describe(sex="Used for the IPF GL formula", bodyweight="Your current bodyweight", unit="lb or kg")
async def setup(
    interaction: discord.Interaction,
    sex: Literal["male", "female"],
    bodyweight: app_commands.Range[float, 50, 700],
    unit: Literal["lb", "kg"],
):
    db.upsert_lifter(interaction.guild_id, interaction.user.id, sex, to_kg(bodyweight, unit), unit)
    await interaction.response.send_message(
        f"Saved: {sex}, {bodyweight:g} {unit}. Log a lift with `/pr`.", ephemeral=True
    )


@bot.tree.command(name="pr", description="Log a lift (1 rep max)")
@app_commands.guild_only()
@app_commands.describe(lift="Which lift", weight="Weight in your unit")
async def pr(
    interaction: discord.Interaction,
    lift: Literal["squat", "bench", "deadlift"],
    weight: app_commands.Range[float, 1, 2000],
):
    lifter = db.get_lifter(interaction.guild_id, interaction.user.id)
    if lifter is None:
        await interaction.response.send_message("Run `/setup` first.", ephemeral=True)
        return
    await log_single(interaction, lifter, lift, weight)


async def log_single(interaction: discord.Interaction, lifter, lift: str, weight: float):
    unit = lifter["unit"]
    weight_kg = to_kg(weight, unit)
    old_best = db.best_lifts(interaction.guild_id, interaction.user.id).get(lift)
    db.add_lift(interaction.guild_id, interaction.user.id, lift, weight_kg, lifter["bodyweight_kg"])

    if old_best is None or weight_kg > old_best.weight_kg:
        msg = f"🏆 **New {lift} PR** for {interaction.user.mention}: {fmt(weight_kg, unit)}"
        if old_best is not None:
            msg += f" (up {fmt(weight_kg - old_best.weight_kg, unit)})"
    else:
        msg = f"Logged {lift} {fmt(weight_kg, unit)}. Your best is still {fmt(old_best.weight_kg, unit)}."
    await interaction.response.send_message(msg)


@bot.tree.command(name="set", description="Log a rep set like 225 x 5 and get an estimated 1 rep max")
@app_commands.guild_only()
@app_commands.describe(lift="Which lift", set="Weight x reps in your unit, like 225 x 5")
async def log_set(interaction: discord.Interaction, lift: Literal["squat", "bench", "deadlift"], set: str):
    lifter = db.get_lifter(interaction.guild_id, interaction.user.id)
    if lifter is None:
        await interaction.response.send_message("Run `/setup` first.", ephemeral=True)
        return

    match = SET_PATTERN.match(set)
    if not match:
        await interaction.response.send_message("Write the set as weight x reps, like `225 x 5`.", ephemeral=True)
        return
    weight, reps = float(match[1]), int(match[2])
    if not 1 <= weight <= 2000 or not 1 <= reps <= scoring.MAX_REPS:
        await interaction.response.send_message(
            f"Weight has to be 1–2000 and reps 1–{scoring.MAX_REPS}.", ephemeral=True
        )
        return
    if reps == 1:
        # A single is a real max, so it counts like /pr
        await log_single(interaction, lifter, lift, weight)
        return

    unit = lifter["unit"]
    weight_kg = to_kg(weight, unit)
    e1rm_kg = epley(weight_kg, reps)
    old = db.best_estimates(interaction.guild_id, interaction.user.id).get(lift)
    db.add_set(interaction.guild_id, interaction.user.id, lift, weight_kg, reps, e1rm_kg, lifter["bodyweight_kg"])

    if old is None or e1rm_kg > old.e1rm_kg:
        msg = (f"📈 **New estimated {lift} max** for {interaction.user.mention}: {fmt(e1rm_kg, unit)} "
               f"(from {fmt(weight_kg, unit)} × {reps})")
        if old is not None:
            msg += f", up {fmt(e1rm_kg - old.e1rm_kg, unit)}"
    else:
        msg = (f"Logged {lift} {fmt(weight_kg, unit)} × {reps} (≈ {fmt(e1rm_kg, unit)}). "
               f"Your best estimate is still {fmt(old.e1rm_kg, unit)}.")
    msg += "\n-# Estimated maxes show in `/stats` and `/history` but don't count for leaderboards or ranks."
    await interaction.response.send_message(msg)


@bot.tree.command(name="history", description="Chart a lift over time")
@app_commands.guild_only()
@app_commands.describe(lift="Which lift", member="Chart someone else instead of you")
async def history(
    interaction: discord.Interaction,
    lift: Literal["squat", "bench", "deadlift"],
    member: Optional[discord.Member] = None,
):
    target = member or interaction.user
    lifter = db.get_lifter(interaction.guild_id, target.id)
    if lifter is None:
        await interaction.response.send_message(f"{target.display_name} hasn't run `/setup` yet.", ephemeral=True)
        return

    singles, sets = db.history(interaction.guild_id, target.id, lift)
    if not singles and not sets:
        await interaction.response.send_message(
            f"{target.display_name} hasn't logged a {lift} yet. Use `/pr` or `/set`.", ephemeral=True
        )
        return

    # Chart in the viewer's unit so it matches what they're used to reading
    viewer = db.get_lifter(interaction.guild_id, interaction.user.id)
    unit = viewer["unit"] if viewer else lifter["unit"]
    singles = [(t, from_kg(kg, unit)) for t, kg in singles]
    sets = [(t, from_kg(kg, unit)) for t, kg in sets]

    await interaction.response.defer()
    title = f"{target.display_name} — {lift.title()}"
    image = await asyncio.to_thread(charts.history_chart, title, unit, singles, sets)
    await interaction.followup.send(file=discord.File(image, filename=f"{lift}_history.png"))


@bot.tree.command(name="stats", description="Show best lifts, total, and IPF GL points")
@app_commands.guild_only()
async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    lifter = db.get_lifter(interaction.guild_id, target.id)
    if lifter is None:
        await interaction.response.send_message(f"{target.display_name} hasn't run `/setup` yet.", ephemeral=True)
        return

    unit = lifter["unit"]
    bests = db.best_lifts(interaction.guild_id, target.id)
    embed = discord.Embed(title=f"{target.display_name}'s lifts", color=discord.Color.gold())
    for lift in LIFTS:
        embed.add_field(name=lift.title(), value=fmt(bests[lift].weight_kg, unit) if lift in bests else "—")

    result = best_total(bests)
    if result:
        total, bodyweight = result
        score = gl_points(total, bodyweight, lifter["sex"])
        embed.add_field(name="Total", value=fmt(total, unit))
        embed.add_field(name="IPF GL", value=f"{score:.1f} (at {fmt(bodyweight, unit)})")
        (name, emoji, color, _), _ = tier(score)
        embed.add_field(name="Rank", value=f"{emoji} {name}")
        embed.color = discord.Color(color)
    else:
        embed.set_footer(text="Log all three lifts to get a total, IPF GL score, and rank.")
    embed.add_field(name="Bodyweight", value=fmt(lifter["bodyweight_kg"], unit))

    estimates = db.best_estimates(interaction.guild_id, target.id)
    if estimates:
        embed.add_field(
            name="Estimated maxes (Epley, not ranked)",
            value="\n".join(
                f"{lift.title()}: {fmt(e.e1rm_kg, unit)} ({fmt(e.weight_kg, unit)} × {e.reps})"
                for lift in LIFTS if (e := estimates.get(lift))
            ),
            inline=False,
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Leaderboard for this server, all bot users, or IPF lifters")
@app_commands.guild_only()
@app_commands.describe(
    scope="server = this server, global = all Pepcebo users, ipf = all-time raw IPF lifters in your class",
    category="Total or a single lift",
    member="IPF only: compare someone else instead of you",
)
async def leaderboard(
    interaction: discord.Interaction,
    scope: Literal["server", "global", "ipf"],
    category: Literal["total", "squat", "bench", "deadlift"] = "total",
    member: Optional[discord.Member] = None,
):
    if scope == "server":
        await bot_leaderboard(interaction, category, db.guild_bests(interaction.guild_id).items(), "Server")
    elif scope == "global":
        await bot_leaderboard(interaction, category, db.all_bests(), "Global")
    else:
        await ipf_leaderboard(interaction, category, member)


async def bot_leaderboard(interaction: discord.Interaction, category: str, profiles, label: str):
    """Leaderboard of bot users: total by IPF GL points, single lifts by weight."""
    viewer = db.get_lifter(interaction.guild_id, interaction.user.id)
    unit = viewer["unit"] if viewer else "kg"

    ranked = []
    for user_id, data in profiles:
        bests = data["bests"]
        if category == "total":
            result = best_total(bests)
            if result:
                total, bodyweight = result
                ranked.append((gl_points(total, bodyweight, data["sex"]), total, user_id))
        elif category in bests:
            weight = bests[category].weight_kg
            ranked.append((weight, weight, user_id))

    if not ranked:
        empty = "Nobody has logged all three lifts yet." if category == "total" else f"Nobody has logged a {category} yet."
        await interaction.response.send_message(empty)
        return

    # Best first, and only each user's best entry (global can have one profile per server)
    ranked.sort(reverse=True)
    seen = set()
    ranked = [r for r in ranked if not (r[2] in seen or seen.add(r[2]))][:10]

    if label == "Server":
        names = {uid: f"<@{uid}>" for _, _, uid in ranked}
    else:
        # Mentions of people outside this server don't render, so show their Discord name
        names = {}
        for _, _, uid in ranked:
            user = bot.get_user(uid)
            if user is None:
                try:
                    user = await bot.fetch_user(uid)
                except discord.HTTPException:
                    user = None
            names[uid] = discord.utils.escape_markdown(user.display_name) if user else "Unknown user"

    medals = ["🥇", "🥈", "🥉"]
    if category == "total":
        title = f"{label} Leaderboard — Total (IPF GL)"
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} {names[uid]} — **{score:.1f}** GL {tier(score)[0][1]} "
            f"({fmt(total, unit)} total)"
            for i, (score, total, uid) in enumerate(ranked)
        ]
    else:
        title = f"{label} Leaderboard — {category.title()}"
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} {names[uid]} — **{fmt(weight, unit)}**"
            for i, (weight, _, uid) in enumerate(ranked)
        ]
    embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


async def ipf_leaderboard(interaction: discord.Interaction, category: str, member: Optional[discord.Member]):
    """Top raw IPF lifters in the weight class, plus where you'd place among them."""
    stats = ipf_data.load()
    if stats is None:
        await interaction.response.send_message(
            "IPF data hasn't been downloaded yet. Run `python ipf_data.py` on the bot's machine.", ephemeral=True
        )
        return

    target = member or interaction.user
    lifter = db.get_lifter(interaction.guild_id, target.id)
    if lifter is None:
        await interaction.response.send_message(f"{target.display_name} hasn't run `/setup` yet.", ephemeral=True)
        return

    unit = lifter["unit"]
    sex = lifter["sex"]
    bests = db.best_lifts(interaction.guild_id, target.id)
    if category == "total":
        result = best_total(bests)
        mine, bodyweight = result if result else (None, None)
    else:
        best = bests.get(category)
        mine, bodyweight = best if best else (None, None)
    # Use the class they were in when they did the lift
    wc = ipf_data.weight_class(bodyweight or lifter["bodyweight_kg"], sex)
    entry = stats[sex][wc][category]

    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i] if i < 3 else f'`{i + 1}.`'} {re.sub(r' #\d+$', '', name)}"
        f"{f' ({country})' if country else ''} — **{fmt(kg, unit)}**"
        for i, (name, country, kg) in enumerate(entry["top"])
    ]
    embed = discord.Embed(
        title=f"IPF {sex.title()} {wc} kg — {category.title()}",
        description="\n".join(lines),
        color=discord.Color.blue(),
    )

    if mine is None:
        need = "all three lifts" if category == "total" else f"a {category}"
        embed.add_field(name=target.display_name, value=f"Log {need} with `/pr` to see where you stand.", inline=False)
    else:
        beats, rank, count = ipf_data.compare(mine, entry["values"])
        embed.add_field(
            name=target.display_name,
            value=f"{fmt(mine, unit)} beats **{beats:.1f}%** of {count:,} IPF lifters in this class "
                  f"(would rank #{rank:,}).",
            inline=False,
        )
    embed.set_footer(text="Best raw full-power meet results, all-time. Data: OpenIPF (openipf.org)")
    await interaction.response.send_message(embed=embed)


def tier_list() -> str:
    lines = []
    for i, (name, emoji, _, low) in enumerate(scoring.TIERS):
        span = f"{low}+" if i == len(scoring.TIERS) - 1 else f"{low}–{scoring.TIERS[i + 1][3]}"
        lines.append(f"{emoji} **{name}** — {span} GL")
    return "\n".join(lines)


@bot.tree.command(name="ranking", description="Your rank tier, from Bronze to Ascender, based on IPF GL points")
@app_commands.guild_only()
@app_commands.describe(member="See someone else's rank instead")
async def ranking(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    lifter = db.get_lifter(interaction.guild_id, target.id)
    if lifter is None:
        await interaction.response.send_message(f"{target.display_name} hasn't run `/setup` yet.", ephemeral=True)
        return

    result = best_total(db.best_lifts(interaction.guild_id, target.id))
    if result is None:
        embed = discord.Embed(
            title=f"{target.display_name} is unranked",
            description="Log a squat, bench, and deadlift with `/pr` to get a rank. "
                        "Estimated maxes from `/set` don't count.",
            color=discord.Color.light_grey(),
        )
        embed.add_field(name="Tiers", value=tier_list(), inline=False)
        await interaction.response.send_message(embed=embed)
        return

    unit = lifter["unit"]
    total, bodyweight = result
    score = gl_points(total, bodyweight, lifter["sex"])
    (name, emoji, color, low), up = tier(score)
    embed = discord.Embed(
        title=f"{emoji} {target.display_name} — {name}",
        description=f"**{score:.1f} GL** from a {fmt(total, unit)} total at {fmt(bodyweight, unit)}",
        color=discord.Color(color),
    )
    if up:
        next_name, next_emoji, _, next_low = up
        filled = int((score - low) / (next_low - low) * 10)
        need = total_for_gl(next_low, bodyweight, lifter["sex"]) - total
        embed.add_field(
            name=f"Next: {next_emoji} {next_name} ({next_low} GL)",
            value=f"{'▰' * filled}{'▱' * (10 - filled)} {next_low - score:.1f} GL to go\n"
                  f"About {fmt(need, unit)} more on your total at this bodyweight.",
            inline=False,
        )
    else:
        embed.add_field(name="Top tier", value="Nowhere left to climb. That's world-class lifting.", inline=False)
    embed.add_field(name="Tiers", value=tier_list(), inline=False)
    embed.set_footer(text="Ranks use logged 1 rep maxes only, scored with IPF GL points.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="faq", description="How the bot works, how to get started, and how IPF GL points are calculated")
async def faq(interaction: discord.Interaction):
    (ma, mb, mc), (fa, fb, fc) = scoring.MALE, scoring.FEMALE
    embed = discord.Embed(
        title="Pepcebo FAQ",
        description="Track your squat, bench, and deadlift, see your total and IPF GL points, "
                    "and compare yourself with this server, every Pepcebo user, or real IPF lifters.",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="🚀 Getting started",
        value="1. `/setup` — enter your sex, bodyweight, and unit (lb or kg).\n"
              "2. `/pr` — log your best single (1 rep max) for squat, bench, and deadlift.\n"
              "3. `/stats` — see your bests, total, and IPF GL points.\n"
              "4. `/leaderboard` and `/ranking` — see where you stand.",
        inline=False,
    )
    embed.add_field(
        name="📋 Commands",
        value="`/setup` — rerun any time your bodyweight changes. Each lift keeps the bodyweight "
              "you had when you logged it, so old GL scores don't shift.\n"
              "`/pr lift weight` — log a single. A new best is announced as a PR; anything lower is "
              "still saved but your best stays the same.\n"
              "`/set lift 225 x 5` — log a rep set and get an estimated max (see below).\n"
              "`/stats [member]` — bests, estimated maxes, total, GL points, rank, and bodyweight.\n"
              "`/history lift [member]` — a chart of that lift over time.\n"
              "`/leaderboard scope [category] [member]` — top 10 lists (see below).\n"
              "`/ranking [member]` — your rank tier.\n"
              "`/faq` — this page.",
        inline=False,
    )
    embed.add_field(
        name="📈 Rep sets and estimated maxes",
        value="`/set` estimates your 1 rep max with the Epley formula: **weight × (1 + reps / 30)**. "
              f"So 225 × 5 ≈ {scoring.epley(225, 5):.0f}. Up to {scoring.MAX_REPS} reps; past ~10 it gets less accurate. "
              "Estimates are kept apart from real singles and never count for leaderboards or ranks. "
              "A set of 1 is logged as a real single, same as `/pr`.",
        inline=False,
    )
    embed.add_field(
        name="🎖️ Ranking tiers",
        value="Your rank comes from your IPF GL points (logged singles only):\n" + tier_list(),
        inline=False,
    )
    embed.add_field(
        name="🏆 Leaderboards",
        value="**`scope: server`** — top 10 in this Discord server. `total` is ranked by IPF GL points "
              "(you need all three lifts logged); `squat`, `bench`, or `deadlift` are ranked by weight.\n"
              "**`scope: global`** — the same, but across everyone using Pepcebo in every server. "
              "If you're in several servers, your best profile counts.\n"
              "**`scope: ipf`** — top 10 all-time raw IPF lifters in your weight class (from your "
              "bodyweight when you logged the lift), plus the percentage of them you beat. Uses best results from raw "
              "full-power IPF meets via OpenIPF. Competition lifts are judged, so treat it as a rough guide.",
        inline=False,
    )
    embed.add_field(
        name="📐 What are IPF GL points?",
        value="The International Powerlifting Federation's formula for comparing lifters of different "
              "bodyweights. Heavier lifters lift more but not proportionally more, so GL scores your "
              "total against what's expected at your bodyweight. A higher score is better, no matter "
              "your weight class. Roughly: **~100+** is world-class; most gym lifters are well below.",
        inline=False,
    )
    embed.add_field(
        name="🧮 How GL is calculated",
        value="```\nGL = total × 100 / (A − B × e^(−C × bodyweight))\n```"
              "Total and bodyweight are in kg. Your best lifts may be from different days, so your "
              "total is scored at the heaviest bodyweight among them. The bot uses the raw (classic) coefficients:\n"
              f"```\nMen:   A = {ma}  B = {mb}  C = {mc}\nWomen: A = {fa}  B = {fb}  C = {fc}\n```"
              "The bottom half is the **benchmark total** that scores exactly 100 GL at your bodyweight.\n"
              "• **A** — the ceiling: the benchmark for a very heavy lifter.\n"
              "• **B** — how far below the ceiling light lifters start.\n"
              "• **C** — how fast the benchmark levels off as bodyweight goes up.\n"
              "**Example:** a 90 kg man with a 600 kg total → 600 × 100 / (1199.73 − 1025.18 × e^(−0.829)) "
              f"≈ **{scoring.gl_points(600, 90, 'male'):.1f} GL**.",
        inline=False,
    )
    embed.add_field(
        name="❓ Other questions",
        value="**Can I use lb?** Yes. Everything is stored in kg and shown in your unit.\n"
              "**Typo in a lift?** Your best is the heaviest you've logged, so a too-high entry will stick. "
              "Ask the bot owner to remove it.\n"
              "**Is my data shared between servers?** No, each server has its own profiles and lifts.",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN in .env")
    bot.run(TOKEN)
