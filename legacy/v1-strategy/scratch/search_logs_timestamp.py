import os
import glob
import re

def search():
    log_files = glob.glob("storage/*.log*")
    found = False
    for fpath in log_files:
        print(f"Searching in {fpath}...")
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            count = 0
            for line in f:
                # search for ZSPD and 2026-07-18 or 07-18
                if "ZSPD" in line and ("2026-07-18" in line or "07-18" in line):
                    print(line.strip())
                    found = True
                    count += 1
                    if count > 50:
                        print("... truncated ...")
                        break
    if not found:
        print("Not found")

if __name__ == '__main__':
    search()
