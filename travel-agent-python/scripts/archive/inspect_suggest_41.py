"""Inspect latest Bali suggestions and discover image URLs."""
import json
import os
import pymysql
from collections import Counter

conn = pymysql.connect(
    # Credentials come from the same env names as app/common/config.py.
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.environ["DB_PASSWORD"],
    database=os.getenv("DB_NAME", "travel_assistant"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)
with conn.cursor() as c:
    c.execute("SELECT id FROM itinerary_main WHERE city='巴厘岛' ORDER BY id DESC LIMIT 1")
    it_id = c.fetchone()["id"]
    print("itinerary", it_id)
    c.execute("SELECT suggestions_json FROM itinerary_main WHERE id=%s", (it_id,))
    sug = json.loads(c.fetchone()["suggestions_json"] or "[]")
    print("suggestions", len(sug), Counter(s.get("category") for s in sug))
    for s in sug:
        print(f"  [{s.get('category')}] {s.get('name')} lat={s.get('latitude')} src={s.get('source')}")
    c.execute("""
      SELECT d.day_no, i.poi_name, i.item_type, i.image_url, i.latitude
      FROM itinerary_item i JOIN itinerary_day d ON i.day_id=d.id
      WHERE d.itinerary_id=%s AND i.deleted=0 ORDER BY d.day_no, i.sort_no
    """, (it_id,))
    for r in c.fetchall():
        print(f"  item D{r['day_no']} {r['poi_name'][:16]} img={r['image_url']}")
    # knowledge pool counts by category for Bali
    c.execute("SELECT category, COUNT(*) c FROM poi_knowledge WHERE city='巴厘岛' GROUP BY category")
    print("knowledge", c.fetchall())
conn.close()
