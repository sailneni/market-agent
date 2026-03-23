"# market-agent" 

# How to Run
One-time setup (only needed once):


python -m venv venv

venv\Scripts\activate

pip install -r requirements.txt

Terminal 1 — Collect data (runs continuously):

venv\Scripts\activate

python watcher.py --mode feeds

This checks RSS feeds + NewsAPI every 30 minutes, runs Claude analysis on each article, saves reports to reports/.

To also monitor your 18 YouTube channels:


python watcher.py --mode both

Terminal 2 — Dashboard (open anytime):


venv\Scripts\activate

streamlit run app/ui/dashboard.py

Opens at http://localhost:8501. Works immediately — you already have 11 reports in reports/ from before.

Terminal 3 — REST API (optional):

venv\Scripts\activate

uvicorn app.api.main:app --reload --port 8000

Then visit http://localhost:8000/docs for interactive API docs, or:

http://localhost:8000/signals — top buy/sell signals

http://localhost:8000/reports — recent analyses

http://localhost:8000/tickers/NVDA — deep dive on any ticker


Quickest start — just open the dashboard with existing data:

venv\Scripts\activate

streamlit run app/ui/dashboard.py
