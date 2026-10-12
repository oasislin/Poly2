import os
import glob

def search():
    log_files = glob.glob("storage/*.log*")
    found = False
    for fpath in log_files:
        print(f"Searching in {fpath}...")
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            count = 0
            for line in f:
                if "lowest-temperature-in-shanghai-on-july-18-2026" in line:
                    print(line.strip())
                    found = True
                    count += 1
                    if count > 30:
                        print("... truncated ...")
                        break
    if not found:
        print("Not found in any log files")

if __name__ == '__main__':
    search()
