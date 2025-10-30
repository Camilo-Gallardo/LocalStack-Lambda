#!/usr/bin/env python3
import argparse
import logging
import os
import time
from logging.handlers import RotatingFileHandler

import boto3


def parse_args():
    p = argparse.ArgumentParser(description="Tail CloudWatch Logs in LocalStack with auto-exit + file rotation.")
    p.add_argument("--log-group", default="/aws/lambda/hello_world", help="Log group name")
    p.add_argument("--since-seconds", type=int, default=60, help="Look back window in seconds")
    p.add_argument("--follow", action="store_true", help="Follow new logs (like tail -f)")
    p.add_argument(
        "--idle-exit",
        type=int,
        default=10,
        help="If following, exit after N seconds without new events",
    )
    p.add_argument(
        "--max-seconds",
        type=int,
        default=0,
        help="If following, hard stop after N seconds (0 = unlimited)",
    )
    p.add_argument("--output-file", default="logs/hello_world.log", help="Path to output log file")
    p.add_argument(
        "--max-bytes",
        type=int,
        default=2_000_000,
        help="Rotate when file exceeds this size (bytes)",
    )
    p.add_argument("--backup-count", type=int, default=5, help="How many rotated files to keep")
    return p.parse_args()


def ensure_logger(path, max_bytes, backup_count):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger = logging.getLogger("tail")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # Console
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(sh)

    # Rotating file
    fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    return logger


def client():
    return boto3.client(
        "logs",
        endpoint_url=os.environ.get("AWS_ENDPOINT", "http://localhost:4566"),
        region_name=os.environ.get("REGION", "us-east-1"),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def print_events(cw, group, start_ms, logger):
    """Imprime y guarda eventos desde start_ms. Devuelve (next_start_ms, count_printed)."""
    params = {"logGroupName": group, "startTime": start_ms, "interleaved": True}
    printed = 0
    last_ts = start_ms
    while True:
        resp = cw.filter_log_events(**params)
        for e in resp.get("events", []):
            ts = e["timestamp"]
            msg = e["message"].rstrip()
            line = f"[{ts}] {msg}"
            logger.info(line)  # consola + archivo (rotación)
            printed += 1
            if ts > last_ts:
                last_ts = ts
        nt = resp.get("nextToken")
        if not nt:
            break
        params["nextToken"] = nt
    return (last_ts + 1, printed)


def main():
    args = parse_args()
    logger = ensure_logger(args.output_file, args.max_bytes, args.backup_count)
    cw = client()

    start_ms = int((time.time() - args.since_seconds) * 1000)
    start_time = time.time()
    last_new_event_time = start_time

    # Primera pasada
    start_ms, printed = print_events(cw, args.log_group, start_ms, logger)
    if printed > 0:
        last_new_event_time = time.time()
    if not args.follow:
        return 0

    # Follow con salidas controladas
    try:
        while True:
            if args.max_seconds and (time.time() - start_time) >= args.max_seconds:
                break
            if (time.time() - last_new_event_time) >= args.idle_exit:
                break

            time.sleep(1)
            start_ms, printed = print_events(cw, args.log_group, start_ms, logger)
            if printed > 0:
                last_new_event_time = time.time()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
