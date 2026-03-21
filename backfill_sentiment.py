import os, json, glob
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"], connect_args={"sslmode": "require"})

with engine.connect() as conn:
    for file in glob.glob("reports/*.json"):
        r = json.load(open(file))
        raw_file  = os.path.basename(file)
        sentiment = (r.get("analysis", {}).get("overall_market_sentiment") or "neutral").lower().strip()

        conn.execute(text("""
            UPDATE reports
            SET overall_sentiment = :sentiment
            WHERE raw_file = :raw_file
        """), {"sentiment": sentiment, "raw_file": raw_file})

    conn.commit()
    print("✅ Backfill complete")
