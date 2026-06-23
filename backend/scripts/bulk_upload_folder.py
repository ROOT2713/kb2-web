#!/usr/bin/env python3
"""Bulk upload a folder of documents to kb2-web with automatic:
  - Version chain (same standard -> auto supersede older)
  - Quality gate (G1/G2/G3 initialization)
  - Concept generation + KG + summary backfill
  - State file (.bulk_upload_state.json) to skip already-uploaded files on rerun

Usage:
  # Dry-run (scan only, no upload)
  python bulk_upload_folder.py /path/to/folder --bank=standards --dry-run

  # Upload all files
  python bulk_upload_folder.py /path/to/folder --bank=standards

  # Upload with title prefix and category
  python bulk_upload_folder.py /path/to/folder --bank=standards --category=GB --title-prefix=2024

  # Resume after interruption (skips files in state)
  python bulk_upload_folder.py /path/to/folder --bank=standards --resume

  # Force re-upload (ignore state)
  python bulk_upload_folder.py /path/to/folder --bank=standards --force

Environment:
  KB2_URL          Default: http://127.0.0.1:3027
  ADMIN_USERNAME   Default: read from backend/.env
  ADMIN_PASSWORD   Default: read from backend/.env

Banks (kb2-web 5 banks):
  standards        规范标准 (GB/T, JJF, GA/T, T/EGAG etc.)
  checklist        Excel 检查表
  project_docs     项目资料
  industry_docs    行业文档
  general          综合文件 (default)

Supported file types: .pdf .docx .doc .xlsx .xls .txt .md (其他类型会被服务端拒绝)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import hashlib
import pathlib
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)


KB2_URL = os.environ.get("KB2_URL", "http://127.0.0.1:3027")
ENV_PATH = Path("/home/ubuntu/kb2-web/backend/.env")
STATE_FILE = ".bulk_upload_state.json"

SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}


def load_env_credentials() -> tuple[str, str]:
    """Read ADMIN_USERNAME/PASSWORD from .env or environment."""
    user = os.environ.get("ADMIN_USERNAME")
    pwd = os.environ.get("ADMIN_PASSWORD")
    if user and pwd:
        return user, pwd
    if not ENV_PATH.exists():
        print(f"ERROR: {ENV_PATH} not found and ADMIN_USERNAME/PASSWORD not in env", file=sys.stderr)
        sys.exit(1)
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    user = user or env.get("ADMIN_USERNAME", "")
    pwd = pwd or env.get("ADMIN_PASSWORD", "")
    if not user or not pwd:
        print("ERROR: ADMIN_USERNAME/PASSWORD not found in .env", file=sys.stderr)
        sys.exit(1)
    return user, pwd


def login(user: str, pwd: str) -> str:
    r = requests.post(
        f"{KB2_URL}/api/auth/login",
        json={"username": user, "password": pwd},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_state(folder: Path) -> dict:
    state_path = folder / STATE_FILE
    if not state_path.exists():
        return {"uploaded": {}}
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return {"uploaded": {}}


def save_state(folder: Path, state: dict) -> None:
    (folder / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2))


def scan_folder(folder: Path, recursive: bool = True) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files: list[Path] = []
    for p in folder.glob(pattern):
        if not p.is_file():
            continue
        if p.name.startswith("."):  # skip hidden + state file
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        files.append(p)
    return sorted(files)


def upload_one(token: str, path: Path, bank: str, category: str, title_prefix: str) -> dict:
    """Upload single file. Returns server response dict."""
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        data = {
            "title": (f"{title_prefix} {path.stem}".strip() if title_prefix else ""),
            "category": category,
            "bank": bank,
            "source": "bulk_folder_upload",
            "confirm_quality": "false",  # let quality gate decide
        }
        r = requests.post(
            f"{KB2_URL}/api/upload",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=300,
        )
    try:
        return {"status": r.status_code, "body": r.json()}
    except Exception:
        return {"status": r.status_code, "body": {"detail": r.text[:500]}}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk upload a folder to kb2-web")
    ap.add_argument("folder", type=Path, help="Folder containing documents")
    ap.add_argument("--bank", default="general",
                    choices=["standards", "checklist", "project_docs", "industry_docs", "general"],
                    help="Target bank (default: general)")
    ap.add_argument("--category", default="", help="Category label")
    ap.add_argument("--title-prefix", default="", help="Prepend to each doc title")
    ap.add_argument("--no-recursive", action="store_true", help="Only scan top-level (default: recursive)")
    ap.add_argument("--dry-run", action="store_true", help="Scan only, no upload")
    ap.add_argument("--resume", action="store_true", help="Skip files already in state (default)")
    ap.add_argument("--force", action="store_true", help="Force re-upload ignoring state")
    ap.add_argument("--limit", type=int, default=0, help="Only upload first N files (0=unlimited)")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds between uploads (default 1.0)")
    args = ap.parse_args()

    folder = args.folder.resolve()
    if not folder.is_dir():
        print(f"ERROR: {folder} is not a directory", file=sys.stderr)
        return 1

    # Scan
    files = scan_folder(folder, recursive=not args.no_recursive)
    print(f"[scan] Found {len(files)} supported files in {folder}")
    by_ext: dict[str, int] = {}
    for f in files:
        by_ext[f.suffix.lower()] = by_ext.get(f.suffix.lower(), 0) + 1
    for ext, n in sorted(by_ext.items(), key=lambda x: -x[1]):
        print(f"  {ext}: {n}")

    if args.dry_run:
        print("\n[dry-run] Sample files:")
        for f in files[:10]:
            print(f"  {f.relative_to(folder)}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")
        return 0

    # State (resume)
    state = load_state(folder)
    if not args.force and not args.resume:
        # default = resume
        args.resume = True

    # Login
    user, pwd = load_env_credentials()
    token = login(user, pwd)
    print(f"[auth] JWT acquired for {user}")

    # Health check
    h = requests.get(f"{KB2_URL}/health", timeout=10)
    if h.status_code != 200:
        print(f"ERROR: kb2-web health check failed: {h.status_code}", file=sys.stderr)
        return 1

    # Upload loop
    success = 0
    skipped = 0
    failed = 0
    failures: list[dict] = []
    started = time.time()
    target = files[: args.limit] if args.limit > 0 else files

    for i, f in enumerate(target, 1):
        rel = str(f.relative_to(folder))
        sha = file_sha1(f)

        if args.resume and sha in state["uploaded"]:
            old = state["uploaded"][sha]
            print(f"[{i}/{len(target)}] SKIP {rel} (doc_id={old.get('doc_id','?')[:8]} from {old.get('uploaded_at','?')})")
            skipped += 1
            continue

        elapsed = time.time() - started
        rate = (success + failed) / max(elapsed, 1)
        eta = (len(target) - i) / max(rate, 0.01)
        print(f"[{i}/{len(target)}] UPLOAD {rel} ({f.stat().st_size // 1024}KB) | "
              f"rate={rate:.1f}/s ETA={eta/60:.1f}min", end=" ... ", flush=True)

        try:
            res = upload_one(token, f, args.bank, args.category, args.title_prefix)
            body = res["body"]
            if res["status"] == 200 and body.get("ok"):
                doc_id = body.get("doc_id") or "?"
                title = (body.get("title") or "?")
                if isinstance(title, str):
                    title = title[:50]
                quality = body.get("quality") or {}
                cov = quality.get("coverage_pct", "?") if isinstance(quality, dict) else "?"
                searchable = body.get("searchable", "?")
                print(f"OK doc_id={str(doc_id)[:8]} cov={cov}% search={searchable} | {title}")
                state["uploaded"][sha] = {
                    "doc_id": doc_id,
                    "title": title,
                    "rel_path": rel,
                    "bank": args.bank,
                    "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                success += 1
            else:
                raw_detail = body.get("detail", "")
                if isinstance(raw_detail, dict):
                    code = raw_detail.get("code", "")
                    issues = raw_detail.get("issues", [])
                    detail = f"{code}: {'; '.join(str(i) for i in issues)}"[:300]
                elif isinstance(raw_detail, list):
                    detail = "; ".join(str(i) for i in raw_detail)[:300]
                else:
                    detail = str(raw_detail)[:300]
                print(f"FAIL status={res['status']} | {detail}")
                failures.append({"file": rel, "status": res["status"], "detail": detail})
                failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failures.append({"file": rel, "status": "exception", "detail": str(e)[:200]})
            failed += 1

        # Save state every 5 files (crash safety)
        if i % 5 == 0:
            save_state(folder, state)

        # JWT refresh every 50 files (token may expire)
        if i % 50 == 0:
            try:
                token = login(user, pwd)
                print(f"[auth] JWT refreshed at {i}/{len(target)}")
            except Exception as e:
                print(f"[auth] refresh failed: {e}", file=sys.stderr)

        time.sleep(args.sleep)

    save_state(folder, state)

    # Summary
    print("\n" + "=" * 60)
    print(f"Done in {(time.time() - started)/60:.1f}min")
    print(f"  Success: {success}")
    print(f"  Skipped (already uploaded): {skipped}")
    print(f"  Failed:  {failed}")
    if failures:
        print("\nFailures:")
        for fail in failures[:20]:
            print(f"  - {fail['file']}: {fail['detail']}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more (see logs)")
    print(f"\nState saved to: {folder / STATE_FILE}")
    print("Rerun the same command to resume / catch new files.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
