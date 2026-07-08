# Survivor Challenge Archive

Browse every US Survivor challenge — grouped by individual, pairs, or team format — with every airing, type, and winner.

- `index.html` — the whole app (vanilla HTML/CSS/JS), works as a plain local file
- `data.js` — generated challenge data
- `scrape.py` — rebuilds `data.js` from the [Survivor Wiki](https://survivor.fandom.com/wiki/Category:Challenges): `python3 scrape.py` (stdlib only). Rerun after a new season airs.

Coverage = every challenge with a Survivor Wiki page. Photos hotlink from the wiki CDN, so they need internet.
