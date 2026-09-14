"""Poll itinerary until status is terminal, then print items."""
import json
import sys
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


def get_detail(token, it_id):
    req = urllib.request.Request(
        f"{BASE}/api/itinerary/{it_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return json.load(urllib.request.urlopen(req))["data"]


def main(it_id: int):
    token = login()
    for i in range(40):
        data = get_detail(token, it_id)
        status = data.get("status")
        print(f"poll#{i} status={status} items={sum(len(d.get('items') or []) for d in data.get('dayList') or [])}")
        if status in (2, 3):
            print("city", data.get("city"), "note", (data.get("planNote") or "")[:200])
            for d in data.get("dayList") or []:
                for it in d.get("items") or []:
                    print(
                        f"  D{d.get('dayNo')} {it.get('poiName')} "
                        f"lat={it.get('latitude')} lng={it.get('longitude')} "
                        f"src={it.get('source')} ver={it.get('verificationStatus')}"
                    )
            return
        time.sleep(3)
    print("timeout waiting")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 37)
