import json
import pymysql
from collections import Counter

conn = pymysql.connect(
    host="localhost", user="root", password="259243",
    database="travel_assistant", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)

with conn.cursor() as c:
    c.execute(
        "SELECT suggestions_json, budget, persons, days, hotel_tier FROM itinerary_main WHERE id=38"
    )
    row = c.fetchone()
    sug = json.loads(row["suggestions_json"] or "[]")
    print("budget", row["budget"], "persons", row["persons"], "days", row["days"], "hotel", row["hotel_tier"])
    print("suggestions", len(sug))
    cats = Counter((s.get("category") or "?") for s in sug)
    print("by category", dict(cats))
    for s in sug:
        print(
            f"  [{s.get('category')}] {s.get('name')} cost={s.get('estimatedCost')} "
            f"lat={s.get('latitude')} used={s.get('used')} intro={str(s.get('intro') or '')[:40]}"
        )

    # items cost analysis
    c.execute(
        """
        SELECT d.day_no, i.item_type, i.poi_name, i.cost, i.latitude, i.image_url, i.open_time
        FROM itinerary_item i
        JOIN itinerary_day d ON i.day_id=d.id
        WHERE d.itinerary_id=38 AND i.deleted=0
        ORDER BY d.day_no, i.sort_no
        """
    )
    items = c.fetchall()
    print("\n=== items ===")
    total = 0.0
    for it in items:
        print(
            f"  D{it['day_no']} {it['item_type']:10} {it['poi_name'][:20]:20} "
            f"cost={it['cost']} img={it['image_url']} open={it['open_time']}"
        )
        if it["cost"]:
            total += float(it["cost"])
    print("sum of item.cost (raw, no persons):", total)

    # budget_detail
    c.execute("SHOW TABLES LIKE 'budget%'")
    print("tables", c.fetchall())
    try:
        c.execute("SELECT * FROM budget_detail WHERE itinerary_id=38 LIMIT 20")
        print("budget_detail", c.fetchall())
    except Exception as e:
        print("budget_detail err", e)

conn.close()
