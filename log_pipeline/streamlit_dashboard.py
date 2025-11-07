import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

DB_PATH = Path("log_pipeline/data/azlure.db")

st.title("AzLure — Cheap Log Analysis Dashboard")

if not DB_PATH.exists():
    st.warning(f"DB not found at {DB_PATH}. Run parser first.")
    st.stop()

conn = sqlite3.connect(DB_PATH)

st.subheader("Recent events")
df = pd.read_sql_query("""
  SELECT time, category, operation_name, request_uri_redacted as request_uri, caller_ip, status_code, auth_type
  FROM events
  ORDER BY id DESC LIMIT 200
""", conn)
st.dataframe(df, use_container_width=True)

st.subheader("Top caller IPs (last 7 days)")
df_ips = pd.read_sql_query("""
  SELECT caller_ip, COUNT(*) as cnt
  FROM events
  WHERE time >= datetime('now','-7 day')
  GROUP BY caller_ip
  ORDER BY cnt DESC LIMIT 20
""", conn)
st.bar_chart(df_ips.set_index("caller_ip"))

st.subheader("Top URIs (last 7 days)")
df_uri = pd.read_sql_query("""
  SELECT request_uri, COUNT(*) as cnt
  FROM events
  WHERE time >= datetime('now','-7 day')
  GROUP BY request_uri
  ORDER BY cnt DESC LIMIT 20
""", conn)
st.dataframe(df_uri, use_container_width=True)

st.subheader("Alerts")
df_alerts = pd.read_sql_query("""
  SELECT a.created_at, a.rule_name, e.category, e.request_uri_redacted as request_uri, e.caller_ip
  FROM alerts a
  JOIN events e ON e.id = a.event_id
  ORDER BY a.id DESC LIMIT 100
""", conn)
st.dataframe(df_alerts, use_container_width=True)
