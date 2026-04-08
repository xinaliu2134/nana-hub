#!/usr/bin/env python3
"""
Venue coordinate auditor for Kids Explorer HTML files.

Extracts venues matching given category filters, geocodes each via
Nominatim then Photon fallback, and saves a patch plan JSON.

Usage:
    python3 tools/data-audit/audit.py <html_file> \\
        --categories indoor_playground theme_park museum \\
        --out /tmp/audit_plan.json

Supported categories (OSM tag values):
    tourism:  theme_park, zoo, aquarium, museum, attraction, visitor_centre
    leisure:  indoor_playground, playground, nature_reserve, park,
              trampoline_park, swimming_pool, climbing_park, ice_rink,
              go_kart, miniature_golf
"""
import re, json, time, urllib.request, urllib.parse, math, sys, argparse

TAG_KIND = {
    # leisure tags
    'indoor_playground':'leisure', 'playground':'leisure',
    'nature_reserve':'leisure', 'park':'leisure',
    'trampoline_park':'leisure', 'swimming_pool':'leisure',
    'climbing_park':'leisure', 'ice_rink':'leisure',
    'go_kart':'leisure', 'miniature_golf':'leisure',
    # tourism tags
    'theme_park':'tourism', 'zoo':'tourism', 'aquarium':'tourism',
    'museum':'tourism', 'attraction':'tourism', 'visitor_centre':'tourism',
    # amenity tags
    'theatre':'amenity', 'cinema':'amenity',
}

def haversine_m(a1,o1,a2,o2):
    R=6371000; p1,p2=math.radians(a1),math.radians(a2)
    dp=math.radians(a2-a1); dl=math.radians(o2-o1)
    return 2*R*math.asin(math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))

UA = {'User-Agent':'HollandKidsExplorer-DataAudit/1.0'}

def nominatim(query):
    url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({
        'q': query, 'format':'json', 'limit':1, 'countrycodes':'nl'
    })
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]['lat']), float(data[0]['lon']), data[0].get('display_name','')
    except Exception as e:
        print(f'  nominatim err: {e}', file=sys.stderr)
    return None

def photon(query, bias_lat=None, bias_lon=None):
    params = {'q':query, 'limit':1, 'lang':'en'}
    if bias_lat is not None:
        params['lat']=bias_lat; params['lon']=bias_lon
    url = 'https://photon.komoot.io/api/?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            for f in data.get('features',[]):
                if f['properties'].get('countrycode') == 'NL':
                    c = f['geometry']['coordinates']  # [lon,lat]
                    return float(c[1]), float(c[0]), f['properties'].get('name','')
    except Exception as e:
        print(f'  photon err: {e}', file=sys.stderr)
    return None

ENTRY_RE = re.compile(
    r"\{\s*type:'node',id:(\d+),lat:([\d.]+),lon:([\d.]+),\s*tags:\{([^}]*)\}\s*\}",
    re.DOTALL
)

def get_tag(tags, key):
    """Extract a tag value, handling both single- and double-quoted strings."""
    if ':' in key:
        mm = re.search(rf"'{re.escape(key)}':\s*['\"]((?:[^'\"\\]|\\.)*)['\"]", tags)
    else:
        mm = re.search(rf"\b{key}:['\"]((?:[^'\"\\]|\\.)*)['\"]", tags)
    return mm.group(1) if mm else None

def extract_entries(html, categories):
    m = re.search(r'const STATIC_NL_VENUES = \[(.*?)^\];', html, re.DOTALL|re.MULTILINE)
    if not m:
        print('ERROR: STATIC_NL_VENUES array not found', file=sys.stderr)
        return []
    block = m.group(1)
    wanted_markers = set()
    for cat in categories:
        kind = TAG_KIND.get(cat)
        if not kind:
            print(f'WARN: unknown category {cat}', file=sys.stderr)
            continue
        wanted_markers.add((cat, f"{kind}:'{cat}'"))
    entries = []
    for m in ENTRY_RE.finditer(block):
        tags = m.group(4)
        for cat, marker in wanted_markers:
            if marker in tags:
                entries.append({
                    'id': int(m.group(1)),
                    'lat': float(m.group(2)),
                    'lon': float(m.group(3)),
                    'cat': cat,
                    'name': get_tag(tags,'name'),
                    'nameZh': get_tag(tags,'nameZh'),
                    'city': get_tag(tags,'addr:city'),
                    'street': get_tag(tags,'addr:street'),
                    'housenumber': get_tag(tags,'addr:housenumber'),
                })
                break
    return entries

def build_query(e):
    if e['name'] and e['city']:
        return f"{e['name']}, {e['city']}, Netherlands"
    if e['street'] and e['housenumber'] and e['city']:
        return f"{e['street']} {e['housenumber']}, {e['city']}, Netherlands"
    if e['name']:
        return f"{e['name']}, Netherlands"
    return None

def audit(html_path, categories, out_path):
    html = open(html_path).read()
    entries = extract_entries(html, categories)
    print(f'Extracted {len(entries)} venues across {len(categories)} categories', file=sys.stderr)

    results = []
    for i, e in enumerate(entries):
        q = build_query(e)
        if not q:
            results.append({**e, 'new_lat':None, 'new_lon':None, 'source':None})
            continue
        print(f"[{i+1}/{len(entries)}] {e['cat']} | {e['name']} ({e['city']})", file=sys.stderr)
        # Try Nominatim first
        res = nominatim(q)
        src = 'nominatim'
        time.sleep(1.1)
        if not res:
            # Photon fallback
            res = photon(q, e['lat'], e['lon'])
            src = 'photon'
            time.sleep(0.5)
        dist = None
        if res:
            dist = haversine_m(e['lat'], e['lon'], res[0], res[1])
            print(f"    → {res[0]:.5f},{res[1]:.5f} ({dist:.0f}m) [{src}]", file=sys.stderr)
        results.append({**e, 'new_lat':res[0] if res else None, 'new_lon':res[1] if res else None,
                        'nominatim':res[2] if res else None, 'distance_m':dist, 'source':src if res else None})
    json.dump(results, open(out_path,'w'), ensure_ascii=False, indent=2)
    print(f'\nSaved to {out_path}', file=sys.stderr)

    # Print summary
    found = [r for r in results if r['new_lat'] is not None]
    buckets = {'<100m':0,'100-500m':0,'500m-2km':0,'2-5km':0,'>5km':0}
    for r in found:
        d = r['distance_m']
        if d<100: buckets['<100m']+=1
        elif d<500: buckets['100-500m']+=1
        elif d<2000: buckets['500m-2km']+=1
        elif d<5000: buckets['2-5km']+=1
        else: buckets['>5km']+=1
    print(f'\nDistance buckets (vs current coords):', file=sys.stderr)
    for k,v in buckets.items():
        print(f'  {k}: {v}', file=sys.stderr)
    print(f'  Not found: {len(results)-len(found)}', file=sys.stderr)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('html_file')
    p.add_argument('--categories', nargs='+', required=True,
                   help='OSM tag values to audit (e.g. indoor_playground theme_park)')
    p.add_argument('--out', default='/tmp/audit_plan.json')
    args = p.parse_args()
    audit(args.html_file, args.categories, args.out)
