#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

STANZA = os.environ.get("PGBR_STANZA", "pgsql-cluster")
OUT = "/var/lib/node_exporter/textfile_collector/pgbackrest.prom"
TMP = OUT + ".tmp"

def run_pgbackrest_info():
    cmd = ["sudo", "-iu", "postgres", "pgbackrest", "--stanza", STANZA, "info", "--output=json"]
    return subprocess.check_output(cmd, text=True)

def write_metrics(lines):
    with open(TMP, "w") as f:
        f.write("# HELP pgbackrest_info_up pgBackRest info command status\n")
        f.write("# TYPE pgbackrest_info_up gauge\n")
        f.write("\n".join(lines) + "\n")
    os.replace(TMP, OUT)

def main():
    now = int(time.time())
    try:
        j = run_pgbackrest_info()
        data = json.loads(j)

        stanzas = data if isinstance(data, list) else [data]

        stanza_obj = None
        for s in stanzas:
            if s.get("name") == STANZA:
                stanza_obj = s
                break

        last_success = 0
        last_type = "unknown"

        if stanza_obj:
            backups = stanza_obj.get("backup", []) or []
            best_stop = 0
            best_type = "unknown"

            for b in backups:
                if b.get("error") not in (False, 0, None):
                    continue

                tmap = b.get("timestamp", {})
                stop = 0
                if isinstance(tmap, dict):
                    stop = int(tmap.get("stop") or tmap.get("start") or 0)
                else:
                    stop = int(tmap or 0)

                if stop > best_stop:
                    best_stop = stop
                    best_type = b.get("type", "unknown")

            last_success = best_stop
            last_type = best_type

        info_up = 1 if last_success > 0 else 0

        lines = [
            f'pgbackrest_info_up{{stanza="{STANZA}"}} {info_up}',
            f'pgbackrest_last_success_timestamp{{stanza="{STANZA}"}} {last_success}',
            f'pgbackrest_last_error_timestamp{{stanza="{STANZA}"}} 0',
            f'pgbackrest_last_backup_type{{stanza="{STANZA}",type="{last_type}"}} 1',
            f'pgbackrest_textfile_generated_timestamp{{stanza="{STANZA}"}} {now}',
        ]
        write_metrics(lines)
        return 0

    except Exception:
        lines = [
            f'pgbackrest_info_up{{stanza="{STANZA}"}} 0',
            f'pgbackrest_last_success_timestamp{{stanza="{STANZA}"}} 0',
            f'pgbackrest_last_error_timestamp{{stanza="{STANZA}"}} {now}',
            f'pgbackrest_textfile_generated_timestamp{{stanza="{STANZA}"}} {now}',
        ]
        write_metrics(lines)
        return 1

if __name__ == "__main__":
    sys.exit(main())
