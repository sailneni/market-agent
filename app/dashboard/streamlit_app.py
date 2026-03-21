import streamlit as st
import requests

st.set_page_config(page_title="Market Intelligence Agent", layout="wide")
st.title("📊 Market Intelligence Agent")

st.sidebar.header("Analyze a Video")
video_id = st.sidebar.text_input("YouTube Video ID")
if st.sidebar.button("Analyze"):
    resp = requests.post(f"http://localhost:8000/analyze/video?video_id={video_id}")
    st.sidebar.success(f"Queued: {resp.json()}")

st.header("Signal Dashboard")
ticker = st.text_input("Enter Ticker (e.g. NVDA)")
if ticker:
    col1, col2, col3 = st.columns(3)
    col1.metric("YouTube Signal", "Bullish", "+2 videos")
    col2.metric("Bloomberg News", "Neutral", "0 change")
    col3.metric("Price Action", "RSI 72", "Overbought")

    st.subheader("Investment Tactic")
    st.json({
        "bull_case": "Strong earnings + AI capex momentum",
        "bear_case": "Valuation stretched, macro risks",
        "tactic": "Hold",
        "stop_loss": "$105",
        "conviction": "Medium"
    })
