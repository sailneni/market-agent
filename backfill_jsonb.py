import os, json, glob
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"], connect_args={"sslmode": "require"})
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

with engine.connect() as conn:
    updated = 0
    for file in glob.glob(os.path.join(REPORTS_DIR, "*.json")):
        r        = json.load(open(file))
        raw_file = os.path.basename(file)

        tech_data      = json.dumps(r.get("tech_data",      {}))
        market_context = json.dumps(r.get("market_context", {}))
        price_data     = json.dumps(r.get("price_data",     {}))
        news_data      = json.dumps(r.get("news_data",      {}))

        conn.execute(text("""
            UPDATE reports
            SET tech_data      = CAST(:tech_data AS jsonb),
                market_context = CAST(:market_context AS jsonb),
                price_data     = CAST(:price_data AS jsonb),
                news_data      = CAST(:news_data AS jsonb)
            WHERE raw_file = :raw_file
            AND (tech_data IS NULL OR market_context IS NULL)
        """), {
            "tech_data":      tech_data,
            "market_context": market_context,
            "price_data":     price_data,
            "news_data":      news_data,
            "raw_file":       raw_file
        })
        updated += 1

    conn.commit()
    print(f"✅ Backfilled {updated} reports")
