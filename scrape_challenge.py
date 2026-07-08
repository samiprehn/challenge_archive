#!/usr/bin/env python3
"""Build data_tc.js — daily challenges and elimination games from MTV's The Challenge.

Dailies come from each season page's "Game Summary" elimination chart (names +
format inferred from winner icons). Eliminations come from the wiki's big
"Eliminations" page (names + descriptions per season). The wiki has no winners
tables per game, so airings carry no winners.
"""

import json
import re
import time
import urllib.parse
import urllib.request

from scrape import strip_markup, element_tags, extract_section, norm_file, clean_description

API = "https://thechallenge.fandom.com/api.php"
WIKI = "https://thechallenge.fandom.com/wiki/"
OUT = "data_tc.js"

# flagship seasons by official number
FLAGSHIP = {
    1: "Road Rules: All Stars",
    2: "Real World/Road Rules Challenge",
    3: "Real World/Road Rules Challenge 2000",
    4: "Real World/Road Rules Extreme Challenge",
    5: "Real World/Road Rules Challenge: Battle of the Seasons",
    6: "Real World/Road Rules Challenge: Battle of the Sexes",
    7: "Real World/Road Rules Challenge: The Gauntlet",
    8: "Real World/Road Rules Challenge: The Inferno",
    9: "Real World/Road Rules Challenge: Battle of the Sexes 2",
    10: "Real World/Road Rules Challenge: The Inferno II",
    11: "Real World/Road Rules Challenge: The Gauntlet 2",
    12: "Real World/Road Rules Challenge: Fresh Meat",
    13: "Real World/Road Rules Challenge: The Duel",
    14: "Real World/Road Rules Challenge: The Inferno 3",
    15: "Real World/Road Rules Challenge: The Gauntlet III",
    16: "Real World/Road Rules Challenge: The Island",
    17: "Real World/Road Rules Challenge: The Duel II",
    18: "Real World/Road Rules Challenge: The Ruins",
    19: "The Challenge: Fresh Meat II",
    20: "The Challenge: Cutthroat",
    21: "The Challenge: Rivals",
    22: "The Challenge: Battle of the Exes",
    23: "The Challenge: Battle of the Seasons",
    24: "The Challenge: Rivals II",
    25: "The Challenge: Free Agents",
    26: "The Challenge: Battle of the Exes II",
    27: "The Challenge: Battle of the Bloodlines",
    28: "The Challenge: Rivals III",
    29: "The Challenge: Invasion of the Champions",
    30: "The Challenge XXX: Dirty 30",
    31: "The Challenge: Vendettas",
    32: "The Challenge: Final Reckoning",
    33: "The Challenge: War of the Worlds",
    34: "The Challenge: War of the Worlds 2",
    35: "The Challenge: Total Madness",
    36: "The Challenge: Double Agents",
    37: "The Challenge: Spies, Lies & Allies",
    38: "The Challenge: Ride or Dies",
    39: "The Challenge: Battle for a New Champion",
    40: "The Challenge 40: Battle of the Eras",
    41: "The Challenge: Vets & New Threats",
}
# spinoffs: sort index -> page title
SPINOFFS = {
    101: "The Challenge: All Stars 1",
    102: "The Challenge: All Stars 2",
    103: "The Challenge: All Stars 3",
    104: "The Challenge: All Stars 4",
    105: "The Challenge: All Stars 5",  # no season page yet; used for Eliminations tab only
    111: "Champs vs. Pros",
    112: "Champs vs. Stars",
    113: "Champs vs. Stars 2",
    121: "The Challenge: USA 1",
    122: "The Challenge: USA 2",
    131: "The Challenge: Australia",
    132: "The Challenge: Argentina",
    133: "The Challenge: UK",
    134: "The Challenge: World Championship",
}
SEASONS = {**FLAGSHIP, **SPINOFFS}

# Eliminations page tab label -> season index
TAB_SEASONS = dict(
    [(f"CH{n}", n) for n in FLAGSHIP],
    AS1=101, AS2=102, AS3=103, AS4=104, AS5=105,
    CvS1=112, CvS2=113, USA1=121, USA2=122,
    Australia=131, Argentina=132, UK=133, WC=134,
)


def edition(idx):
    """Filter code for a season: MTV flagship/Champs, All Stars, USA, or country."""
    if idx in (131, 132, 133, 134):
        return {131: "AU", 132: "AR", 133: "UK", 134: "WC"}[idx]
    if 101 <= idx <= 105:
        return "TCAS"
    if 121 <= idx <= 122:
        return "TCUSA"
    return "TC"


def short_label(idx):
    title = SEASONS[idx]
    for pre in ("Real World/Road Rules Challenge: ", "Real World/Road Rules ",
                "The Challenge: ", "The Challenge "):
        if title.startswith(pre):
            return title[len(pre):]
    return title


def api_get(params):
    params = dict(params, format="json", formatversion="2")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "survivor-challenges-scraper"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def get_wikitext(page):
    data = api_get({"action": "parse", "page": page, "prop": "wikitext"})
    if "parse" not in data:
        return None
    return data["parse"]["wikitext"]


# seasons whose episodes have their own wiki pages (with stills)
EPISODE_CATS = {
    121: "Category:The Challenge: USA 1 Episodes",
    122: "Category:The Challenge: USA 2 Episodes",
    131: "Category:The Challenge: Australia Episodes",
    133: "Category:The Challenge: UK Episodes",
}


def infobox_image(text):
    m = re.search(r"\|\s*image\d?\s*=\s*([^|}\n]+)", text or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    f = re.search(r"(?:File|Image):\s*([^|\]]+)", raw)
    return f.group(1).strip() if f else raw


def episode_stills():
    """(season_idx, episode) -> image file, from episode page infoboxes."""
    stills = {}
    for idx, cat in EPISODE_CATS.items():
        members = api_get({"action": "query", "list": "categorymembers",
                           "cmtitle": cat, "cmnamespace": "0", "cmlimit": "500"})
        titles = [m["title"] for m in members["query"]["categorymembers"]]
        for i in range(0, len(titles), 50):
            data = api_get({"action": "query", "prop": "revisions", "rvprop": "content",
                            "rvslots": "main", "titles": "|".join(titles[i:i + 50])})
            for page in data["query"]["pages"]:
                revs = page.get("revisions")
                if not revs:
                    continue
                text = revs[0]["slots"]["main"]["content"]
                ep = re.search(r"\|\s*episode\s*=\s*(\d+)", text)
                img = infobox_image(text)
                if ep and img:
                    stills[(idx, int(ep.group(1)))] = img
            time.sleep(0.2)
    return stills


def resolve_images(filenames):
    urls = {}
    names = sorted({"File:" + norm_file(f) for f in filenames if f})
    for i in range(0, len(names), 50):
        data = api_get({"action": "query", "prop": "imageinfo", "iiprop": "url",
                        "titles": "|".join(names[i:i + 50])})
        for page in data["query"]["pages"]:
            info = page.get("imageinfo")
            if info:
                urls[page["title"].replace("File:", "", 1)] = info[0]["url"]
        time.sleep(0.2)
    return urls


def strip_cell_attrs(cell):
    return re.sub(r'^\s*(?:(?:rowspan|colspan|style|class|bgcolor|align|nowrap|width)\s*'
                  r'(?:=\s*(?:"[^"]*"|[^|\s]+))?\s*\|?\s*)+', "", cell)


def parse_dailies(text, season_idx):
    """Daily challenge names + inferred format from a season's elimination chart."""
    section = extract_section(text, r"Game [Ss]ummary")
    if not section:
        return []
    table = re.search(r"\{\|.*?\n\|\}", section, re.S)
    if not table:
        return []
    rows = re.split(r"\n\|-", table.group(0))

    # group rows by episode-header rows (! N)
    groups, cur = [], None
    for row in rows:
        lines = [l.strip() for l in row.split("\n") if l.strip()]
        ep = None
        for l in lines:
            if l.startswith("!") and not l.startswith("!!"):
                content = strip_cell_attrs(l[1:]).strip()
                m = re.match(r"(\d+)(?:/\d+)?$", content)
                if m:
                    ep = int(m.group(1))
                break
        if ep is not None:
            cur = {"episode": ep, "lines": lines}
            groups.append(cur)
        elif cur:
            cur["lines"] += lines

    dailies = []
    for g in groups:
        # first pipe-cell after the episode header is the challenge name
        name = None
        seen_ep = False
        fmt = None
        for l in g["lines"]:
            if l.startswith("!"):
                seen_ep = True
                continue
            if not l.startswith("|") or l.startswith("|}"):
                continue
            cell = strip_cell_attrs(l[1:])
            if name is None and seen_ep:
                name = strip_markup(cell)
                continue
            if name is not None and fmt is None:
                if re.search(r"\bTeam\s", cell):
                    fmt = "Team"
                else:
                    icons = len(re.findall(r"\[\[File:", cell))
                    if icons == 1:
                        fmt = "Individual"
                    elif icons == 2:
                        fmt = "Pairs"
                    elif icons > 2:
                        fmt = "Team"
        if name and 1 < len(name) < 60 and not re.search(r"[{}=]|wikitable", name):
            dailies.append({
                "country": edition(season_idx), "season": season_idx, "label": short_label(season_idx),
                "episode": g["episode"],
                "type": f"Daily Challenge ({fmt})" if fmt else "Daily Challenge",
                "winners": [],
            })
            dailies[-1]["name"] = name
    return dailies


def parse_eliminations():
    """Elimination games with descriptions from the Eliminations page."""
    text = get_wikitext("Eliminations")
    games = []
    season_idx = None
    for line in text.split("\n"):
        for m in re.finditer(r"(?:<tabber>|\|-\|)\s*([A-Za-z0-9]+)\s*=", line):
            season_idx = TAB_SEASONS.get(m.group(1))
        m = re.match(r"\*\s*'''(.+?)'''\s*:?\s*(.*)", line)
        if m and season_idx:
            name = strip_markup(m.group(1)).strip().rstrip(":")
            desc = clean_description(strip_markup(m.group(2)))
            if not name or len(name) > 60:
                continue
            fmt = "Pairs" if re.search(
                r"\b(pairs?|partners?|two teams of two|2v2|two.on.two|both team(mate)?s)\b",
                desc, re.I) else "1v1"
            games.append({
                "name": name, "description": desc,
                "airing": {"country": edition(season_idx), "season": season_idx,
                           "label": short_label(season_idx), "episode": None,
                           "type": f"Elimination ({fmt})", "winners": []},
            })
    return games


def main():
    entries = {}  # name -> challenge entry

    def entry(name):
        return entries.setdefault(name, {
            "name": name, "description": "", "rules": "", "image": "",
            "show": "tc", "rulesPairs": False, "elements": [], "airings": [], "url": "",
        })

    season_art = {}
    for idx in sorted(SEASONS):
        text = get_wikitext(SEASONS[idx])
        if text is None:
            print(f"  !! missing page: {SEASONS[idx]}")
            continue
        season_art[idx] = infobox_image(text)
        dailies = parse_dailies(text, idx)
        print(f"  {short_label(idx)}: {len(dailies)} dailies")
        for d in dailies:
            name = d.pop("name")
            e = entry(name)
            e["airings"].append(d)
            if not e["url"]:
                e["url"] = WIKI + urllib.parse.quote(SEASONS[idx].replace(" ", "_"))
        time.sleep(0.2)

    games = parse_eliminations()
    print(f"{len(games)} elimination listings")
    for g in games:
        e = entry(g["name"])
        e["airings"].append(g["airing"])
        if g["description"] and len(g["description"]) > len(e["description"]):
            e["description"] = g["description"]
        e["url"] = WIKI + "Eliminations"

    challenges = list(entries.values())
    for c in challenges:
        c["elements"] = element_tags(c["description"])

    # images: episode still of earliest airing if one exists, else that season's key art
    stills = episode_stills()
    print(f"{len(stills)} episode stills")
    for c in challenges:
        for a in sorted(c["airings"], key=lambda a: a["season"]):
            f = stills.get((a["season"], a["episode"])) or season_art.get(a["season"])
            if f:
                c["image"] = f
                break
    urls = resolve_images([c["image"] for c in challenges])
    withimg = 0
    for c in challenges:
        c["image"] = urls.get(norm_file(c["image"]), "")
        withimg += bool(c["image"])
    print(f"{withimg}/{len(challenges)} entries with an image")
    print(f"{len(challenges)} The Challenge entries, "
          f"{sum(len(c['airings']) for c in challenges)} airings")

    with open(OUT, "w") as f:
        f.write("const TC_CHALLENGES = ")
        json.dump(challenges, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
