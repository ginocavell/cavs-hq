# Cavs HQ - Phase 2
# Games (next game, recent results, schedule), Players (stats, profiles, game logs), Injuries.
# Data comes from ESPN's public feeds.

from concurrent.futures import ThreadPoolExecutor
from functools import partial
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


# ---------- Shot charts ----------
HOOP_X, HOOP_Y = 25.0, 5.25  # court is in feet: 50 wide, hoop 5.25 ft from the baseline


def parse_shots(box_scores, games):
    """Every Cavs field-goal attempt with its spot on the floor."""
    game_by_id = {g["id"]: g for g in games}
    shots = []
    for event_id, summary in box_scores.items():
        if not summary or event_id not in game_by_id:
            continue
        cavs_ids = {
            str((b.get("team") or {}).get("id"))
            for b in (summary.get("boxscore") or {}).get("players", [])
            if is_cavs(b.get("team"))
        }
        for play in summary.get("plays", []):
            if not play.get("shootingPlay"):
                continue
            text = play.get("text", "")
            kind = (play.get("type") or {}).get("text", "")
            if "free throw" in (text + " " + kind).lower():
                continue
            if str((play.get("team") or {}).get("id")) not in cavs_ids:
                continue
            coord = play.get("coordinate") or {}
            x, y = to_number(coord.get("x")), to_number(coord.get("y"))
            if x is None or y is None or abs(x) > 200 or abs(y) > 200:
                continue  # missing or junk location
            raw_x, raw_y = x, y
            y = raw_y + HOOP_Y  # ESPN measures y from the hoop; the chart measures from the baseline
            participants = play.get("participants") or [{}]
            shooter = str((participants[0].get("athlete") or {}).get("id"))
            three = "three point" in text.lower() or "3pt" in kind.lower() or play.get("scoreValue") == 3
            distance = ((x - HOOP_X) ** 2 + (y - HOOP_Y) ** 2) ** 0.5
            if three:
                zone = "Corner 3" if y <= 14 else "Above-the-break 3"
            elif distance <= 4:
                zone = "At the rim"
            elif abs(x - HOOP_X) <= 8 and y <= 19:
                zone = "Paint (non-rim)"
            else:
                zone = "Mid-range"
            g = game_by_id[event_id]
            shots.append(
                {
                    "event": event_id, "player": shooter, "x": x, "y": y, "raw_x": raw_x, "raw_y": raw_y,
                    "made": bool(play.get("scoringPlay")), "three": three, "zone": zone,
                    "text": text, "type": kind,
                    "when": f"Q{(play.get('period') or {}).get('number', '?')} {(play.get('clock') or {}).get('displayValue', '')}",
                    "game": f"{matchup(g, short=True)} · {g['date'].strftime('%b %-d')}",
                }
            )
    return shots


def arc_path(cx, cy, r, start_deg, end_deg, steps=60):
    import math
    pts = [
        (cx + r * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
         cy + r * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / steps)))
        for i in range(steps + 1)
    ]
    return "M " + " L ".join(f"{px:.2f},{py:.2f}" for px, py in pts)


def shot_chart(shots, title):
    import math
    import plotly.graph_objects as go

    line = dict(color="rgba(255,255,255,0.55)", width=2)
    corner_y = HOOP_Y + (23.75 ** 2 - 22 ** 2) ** 0.5  # where the 3-pt arc meets the corner lines
    arc_angle = math.degrees(math.asin((corner_y - HOOP_Y) / 23.75))
    shapes = [
        dict(type="rect", x0=0, y0=0, x1=50, y1=47, line=line),                        # half court
        dict(type="rect", x0=17, y0=0, x1=33, y1=19, line=line),                       # paint
        dict(type="line", x0=22, y0=4, x1=28, y1=4, line=line),                        # backboard
        dict(type="circle", x0=24.25, y0=4.5, x1=25.75, y1=6, line=dict(color="#FDBB30", width=2)),  # rim
        dict(type="path", path=arc_path(25, 19, 6, 0, 180), line=line),               # free-throw circle
        dict(type="path", path=arc_path(HOOP_X, HOOP_Y, 4, 0, 180), line=line),       # restricted area
        dict(type="line", x0=3, y0=0, x1=3, y1=corner_y, line=line),                   # corner 3 lines
        dict(type="line", x0=47, y0=0, x1=47, y1=corner_y, line=line),
        dict(type="path", path=arc_path(HOOP_X, HOOP_Y, 23.75, arc_angle, 180 - arc_angle), line=line),  # 3-pt arc
        dict(type="path", path=arc_path(25, 47, 6, 180, 360), line=line),             # center circle
    ]
    fig = go.Figure()
    on_court = [s for s in shots if s["y"] <= 47]  # leave out backcourt heaves
    for made, name, color, symbol in [(True, "Made", "#2ecc71", "circle"), (False, "Missed", "#e74c3c", "x")]:
        group = [s for s in on_court if s["made"] == made]
        fig.add_trace(
            go.Scatter(
                x=[s["x"] for s in group], y=[s["y"] for s in group], mode="markers", name=f"{name} ({len(group)})",
                marker=dict(color=color, symbol=symbol, size=10, line=dict(width=1, color="white") if made else None),
                text=[f"{s['text']}<br>{s['game']} · {s['when']}" for s in group],
                hovertemplate="%{text}<extra></extra>",
            )
        )
    fig.update_layout(
        title=title, shapes=shapes, height=560, margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="#041E42", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.02), font=dict(color="white"),
    )
    fig.update_xaxes(range=[-1, 51], visible=False)
    fig.update_yaxes(range=[-1, 48], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def zone_table(shots):
    order = ["At the rim", "Paint (non-rim)", "Mid-range", "Corner 3", "Above-the-break 3"]
    rows = []
    for zone in order:
        group = [s for s in shots if s["zone"] == zone]
        if group:
            made = sum(s["made"] for s in group)
            rows.append({"Zone": zone, "FG": f"{made}-{len(group)}", "FG%": round(100 * made / len(group), 1),
                         "Share of shots": f"{round(100 * len(group) / len(shots))}%"})
    return rows


# ---------- Standings ----------
STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"


@st.cache_data(ttl=30 * 60)
def fetch_standings():
    return get_json(STANDINGS_URL)


def parse_standings(data):
    """Returns {"Eastern Conference": [rows], "Western Conference": [rows]}."""
    conferences = {}

    def entries_of(node):
        found = list((node.get("standings") or {}).get("entries", []))
        for child in node.get("children", []):  # sometimes split into divisions
            found += entries_of(child)
        return found

    for conf in data.get("children", []):
        rows = []
        for entry in entries_of(conf):
            stats = {}
            for s in entry.get("stats", []):
                for key in (s.get("name"), s.get("type"), s.get("displayName")):
                    if key:
                        stats.setdefault(key.lower(), s)

            def val(*keys):
                for k in keys:
                    s = stats.get(k.lower())
                    if s:
                        return s.get("displayValue") or s.get("summary") or s.get("value")
                return ""

            team = entry.get("team", {})
            seed = to_number(val("playoffSeed"))
            rows.append(
                {
                    "Seed": int(seed) if seed else None,
                    "Team": team.get("displayName", ""),
                    "W": val("wins"), "L": val("losses"), "PCT": val("winPercent"),
                    "GB": val("gamesBehind"), "Home": val("home"), "Away": val("road", "away"),
                    "L10": val("lasttengames", "last ten games"), "Streak": val("streak"),
                    "Diff": val("differential", "pointDifferential"),
                    "_pct": to_number(val("winPercent")) or 0,
                    "_cavs": is_cavs(team),
                }
            )
        rows.sort(key=lambda r: (r["Seed"] is None, r["Seed"] or 0, -r["_pct"]))
        for i, r in enumerate(rows, start=1):
            r["Seed"] = r["Seed"] or i
            r["Spot"] = "Playoffs" if r["Seed"] <= 6 else ("Play-in" if r["Seed"] <= 10 else "")
        conferences[conf.get("name", "Conference")] = rows
    return conferences


def standings_table(rows):
    import pandas as pd

    df = pd.DataFrame(rows)
    cavs_flags = df.pop("_cavs")
    df.pop("_pct")
    df = df[["Seed", "Team", "W", "L", "PCT", "GB", "Home", "Away", "L10", "Streak", "Diff", "Spot"]]
    return df.style.apply(
        lambda row: ["background-color:#860038;color:white;font-weight:bold" if cavs_flags[row.name] else "" for _ in row],
        axis=1,
    )


# ---------- News ----------
ESPN_NEWS_URLS = [f"{BASE}/news?team=5", f"{BASE}/teams/{TEAM}/news"]
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q=%22Cleveland+Cavaliers%22+OR+Cavs+NBA&hl=en-US&gl=US&ceid=US:en"


def time_ago(when):
    if not when:
        return ""
    seconds = int((datetime.now(timezone.utc) - when).total_seconds())
    if seconds < 3600:
        return f"{max(seconds // 60, 1)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


@st.cache_data(ttl=15 * 60)
def fetch_news():
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    articles = []
    for url in ESPN_NEWS_URLS:  # ESPN
        try:
            for a in get_json(url).get("articles", []):
                published = a.get("published") or a.get("lastModified")
                articles.append(
                    {
                        "title": a.get("headline", ""),
                        "link": ((a.get("links") or {}).get("web") or {}).get("href", ""),
                        "source": "ESPN",
                        "summary": a.get("description", ""),
                        "when": datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
                    }
                )
            if articles:
                break
        except Exception:
            continue

    try:  # Google News (pulls from Cleveland.com, The Athletic, Cavs.com, etc.)
        response = requests.get(GOOGLE_NEWS_URL, headers=HEADERS, timeout=15)
        root = ET.fromstring(response.content)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            source = item.findtext("source", "")
            if source and title.endswith(f" - {source}"):
                title = title[: -len(f" - {source}")]
            pub = item.findtext("pubDate")
            articles.append(
                {"title": title, "link": item.findtext("link", ""), "source": source or "News",
                 "summary": "", "when": parsedate_to_datetime(pub) if pub else None}
            )
    except Exception:
        pass

    seen, unique = set(), []
    for a in articles:
        key = a["title"].lower()[:70]
        if a["title"] and key not in seen:
            seen.add(key)
            unique.append(a)
    unique.sort(key=lambda a: a["when"] or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True)
    return unique


# ---------- Press conferences (Cavs YouTube channel) ----------
CAVS_CHANNEL_PREFIX = "UCOdS-I1sY"  # start of the official Cavs channel ID
CHANNEL_HANDLES = ["cavs", "Cavaliers", "cavaliers", "ClevelandCavaliers"]
PRESSER_WORDS = ["postgame", "post-game", "pregame", "pre-game", "practice", "press", "media", "availability",
                 "shootaround", "presser", "interview", "speaks", "talks", "media day"]


CAVS_CHANNEL_ID = "UCOdS-I1sYkKWhtTjMUWP_TA"  # official Cleveland Cavaliers YouTube channel


@st.cache_data(ttl=24 * 60 * 60)
def find_cavs_channel_id():
    import re

    if CAVS_CHANNEL_ID:
        return CAVS_CHANNEL_ID
    for handle in CHANNEL_HANDLES:
        try:
            page = requests.get(f"https://www.youtube.com/@{handle}", headers=HEADERS, timeout=15).text
            for cid in re.findall(r"(UC[\w-]{22})", page):
                if cid.startswith(CAVS_CHANNEL_PREFIX):
                    return cid
        except Exception:
            continue
    return None


def youtube_api_key():
    try:
        return st.secrets.get("YOUTUBE_API_KEY", "")
    except Exception:
        return ""


@st.cache_data(ttl=30 * 60)
def fetch_videos(channel_id):
    key = youtube_api_key()
    if key:  # Official YouTube API (most reliable)
        data = get_json(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            {"part": "snippet", "playlistId": f"UU{channel_id[2:]}", "maxResults": 50, "key": key},
        )
        videos = []
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            published = sn.get("publishedAt", "")
            thumbs = sn.get("thumbnails", {})
            videos.append(
                {
                    "title": sn.get("title", ""),
                    "id": (sn.get("resourceId") or {}).get("videoId", ""),
                    "when": datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
                    "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                }
            )
        return videos
    return fetch_videos_rss(channel_id)


def fetch_videos_rss(channel_id):
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    feeds = [
        f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
        f"https://www.youtube.com/feeds/videos.xml?playlist_id=UU{channel_id[2:]}",  # the channel's "uploads" playlist
    ]
    problems, root = [], None
    for url in feeds:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                problems.append(f"HTTP {response.status_code}")
                continue
            root = ET.fromstring(response.content)
            break
        except Exception as error:
            problems.append(type(error).__name__)
    if root is None:
        raise RuntimeError("YouTube feed failed: " + ", ".join(problems))
    videos = []
    for entry in root.findall("a:entry", ns):
        published = entry.findtext("a:published", "", ns)
        thumb = entry.find("m:group/m:thumbnail", ns)
        videos.append(
            {
                "title": entry.findtext("a:title", "", ns),
                "id": entry.findtext("yt:videoId", "", ns),
                "when": datetime.fromisoformat(published) if published else None,
                "thumb": thumb.get("url") if thumb is not None else "",
            }
        )
    return videos


# ---------- Box scores ----------
@st.cache_data(ttl=60)
def fetch_summary(event_id):
    """Fresh box score for one game (used for live games)."""
    return get_json(SUMMARY_URL, {"event": event_id})


def pick_box_game(event_id):
    st.session_state["box_game"] = event_id


def pick_from_table(table_key):
    rows = st.session_state[table_key].selection.rows
    ids = st.session_state.get(f"ids_{table_key}", [])
    if rows and rows[0] < len(ids):
        st.session_state["box_game"] = ids[rows[0]]


def render_box_score(summary, game):
    import pandas as pd

    # Quarter-by-quarter scoring
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    line_rows = []
    for c in sorted(comp.get("competitors", []), key=lambda c: c.get("homeAway") != "away"):
        quarters = [ls.get("displayValue", ls.get("value", "")) for ls in c.get("linescores", [])]
        row = {"Team": (c.get("team") or {}).get("abbreviation", "")}
        for i, q in enumerate(quarters, start=1):
            row[f"Q{i}" if i <= 4 else f"OT{i - 4}" if len(quarters) > 5 else "OT"] = q
        row["Total"] = to_number(c.get("score"))
        row["Total"] = int(row["Total"]) if row["Total"] is not None else ""
        line_rows.append(row)
    if line_rows:
        st.dataframe(line_rows, hide_index=True)

    # Player stats for both teams (Cavs first)
    blocks = sorted((summary.get("boxscore") or {}).get("players", []), key=lambda b: not is_cavs(b.get("team")))
    for block in blocks:
        team = block.get("team") or {}
        for group in block.get("statistics", []):
            columns = group.get("labels") or group.get("names") or []
            starters, bench, dnp = [], [], []
            for e in group.get("athletes", []):
                name = (e.get("athlete") or {}).get("displayName", "Unknown")
                stats = e.get("stats") or []
                if e.get("didNotPlay") or not stats:
                    dnp.append(f"{name} ({e.get('reason') or 'DNP'})")
                    continue
                row = {"Player": name}
                row.update(dict(zip(columns, stats)))
                (starters if e.get("starter") else bench).append(row)
            totals = group.get("totals") or []
            if not starters and not bench:
                continue
            st.markdown(f"#### {team.get('displayName', 'Team')}")
            table = (
                [{"Player": "— STARTERS —"}] + starters
                + ([{"Player": "— BENCH —"}] + bench if bench else [])
                + ([dict({"Player": "TEAM TOTALS"}, **dict(zip(columns, totals)))] if totals else [])
            )
            st.dataframe(pd.DataFrame(table).fillna(""), width="stretch", hide_index=True)
            if dnp:
                st.caption("Did not play: " + ", ".join(dnp))

    # Team stat comparison
    teams = (summary.get("boxscore") or {}).get("teams", [])
    if len(teams) == 2:
        teams = sorted(teams, key=lambda t: not is_cavs(t.get("team")))
        a_stats = {s.get("name") or s.get("label"): s for s in teams[0].get("statistics", [])}
        b_stats = {s.get("name") or s.get("label"): s for s in teams[1].get("statistics", [])}
        compare = [
            {
                "Stat": s.get("label") or key,
                teams[0].get("team", {}).get("abbreviation", "CLE"): s.get("displayValue", ""),
                teams[1].get("team", {}).get("abbreviation", "OPP"): b_stats.get(key, {}).get("displayValue", ""),
            }
            for key, s in a_stats.items()
        ]
        if compare:
            with st.expander("Team stats comparison"):
                st.dataframe(compare, width="stretch", hide_index=True)

    # Cavs shot chart for this game
    game_shots = [s for s in all_shots if s["event"] == game["id"]]
    if game_shots:
        with st.expander("🎯 Cavs shot chart for this game"):
            made = sum(s["made"] for s in game_shots)
            st.plotly_chart(
                shot_chart(game_shots, f"Cavs {matchup(game, short=True)} · {made}-{len(game_shots)} FG"),
                width="stretch", config={"displayModeBar": False}, key=f"box_chart_{game['id']}",
            )


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
all_shots = parse_shots(box_scores, games)

team_info = schedule_data.get("team", {})
record = team_info.get("recordSummary", "")
standing = team_info.get("standingSummary", "")
if record or standing:
    st.subheader(" · ".join(x for x in [record, standing] if x))

games_tab, players_tab, injuries_tab, standings_tab, news_tab, pressers_tab = st.tabs(
    ["📅 Games", "👥 Players", f"🩹 Injuries ({len(injuries)})", "🏆 Standings", "📰 News", "🎤 Pressers"]
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
            st.button(
                f"{icon} {text} {matchup(g)} · {g['date'].strftime('%b %-d')}",
                key=f"last5_{g['id']}", on_click=pick_box_game, args=(g["id"],), type="tertiary",
            )
        if last5:
            wins = sum(1 for g in last5 if result_text(g).startswith("W"))
            st.caption(f"{wins}-{len(last5) - wins} over the last {len(last5)} · click a game for its box score")

    st.markdown("---")
    st.markdown("### Full schedule")
    views = {
        "Upcoming": [g for g in games if not g["completed"]],
        "Played": finished[::-1],
        "All": games,
    }
    for sub_tab, (name, rows) in zip(st.tabs(list(views)), views.items()):
        with sub_tab:
            table_key = f"schedule_table_{name}"
            st.session_state[f"ids_{table_key}"] = [g["id"] for g in rows]
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
                key=table_key,
                on_select=partial(pick_from_table, table_key),
                selection_mode="single-row",
            )
    st.caption("Click a row in Played or All to see that game's box score")

    # --- Box score ---
    st.markdown("---")
    game_by_id = {g["id"]: g for g in games}
    box_id = st.session_state.get("box_game")
    if box_id not in game_by_id:
        box_id = live[0]["id"] if live else (finished[-1]["id"] if finished else None)
    if box_id:
        box_game = game_by_id[box_id]
        st.markdown(f"### 📋 Box score: Cavs {matchup(box_game)} · {box_game['date'].strftime('%a %b %-d')}")
        if not box_game["completed"] and box_game["state"] != "in":
            st.info("This game hasn't been played yet. Box scores show up once it tips off.")
        else:
            summary = box_scores.get(box_id) if box_game["completed"] else None
            if not summary:
                try:
                    summary = fetch_summary(box_id)
                except Exception:
                    summary = None
            if not summary:
                st.warning("Couldn't load this box score right now. Try Refresh.")
            else:
                render_box_score(summary, box_game)

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

        # --- Shot chart ---
        st.markdown("---")
        st.markdown("### 🎯 Shot chart")
        whole_team = st.toggle("Show the whole team instead of this player")
        pool = all_shots if whole_team else [s for s in all_shots if s["player"] == pid]
        who = "Cavs" if whole_team else names[pid]

        if not pool:
            st.info("No shot locations found yet for this selection.")
        else:
            game_options = ["All season"] + list(dict.fromkeys(s["game"] for s in sorted(pool, key=lambda s: s["event"], reverse=True)))
            pick = st.selectbox("Game", game_options)
            shots = pool if pick == "All season" else [s for s in pool if s["game"] == pick]

            chart_col, zone_col = st.columns([3, 2])
            with chart_col:
                made = sum(s["made"] for s in shots)
                st.plotly_chart(
                    shot_chart(shots, f"{who} · {pick} · {made}-{len(shots)} FG"),
                    width="stretch", config={"displayModeBar": False},
                )
            with zone_col:
                st.markdown("**By zone**")
                st.dataframe(zone_table(shots), width="stretch", hide_index=True)
                threes = [s for s in shots if s["three"]]
                twos = [s for s in shots if not s["three"]]
                c1, c2 = st.columns(2)
                if twos:
                    c1.metric("2PT", f"{sum(s['made'] for s in twos)}-{len(twos)}", f"{round(100 * sum(s['made'] for s in twos) / len(twos))}%", delta_color="off")
                if threes:
                    c2.metric("3PT", f"{sum(s['made'] for s in threes)}-{len(threes)}", f"{round(100 * sum(s['made'] for s in threes) / len(threes))}%", delta_color="off")

            with st.expander("🔧 Shot data check (screenshot this for Claude if the chart looks off)"):
                xs, ys = [s["raw_x"] for s in all_shots], [s["raw_y"] for s in all_shots]
                st.write(f"{len(all_shots)} shots · raw x {min(xs)} to {max(xs)} · raw y {min(ys)} to {max(ys)}")
                st.dataframe(
                    [{"raw x": s["raw_x"], "raw y": s["raw_y"], "made": s["made"], "play": s["text"]} for s in all_shots[:12]],
                    width="stretch", hide_index=True,
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

# ---------- Standings tab ----------
with standings_tab:
    try:
        conferences = parse_standings(fetch_standings())
    except Exception as error:
        conferences = {}
        st.error("Couldn't load standings from ESPN right now.")
        st.caption(f"Technical details: {error}")

    if conferences:
        east = next((k for k in conferences if "east" in k.lower()), list(conferences)[0])
        cavs_row = next((r for rows in conferences.values() for r in rows if r["_cavs"]), None)
        if cavs_row:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("East seed", f"#{cavs_row['Seed']}")
            c2.metric("Record", f"{cavs_row['W']}-{cavs_row['L']}")
            c3.metric("Games back", cavs_row["GB"] or "-")
            c4.metric("Streak", cavs_row["Streak"] or "-")

        pick = st.radio("Conference", list(conferences), index=list(conferences).index(east), horizontal=True)
        st.dataframe(standings_table(conferences[pick]), width="stretch", hide_index=True, height=565)
        st.caption("Seeds 1-6 make the playoffs · 7-10 go to the play-in tournament")

# ---------- News tab ----------
with news_tab:
    st.markdown("### Latest Cavs news")
    news = fetch_news()
    if not news:
        st.info("Couldn't load news right now. Try Refresh in a few minutes.")
    else:
        sources = sorted({a["source"] for a in news})
        chosen = st.multiselect("Sources", sources, placeholder="All sources")
        shown = [a for a in news if not chosen or a["source"] in chosen][:40]
        for a in shown:
            st.markdown(f"**[{a['title']}]({a['link']})**  \n{a['source']} · {time_ago(a['when'])}")
            if a["summary"]:
                st.caption(a["summary"])

# ---------- Pressers tab ----------
with pressers_tab:
    st.markdown("### Press conferences & interviews")
    channel_id = find_cavs_channel_id()
    videos, problem = [], ""
    if channel_id:
        try:
            videos = fetch_videos(channel_id)
        except Exception as error:
            problem = str(error)
    if not videos:
        st.info("Couldn't load the Cavs YouTube channel right now. Try Refresh in a few minutes.")
        if problem:
            st.caption(f"Technical details: {problem}")
        st.markdown(
            "**Go straight to YouTube instead:**  \n"
            "[▶️ Cavs channel: latest videos](https://www.youtube.com/@cavs/videos)  \n"
            "[🔎 Search: Cavs postgame press conferences](https://www.youtube.com/results?search_query=cavaliers+postgame+press+conference&sp=CAI%253D)"
        )
    else:
        view = st.radio("Show", ["Last 48 hours", "Pressers & interviews only", "All recent uploads"], horizontal=True)
        cutoff = datetime.now(timezone.utc).timestamp() - 48 * 3600
        if view == "Last 48 hours":
            shown = [v for v in videos if v["when"] and v["when"].timestamp() >= cutoff]
            if not shown:
                st.caption("Nothing posted in the last 48 hours, so here are the latest uploads.")
                shown = videos
        elif view == "Pressers & interviews only":
            shown = [v for v in videos if any(w in v["title"].lower() for w in PRESSER_WORDS)]
            if not shown:
                st.caption("No pressers in the latest uploads, so here's everything new.")
                shown = videos
        else:
            shown = videos
        st.caption(f"{len(shown)} video{'s' if len(shown) != 1 else ''}")

        featured, rest = shown[:2], shown[2:]
        cols = st.columns(2)
        for col, v in zip(cols, featured):
            with col:
                st.video(f"https://www.youtube.com/watch?v={v['id']}")
                st.markdown(f"**{v['title']}**  \n{time_ago(v['when'])}")
        for v in rest:
            thumb_col, text_col = st.columns([1, 4])
            with thumb_col:
                if v["thumb"]:
                    st.image(v["thumb"], width=160)
            with text_col:
                st.markdown(f"**[{v['title']}](https://www.youtube.com/watch?v={v['id']})**  \n{time_ago(v['when'])}")
        st.caption("From the official Cavs YouTube channel · shows their latest uploads")

st.caption(
    f"Data from ESPN · page loaded {datetime.now(EASTERN).strftime('%b %-d, %-I:%M %p ET')}"
)
