"""Generate Bali trip and print density / hotel / budget / suggestions summary."""
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


def generate(token):
    payload = {
        "city": "巴厘岛",
        "days": 3,
        "persons": 2,
        "stayNights": 2,
        "budget": 20000,
        "preferences": ["自然风光", "美食", "网红出片"],
        "hotelTier": "奢华型",
    }
    req = urllib.request.Request(
        f"{BASE}/api/itinerary/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]["id"]


def detail(token, it_id):
    req = urllib.request.Request(
        f"{BASE}/api/itinerary/{it_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return json.load(urllib.request.urlopen(req))["data"]


def main():
    token = login()
    it_id = generate(token)
    print("created id", it_id)
    for i in range(50):
        data = detail(token, it_id)
        if data.get("status") in (2, 3):
            break
        time.sleep(3)
    print("status", data.get("status"), "city", data.get("city"), "days", data.get("days"))
    for d in data.get("dayList") or []:
        items = d.get("items") or []
        types = [it.get("itemType") for it in items]
        print(f"D{d.get('dayNo')} n={len(items)} types={types}")
        for it in items:
            print(f"   {it.get('itemType')} {it.get('poiName')} {it.get('startTime')}-{it.get('endTime')} cost={it.get('cost')} img={bool(it.get('image') or it.get('imageUrl'))}")
    from collections import Counter
    sug = data.get("suggestions") or []
    print("suggestions", len(sug), Counter(s.get("category") for s in sug))
    print("budgetList", data.get("budgetList"))
    print("totalAmount", data.get("totalAmount"))


if __name__ == "__main__":
    main()
