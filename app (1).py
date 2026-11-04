# Cavs HQ - Phase 2
# Games (next game, recent results, schedule), Players (stats, profiles, game logs), Injuries.
# Data comes from ESPN's public feeds.

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

# ---------- Settings ----------
TEAM = "cle"
TEAM_NAME = "Cleveland Cavaliers"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SCHEDULE_URL = f"{BASE}/teams/{TEAM}/schedule"
ROSTER_URL = f"{BASE}/teams/{TEAM}/roster"
INJURIES_URL = f"{BASE}/injuries"
SUMMARY_URL = f"{BASE}/summary"
EASTERN = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (CavsHQ dashboard)"}

st.set_page_config(page_title="Cavs HQ", page_icon="🏀", layout="wide")

# Cavs colors: wine #860038, gold #FDBB30, navy #041E42
st.markdown(
    """
    <style>
    .game-card {background:#860038;color:white;padding:22px 26px;border-radius:14px;}
    .game-card h2 {color:#FDBB30;margin:0 0 6px 0;}
    .game-card p {margin:4px 0;font-size:1.05rem;}
    .countdown {font-size:1.6rem;font-weight:700;color:#FDBB30;margin-top:10px;}
    .injury {border-left:5px solid #860038;padding:8px 14px;margin:8px 0;background:rgba(134,0,56,.12);border-radius:6px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Helpers for getting data ----------
def get_json(url, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15 * 60)
def fetch_schedule():
    return get_json(SCHEDULE_URL, {"seasontype": 2})  # 2 = regular season


@st.cache_data(ttl=60 * 60)
def fetch_roster():
    return get_json(ROSTER_URL)


@st.cache_data(ttl=15 * 60)
def fetch_injuries():
    return get_json(INJURIES_URL)


@st.cache_data(ttl=6 * 60 * 60)
def fetch_box_scores(event_ids):
    """Download the box score for every finished game (several at once to be fast)."""
    def one(event_id):
        try:
            return event_id, get_json(SUMMARY_URL, {"event": event_id})
        except Exception:
            return event_id, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, event_ids))


def is_cavs(team):
    team = team or {}
    return team.get("abbreviation", "").lower() == TEAM or team.get("displayName") == TEAM_NAME


def to_number(raw):
    if isinstance(raw, dict):
        raw = raw.get("displayValue", raw.get("value"))
    if raw in (None, "", "--"):
        return None
    try:
        return float(str(raw).replace("+", ""))
    except ValueError:
        return None


# ---------- Games ----------
def parse_games(data):
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        cavs = next((c for c in competitors if is_cavs(c.get("team"))), None)
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
        cs, os_ = to_number(cavs.get("score")), to_number(opp.get("score"))
        games.append(
            {
                "id": event.get("id"),
                "date": datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(EASTERN),
                "home": cavs.get("homeAway") == "home",
                "opponent": opp.get("team", {}).get("displayName", "TBD"),
                "opp_abbr": opp.get("team", {}).get("abbreviation", ""),
                "opp_logo": logos[0].get("href") or opp.get("team", {}).get("logo"),
                "cavs_score": int(cs) if cs is not None else None,
                "opp_score": int(os_) if os_ is not None else None,
                "completed": bool(status.get("completed")),
                "state": status.get("state", ""),
                "status_text": status.get("shortDetail", ""),
                "tv": ", ".join(broadcasts) or "TBD",
                "venue": comp.get("venue", {}).get("fullName", ""),
            }
        )
    games.sort(key=lambda g: g["date"])
    return games


def result_text(game):
    if game["cavs_score"] is None or game["opp_score"] is None:
        return game["status_text"]
    letter = "W" if game["cavs_score"] > game["opp_score"] else "L"
    return f"{letter} {game['cavs_score']}-{game['opp_score']}"


def matchup(game, short=False):
    name = game["opp_abbr"] if short else game["opponent"]
    return f"vs {name}" if game["home"] else f"@ {name}"


def countdown(target):
    seconds = int((target - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0:
        return "Tipping off now"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


# ---------- Players ----------
def parse_roster(data):
    """Returns {player_id: profile}. ESPN sometimes groups players, sometimes not."""
    raw = data.get("athletes", [])
    athletes = []
    for item in raw:
        if isinstance(item, dict) and "items" in item:
            athletes.extend(item["items"])
        else:
            athletes.append(item)

    roster = {}
    for a in athletes:
        injuries = a.get("injuries") or []
        roster[str(a.get("id"))] = {
            "name": a.get("displayName") or a.get("fullName", "Unknown"),
            "jersey": a.get("jersey", ""),
            "position": (a.get("position") or {}).get("abbreviation", ""),
            "age": a.get("age", ""),
            "height": a.get("displayHeight", ""),
            "weight": a.get("displayWeight", ""),
            "college": (a.get("college") or {}).get("name", ""),
            "experience": (a.get("experience") or {}).get("years", ""),
            "headshot": (a.get("headshot") or {}).get("href", ""),
            "injury": injuries[0].get("status", "") if injuries else "",
        }
    return roster


def made_attempted(text):
    try:
        made, att = str(text).split("-")
        return int(made), int(att)
    except ValueError:
        return 0, 0


def minutes(text):
    text = str(text)
    if ":" in text:
        mins, secs = text.split(":")
        return int(mins) + int(secs) / 60
    return to_number(text) or 0


def parse_game_logs(box_scores, games):
    """Pull every Cavs player's line from every box score. Returns {player_id: [game lines]}."""
    game_by_id = {g["id"]: g for g in games}
    logs = {}
    for event_id, summary in box_scores.items():
        if not summary or event_id not in game_by_id:
            continue
        game = game_by_id[event_id]
        for team_block in (summary.get("boxscore") or {}).get("players", []):
            if not is_cavs(team_block.get("team")):
                continue
            for stat_group in team_block.get("statistics", []):
                columns = [c.upper() for c in (stat_group.get("names") or stat_group.get("labels") or [])]
                for entry in stat_group.get("athletes", []):
                    stats = entry.get("stats") or []
                    if entry.get("didNotPlay") or not stats:
                        continue
                    row = dict(zip(columns, stats))
                    athlete = entry.get("athlete", {})
                    fgm, fga = made_attempted(row.get("FG", "0-0"))
                    tpm, tpa = made_attempted(row.get("3PT", "0-0"))
                    ftm, fta = made_attempted(row.get("FT", "0-0"))
                    logs.setdefault(str(athlete.get("id")), []).append(
                        {
                            "name": athlete.get("displayName", "Unknown"),
                            "headshot": (athlete.get("headshot") or {}).get("href", ""),
                            "date": game["date"],
                            "game": matchup(game, short=True),
                            "result": result_text(game),
                            "starter": bool(entry.get("starter")),
                            "MIN": minutes(row.get("MIN", 0)),
                            "PTS": to_number(row.get("PTS")) or 0,
                            "REB": to_number(row.get("REB")) or 0,
                            "AST": to_number(row.get("AST")) or 0,
                            "STL": to_number(row.get("STL")) or 0,
                            "BLK": to_number(row.get("BLK")) or 0,
                            "TO": to_number(row.get("TO")) or 0,
                            "+/-": to_number(row.get("+/-")) or 0,
                            "FGM": fgm, "FGA": fga, "3PM": tpm, "3PA": tpa, "FTM": ftm, "FTA": fta,
                        }
                    )
    for lines in logs.values():
        lines.sort(key=lambda x: x["date"])
    return logs


def averages(lines):
    n = len(lines)
    if not n:
        return {}

    def avg(key):
        return round(sum(x[key] for x in lines) / n, 1)

    def pct(made, att):
        total_att = sum(x[att] for x in lines)
        return round(100 * sum(x[made] for x in lines) / total_att, 1) if total_att else None

    return {
        "GP": n, "GS": sum(x["starter"] for x in lines),
        "MIN": avg("MIN"), "PTS": avg("PTS"), "REB": avg("REB"), "AST": avg("AST"),
        "STL": avg("STL"), "BLK": avg("BLK"), "TO": avg("TO"), "+/-": avg("+/-"),
        "FG%": pct("FGM", "FGA"), "3P%": pct("3PM", "3PA"), "FT%": pct("FTM", "FTA"),
    }


# ---------- Injuries ----------
def parse_injuries(data, roster):
    for team_block in data.get("injuries", []):
        if team_block.get("displayName") == TEAM_NAME or is_cavs(team_block.get("team")):
            out = []
            for i in team_block.get("injuries", []):
                athlete = i.get("athlete", {})
                details = i.get("details") or {}
                when = i.get("date", "")
                out.append(
                    {
                        "name": athlete.get("displayName", "Unknown"),
                        "status": i.get("status", ""),
                        "injury": " ".join(x for x in [details.get("side", ""), details.get("type", "")] if x and x != "Not Specified"),
                        "return": details.get("returnDate", ""),
                        "comment": i.get("shortComment") or i.get("longComment", ""),
                        "updated": when[:10],
                    }
                )
            return out
    # Backup: use the injury tags on the roster
    return [{"name": p["name"], "status": p["injury"], "injury": "", "return": "", "comment": "", "updated": ""}
            for p in roster.values() if p["injury"]]


# ---------- Load everything ----------
title_col, button_col = st.columns([5, 1])
with title_col:
    st.title("🏀 Cavs HQ")
with button_col:
    st.write("")
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

try:
    schedule_data = fetch_schedule()
    games = parse_games(schedule_data)
except Exception as error:
    st.error("Couldn't load the Cavs schedule from ESPN right now. Try Refresh in a minute.")
    st.caption(f"Technical details: {error}")
    st.stop()

try:
    roster = parse_roster(fetch_roster())
except Exception:
    roster = {}

try:
    injuries = parse_injuries(fetch_injuries(), roster)
except Exception:
    injuries = parse_injuries({}, roster)

finished = [g for g in games if g["completed"]]
with st.spinner("Loading box scores..."):
    box_scores = fetch_box_scores(tuple(g["id"] for g in finished))
logs = parse_game_logs(box_scores, games)

team_info = schedule_data.get("team", {})
record = team_info.get("recordSummary", "")
standing = team_info.get("standingSummary", "")
if record or standing:
    st.subheader(" · ".join(x for x in [record, standing] if x))

games_tab, players_tab, injuries_tab = st.tabs(
    ["📅 Games", "👥 Players", f"🩹 Injuries ({len(injuries)})"]
)

# ---------- Games tab ----------
with games_tab:
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
        last5 = finished[-5:]
        if not last5:
            st.write("No games played yet.")
        for g in reversed(last5):
            text = result_text(g)
            icon = "🟢" if text.startswith("W") else "🔴"
            st.markdown(f"{icon} **{text}** {matchup(g)} · {g['date'].strftime('%b %-d')}")
        if last5:
            wins = sum(1 for g in last5 if result_text(g).startswith("W"))
            st.caption(f"{wins}-{len(last5) - wins} over the last {len(last5)}")

    st.markdown("---")
    st.markdown("### Full schedule")
    show = st.radio("Show", ["Upcoming", "Played", "All"], horizontal=True)
    if show == "Upcoming":
        rows = [g for g in games if not g["completed"]]
    elif show == "Played":
        rows = finished[::-1]
    else:
        rows = games
    st.dataframe(
        [
            {
                "Date": g["date"].strftime("%a %b %-d"),
                "Time (ET)": g["date"].strftime("%-I:%M %p"),
                "Matchup": matchup(g),
                "Result": result_text(g) if g["completed"] or g["state"] == "in" else "",
                "TV": g["tv"],
            }
            for g in rows
        ],
        width="stretch",
        hide_index=True,
    )

# ---------- Players tab ----------
with players_tab:
    if not logs:
        st.info("No player stats yet. They'll show up once the Cavs have played a game.")
    else:
        st.markdown("### Season averages")
        st.caption(f"Built from {len(finished)} box scores · click a column to sort")
        season_rows = []
        for pid, lines in logs.items():
            profile = roster.get(pid, {})
            row = {"Player": profile.get("name") or lines[-1]["name"], "Pos": profile.get("position", "")}
            row.update(averages(lines))
            season_rows.append(row)
        season_rows.sort(key=lambda r: r["PTS"], reverse=True)
        st.dataframe(season_rows, width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("### Player profile")
        order = [pid for pid, _ in sorted(logs.items(), key=lambda kv: -averages(kv[1])["PTS"])]
        order += [pid for pid in roster if pid not in logs]  # players who haven't played yet
        names = {pid: (roster.get(pid, {}).get("name") or logs[pid][-1]["name"]) for pid in order}
        pid = st.selectbox("Pick a player", order, format_func=lambda p: names[p])

        profile = roster.get(pid, {})
        lines = logs.get(pid, [])
        photo_col, info_col = st.columns([1, 4])
        with photo_col:
            photo = profile.get("headshot") or (lines[-1]["headshot"] if lines else "")
            if photo:
                st.image(photo, width=150)
        with info_col:
            jersey = f"#{profile['jersey']} · " if profile.get("jersey") else ""
            st.markdown(f"## {names[pid]}")
            facts = [
                f"{jersey}{profile.get('position', '')}",
                profile.get("height", ""), profile.get("weight", ""),
                f"Age {profile['age']}" if profile.get("age") else "",
                f"{profile['experience']} yrs exp" if profile.get("experience") not in ("", None) else "",
                profile.get("college", ""),
            ]
            st.write(" · ".join(f for f in facts if f))
            status = next((i for i in injuries if i["name"] == names[pid]), None)
            if status:
                st.warning(f"🩹 {status['status']}{' · ' + status['injury'] if status['injury'] else ''}")

        if not lines:
            st.info("Hasn't played yet this season.")
        else:
            season = averages(lines)
            recent = averages(lines[-5:])
            st.markdown(f"**Last {min(5, len(lines))} games vs season average**")
            cols = st.columns(6)
            for col, key in zip(cols, ["PTS", "REB", "AST", "MIN", "FG%", "3P%"]):
                now, base = recent.get(key), season.get(key)
                delta = round(now - base, 1) if now is not None and base is not None else None
                col.metric(key, now if now is not None else "-", delta)

            st.markdown("**Game log**")
            st.dataframe(
                [
                    {
                        "Date": x["date"].strftime("%b %-d"),
                        "Game": x["game"],
                        "Result": x["result"],
                        "MIN": round(x["MIN"]),
                        "PTS": int(x["PTS"]), "REB": int(x["REB"]), "AST": int(x["AST"]),
                        "STL": int(x["STL"]), "BLK": int(x["BLK"]), "TO": int(x["TO"]),
                        "FG": f"{x['FGM']}-{x['FGA']}", "3PT": f"{x['3PM']}-{x['3PA']}", "FT": f"{x['FTM']}-{x['FTA']}",
                        "+/-": int(x["+/-"]),
                    }
                    for x in reversed(lines)
                ],
                width="stretch",
                hide_index=True,
            )

# ---------- Injuries tab ----------
with injuries_tab:
    st.markdown("### Injury report")
    if not injuries:
        st.success("No Cavs on the injury report right now. 🙌")
    for i in injuries:
        bits = [x for x in [i["injury"], f"Expected back: {i['return']}" if i["return"] else "", f"Updated {i['updated']}" if i["updated"] else ""] if x]
        st.markdown(
            f'<div class="injury"><b>{i["name"]}</b> · <b style="color:#FDBB30">{i["status"]}</b><br>'
            f'<span style="opacity:.85">{" · ".join(bits)}</span><br>'
            f'<span style="opacity:.75">{i["comment"]}</span></div>',
            unsafe_allow_html=True,
        )
    st.caption("Statuses can change right up to tip-off. Check the official NBA injury report on game days.")

st.caption(
    f"Data from ESPN · page loaded {datetime.now(EASTERN).strftime('%b %-d, %-I:%M %p ET')}"
)
