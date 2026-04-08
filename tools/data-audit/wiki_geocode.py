#!/usr/bin/env python3
"""Fetch coordinates from Wikipedia for famous venues that Nominatim/Photon missed."""
import json, urllib.request, urllib.parse, time, re, math, sys

# Manually curated list: (db_id, search_title, expected_city)
# Using Wikipedia article titles (English) that are likely to match
VENUES = [
    # museums
    (30, 'NEMO Science Museum', 'Amsterdam'),
    (34, 'Naturalis Biodiversity Center', 'Leiden'),
    (42, 'Tropenmuseum', 'Amsterdam'),
    (43, 'Kunstmuseum Den Haag', 'Den Haag'),  # renamed from Gemeentemuseum
    (138, 'Corpus (museum)', 'Oegstgeest'),
    (141, 'Het Dolhuys', 'Haarlem'),
    (143, 'Ontdekhoek', 'Rotterdam'),  # actually in Rotterdam, not Amsterdam
    (814, 'Orvelte', 'Orvelte'),
    (832, 'Kijk en Luistermuseum', 'Bennekom'),
    (840, 'Maritiem MuZEEum', 'Vlissingen'),
    (891, 'Museum Stoomtram Hoorn–Medemblik', 'Hoorn'),
    (892, 'Westfries Museum', 'Hoorn'),
    (914, 'Wrakkenmuseum', 'Terschelling'),
    # theme parks / aquariums / zoos
    (130, 'Speelpark Oud Valkeveen', 'Naarden'),
    (133, 'Attractiepark Tivoli', 'Berg en Dal'),
    (939, 'Columbus Amusement Park', 'Valkenburg aan de Geul'),
    (136, 'Vogelpark Avifauna', 'Alphen aan den Rijn'),
    (21, 'Sea Life Amsterdam', 'Amsterdam'),
]

def wiki_coords(title, lang='en'):
    # Try English Wikipedia first, then Dutch
    for L in [lang, 'nl']:
        url = f'https://{L}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({
            'action':'query','prop':'coordinates','titles':title,
            'format':'json','coprop':'type','redirects':1
        })
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'HollandKidsExplorer/1.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                pages = data.get('query',{}).get('pages',{})
                for pid, page in pages.items():
                    if 'coordinates' in page:
                        c = page['coordinates'][0]
                        return float(c['lat']), float(c['lon']), page.get('title',title), L
        except Exception as e:
            print(f'  err {L}: {e}', file=sys.stderr)
    return None

src_path = '/Users/nana/Desktop/nana-hub/holland-kids-explorer.html'
src = open(src_path).read()

fixes = []
for db_id, title, city in VENUES:
    print(f"[{db_id}] {title}", file=sys.stderr)
    res = wiki_coords(title)
    if res:
        print(f"  → {res[0]:.5f},{res[1]:.5f}  ({res[2]} via {res[3]}.wiki)", file=sys.stderr)
        fixes.append((db_id, res[0], res[1]))
    else:
        print(f"  NOT FOUND", file=sys.stderr)
    time.sleep(0.4)

applied = 0
for id_, lat, lon in fixes:
    pat = re.compile(rf"(\{{\s*type:'node',id:{id_},lat:)([\d.]+)(,lon:)([\d.]+)")
    new_src, n = pat.subn(rf"\g<1>{lat:.6f}\g<3>{lon:.6f}", src)
    if n == 1:
        src = new_src; applied += 1
open(src_path, 'w').write(src)
print(f'\nFixed {applied}/{len(VENUES)} venues from Wikipedia', file=sys.stderr)
