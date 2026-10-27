# Pepcebo

Pepcebo is a Discord bot for tracking powerlifting PRs. You log your squat, bench, and deadlift, and it works out your total and IPF GL points. It can also rank you against people in your server, everyone using the bot, or real lifters from IPF meets in your weight class.

## Commands

- `/setup` saves your sex, bodyweight, and unit (lb or kg). Run it again whenever your bodyweight changes.
- `/pr` logs a lift. If it beats your old best, the bot announces it as a PR.
- `/stats` shows your bests, total, GL points, and bodyweight. You can pass a member to see someone else's.
- `/rankings` shows a top 10. The scope can be `server`, `global`, or `ipf`, and the category can be total or a single lift.
- `/faq` explains how everything works, including the GL formula.

## How scoring works

GL points are the IPF's formula for comparing lifters at different bodyweights. Heavier lifters can lift more, but not proportionally more, so GL compares your total to what's expected at your bodyweight. The bot uses the raw (classic) coefficients from [scoring.py](scoring.py).

Every lift saves the bodyweight you had when you logged it. That way, if you cut or bulk later, your old lifts keep their original GL points. Since your three best lifts might come from different days, your total gets scored at the heaviest of those bodyweights. That's closer to a real meet where you weigh in once, and it means you can't log a squat at 100 kg, cut to 70 kg, and have the squat count as a 70 kg lift.

The IPF rankings come from the [OpenIPF](https://www.openipf.org) data. They only use raw full-power meets and each lifter's best result in a weight class. Meet lifts are judged and gym lifts aren't, so it's a rough comparison.

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

`ipf_data.py` downloads around 70 MB and builds `data/ipf_stats.json`, so it takes a minute. Rerun it whenever you want fresher rankings. The bot works without it, but `/rankings scope:ipf` won't.

## Files

- [bot.py](bot.py) has the slash commands.
- [db.py](db.py) handles the SQLite database (`liftbot.db`, created on first run).
- [scoring.py](scoring.py) has the GL formula and unit conversion.
- [ipf_data.py](ipf_data.py) builds the IPF weight class rankings.
