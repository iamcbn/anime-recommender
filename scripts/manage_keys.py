#!/usr/bin/env python
"""
scripts/manage_keys.py

Break-Glass Administrative API Key Management CLI (Sprint 2).
Provides direct database & Redis management for operators:
- create-admin: Provisions high-privilege admin keys with custom expiry.
- list: Displays key metadata and statuses without leaking secrets.
- revoke: Emergency revocation with immediate Redis tombstone publishing.

Usage:
    python scripts/manage_keys.py create-admin --name "hourly-eval" --expires-days 30
    python scripts/manage_keys.py list --include-revoked
    python scripts/manage_keys.py revoke --id <UUID>
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

# Ensure project root is in sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2 import extras
from backend.rag_pipeline.config import config as get_db_config
from backend.auth.keys import generate_api_key, revoke_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("manage_keys")


def get_db_connection():
    cfg = get_db_config()
    return psycopg2.connect(**cfg)


def handle_create_admin(args):
    """Provisions a new administrative API key."""
    name = args.name.strip()
    expires_days = args.expires_days
    rate_limit = args.rate_limit
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    owner_id = args.owner if args.owner else None

    if expires_days > 90:
        print("\n[!] WARNING: Administrative keys with lifetime > 90 days are discouraged.")

    conn = get_db_connection()
    try:
        raw_key, record = generate_api_key(
            name=name,
            owner_id=owner_id,
            role="admin",
            scopes=scopes,
            rate_limit_per_min=rate_limit,
            expires_in_days=expires_days,
            actor="cli:manage_keys",
            client_ip="127.0.0.1",
            conn=conn
        )

        print("\n" + "=" * 80)
        print(f"[+] Successfully provisioned admin API key: '{name}'")
        print("-" * 80)
        print(f"Key ID:         {record['id']}")
        print(f"Key Prefix:     {record['prefix']}")
        print(f"Role:           admin")
        print(f"Scopes:         {scopes}")
        print(f"Rate Limit:     {rate_limit} req/min")
        exp_str = record['expires_at'].strftime("%Y-%m-%d %H:%M:%S UTC") if record['expires_at'] else "Never"
        print(f"Expires At:     {exp_str} (in {expires_days} days)")
        print("-" * 80)
        print("CRITICAL: Copy the secret key below NOW. It CANNOT be retrieved later.\n")
        print(f"Secret Key:     {raw_key}")
        print("=" * 80 + "\n")
    finally:
        conn.close()


def handle_list(args):
    """Lists registered API keys with operational status."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            query = """
                SELECT id, owner_id, name, key_prefix, role, scopes,
                       rate_limit_per_min, created_at, expires_at, revoked_at, last_used_at
                FROM app_auth.api_keys
                WHERE 1=1
            """
            params = []
            if args.owner:
                query += " AND owner_id = %s"
                params.append(args.owner)
            if args.role:
                query += " AND role = %s"
                params.append(args.role)
            if not args.include_revoked:
                query += " AND revoked_at IS NULL"

            query += " ORDER BY created_at DESC;"
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            now = datetime.now(timezone.utc)
            results = []
            for r in rows:
                status = "ACTIVE"
                if r["revoked_at"] is not None:
                    status = "REVOKED"
                elif r["expires_at"] is not None:
                    exp = r["expires_at"] if r["expires_at"].tzinfo else r["expires_at"].replace(tzinfo=timezone.utc)
                    if exp <= now:
                        status = "EXPIRED"

                results.append({
                    "id": str(r["id"]),
                    "name": r["name"],
                    "prefix": r["key_prefix"],
                    "role": r["role"],
                    "rpm": r["rate_limit_per_min"],
                    "status": status,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                    "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                })

            if args.json:
                print(json.dumps(results, indent=2))
                return

            print("\n" + "=" * 110)
            print(f"{'Key ID':<38} {'Name':<18} {'Role':<8} {'Prefix':<18} {'RPM':<6} {'Status':<10}")
            print("-" * 110)
            for item in results:
                print(f"{item['id']:<38} {item['name'][:16]:<18} {item['role']:<8} {item['prefix']:<18} {item['rpm']:<6} {item['status']:<10}")
            print("=" * 110)
            print(f"Total keys listed: {len(results)}\n")
    finally:
        conn.close()


def handle_revoke(args):
    """Emergency soft-revocation of an API key."""
    key_id = args.id.strip()
    reason = args.reason or "Break-glass CLI emergency revocation"

    conn = get_db_connection()
    try:
        # Check existence
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("SELECT id, name, key_prefix, revoked_at FROM app_auth.api_keys WHERE id = %s;", (key_id,))
            row = cur.fetchone()
            if not row:
                print(f"\n[!] Error: Key with ID '{key_id}' not found.")
                sys.exit(1)

            if row["revoked_at"] is not None:
                print(f"\n[i] Key '{row['name']}' ({row['key_prefix']}) is already revoked.")
                return

            if not args.force:
                confirm = input(f"Confirm revocation of key '{row['name']}' ({row['key_prefix']})? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return

        success = revoke_api_key(
            key_id=key_id,
            actor="cli:manage_keys",
            client_ip="127.0.0.1",
            conn=conn
        )
        if success:
            print(f"\n[+] Successfully revoked key '{key_id}'. Evicted from in-memory cache and published tombstone.\n")
        else:
            print(f"\n[!] Failed to revoke key '{key_id}'.\n")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Break-Glass Administrative API Key Management CLI (Sprint 2)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-admin
    p_create = subparsers.add_parser("create-admin", help="Provision an admin API key")
    p_create.add_argument("--name", required=True, help="Unique name or purpose for the key")
    p_create.add_argument("--expires-days", type=int, default=30, help="Lifespan in days (default: 30)")
    p_create.add_argument("--rate-limit", type=int, default=120, help="Requests per minute (default: 120)")
    p_create.add_argument("--scopes", default="admin,recommend,chat", help="Comma-separated scopes")
    p_create.add_argument("--owner", help="Optional owner UUID")

    # list
    p_list = subparsers.add_parser("list", help="List registered API keys")
    p_list.add_argument("--owner", help="Filter by owner UUID")
    p_list.add_argument("--role", choices=["user", "admin"], help="Filter by role")
    p_list.add_argument("--include-revoked", action="store_true", help="Include revoked keys")
    p_list.add_argument("--json", action="store_true", help="Output JSON format")

    # revoke
    p_revoke = subparsers.add_parser("revoke", help="Soft-revoke an active API key")
    p_revoke.add_argument("--id", required=True, help="UUID of the key to revoke")
    p_revoke.add_argument("--reason", default="Manual CLI emergency revocation", help="Revocation reason")
    p_revoke.add_argument("-f", "--force", action="store_true", help="Bypass confirmation prompt")

    args = parser.parse_args()

    if args.command == "create-admin":
        handle_create_admin(args)
    elif args.command == "list":
        handle_list(args)
    elif args.command == "revoke":
        handle_revoke(args)


if __name__ == "__main__":
    main()
