#!/usr/bin/env python3
"""Build data.js for the Survivor challenge browser.

Pulls every challenge page from the Survivor fandom wiki, keeps the ones with
US airings, and writes them as `const CHALLENGES = [...]`. Rerun after a new
season to refresh the data.
"""

import json
import re
import time
import urllib.parse
import urllib.request

API = "https://survivor.fandom.com/api.php"
OUT = "data.js"


def api_get(params):
    params = dict(params, format="json", formatversion="2")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "survivor-challenges-scraper"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def list_challenge_pages():
    titles, cont = [], {}
    while True:
        data = api_get({
            "action": "query", "list": "categorymembers",
            "cmtitle": "Category:Challenges", "cmnamespace": "0",
            "cmlimit": "500", **cont,
        })
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]


def fetch_wikitexts(titles):
    texts = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = api_get({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "|".join(batch),
        })
        for page in data["query"]["pages"]:
            revs = page.get("revisions")
            if revs:
                texts[page["title"]] = revs[0]["slots"]["main"]["content"]
        time.sleep(0.3)
    return texts


def strip_markup(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"\{\{[Dd]ab\|[^|}]*\|([^}]*)\}\}", r"\1", text)
    text = re.sub(r"\{\{S2?\|(\d+)\}\}", r"season \1", text)
    for _ in range(3):  # remaining templates, innermost first
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_template_params(body):
    """Split template body on top-level pipes (ignores pipes in nested {{ }} / [[ ]])."""
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur += two; i += 2; continue
        if two in ("}}", "]]"):
            depth -= 1; cur += two; i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += body[i]
        i += 1
    parts.append(cur)
    return parts


def extract_infobox(text):
    m = re.search(r"\{\{Challenge\s*\|", text)
    if not m:
        return {}
    # find matching close
    depth, i = 0, m.start()
    while i < len(text):
        if text[i:i + 2] == "{{":
            depth += 1; i += 2; continue
        if text[i:i + 2] == "}}":
            depth -= 1; i += 2
            if depth == 0:
                break
            continue
        i += 1
    body = text[m.end() - 1:i - 2]  # from first pipe
    fields = {}
    for part in split_template_params(body):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip()] = v.strip()
    return fields


def extract_section(text, header):
    m = re.search(r"^==\s*" + header + r"\s*==\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^==[^=].*==\s*$", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def us_winners_wikitext(text):
    section = extract_section(text, "Winners")
    if not section:
        return ""
    if "<tabber>" not in section:
        return section
    tab = re.search(r"United States\s*=(.*?)(?=\|-\||</tabber>|\Z)", section, re.S)
    return tab.group(1) if tab else ""


def parse_winner_names(cell):
    # names carried in image links: [[File:...|60px|link=Name]]
    names = re.findall(r"\[\[(?:File|Image):[^\]]*\|link=([^\]|]+)\]\]", cell)
    for tmpl in re.finditer(r"\{\{tribebox[^{}]*\}\}", cell):
        params = split_template_params(tmpl.group(0)[2:-2])[1:]  # drop template name
        params = [strip_markup(p) for p in params if "[[" not in p]  # links handled above
        params = [p for p in params
                  if p and not re.search(r"\.(png|jpe?g|gif|webp)$", p, re.I)
                  and not re.fullmatch(r"\d+(px)?", p)]
        if params:
            names += params[1:]  # first remaining param is the tribe slug
    if not names:
        for link in re.finditer(r"\[\[([^\]]+)\]\]", cell):
            target = link.group(1)
            if re.match(r"(File|Image):", target, re.I):
                continue
            names.append(target.split("|")[-1].strip())
    if not names:
        plain = strip_markup(cell)
        if plain and not plain.lower().startswith(("none", "n/a")):
            names.append(plain)
    # dedupe, keep order
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out


def parse_airings(table_text, unknown_types):
    """One airing per table row: {season, episode, type, winners}."""
    airings = []
    carry_season = carry_episode = None
    carry_rows = 0
    for raw_row in re.split(r"\n\|-", table_text):
        cells = []
        for line in raw_row.split("\n"):
            line = line.strip()
            if line.startswith("!") or line in ("|}", "{|") or line.startswith("{|"):
                continue
            if line.startswith("|"):
                # split multi-cell lines on || at top level
                for c in re.split(r"\|\|", line[1:]):
                    cells.append(c)
        # drop style-only cells like 'colspan="2" {{tribebox...' -> keep content after last attr
        cleaned = []
        for c in cells:
            c = re.sub(r'^\s*(?:(?:rowspan|colspan|style|class)="[^"]*"\s*\|?\s*)+', "", c)
            cleaned.append(c.strip())
        cells = [c for c in cleaned if c]
        if not cells:
            continue
        season = episode = None
        m = re.search(r"\{\{S2?\|(\d+)\}\}", cells[0])
        if m:
            season = int(m.group(1))
            ep = re.search(r"\{\{Ep\|(\d{3,4})[^}]*\}\}", cells[0])
            if ep:
                code = ep.group(1).zfill(4)
                episode = int(code[2:])
            rs = re.search(r'rowspan="(\d+)"', raw_row)
            carry_season, carry_episode = season, episode
            carry_rows = int(rs.group(1)) - 1 if rs else 0
            type_idx = 1
        elif carry_rows > 0:
            season, episode = carry_season, carry_episode
            carry_rows -= 1
            type_idx = 0
        else:
            continue
        if season is None or len(cells) <= type_idx:
            continue
        ctype = strip_markup(cells[type_idx])
        if not ctype or "{{" in cells[type_idx][:2]:
            continue
        winners = []
        for c in cells[type_idx + 1:]:
            winners += parse_winner_names(c)
        low = ctype.lower()
        if not any(w in low for w in ("immunity", "reward", "duel", "combined",
                                      "tribal", "individual", "team", "pair", "advantage")):
            unknown_types.add(ctype)
        airings.append({"season": season, "episode": episode,
                        "type": ctype, "winners": winners})
    return airings


def format_tags(airings, rules):
    tags = set()
    if re.search(r"\bpairs?\b", rules, re.I):
        tags.add("pairs")
    for a in airings:
        low = a["type"].lower()
        if "pair" in low:
            tags.add("pairs")
        elif "tribal" in low or "team" in low or "tribe" in low:
            # a "team" of exactly two is a pairs run
            tags.add("pairs" if len(a["winners"]) == 2 else "teams")
        elif "individual" in low or "duel" in low:
            tags.add("individual")
        else:
            tags.add("teams" if len(a["winners"]) > 3 else "individual")
    return sorted(tags)


def kind_tags(airings):
    tags = set()
    for a in airings:
        low = a["type"].lower()
        if "reward" in low:
            tags.add("reward")
        if "immunity" in low:
            tags.add("immunity")
        if "duel" in low:
            tags.add("duel")
    return sorted(tags)


def resolve_images(filenames):
    urls = {}
    names = ["File:" + f for f in filenames]
    for i in range(0, len(names), 50):
        data = api_get({
            "action": "query", "prop": "imageinfo", "iiprop": "url",
            "titles": "|".join(names[i:i + 50]),
        })
        for page in data["query"]["pages"]:
            info = page.get("imageinfo")
            if info:
                urls[page["title"].replace("File:", "", 1)] = info[0]["url"]
        time.sleep(0.3)
    return urls


def main():
    titles = list_challenge_pages()
    print(f"{len(titles)} challenge pages in category")
    texts = fetch_wikitexts(titles)
    print(f"{len(texts)} wikitexts fetched")

    unknown_types = set()
    challenges, image_files = [], []
    for title, text in sorted(texts.items()):
        info = extract_infobox(text)
        airings = parse_airings(us_winners_wikitext(text), unknown_types)
        if not airings:
            continue
        rules = strip_markup(extract_section(text, "Rules"))
        image = (info.get("image") or "").split("|")[0].strip()
        if image:
            image_files.append(image)
        challenges.append({
            "name": title,
            "description": strip_markup(info.get("description", "")),
            "rules": rules,
            "imageFile": image,
            "airings": airings,
            "formats": format_tags(airings, rules),
            "kinds": kind_tags(airings),
            "debut": min(a["season"] for a in airings),
            "latest": max(a["season"] for a in airings),
        })

    print(f"{len(challenges)} challenges with US airings")
    if unknown_types:
        print("Unrecognized challenge types:", sorted(unknown_types))

    urls = resolve_images(image_files)
    for c in challenges:
        c["image"] = urls.get(c.pop("imageFile"), "")

    with open(OUT, "w") as f:
        f.write("const CHALLENGES = ")
        json.dump(challenges, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
