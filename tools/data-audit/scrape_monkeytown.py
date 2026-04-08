#!/usr/bin/env python3
"""Scrape every Monkey Town location page for street/postcode/city, then geocode."""
import urllib.request, urllib.parse, re, json, time, math, sys

LOCS = """franeker leeuwarden wolvega apeldoorn arnhem doetinchem ede harderwijk voorthuizen wamel wijchen
groningen middelburg heerlen venlo sittard bergen_op_zoom breda eindhoven mierlo tilburg valkenswaard veghel waalwijk
amsterdam_west amsterdam_noord bussum diemen purmerend schagen uitgeest uithoorn almelo enschede hardenberg zwolle
amersfoort amersfoort_noord ijsselstein leerdam maarssen bleiswijk delft denhaag gouda rijswijk leidschendam rotterdam
sliedrecht spijkenisse vlaardingen warmond""".split()

UA = {'User-Agent':'HollandKidsExplorer/1.0 data audit'}

def fetch(url, retry=2):
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode('utf-8','ignore')
        except Exception as e:
            if i==retry-1:
                print(f'  fetch err: {e}', file=sys.stderr)
            time.sleep(1)
    return ''

def extract_address(html):
    # The Google Maps directions link contains: daddr=Monkeytown+street+postcode+city
    m = re.search(r'daddr=Monkeytown\+([^"&]+)', html)
    if not m: return None
    raw = urllib.parse.unquote_plus(m.group(1))
    # Parse: "Zuidermolenweg 32 1069 CG Amsterdam" - postcode is NL format DDDD AA
    pm = re.search(r'^(.+?)\s+(\d{4}\s?[A-Z]{2})\s+(.+)$', raw)
    if pm:
        return {'street_house': pm.group(1).strip(), 'postcode': pm.group(2), 'city': pm.group(3).strip(), 'raw': raw}
    return {'raw': raw}

def nominatim(query):
    url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({
        'q': query, 'format':'json', 'limit':1, 'countrycodes':'nl'
    })
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]['lat']), float(data[0]['lon']), data[0].get('display_name','')
    except Exception as e:
        print(f'  nom err: {e}', file=sys.stderr)
    return None

results = []
for i, loc in enumerate(LOCS):
    url = f'https://monkeytown.eu/nl/{loc}/home'
    print(f"[{i+1}/{len(LOCS)}] {loc}", file=sys.stderr)
    html = fetch(url)
    addr = extract_address(html) if html else None
    if not addr:
        print(f"  no addr extracted", file=sys.stderr)
        results.append({'slug':loc,'error':'no_addr'})
        time.sleep(0.5)
        continue
    print(f"  addr: {addr.get('raw')}", file=sys.stderr)
    # geocode
    if 'street_house' in addr:
        q = f"{addr['street_house']}, {addr['postcode']}, {addr['city']}, Netherlands"
    else:
        q = f"{addr['raw']}, Netherlands"
    coords = nominatim(q)
    if coords:
        print(f"  → {coords[0]:.6f}, {coords[1]:.6f}", file=sys.stderr)
        results.append({'slug':loc, 'addr':addr, 'lat':coords[0], 'lon':coords[1], 'nominatim':coords[2]})
    else:
        results.append({'slug':loc, 'addr':addr, 'lat':None, 'lon':None})
    time.sleep(1.1)

json.dump(results, open('/tmp/monkeytown_official.json','w'), ensure_ascii=False, indent=2)
print(f'\nSaved {len(results)} → /tmp/monkeytown_official.json', file=sys.stderr)
print(f'With coords: {sum(1 for r in results if r.get("lat"))}', file=sys.stderr)
