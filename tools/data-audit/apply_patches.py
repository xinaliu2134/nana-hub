#!/usr/bin/env python3
"""
Apply a patch plan produced by audit.py to the HTML file.

Only updates lat/lon for entries where:
  - new coords are present
  - distance from old coords is > min_distance (default 100m)
  - distance is < max_distance (default 30km, guards against bad fuzzy matches)

Usage:
    python3 tools/data-audit/apply_patches.py <html_file> <patch_plan.json> \\
        [--min-distance 100] [--max-distance 30000] [--dry-run]
"""
import json, re, sys, argparse

def apply(html_path, plan_path, min_dist, max_dist, dry_run):
    plan = json.load(open(plan_path))
    html = open(html_path).read()
    applied = 0
    skipped_too_close = 0
    skipped_too_far = 0
    not_found = 0
    for e in plan:
        if e['new_lat'] is None:
            not_found += 1
            continue
        d = e.get('distance_m', 0)
        if d < min_dist:
            skipped_too_close += 1
            continue
        if d > max_dist:
            skipped_too_far += 1
            print(f"  REJECT id:{e['id']} {e['name']} — dist {d:.0f}m > max", file=sys.stderr)
            continue
        pat = re.compile(rf"(\{{\s*type:'node',id:{e['id']},lat:)([\d.]+)(,lon:)([\d.]+)")
        new_html, n = pat.subn(rf"\g<1>{e['new_lat']:.6f}\g<3>{e['new_lon']:.6f}", html)
        if n == 1:
            html = new_html
            applied += 1
    if not dry_run:
        open(html_path, 'w').write(html)
    print(f'Applied:             {applied}', file=sys.stderr)
    print(f'Skipped <{min_dist}m: {skipped_too_close}', file=sys.stderr)
    print(f'Rejected >{max_dist}m: {skipped_too_far}', file=sys.stderr)
    print(f'Not found:           {not_found}', file=sys.stderr)
    if dry_run:
        print('\n(dry-run — no file modified)', file=sys.stderr)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('html_file')
    p.add_argument('plan_file')
    p.add_argument('--min-distance', type=int, default=100,
                   help='Skip updates where venue is already within N meters')
    p.add_argument('--max-distance', type=int, default=30000,
                   help='Reject updates that would move venue more than N meters')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    apply(args.html_file, args.plan_file, args.min_distance, args.max_distance, args.dry_run)
