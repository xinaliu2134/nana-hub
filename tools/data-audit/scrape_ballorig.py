#!/usr/bin/env python3
"""Scrape every Ballorig NL location page for street/postcode/city, then geocode."""
import urllib.request, urllib.parse, json, re, time, sys

SLUGS = """assen emmen almere lelystad drachten heerenveen sneek arnhem hattem zutphen
groningen hoogezand-sappemeer utrecht veenendaal houten maastricht nieuw-bergen kerkrade
roermond sittard venlo s-hertogenbosch tilburg veldhoven amsterdam-arena amsterdam-gaasperplas
beverwijk heerhugowaard hoorn vlaardingen alphen-aan-den-rijn s-gravenzande gouda enschede
nijverdal wijhe zwolle vlissingen""".split()

UA = {'User-Agent':'HollandKidsExplorer/1.0'}

def fetch(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8','ignore')
    except Exception as e:
        print(f'  fetch err: {e}', file=sys.stderr)
    return ''

def extract(html):
    street = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', html)
    postcode = re.search(r'"postalCode"\s*:\s*"([^"]+)"', html)
    city = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', html)
    # Many Ballorig pages have multiple JSON-LD (HQ + store) - pick the LAST one which is store
    streets = re.findall(r'"streetAddress"\s*:\s*"([^"]+)"', html)
    postcodes = re.findall(r'"postalCode"\s*:\s*"([^"]+)"', html)
    cities = re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', html)
    # HQ is Entrada 100 / 1114 AA — filter it out
    pairs = list(zip(streets, postcodes, cities))
    pairs = [(s,p,c) for s,p,c in pairs if '1114 AA' not in p]
    if pairs:
        s,p,c = pairs[-1]
        return {'street':s,'postcode':p,'city':c}
    return None

def nominatim(query):
    url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({
        'q': query, 'format':'json', 'limit':1, 'countrycodes':'nl'
    })
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]['lat']), float(data[0]['lon']), data[0].get('display_name','')
    except Exception as e:
        print(f'  nom err: {e}', file=sys.stderr)
    return None

results = []
for i, slug in enumerate(SLUGS):
    url = f'https://www.ballorig.nl/{slug}'
    print(f"[{i+1}/{len(SLUGS)}] {slug}", file=sys.stderr)
    html = fetch(url)
    addr = extract(html) if html else None
    if not addr:
        print(f"  no addr", file=sys.stderr)
        results.append({'slug':slug,'error':'no_addr'})
        time.sleep(0.5)
        continue
    print(f"  addr: {addr['street']}, {addr['postcode']} {addr['city']}", file=sys.stderr)
    q = f"{addr['street']}, {addr['postcode']}, {addr['city']}, Netherlands"
    res = nominatim(q)
    if res:
        print(f"  → {res[0]:.6f}, {res[1]:.6f}", file=sys.stderr)
        results.append({'slug':slug, 'addr':addr, 'lat':res[0], 'lon':res[1], 'nominatim':res[2]})
    else:
        # Fallback: drop postcode
        q2 = f"{addr['street']}, {addr['city']}, Netherlands"
        time.sleep(1.1)
        res2 = nominatim(q2)
        if res2:
            print(f"  → {res2[0]:.6f}, {res2[1]:.6f} (retry)", file=sys.stderr)
            results.append({'slug':slug, 'addr':addr, 'lat':res2[0], 'lon':res2[1], 'nominatim':res2[2]})
        else:
            results.append({'slug':slug, 'addr':addr, 'lat':None, 'lon':None})
    time.sleep(1.1)

json.dump(results, open('/tmp/ballorig_official.json','w'), ensure_ascii=False, indent=2)
print(f'\nSaved {len(results)} | with coords: {sum(1 for r in results if r.get("lat"))}', file=sys.stderr)
