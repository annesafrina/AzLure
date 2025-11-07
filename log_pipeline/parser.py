#!/usr/bin/env python3
"""
AzLure cheap log pipeline:
- Reads Azure diagnostics from Storage containers (insights-logs-*)
- Parses JSON/NDJSON blobs
- Normalizes and stores to SQLite
- Runs simple detection rules and alerts
"""

import os
import sys
import json
import gzip
import sqlite3
import argparse
import time
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional

import yaml
import requests
from dateutil import parser as dtp
from azure.storage.blob import BlobServiceClient


# ---------------------------
# Utilities
# ---------------------------

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def redact_sas(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return uri
    # Basic redaction of common SAS params
    repl = uri
    for key in ["sig", "se", "st", "sp", "spr", "sv", "skoid", "sktid"]:
        repl = repl.replace(f"{key}=", f"{key}=REDACTED")
    return repl

def flatten(d: Dict[str, Any], prefix: str = "properties.") -> Dict[str, Any]:
    """Return only 'properties' nested fields with a prefix, merged into root dict copy."""
    out = dict(d)
    props = d.get("properties") or {}
    for k, v in props.items():
        out[f"{prefix}{k}"] = v
    return out

def guess_category(container_name: str, record: Dict[str, Any]) -> str:
    c = container_name.lower()
    if "storageread" in c:
        return "StorageRead"
    if "storagewrite" in c:
        return "StorageWrite"
    if "auditevent" in c:
        return "AuditEvent"
    if "activity" in c:
        return "Activity"
    # fallback to record-provided category if present
    return record.get("category") or "Unknown"

def normalize_event(container_name: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize across Storage / KV / Activity record shapes.
    We prefer top-level fields, then look under properties.* for common keys.
    """
    r = flatten(rec)

    def g(*keys, default=None):
        for k in keys:
            if k in r and r[k] not in (None, ""):
                return r[k]
        return default

    # time
    t = g("time", "TimeGenerated")

    # operation name
    op = g("operationName", "operationNameValue", "properties.operationName", "properties.operation")

    # uri / request target
    uri = g("requestUri", "properties.requestUri", "uri", "properties.uri")

    # caller ip
    ip = g("callerIpAddress", "properties.callerIpAddress", "callerIp", "properties.callerIp")

    # user agent
    ua = g("userAgentHeader", "properties.userAgentHeader", "userAgent", "properties.userAgent")

    # status
    status = g("statusCode", "properties.httpStatusCode", "properties.statusCode", "resultType")

    # auth
    auth = g("authenticationType", "properties.authenticationType", "properties.authType")

    # resource id
    rid = g("resourceId", "properties.resourceId")

    return {
        "time": t,
        "category": guess_category(container_name, r),
        "operation_name": op,
        "request_uri": uri,
        "request_uri_redacted": redact_sas(uri),
        "caller_ip": ip,
        "user_agent": ua,
        "status_code": str(status) if status is not None else None,
        "auth_type": auth,
        "resource_id": rid,
        "raw_json": json.dumps(rec, ensure_ascii=False),
    }

def parse_blob_bytes(b: bytes) -> Iterable[Dict[str, Any]]:
    """
    Handle Azure diagnostics formats:
    - JSON with {"records": [...]}
    - JSON array [...]
    - NDJSON (one JSON per line)
    """
    body = b.decode("utf-8", errors="replace").strip()
    if not body:
        return []

    # Try records wrapper
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and "records" in obj and isinstance(obj["records"], list):
            for rec in obj["records"]:
                if isinstance(rec, dict):
                    yield rec
            return
        if isinstance(obj, list):
            for rec in obj:
                if isinstance(rec, dict):
                    yield rec
            return
        if isinstance(obj, dict):
            yield obj
            return
    except json.JSONDecodeError:
        pass

    # NDJSON fallback
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                yield rec
        except json.JSONDecodeError:
            continue


# ---------------------------
# Storage client
# ---------------------------

class LogBlobReader:
    def __init__(self, connection_string: str, containers: List[str], since_minutes: int = 1440):
        self.client = BlobServiceClient.from_connection_string(connection_string)
        self.containers = containers
        self.since_minutes = since_minutes

    def iter_blobs(self) -> Iterable[Dict[str, Any]]:
        """
        Yield dicts: {"container": name, "blob_name": name, "etag": etag}
        Only recent blobs (since_minutes) to reduce cost/time.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.since_minutes)

        for c in self.containers:
            container = self.client.get_container_client(c)
            try:
                for b in container.list_blobs():
                    # Many diag blobs follow /y=/m=/d=/h= paths; we filter by last modified
                    if getattr(b, "last_modified", None) and b.last_modified.tzinfo:
                        if b.last_modified < cutoff:
                            continue
                    yield {"container": c, "blob_name": b.name, "etag": getattr(b, "etag", None)}
            except Exception as e:
                print(f"[warn] cannot list container {c}: {e}")

    def download_blob(self, container: str, blob_name: str) -> bytes:
        bc = self.client.get_container_client(container).get_blob_client(blob_name)
        data = bc.download_blob().readall()
        # Some logs may be gz; try to detect
        if blob_name.endswith(".gz"):
            try:
                return gzip.decompress(data)
            except Exception:
                return data
        return data


# ---------------------------
# DB & state
# ---------------------------

class EventStore:
    def __init__(self, db_path: str):
        ensure_dir(Path(db_path))
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              time TEXT,
              category TEXT,
              operation_name TEXT,
              request_uri TEXT,
              request_uri_redacted TEXT,
              caller_ip TEXT,
              user_agent TEXT,
              status_code TEXT,
              auth_type TEXT,
              resource_id TEXT,
              raw_json TEXT,
              container TEXT,
              blob_name TEXT,
              inserted_at TEXT
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_blobs (
              container TEXT,
              blob_name TEXT,
              etag TEXT,
              processed_at TEXT,
              PRIMARY KEY (container, blob_name)
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              rule_name TEXT,
              event_id INTEGER,
              created_at TEXT
            );
        """)
        self.conn.commit()

    def blob_processed(self, container: str, blob_name: str, etag: Optional[str]) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM processed_blobs WHERE container=? AND blob_name=?",
            (container, blob_name))
        return cur.fetchone() is not None

    def mark_blob(self, container: str, blob_name: str, etag: Optional[str]):
        self.conn.execute(
            "INSERT OR REPLACE INTO processed_blobs(container, blob_name, etag, processed_at) VALUES(?,?,?,?)",
            (container, blob_name, etag, now_iso()))
        self.conn.commit()

    def add_event(self, container: str, blob_name: str, ev: Dict[str, Any]) -> int:
        cur = self.conn.execute("""
            INSERT INTO events(time, category, operation_name, request_uri, request_uri_redacted,
              caller_ip, user_agent, status_code, auth_type, resource_id, raw_json, container, blob_name, inserted_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ev.get("time"), ev.get("category"), ev.get("operation_name"), ev.get("request_uri"), ev.get("request_uri_redacted"),
            ev.get("caller_ip"), ev.get("user_agent"), ev.get("status_code"), ev.get("auth_type"), ev.get("resource_id"),
            ev.get("raw_json"), container, blob_name, now_iso()
        ))
        self.conn.commit()
        return int(cur.lastrowid)

    def add_alert(self, rule_name: str, event_id: int):
        self.conn.execute("INSERT INTO alerts(rule_name, event_id, created_at) VALUES(?,?,?)",
                          (rule_name, event_id, now_iso()))
        self.conn.commit()


# ---------------------------
# Rules & alerts
# ---------------------------

class AlertDispatcher:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def send(self, rule_name: str, ev: Dict[str, Any]):
        if self.cfg.get("stdout", True):
            print(f"[ALERT] {rule_name} | {ev.get('time')} | {ev.get('category')} | {ev.get('request_uri_redacted')} | IP={ev.get('caller_ip')}")
        w = self.cfg.get("webhook", {})
        if w.get("enabled") and w.get("url"):
            try:
                requests.post(w["url"], json={
                    "text": f"AzLure alert: {rule_name}",
                    "rule": rule_name,
                    "event": {
                        "time": ev.get("time"),
                        "category": ev.get("category"),
                        "operation_name": ev.get("operation_name"),
                        "request_uri": ev.get("request_uri_redacted"),
                        "caller_ip": ev.get("caller_ip"),
                        "status_code": ev.get("status_code"),
                        "auth_type": ev.get("auth_type"),
                    }
                }, timeout=5)
            except Exception as e:
                print(f"[warn] webhook failed: {e}")


def event_matches(rule: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    when = rule.get("when", {})
    # category
    cat = when.get("category")
    if cat and (ev.get("category") != cat):
        return False
    # contains (string contains conditions)
    contains = when.get("contains")
    if contains:
        field = contains.get("field")
        if not field:
            return False
        val = ev.get(field) or ""
        # ensure lower-case match for safety
        val_l = str(val).lower()
        # all-of
        if "all" in contains:
            if not all(s.lower() in val_l for s in contains["all"]):
                return False
        # any-of
        if "any" in contains:
            if not any(s.lower() in val_l for s in contains["any"]):
                return False
    return True


# ---------------------------
# Main runner
# ---------------------------

def run_once(cfg: Dict[str, Any]) -> None:
    # connection string
    conn_str = (cfg.get("storage", {}) or {}).get("connection_string") or os.getenv("AZURE_STORAGE_CONNECTION_STRING_LOGS")
    if not conn_str:
        print("ERROR: no storage connection string provided. Set AZURE_STORAGE_CONNECTION_STRING_LOGS or config.storage.connection_string")
        sys.exit(2)

    containers = (cfg.get("storage", {}) or {}).get("containers") or []
    since = int((cfg.get("polling", {}) or {}).get("since_minutes", 1440))
    db_path = (cfg.get("database", {}) or {}).get("path") or "log_pipeline/data/azlure.db"

    reader = LogBlobReader(conn_str, containers, since_minutes=since)
    store = EventStore(db_path)
    dispatcher = AlertDispatcher(cfg.get("alerts", {}))
    rules = cfg.get("rules", [])

    # iterate blobs
    for meta in reader.iter_blobs():
        c = meta["container"]
        name = meta["blob_name"]
        etag = meta.get("etag")
        if store.blob_processed(c, name, etag):
            continue

        try:
            raw = reader.download_blob(c, name)
        except Exception as e:
            print(f"[warn] download failed {c}/{name}: {e}")
            continue

        try:
            for rec in parse_blob_bytes(raw):
                ev = normalize_event(c, rec)
                ev_id = store.add_event(c, name, ev)
                # rules
                for rule in rules:
                    if event_matches(rule, ev):
                        store.add_alert(rule["name"], ev_id)
                        dispatcher.send(rule["name"], ev)
        except Exception as e:
            print(f"[warn] parse failed {c}/{name}: {e}")

        # mark processed
        store.mark_blob(c, name, etag)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", "-c", default="log_pipeline/config.yml")
    ap.add_argument("--once", action="store_true", help="Process once and exit")
    ap.add_argument("--loop", action="store_true", help="Run forever")
    ap.add_argument("--interval", type=int, default=None, help="Polling interval seconds (overrides config)")
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    interval = args.interval or int((cfg.get("polling", {}) or {}).get("interval_seconds", 60))

    if args.once and args.loop:
        print("Choose either --once or --loop")
        sys.exit(2)

    if args.once:
        run_once(cfg)
        return

    # loop
    while True:
        run_once(cfg)
        time.sleep(interval)

if __name__ == "__main__":
    main()
