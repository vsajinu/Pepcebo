# Pepcebo

Pepcebo is a Discord bot for tracking powerlifting PRs. You log your squat, bench, and deadlift, and it works out your total and IPF GL or DOTS points. It can also put you on leaderboards against people in your server, everyone using the bot, or real lifters from IPF meets in your weight class.

## Commands

- `/setup` saves your sex, bodyweight, and unit (lb or kg).
- `/setting` opens a private panel where you can update your bodyweight, switch units, switch between IPF GL and DOTS scoring, and pick a progress graph (bodyweight, squat, bench, or deadlift).
- `/pr` logs a single (1 rep max). If it beats your old best, the bot announces it as a PR.
- `/set` logs a rep set like `225 x 5` and estimates your max from it (see below).
- `/stats` shows your bests, estimated maxes, total, points, rank, and bodyweight. You can pass a member to see someone else's.
- `/history` sends a chart of one lift over time, with your logged singles and your estimated maxes as separate lines.
- `/leaderboard` shows a top 10. The scope can be `server`, `global`, or `professional` (raw IPF meet lifters), and the category can be total or a single lift.
- `/ranking` shows your rank tier (Bronze up to Ascender) and how far you are from the next one.
- `/attempts` suggests 1st, 2nd, and 3rd meet attempts for a target total or lift (see below).
- `/1rm` estimates a max from a working set with seven standard formulas. It doesn't log anything.
- `/faq` explains how everything works, including the GL and DOTS formulas.

## How scoring works

GL points are the IPF's formula for comparing lifters at different bodyweights. Heavier lifters can lift more, but not proportionally more, so GL compares your total to what's expected at your bodyweight. The bot uses the raw (classic) coefficients from [scoring.py](scoring.py).

DOTS does the same job and is popular outside the IPF. It runs about 4.9× GL at every bodyweight, so the two rank people almost identically. GL is the default; anyone can switch in `/setting`. `/stats`, `/ranking`, and `/leaderboard` always show scores in the formula of whoever runs the command.

Every lift saves the bodyweight you had when you logged it. That way, if you cut or bulk later, your old lifts keep their original GL points. Since your three best lifts might come from different days, your total gets scored at the heaviest of those bodyweights. That's closer to a real meet where you weigh in once, and it means you can't log a squat at 100 kg, cut to 70 kg, and have the squat count as a 70 kg lift.

## Estimated maxes

`/set` uses the Epley formula, `weight × (1 + reps / 30)`, so 225 × 5 comes out to about 262. It accepts up to 20 reps, though estimates get shaky past about 10. Sets are stored in their own table, apart from your singles, so estimates show up in `/stats` and `/history` but never count toward leaderboards or ranks. A set of 1 is just a single, so it gets logged the same way `/pr` does.

## Meet attempts

`/attempts` plans an opener at about 91% of your target, a second at about 96%, and a third at the target itself. Openers round down so they stay easy. Attempts round to 2.5 kg or 5 lb jumps. If you leave the target out, it uses your logged best, or your estimated max if you haven't logged a single. For a total, the target is split across the three lifts in the same proportions as your current bests. If you haven't logged all three, it uses a typical split of 35% squat, 25% bench, and 40% deadlift.

## Rank tiers

`/ranking` places you by the points of your best total, using logged singles only:

| Tier | GL | DOTS |
| --- | --- | --- |
| 🟤 Bronze | under 45 | under 225 |
| ⚪ Silver | 45–60 | 225–300 |
| 🟡 Gold | 60–70 | 300–350 |
| 💠 Platinum | 70–80 | 350–400 |
| 💎 Diamond | 80–90 | 400–450 |
| 👑 Grandmaster | 90–100 | 450–500 |
| 🌌 Ascender | 100+ | 500+ |

For a sense of scale, a 90 kg man totaling 600 kg scores about 80 GL, or about 390 DOTS. The DOTS floors are rounded, so they sit slightly above the GL floors and a total right on a GL line can be one tier lower in DOTS. The tier floors are in `TIERS` in [scoring.py](scoring.py) if you want to move them.

The IPF leaderboard comes from the [OpenIPF](https://www.openipf.org) data. They only use raw full-power meets and each lifter's best result in a weight class. Meet lifts are judged and gym lifts aren't, so it's a rough comparison.

## Running it yourself

You need Python 3.10 or newer and a bot from the [Discord developer portal](https://discord.com/developers/applications). When you invite it, give it the `bot` and `applications.commands` scopes.

```
python -m venv .venv
.venv\Scripts\activate        # on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your bot token. `GUILD_ID` is optional. If you set it to your test server's ID, slash commands update there right away instead of waiting on Discord's global sync.

Then download the IPF data and start the bot:

```
python ipf_data.py
python bot.py
```

`ipf_data.py` downloads around 70 MB and builds `data/ipf_stats.json`, so it takes a minute. Rerun it whenever you want fresher rankings. The bot works without it, but `/leaderboard scope:professional` won't.

## Files

- [bot.py](bot.py) has the slash commands.
- [db.py](db.py) handles the SQLite database (`liftbot.db`, created on first run).
- [scoring.py](scoring.py) has the GL and DOTS formulas, 1 rep max estimates, meet attempts, rank tiers, and unit conversion.
- [charts.py](charts.py) draws the `/history` and `/setting` graphs with matplotlib.
- [ipf_data.py](ipf_data.py) builds the IPF weight class rankings.
