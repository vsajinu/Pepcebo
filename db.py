"""SQLite storage for lifter profiles and logged lifts."""

import sqlite3
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = "liftbot.db"

# A best lift and the bodyweight it was done at
Best = namedtuple("Best", "weight_kg bodyweight_kg")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lifters (
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                sex           TEXT    NOT NULL,
                bodyweight_kg REAL    NOT NULL,
                unit          TEXT    NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS lifts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                lift          TEXT    NOT NULL,
                weight_kg     REAL    NOT NULL,
                bodyweight_kg REAL,
                logged_at     TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lifts_user
                ON lifts (guild_id, user_id, lift);
            -- Rep sets live apart from lifts so estimated maxes never reach the rankings
            CREATE TABLE IF NOT EXISTS sets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                lift          TEXT    NOT NULL,
                weight_kg     REAL    NOT NULL,
                reps          INTEGER NOT NULL,
                e1rm_kg       REAL    NOT NULL,
                bodyweight_kg REAL    NOT NULL,
                logged_at     TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sets_user
                ON sets (guild_id, user_id, lift);
            -- Every bodyweight change, for the /setting graph
            CREATE TABLE IF NOT EXISTS bodyweights (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                bodyweight_kg REAL    NOT NULL,
                logged_at     TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bodyweights_user
                ON bodyweights (guild_id, user_id);
            """
        )
        _migrate_lift_bodyweight(conn)
        _migrate_formula(conn)
        _seed_bodyweights(conn)


def _migrate_lift_bodyweight(conn):
    # Older lifts didn't save bodyweight, so fill them in with the lifter's current one
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(lifts)")}
    if "bodyweight_kg" not in columns:
        conn.execute("ALTER TABLE lifts ADD COLUMN bodyweight_kg REAL")
    conn.execute(
        """
        UPDATE lifts SET bodyweight_kg = (
            SELECT l.bodyweight_kg FROM lifters l
            WHERE l.guild_id = lifts.guild_id AND l.user_id = lifts.user_id
        )
        WHERE bodyweight_kg IS NULL
        """
    )


def _migrate_formula(conn):
    # Scoring formula preference, added after launch. Everyone starts on GL.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(lifters)")}
    if "formula" not in columns:
        conn.execute("ALTER TABLE lifters ADD COLUMN formula TEXT NOT NULL DEFAULT 'gl'")


def _seed_bodyweights(conn):
    # Lifters from before bodyweight history start with their current bodyweight, dated at their first lift
    conn.execute(
        """
        INSERT INTO bodyweights (guild_id, user_id, bodyweight_kg, logged_at)
        SELECT l.guild_id, l.user_id, l.bodyweight_kg, COALESCE(
            (SELECT MIN(logged_at) FROM lifts x WHERE x.guild_id = l.guild_id AND x.user_id = l.user_id), ?
        )
        FROM lifters l
        WHERE NOT EXISTS (
            SELECT 1 FROM bodyweights b WHERE b.guild_id = l.guild_id AND b.user_id = l.user_id
        )
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )


def _log_bodyweight(conn, guild_id, user_id, bodyweight_kg):
    # Only when it changed, so rerunning /setup doesn't stack up duplicate points
    last = conn.execute(
        "SELECT bodyweight_kg FROM bodyweights WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
        (guild_id, user_id),
    ).fetchone()
    if last is None or abs(last["bodyweight_kg"] - bodyweight_kg) > 1e-6:
        conn.execute(
            "INSERT INTO bodyweights (guild_id, user_id, bodyweight_kg, logged_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, bodyweight_kg, datetime.now(timezone.utc).isoformat()),
        )


def upsert_lifter(guild_id, user_id, sex, bodyweight_kg, unit):
    with connect() as conn:
        _log_bodyweight(conn, guild_id, user_id, bodyweight_kg)
        conn.execute(
            """
            INSERT INTO lifters (guild_id, user_id, sex, bodyweight_kg, unit)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET
                sex = excluded.sex,
                bodyweight_kg = excluded.bodyweight_kg,
                unit = excluded.unit
            """,
            (guild_id, user_id, sex, bodyweight_kg, unit),
        )


def update_settings(guild_id, user_id, bodyweight_kg=None, unit=None, formula=None):
    """Change any of bodyweight, unit, or formula on an existing profile. None leaves it as is."""
    with connect() as conn:
        if bodyweight_kg is not None:
            _log_bodyweight(conn, guild_id, user_id, bodyweight_kg)
        conn.execute(
            """
            UPDATE lifters SET
                bodyweight_kg = COALESCE(?, bodyweight_kg),
                unit = COALESCE(?, unit),
                formula = COALESCE(?, formula)
            WHERE guild_id = ? AND user_id = ?
            """,
            (bodyweight_kg, unit, formula, guild_id, user_id),
        )


def bodyweight_history(guild_id, user_id):
    """Returns [(logged_at, bodyweight_kg)], oldest first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT logged_at, bodyweight_kg FROM bodyweights WHERE guild_id = ? AND user_id = ? ORDER BY id",
            (guild_id, user_id),
        ).fetchall()
    return [tuple(r) for r in rows]


def get_lifter(guild_id, user_id):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM lifters WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()


def add_lift(guild_id, user_id, lift, weight_kg, bodyweight_kg):
    with connect() as conn:
        conn.execute(
            "INSERT INTO lifts (guild_id, user_id, lift, weight_kg, bodyweight_kg, logged_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, lift, weight_kg, bodyweight_kg,
             datetime.now(timezone.utc).isoformat()),
        )


# Heaviest of each lift per user (ties go to the lower bodyweight)
_BESTS = """
    SELECT guild_id, user_id, lift, weight_kg, bodyweight_kg FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY guild_id, user_id, lift
            ORDER BY weight_kg DESC, bodyweight_kg ASC
        ) AS rn
        FROM lifts
    ) WHERE rn = 1
"""


def best_lifts(guild_id, user_id) -> dict:
    """Returns {lift: Best}."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM ({_BESTS}) WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchall()
    return {row["lift"]: Best(row["weight_kg"], row["bodyweight_kg"]) for row in rows}


def _profiles(conn, where="", params=()):
    rows = conn.execute(
        f"""
        SELECT l.guild_id, l.user_id, l.sex, p.lift, p.weight_kg, p.bodyweight_kg
        FROM lifters l
        JOIN ({_BESTS}) p
          ON p.guild_id = l.guild_id AND p.user_id = l.user_id
        {where}
        """,
        params,
    ).fetchall()

    out = {}
    for row in rows:
        entry = out.setdefault((row["guild_id"], row["user_id"]), {"sex": row["sex"], "bests": {}})
        entry["bests"][row["lift"]] = Best(row["weight_kg"], row["bodyweight_kg"])
    return out


def guild_bests(guild_id) -> dict:
    """Returns {user_id: {"sex", "bests": {lift: Best}}}."""
    with connect() as conn:
        out = _profiles(conn, "WHERE l.guild_id = ?", (guild_id,))
    return {user_id: entry for (_, user_id), entry in out.items()}


def all_bests() -> list:
    """Every profile in every server, as [(user_id, {"sex", "bests": {lift: Best}})].

    A user in several servers appears once per server, since profiles are per server.
    """
    with connect() as conn:
        out = _profiles(conn)
    return [(user_id, entry) for (_, user_id), entry in out.items()]


# The best estimated max for a lift and the set it came from
Estimate = namedtuple("Estimate", "e1rm_kg weight_kg reps")


def add_set(guild_id, user_id, lift, weight_kg, reps, e1rm_kg, bodyweight_kg):
    with connect() as conn:
        conn.execute(
            "INSERT INTO sets (guild_id, user_id, lift, weight_kg, reps, e1rm_kg, bodyweight_kg, logged_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, lift, weight_kg, reps, e1rm_kg, bodyweight_kg,
             datetime.now(timezone.utc).isoformat()),
        )


def best_estimates(guild_id, user_id) -> dict:
    """Returns {lift: Estimate} with the highest estimated max per lift."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT lift, e1rm_kg, weight_kg, reps FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY lift ORDER BY e1rm_kg DESC) AS rn
                FROM sets WHERE guild_id = ? AND user_id = ?
            ) WHERE rn = 1
            """,
            (guild_id, user_id),
        ).fetchall()
    return {row["lift"]: Estimate(row["e1rm_kg"], row["weight_kg"], row["reps"]) for row in rows}


def history(guild_id, user_id, lift):
    """Returns (singles, sets) oldest first: [(logged_at, weight_kg)] and [(logged_at, e1rm_kg)]."""
    with connect() as conn:
        singles = conn.execute(
            "SELECT logged_at, weight_kg FROM lifts WHERE guild_id = ? AND user_id = ? AND lift = ? "
            "ORDER BY logged_at",
            (guild_id, user_id, lift),
        ).fetchall()
        sets = conn.execute(
            "SELECT logged_at, e1rm_kg FROM sets WHERE guild_id = ? AND user_id = ? AND lift = ? "
            "ORDER BY logged_at",
            (guild_id, user_id, lift),
        ).fetchall()
    return [tuple(r) for r in singles], [tuple(r) for r in sets]
