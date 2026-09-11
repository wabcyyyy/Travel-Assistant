"""Generate itinerary for a city with no local POI (open mode / LLM-only)."""
import json
import time
import urllib.request

BASE = "http://localhost:8080"


def login():
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "123456"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))["data"]["token"]


def generate(token, city, days=1):
    payload = {
        "city": city,
        "days": days,
        "persons": 2,
        "stayNights": max(days - 1, 0),
        "budget": 8000,
        "preferences": ["自然风光"],
    }
    req = urllib.request.Request(
        f"{BASE}/api/itinerary/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    t0 = time.time()
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=180))
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            body = e.read().decode("utf-8", "replace")
        print(f"[{city}] ERR after {time.time()-t0:.1f}s: {e} {body[:300]}")
        return
    data = resp.get("data") or {}
    print(f"[{city}] {time.time()-t0:.1f}s id={data.get('id')} status={data.get('status')} city={data.get('city')}")
    print("  note:", (data.get("planNote") or "")[:160])
    for d in data.get("dayList") or []:
        for it in d.get("items") or []:
            print(
                f"  D{d.get('dayNo')} {it.get('poiName')} "
                f"lat={it.get('latitude')} lng={it.get('longitude')} src={it.get('source')}"
            )


if __name__ == "__main__":
    token = login()
    generate(token, "马尔代夫", days=1)
