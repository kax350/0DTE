"""Build scheduled FOMC statement dates (last day of each scheduled meeting) 2017-2027.

Source: federalreserve.gov fomccalendars.htm (2021+) and fomchistoricalYYYY.htm (2017-2020).
Unscheduled meetings / notation votes are recorded separately and NOT excluded (PAPER_SPEC §2).
"""
import re, html, sys, datetime as dt, csv, urllib.request
from pathlib import Path

MONTHS = {m: i for i, m in enumerate(["January","February","March","April","May","June","July","August",
                                        "September","October","November","December"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "fomc_dates.csv"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

def parse_current(t):
    rows = []
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", t)]
    heads.sort()
    for i, (pos, year) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(t)
        seg = t[pos:end]
        for mon, day in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<', seg, flags=re.S):
            mon, day = html.unescape(mon).strip(), html.unescape(day).strip()
            kind = "scheduled"
            if "notation" in day.lower() or "unscheduled" in day.lower() or "conference call" in day.lower():
                kind = "unscheduled"
            d = re.sub(r"[^0-9\-]", "", day.split("(")[0])
            last = int(d.split("-")[-1]) if d else None
            months = mon.split("/")
            m = MONTHS.get(months[-1].strip(), MON3.get(months[-1].strip()[:3]))
            if last is None or m is None:
                continue
            rows.append((dt.date(year, m, last), kind, f"{mon} {day}"))
    return rows

def parse_hist(t, year):
    rows = []
    # Headings look like 'March 14-15 Meeting - 2017', 'Jan/Feb 31-1 Meeting - 2017',
    # 'March 2 (unscheduled) Meeting - 2020', 'March 17-18 (cancelled) Meeting - 2020'.
    for h in re.findall(r"<h5[^>]*>(.*?)</h5>", t, flags=re.S):
        s = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(h))).strip()
        m = re.match(r"([A-Za-z]+)(?:/([A-Za-z]+))? (\d+)(?:-(\d+))?", s)
        if not m:
            continue
        low = s.lower()
        kind = ("cancelled" if "cancelled" in low else
                "unscheduled" if ("unscheduled" in low or "notation" in low or "conference call" in low)
                else "scheduled")
        mon = m.group(2) or m.group(1)
        mnum = MONTHS.get(mon, MON3.get(mon[:3]))
        day = int(m.group(4) or m.group(3))
        rows.append((dt.date(year, mnum, day), kind, s))
    return rows

def main():
    rows = parse_current(get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"))
    for y in (2017, 2018, 2019, 2020):
        rows += parse_hist(get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm"), y)
    rows = sorted(set(rows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "kind", "source_text"])
        for r in rows: w.writerow([r[0].isoformat(), r[1], r[2]])
    from collections import Counter
    c = Counter((r[0].year, r[1]) for r in rows)
    for k in sorted(c): print(k, c[k])

if __name__ == "__main__":
    main()
