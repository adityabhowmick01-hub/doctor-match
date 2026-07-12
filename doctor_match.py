#!/usr/bin/env python3
"""CLI: cross-reference NPI Registry providers with ClinicalTrials.gov investigators.

Given a name (and optional state), searches both public registries and prints
a single merged profile for each provider who is also found as a trial
investigator under a matching name and location. No API key required.
"""
import argparse
import difflib
import json
import re
import urllib.parse
import urllib.request

NPI_API = "https://npiregistry.cms.hhs.gov/api/?version=2.1&"
TRIALS_API = "https://clinicaltrials.gov/api/v2/studies?"
USER_AGENT = "DoctorMatch/1.0"

CREDENTIAL_RE = re.compile(
    r"\b(md|do|dr|phd|mph|rn|np|pa|facp|facs|facog|faap|jr|sr|ii|iii|iv)\b\.?",
    re.IGNORECASE,
)

US_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}


def state_abbr(state_str):
    if not state_str:
        return ""
    state_str = state_str.strip()
    if len(state_str) == 2:
        return state_str.upper()
    return US_STATE_ABBR.get(state_str.lower(), state_str.upper())


def normalize_name(name):
    name = name.replace(",", " ")
    name = CREDENTIAL_RE.sub("", name)
    name = re.sub(r"[^a-zA-Z\s\-']", " ", name)
    tokens = [t.lower() for t in name.split() if t]
    return tokens


def token_similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def compare_names(tokens_a, tokens_b, first_threshold=0.75, last_threshold=0.90):
    """Compare first token vs first token and last token vs last token separately.

    A shared surname must not by itself inflate similarity when first names
    differ (e.g. "Hang Chen" vs "Lanyi Chen" should NOT match just because
    both end in "Chen").
    """
    if not tokens_a or not tokens_b:
        return {"match": False, "exact": False}

    first_a, last_a = tokens_a[0], tokens_a[-1]
    first_b, last_b = tokens_b[0], tokens_b[-1]

    last_sim = token_similarity(last_a, last_b)
    if last_sim < last_threshold:
        return {"match": False, "exact": False}

    first_sim = token_similarity(first_a, first_b)
    initial_match = (
        (len(first_a) == 1 and first_b.startswith(first_a))
        or (len(first_b) == 1 and first_a.startswith(first_b))
    )
    if first_sim < first_threshold and not initial_match:
        return {"match": False, "exact": False}

    exact = last_sim > 0.97 and (first_sim > 0.97 or initial_match)
    return {"match": True, "exact": exact}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def search_npi(first_name, last_name, state=None, limit=20):
    qs = {"first_name": first_name, "last_name": last_name, "limit": limit}
    if state:
        qs["state"] = state
    data = fetch_json(NPI_API + urllib.parse.urlencode(qs))
    query_tokens = normalize_name(f"{first_name} {last_name}")
    providers = []
    for r in data.get("results", []):
        basic = r.get("basic", {})
        addresses = r.get("addresses", [])
        taxonomies = r.get("taxonomies", [])
        addr = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), addresses[0] if addresses else {})
        primary_tax = next((t for t in taxonomies if t.get("primary")), taxonomies[0] if taxonomies else {})
        full_name = f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip()
        name_tokens = normalize_name(full_name)

        # NPPES does not do an exact first_name match server-side (it returns
        # phonetic/partial matches too), so re-check locally against the query.
        if not compare_names(query_tokens, name_tokens, first_threshold=0.85, last_threshold=0.92)["match"]:
            continue

        providers.append({
            "npi": r.get("number"),
            "full_name": full_name,
            "credential": basic.get("credential", ""),
            "specialty": primary_tax.get("desc", ""),
            "city": addr.get("city", ""),
            "state": addr.get("state", ""),
            "name_tokens": name_tokens,
        })
    return providers


def search_trials(first_name, last_name, max_results=50):
    query_str = f"{first_name} {last_name}"
    qs = {
        "query.term": query_str,
        "pageSize": max_results,
        "format": "json",
    }
    data = fetch_json(TRIALS_API + urllib.parse.urlencode(qs))
    trials = []
    for s in data.get("studies", []):
        proto = s.get("protocolSection", {})
        id_mod = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        contacts_mod = proto.get("contactsLocationsModule", {})
        conditions_mod = proto.get("conditionsModule", {})
        design_mod = proto.get("designModule", {})

        locations = contacts_mod.get("locations", [])

        # Site-level contacts are tied to one specific city/state each - unambiguous.
        candidates = []
        for loc in locations:
            city, state = loc.get("city", ""), loc.get("state", "")
            for contact in loc.get("contacts", []):
                if contact.get("name"):
                    candidates.append({"name": contact["name"], "city": city, "state": state, "attribution": "site"})

        # Trial-level "overall officials" have no per-site attribution. With a single
        # site the pairing is unambiguous ("site"); with multiple sites, tag as
        # "official-multi" so match() can require an exact name match before trusting
        # any state/city correlation (a fuzzy name match compounded with "any of N
        # sites" is how large multi-site trials produced false positives before).
        officials = [o["name"] for o in contacts_mod.get("overallOfficials", []) if o.get("name")]
        if len(locations) == 1:
            loc = locations[0]
            for name in officials:
                candidates.append({
                    "name": name, "city": loc.get("city", ""), "state": loc.get("state", ""), "attribution": "site",
                })
        elif len(locations) > 1:
            for name in officials:
                for loc in locations:
                    candidates.append({
                        "name": name, "city": loc.get("city", ""), "state": loc.get("state", ""),
                        "attribution": "official-multi",
                    })

        if not candidates:
            continue
        trials.append({
            "nct_id": id_mod.get("nctId", ""),
            "title": id_mod.get("briefTitle", ""),
            "conditions": conditions_mod.get("conditions", []),
            "phase": ", ".join(design_mod.get("phases", [])) if design_mod.get("phases") else "",
            "status": status_mod.get("overallStatus", ""),
            "candidates": candidates,
        })
    return trials


def match(providers, trials, min_confidence="low"):
    tiers = {"low": 0, "medium": 1, "high": 2}
    threshold = tiers[min_confidence]
    profiles = []

    for provider in providers:
        matched_trials = []
        best_confidence = None

        for trial in trials:
            best_trial_confidence = None

            for candidate in trial["candidates"]:
                candidate_tokens = normalize_name(candidate["name"])
                if not candidate_tokens:
                    continue
                result = compare_names(provider["name_tokens"], candidate_tokens)
                if not result["match"]:
                    continue

                # Ambiguous trial-level officials (multi-site, no per-site attribution)
                # are only trustworthy on an exact name match - a fuzzy match paired
                # with "any of N sites" is how false positives crept in before.
                if candidate["attribution"] == "official-multi" and not result["exact"]:
                    continue

                state_match = bool(provider["state"]) and bool(candidate["state"]) and (
                    state_abbr(candidate["state"]) == state_abbr(provider["state"])
                )
                city_match = bool(candidate["city"]) and bool(provider["city"]) and (
                    candidate["city"].lower() == provider["city"].lower()
                )

                if not state_match:
                    continue

                if result["exact"] and city_match:
                    confidence = "high"
                elif result["exact"]:
                    confidence = "medium"
                else:
                    confidence = "low"

                if best_trial_confidence is None or tiers[confidence] > tiers[best_trial_confidence]:
                    best_trial_confidence = confidence

            if best_trial_confidence is None or tiers[best_trial_confidence] < threshold:
                continue

            matched_trials.append({
                "nct_id": trial["nct_id"],
                "title": trial["title"],
                "conditions": trial["conditions"],
                "phase": trial["phase"],
                "status": trial["status"],
                "confidence": best_trial_confidence,
            })
            if best_confidence is None or tiers[best_trial_confidence] > tiers[best_confidence]:
                best_confidence = best_trial_confidence

        if matched_trials:
            profiles.append({
                "name": provider["full_name"],
                "npi": provider["npi"],
                "specialty": provider["specialty"],
                "practice_city": provider["city"],
                "practice_state": provider["state"],
                "match_confidence": best_confidence,
                "trials": matched_trials,
            })

    return profiles


def print_profiles(profiles):
    if not profiles:
        print("No matches found.")
        return
    for p in profiles:
        print("=" * 70)
        print(f"{p['name']}  (NPI {p['npi']})  [{p['match_confidence'].upper()} confidence]")
        print(f"  Specialty: {p['specialty'] or 'n/a'}")
        print(f"  Practice location: {p['practice_city']}, {p['practice_state']}")
        print(f"  Trials ({len(p['trials'])}):")
        for t in p["trials"]:
            conditions = ", ".join(t["conditions"]) if t["conditions"] else "n/a"
            print(f"    - {t['nct_id']}: {t['title']}")
            print(f"        Conditions: {conditions} | Phase: {t['phase'] or 'n/a'} | Status: {t['status']}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Match doctors across NPI Registry and ClinicalTrials.gov")
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--state", help="Two-letter state code to narrow the NPI search (e.g. NY)")
    parser.add_argument("--limit", type=int, default=20, help="Max NPI providers to consider")
    parser.add_argument("--max-trials", type=int, default=50, help="Max trials to search")
    parser.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    args = parser.parse_args()

    providers = search_npi(args.first_name, args.last_name, state=args.state, limit=args.limit)
    trials = search_trials(args.first_name, args.last_name, max_results=args.max_trials)
    profiles = match(providers, trials, min_confidence=args.min_confidence)

    if args.json:
        print(json.dumps(profiles, indent=2))
    else:
        print_profiles(profiles)


if __name__ == "__main__":
    main()
