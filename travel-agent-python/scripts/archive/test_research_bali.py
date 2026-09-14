"""Quick check research context for Bali hotels."""
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from app.agent.research import run_research_context
from app.schemas.trip import GenerateRequest

req = GenerateRequest(city="巴厘岛", days=3, persons=2, preferences=["自然风光", "美食"])
ctx = run_research_context(req)
print("candidates", len(ctx.get("candidates") or []))
print("foods", len(ctx.get("foods") or []))
print("hotels", len(ctx.get("hotels") or []))
print("hotel names", [h.get("name") for h in (ctx.get("hotels") or [])][:10])
print("report", (ctx.get("research_report") or {}))
