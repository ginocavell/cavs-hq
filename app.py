# Cavs HQ - Phase 1
# Next game, recent results, and full schedule for the Cleveland Cavaliers.
# Data comes from ESPN's public feed and refreshes every 15 minutes.

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

# ---------- Settings ----------
TEAM = "cle"
SCHEDULE_URL = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{TEAM}/schedule"
EASTERN = ZoneInfo("America/New_York")
CACHE_SECONDS = 15 * 60  # how long to keep data before pulling fresh

st.set_page_config(page_title="Cavs HQ", page_icon="🏀", layout="wide")

# Cavs colors: wine #860038, gold #FDBB30, navy #041E42
st.markdown(
    """
    <style>
    .game-card {background:#860038;color:white;padding:22px 26px;border-radius:14px;}
    .game-card h2 {color:#FDBB30;margin:0 0 6px 0;}
    .game-card p {margin:4px 0;font-size:1.05rem;}
    .countdown {font-size:1.6rem;font-weight:700;color:#FDBB30;margin-top:10px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Getting the data ----------
@st.cache_data(ttl=CACHE_SECONDS)
def fetch_schedule():
    """Download the Cavs schedule from ESPN."""
    response = requests.get(
        SCHEDULE_URL,
        params={"seasontype": 2},  # 2 = regular season
        headers={"User-Agent": "Mozilla/5.0 (CavsHQ dashboard)"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def read_score(raw):
    """ESPN sometimes sends a score as a number, a string, or an object."""
    if isinstance(raw, dict):
        raw = raw.get("displayValue", raw.get("value"))
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def parse_games(data):
    """Turn ESPN's raw data into a simple list of games."""
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        cavs = next((c for c in competitors if c.get("team", {}).get("abbreviation", "").lower() == TEAM), None)
        opp = next((c for c in competitors if c is not cavs), None)
        if not cavs or not opp:
            continue

        status = comp.get("status", event.get("status", {})).get("type", {})
        broadcasts = []
        for b in comp.get("broadcasts", []):
            name = b.get("media", {}).get("shortName") or ", ".join(b.get("names", []))
            if name and name not in broadcasts:
                broadcasts.append(name)

        logos = opp.get("team", {}).get("logos") or [{}]
        games.append(
            {
                "id": event.get("id"),
                "date": datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(EASTERN),
                "home": cavs.get("homeAway") == "home",
                "opponent": opp.get("team", {}).get("displayName", "TBD"),
                "opp_abbr": opp.get("team", {}).get("abbreviation", ""),
                "opp_logo": logos[0].get("href") or opp.get("team", {}).get("logo"),
                "cavs_score": read_score(cavs.get("score")),
                "opp_score": read_score(opp.get("score")),
                "completed": bool(status.get("completed")),
                "state": status.get("state", ""),  # "pre", "in", or "post"
                "status_text": status.get("shortDetail", ""),
                "tv": ", ".join(broadcasts) or "TBD",
                "venue": comp.get("venue", {}).get("fullName", ""),
            }
        )
    games.sort(key=lambda g: g["date"])
    return games


def result_text(game):
    """Example: 'W 112-104' or 'L 98-101'."""
    if game["cavs_score"] is None or game["opp_score"] is None:
        return game["status_text"]
    letter = "W" if game["cavs_score"] > game["opp_score"] else "L"
    return f"{letter} {game['cavs_score']}-{game['opp_score']}"


def matchup(game):
    return f"vs {game['opponent']}" if game["home"] else f"@ {game['opponent']}"


def countdown(target):
    delta = target - datetime.now(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "Tipping off now"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


# ---------- The page ----------
title_col, button_col = st.columns([5, 1])
with title_col:
    st.title("🏀 Cavs HQ")
with button_col:
    st.write("")
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

try:
    data = fetch_schedule()
    games = parse_games(data)
except Exception as error:
    st.error("Couldn't load the Cavs schedule from ESPN right now. Try Refresh in a minute.")
    st.caption(f"Technical details: {error}")
    st.stop()

if not games:
    st.warning("ESPN returned no games. The feed may have changed. Send a screenshot to Claude.")
    st.stop()

team_info = data.get("team", {})
record = team_info.get("recordSummary", "")
standing = team_info.get("standingSummary", "")
if record or standing:
    st.subheader(" · ".join(x for x in [record, standing] if x))

# --- Live or next game ---
live = [g for g in games if g["state"] == "in"]
upcoming = [g for g in games if not g["completed"] and g["state"] != "in"]
featured = live[0] if live else (upcoming[0] if upcoming else None)

left, right = st.columns([3, 2])

with left:
    if featured:
        label = "🔴 LIVE NOW" if live else "NEXT GAME"
        when = featured["date"].strftime("%A, %b %-d · %-I:%M %p ET")
        extra = (
            f'<div class="countdown">{result_text(featured)} · {featured["status_text"]}</div>'
            if live
            else f'<div class="countdown">⏱ {countdown(featured["date"])}</div>'
        )
        logo = f'<img src="{featured["opp_logo"]}" width="70" style="float:right">' if featured["opp_logo"] else ""
        st.markdown(
            f"""
            <div class="game-card">
              {logo}
              <p style="opacity:.8;letter-spacing:2px">{label}</p>
              <h2>Cavs {matchup(featured)}</h2>
              <p>📅 {when}</p>
              <p>📺 {featured["tv"]}</p>
              <p>📍 {featured["venue"]}</p>
              {extra}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No upcoming games found. The season may be over.")

with right:
    st.markdown("### Last 5 games")
    finished = [g for g in games if g["completed"]][-5:]
    if not finished:
        st.write("No games played yet.")
    for g in reversed(finished):
        text = result_text(g)
        icon = "🟢" if text.startswith("W") else "🔴"
        st.markdown(f"{icon} **{text}** {matchup(g)} · {g['date'].strftime('%b %-d')}")

    wins = sum(1 for g in finished if result_text(g).startswith("W"))
    if finished:
        st.caption(f"{wins}-{len(finished) - wins} over the last {len(finished)}")

# --- Full schedule ---
st.markdown("---")
st.markdown("### Full schedule")

show = st.radio("Show", ["Upcoming", "Played", "All"], horizontal=True)
if show == "Upcoming":
    rows = [g for g in games if not g["completed"]]
elif show == "Played":
    rows = [g for g in games if g["completed"]][::-1]
else:
    rows = games

table = [
    {
        "Date": g["date"].strftime("%a %b %-d"),
        "Time (ET)": g["date"].strftime("%-I:%M %p"),
        "Matchup": matchup(g),
        "Result": result_text(g) if g["completed"] or g["state"] == "in" else "",
        "TV": g["tv"],
    }
    for g in rows
]
st.dataframe(table, width="stretch", hide_index=True)

st.caption(
    f"Data from ESPN · refreshes every 15 minutes · page loaded "
    f"{datetime.now(EASTERN).strftime('%b %-d, %-I:%M %p ET')}"
)
