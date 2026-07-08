# Survivor Challenge Archive

Browse every Survivor challenge worldwide plus MTV's The Challenge (dailies + eliminations) — filter by show, country, format (individual/pairs/teams), type, and elements like puzzle or endurance.

- `index.html` — the whole app (vanilla HTML/CSS/JS), works as a plain local file
- `data.js` / `data_tc.js` — generated challenge data
- `scrape.py` — rebuilds `data.js` from the [Survivor Wiki](https://survivor.fandom.com/wiki/Category:Challenges)
- `scrape_challenge.py` — rebuilds `data_tc.js` from [The Challenge Wiki](https://thechallenge.fandom.com/) (season charts + Eliminations page; that wiki has no per-game winners)
- Rerun the scrapers (`python3 scrape.py`, stdlib only) after a new season airs; new The Challenge seasons need their title added to `FLAGSHIP`/`SPINOFFS` in `scrape_challenge.py`.

Coverage = every challenge with a Survivor Wiki page. Photos hotlink from the wiki CDN, so they need internet.
