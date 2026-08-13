"""Render docs/index.html from the latest run (served by GitHub Pages)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest.json")
CALIB = os.path.join(ROOT, "data", "calibration.json")
OUT = os.path.join(ROOT, "docs", "index.html")

CSS = """
:root{--bg:#FCFCFD;--sf:#F1F3F7;--ink:#14161C;--ink2:#333947;--mut:#5A6274;
--rule:#DCE0E8;--acc:#8A6B2C;--pos:#136B4F;--neg:#9E2F28;--posbg:#DDEDE6;--flatbg:#ECEEF3;
--mono:ui-monospace,Consolas,'SF Mono',monospace;
--sans:system-ui,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
--serif:Georgia,'Iowan Old Style',serif}
@media(prefers-color-scheme:dark){:root{--bg:#101319;--sf:#171B23;--ink:#E9EBF1;
--ink2:#C2C7D4;--mut:#939BAD;--rule:#272D3A;--acc:#C9A227;--pos:#4FBF95;--neg:#E0685E;
--posbg:#12281F;--flatbg:#1C212B}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);margin:0;
padding:clamp(1.2rem,4vw,3rem);line-height:1.6}
.w{max-width:62rem;margin:0 auto;display:flex;flex-direction:column;gap:2rem}
h1{font-family:var(--serif);font-size:clamp(1.6rem,4vw,2.3rem);margin:0;letter-spacing:-.015em}
h2{font-family:var(--serif);font-size:1.3rem;margin:0}
h3{font-size:.98rem;margin:0}
header{border-bottom:2px solid var(--ink);padding-bottom:1.1rem;display:flex;
flex-direction:column;gap:.5rem}
.meta{font-family:var(--mono);font-size:.73rem;color:var(--mut);
display:flex;gap:1.2rem;flex-wrap:wrap}
.banner{background:var(--sf);border-left:3px solid var(--acc);padding:1rem 1.2rem;font-size:.92rem}
.prov{border-left-color:var(--neg)}
section{display:flex;flex-direction:column;gap:.7rem;border-top:1px solid var(--rule);
padding-top:1.2rem}
.sc{overflow-x:auto;border:1px solid var(--rule)}
table{border-collapse:collapse;width:100%;font-size:.79rem;
font-variant-numeric:tabular-nums;min-width:36rem}
th,td{padding:.42rem .75rem;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th{background:var(--sf);font-family:var(--mono);font-size:.64rem;letter-spacing:.06em;
text-transform:uppercase;color:var(--mut);font-weight:400}
td:first-child,th:first-child{text-align:left}
td.s{font-family:var(--mono);font-weight:600}
tr:last-child td{border-bottom:none}
tr.g td{background:var(--posbg)}
.pos{color:var(--pos)}.neg{color:var(--neg)}.mut{color:var(--mut)}
.stat{font-family:var(--mono);font-size:.74rem;color:var(--mut)}
.hd{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline}
footer{border-top:2px solid var(--ink);padding-top:1rem;font-size:.78rem;color:var(--mut)}
"""


def row(h):
    r1y = f"{h['ret1y']}%" if h.get("ret1y") is not None else "—"
    cls = "pos" if (h.get("ret1y") or 0) > 0 else "mut"
    return (f"<tr><td class='s'>{h['symbol']}</td>"
            f"<td>{h['close']:,}</td><td>{h['rsi']}</td><td>{h['adx']}</td>"
            f"<td class='{cls}'>{r1y}</td><td>{h['from_52wh']}%</td>"
            f"<td>{h['turnover_cr']}</td><td class='mut'>{h.get('sector') or '—'}</td></tr>")


def main():
    if not os.path.exists(LATEST):
        print("no latest.json")
        return
    with open(LATEST) as f:
        rep = json.load(f)
    with open(CALIB) as f:
        cal = json.load(f)

    prov = rep.get("provisional")
    banner = (f"<div class='banner prov'><strong>Provisional.</strong> The session is "
              f"open and roughly {rep.get('volume_elapsed_pct', 0)}% of the day's volume "
              f"has traded. Today's bar is incomplete — volume is projected to a "
              f"full-session estimate, and these signals can un-fire by the close. The "
              f"post-close run at 15:35 IST is the one that matches the calibration.</div>"
              if prov else
              "<div class='banner'><strong>Confirmed.</strong> Session closed; signals "
              "are computed on completed daily bars, matching how the base rates were "
              "measured.</div>")

    parts = [f"<style>{CSS}</style><div class='w'><header>",
             "<h1>NSE Screener</h1>",
             f"<div class='meta'><span>As of {rep['as_of']}</span>"
             f"<span>session: {rep.get('session')}</span>"
             f"<span>{len(rep.get('new', []))} new this run</span></div></header>",
             banner]

    edge = [(n, d) for n, d in rep["screens"].items() if d["verdict"] == "EDGE"]
    for name, d in sorted(edge, key=lambda x: -(x[1]["edge_pct"] or 0)):
        c = cal.get(name, {})
        parts.append(
            f"<section><div class='hd'><h3>{name}</h3>"
            f"<span class='stat'>edge {d['edge_pct']:+.2f}% · t={d['t']:+.1f} · "
            f"{d['n']} hits · median {c.get('median_days','?')} sessions to +10% · "
            f"typical drawdown {c.get('median_drawdown_pct','?')}%</span></div>")
        if d["hits"]:
            parts.append("<div class='sc'><table><thead><tr><th>Symbol</th>"
                         "<th>Close ₹</th><th>RSI</th><th>ADX</th><th>1y</th>"
                         "<th>From 52wH</th><th>₹cr/day</th><th>Sector</th></tr></thead><tbody>")
            parts.append("".join(row(h) for h in d["hits"][:20]))
            parts.append("</tbody></table></div>")
        else:
            parts.append("<p class='mut'>No hits.</p>")
        parts.append("</section>")

    other = [(n, d) for n, d in rep["screens"].items() if d["verdict"] != "EDGE"]
    if other:
        parts.append("<section><h2>Screens without demonstrated edge</h2>"
                     "<p class='mut' style='font-size:.88rem'>These still run. They are "
                     "separated because acting on them measured no better than picking "
                     "any liquid stock that day — or worse.</p><div class='sc'><table>"
                     "<thead><tr><th>Screen</th><th>Verdict</th><th>Edge 6m</th>"
                     "<th>t</th><th>Hits now</th></tr></thead><tbody>")
        for n, d in sorted(other, key=lambda x: -(x[1]["edge_pct"] or 0)):
            v = d["verdict"]
            cls = "neg" if v == "NEGATIVE" else "mut"
            e = d["edge_pct"]
            parts.append(f"<tr><td>{n}</td><td class='{cls}'>{v}</td>"
                         f"<td class='{cls}'>{e:+.2f}%</td><td class='{cls}'>{d['t']:+.1f}</td>"
                         f"<td>{d['n']}</td></tr>")
        parts.append("</tbody></table></div></section>")

    b = cal.get("_meta", {}).get("baseline", {})
    parts.append(
        "<footer><p>Base rate for any liquid NSE stock: "
        f"<strong>{b.get('P_touch_plus10pct_within_126d')}%</strong> chance of touching "
        f"+10% within six months, median <strong>{b.get('median_days_to_plus10pct')} "
        "sessions</strong>. The screens above shift that by two to four points. "
        f"{b.get('caveat','')}</p>"
        "<p>Historical base rates, not forecasts. Research tooling only — "
        "not investment advice.</p></footer></div>")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
