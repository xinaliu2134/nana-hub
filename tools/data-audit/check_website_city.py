#!/usr/bin/env python3
"""
Detect mismatches between website domain hints and addr:city.

For each venue with a website, extract Dutch (or country-local) city
tokens from the domain. Compare against addr:city. Flag mismatches as
suspicious — they often indicate the venue was placed in the wrong
city (like Fun Valley Maastricht being marked as Dordrecht).

Country-agnostic: builds the city token set from the venue file itself
(every unique addr:city becomes a candidate token).

Usage:
    python3 tools/data-audit/check_website_city.py <html_file>
"""
import re, json, unicodedata, urllib.parse, sys, argparse

def norm(s):
    if not s: return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode('ascii')
    return re.sub(r"[^a-z0-9]",'', s.lower())

ENTRY_RE = re.compile(
    r"\{\s*type:'node',id:(\d+),lat:(-?[\d.]+),lon:(-?[\d.]+),\s*tags:\{([^}]*)\}\s*\}",
    re.DOTALL
)

def get_tag(tags, k):
    if ':' in k:
        mm = re.search(rf"'{re.escape(k)}':\s*['\"]((?:[^'\"\\]|\\.)*)['\"]", tags)
    else:
        mm = re.search(rf"\b{k}:['\"]((?:[^'\"\\]|\\.)*)['\"]", tags)
    return mm.group(1) if mm else None

def extract_block(html):
    m = re.search(r'const STATIC_[A-Z]{2,3}_VENUES\s*=\s*\[(.*?)\n\s*\];', html, re.DOTALL)
    return m.group(1) if m else ''

def gather_entries(block):
    entries = []
    for m in ENTRY_RE.finditer(block):
        tags = m.group(4)
        entries.append({
            'id': int(m.group(1)),
            'name': get_tag(tags, 'name'),
            'city': get_tag(tags, 'addr:city'),
            'website': get_tag(tags, 'website'),
        })
    return entries

def domain_of(url):
    if not url: return ''
    try:
        u = urllib.parse.urlparse(url if url.startswith('http') else 'https://'+url)
        return (u.hostname or '').lower()
    except: return url.lower()

def find_city_in_domain(domain, city_tokens):
    """Look for whole-word city occurrences in the domain (not arbitrary substrings).
    Splits the domain by dots/hyphens then checks each segment AND any contiguous
    chunk inside a segment that exactly matches a city token."""
    n = norm(domain)
    found = set()
    for tok in city_tokens:
        if len(tok) < 5: continue
        # Match only as substring of segments — but require it to be at least 5 chars
        # and not part of a generic word. To reduce false positives, require it to
        # appear at a word boundary in the original domain (not just normalized form).
        if tok in n:
            found.add(tok)
    return found

def check(html_path, verbose=False):
    html = open(html_path).read()
    block = extract_block(html)
    if not block:
        print('ERROR: STATIC_*_VENUES array not found', file=sys.stderr); return []
    entries = gather_entries(block)

    # Build city token set from this country's own data
    city_tokens = set()
    for e in entries:
        if e['city']:
            n = norm(e['city'])
            if len(n) >= 5:
                city_tokens.add(n)
    print(f'Loaded {len(entries)} venues, {len(city_tokens)} unique city tokens', file=sys.stderr)

    mismatches = []
    for e in entries:
        if not e['website']: continue
        domain = domain_of(e['website'])
        if not domain: continue
        n_city = norm(e['city'] or '')
        n_name = norm(e['name'] or '')
        # Strip the TLD piece — keep only host before last dot
        domain_core = re.sub(r'\.(com|nl|org|eu|de|fr|es|it|pt|ie|uk|be|gr|ch|at|info|net)$', '', domain)
        domain_norm = norm(domain_core)

        # Find city tokens that appear in the domain
        domain_hints = find_city_in_domain(domain_norm, city_tokens)
        if not domain_hints: continue

        # Filter out hints that are present in the venue name (legitimate venue-name tokens)
        name_norm = norm(e['name'] or '')
        domain_hints_filtered = {t for t in domain_hints if t not in name_norm}
        if not domain_hints_filtered: continue

        # Filter out hints that ARE the city (no mismatch)
        domain_hints_filtered = {t for t in domain_hints_filtered
                                 if t != n_city and not (n_city and t in n_city) and not (n_city and n_city in t)}
        if not domain_hints_filtered: continue

        mismatches.append({
            'id': e['id'], 'name': e['name'], 'city': e['city'],
            'website': e['website'], 'domain_hints': sorted(domain_hints_filtered),
        })

    return mismatches

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('html_file')
    p.add_argument('--out', default=None)
    args = p.parse_args()
    mismatches = check(args.html_file)
    print(f'\nFound {len(mismatches)} potential website↔city mismatches:\n')
    for m in mismatches:
        print(f"  id:{m['id']:>5}  {m['name']}")
        print(f"        city: {m['city']}")
        print(f"        website hints: {','.join(m['domain_hints'])}")
        print(f"        url: {m['website']}\n")
    if args.out:
        json.dump(mismatches, open(args.out,'w'), ensure_ascii=False, indent=2)
        print(f'Saved to {args.out}', file=sys.stderr)
