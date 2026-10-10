"""
Every pairwise comparison in every sweep, as one matrix per sweep.

matrix_html() is the piece that matters: sweep_runner calls it at the end of
every report, so running a sweep puts the matrix in that sweep's own report,
with no second command to remember. That is the whole point -- the numbers are
there the moment the sweep finishes.

This file also renders one page holding every sweep at once, for reading them
side by side:

    python -m single.multi_signal.sweep_matrix
    python -m single.multi_signal.sweep_matrix percent_sell breadth_sell
    python -m single.multi_signal.sweep_matrix --keep-excluded

It reads the *_raw.json files, so it shows the last run of each sweep and can go
stale; a sweep's own report cannot.

WHY THIS EXISTS

  A sweep report shows the paired comparison against ONE reference at a time --
  click a row and the vs column recomputes. That is the correct comparison, and
  seeing one row of it at a time hides the shape: whether a cell that beats the
  live value also beats its own neighbours, whether the winners form a
  connected region or a scatter, whether the grid distinguishes anything at all.

  A sweep with N settings has N x (N-1) ordered pairs. This renders all of them.

READ THE CELL AS "ROW MINUS COLUMN"

  Green means the row's setting beat the column's; red means it lost. The
  diagonal is blank. The matrix is antisymmetric for median and mean -- cell
  (a,b) is the negative of (b,a) -- but NOT for the win count or p, since those
  count symbols rather than sum differences.

  Bold marks p < 0.05 by the sign test. With N settings there are N(N-1)/2
  distinct pairs -- 406 for the 29-cell PERCENT_SELL grid -- so at the 5% level
  about twenty cells are expected to look significant by chance alone. A
  scattering of bold cells means nothing; a solid block of them is worth
  reading.

WHY MEDIAN AND TOTAL DISAGREE, AND WHY BOTH ARE SHOWN

  A setting can win on more symbols while losing more money, and on this data
  that happens: against PERCENT_SELL 55, the threshold 65 improves 31 of 52
  symbols and still loses 863 points in total, because HCM alone swings -950.
  Neither number is the right one; the pair of them is the finding.

EXCLUSIONS

  EXCLUDE_SYMBOLS (VIX, VIC) are dropped by default, which is what every sweep
  report does before aggregating -- their absence is why the report's mean and a
  naive read of the raw JSON disagree. --keep-excluded includes them.
"""

import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from single.multi_signal import config

HERE = Path(__file__).parent / "charts" / "sweeps"   # where sweep_runner writes
OUT = HERE / "SWEEP_MATRIX.html"

# diff is index 0 in every sweep's cell tuple. The rest of the tuple is ordered
# differently between files -- sweep_sell_slope writes (diff, buys, sells,
# reinvests) where the others write (diff, reinvests, buys, sells) -- so nothing
# past index 0 is read here.
DIFF = 0

# Luoi lon hon nguong nay khong ve: 40 o la 1560 cap, da la muc kho doc; mot vai
# sweep 2D co toi 500 o, tuc 250 nghin cap.
# Tran cua ma tran. Hai sweep 2 chieu co 63 va 77 o -- van ve duoc, chi la
# phai bo tooltip (xem TIP_KEYS). Tren nua thi trang khong con doc duoc.
MAX_KEYS = 80
TIP_KEYS = 40

METRICS = [
    ("median", "trung vị của các hiệu", "Mã điển hình được lợi bao nhiêu điểm."),
    ("mean", "trung bình của các hiệu", "Bị vài mã lớn chi phối; đọc cạnh trung vị."),
    ("total", "tổng các hiệu", "Tổng tài sản chênh nhau; một mã có thể chiếm hết."),
    ("win", "số mã tốt lên / số mã đổi", "Đếm chiều, không đếm độ lớn."),
    ("p", "kiểm định dấu", "Xác suất thấy chừng này mã tốt lên nếu hai bên như nhau."),
]


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    per = d.get("results", {})
    if not per:
        return None
    keys = d.get("meta", {}).get("grid") or []
    if not keys:
        # Suy tu chinh du lieu: co sweep khong ghi grid vao meta.
        seen = {}
        for v in per.values():
            for k in v:
                seen[k] = seen.get(k, 0) + 1
        keys = [k for k, n in seen.items() if n >= len(per) * 0.5]
        keys.sort(key=lambda k: (k == "none", _num(k)))
    return {"per": per, "keys": [k for k in keys], "meta": d.get("meta", {})}


def _num(k):
    try:
        return float(k)
    except (TypeError, ValueError):
        return float("inf")


def _diff(cell):
    """Moi sweep luu mot cell khac nhau: co cai la tuple, co cai la mot so."""
    if isinstance(cell, (int, float)):
        return float(cell)
    return float(cell[DIFF])


def pair(per, a, b):
    d = [_diff(v[a]) - _diff(v[b]) for v in per.values() if a in v and b in v]
    if not d:
        return None
    up = sum(1 for x in d if x > 1e-9)
    dec = sum(1 for x in d if abs(x) > 1e-9)
    p = (sum(math.comb(dec, i) for i in range(up, dec + 1)) / 2 ** dec
         if dec else 1.0)
    return {"median": st.median(d), "mean": st.mean(d), "total": sum(d),
            "up": up, "dec": dec, "n": len(d), "p": p}


def cell_html(c, metric, tip=True):
    # tip=False cho luoi 2 chieu: o do title chiem hon nua so byte cua trang,
    # va 5.929 o x 5 chi so voi tooltip la hon 3 MB HTML. Bo tooltip thi con
    # doc duoc; doi tab van thay du ca nam chi so.
    if c is None:
        return "<td class=na></td>"
    if metric == "win":
        txt = f"{c['up']}/{c['dec']}"
        v = (c["up"] / c["dec"] - 0.5) if c["dec"] else 0
    elif metric == "p":
        txt = f"{c['p']:.3f}"
        v = 0.05 - c["p"]
    else:
        x = c[metric]
        txt = f"{x:+,.0f}" if metric == "total" else f"{x:+.2f}"
        v = x
    sig = c["p"] < 0.05
    col = "#4ade80" if v > 0 else "#f87171" if v < 0 else "#64748b"
    w = ";font-weight:700" if sig else ""
    if not tip:
        return f"<td style='color:{col}{w}'>{txt}</td>"
    t = (f"TV {c['median']:+.2f} · TB {c['mean']:+.1f} · tổng {c['total']:+,.0f}"
         f" · {c['up']}/{c['dec']} · p={c['p']:.3f}")
    return f"<td style='color:{col}{w}' title='{t}'>{txt}</td>"


def keys_of(per):
    """Cac o co mat o phan lon so ma, sap theo gia tri so."""
    seen = {}
    for v in per.values():
        for k in v:
            seen[k] = seen.get(k, 0) + 1
    keys = [k for k, n in seen.items() if n >= len(per) * 0.5]
    keys.sort(key=lambda k: (k == "none", _num(k)))
    return keys


def matrix_html(per, keys=None, drop_excluded=True):
    """
    Khoi HTML doc lap: ma tran ghep cap moi cap o, nam cach do.

    Duoc goi tu cuoi build_html cua tung sweep, nen mot lan chay sweep la co
    ngay so tai cho -- khong phai chay them cong cu nao. Tu chua style va
    script; khong dung id trung voi phan con lai cua trang.
    """
    if not per:
        return ""
    if drop_excluded:
        skip = {x.upper() for x in getattr(config, "EXCLUDE_SYMBOLS", [])}
        per = {k: v for k, v in per.items() if k.upper() not in skip}
    keys = keys or keys_of(per)
    if len(keys) < 2:
        return ""
    if len(keys) > MAX_KEYS:
        return (f"<p class=note>Ma trận ghép cặp không vẽ: lưới {len(keys)} ô "
                f"là {len(keys)*(len(keys)-1)//2:,} cặp, quá lớn để đọc.</p>")

    # Moi cap tinh MOT lan roi dung lai cho ca nam chi so. Truoc do pair() bi
    # goi lai o moi tab, tuc 5 lan cho moi o -- 30.000 lan tren luoi 77 o.
    P = {}
    for a in keys:
        for b in keys:
            if a != b:
                P[(a, b)] = pair(per, a, b)
    tot = sum(1 for i, a in enumerate(keys) for b in keys[i + 1:] if P[(a, b)])
    sig = sum(1 for i, a in enumerate(keys) for b in keys[i + 1:]
              if P[(a, b)] and P[(a, b)]["p"] < 0.05)
    tip = len(keys) <= TIP_KEYS
    grids = ""
    for mi, (metric, label, note) in enumerate(METRICS):
        rows = ""
        for a in keys:
            cells = "".join("<td class=mxdiag></td>" if a == b
                            else cell_html(P[(a, b)], metric, tip)
                            for b in keys)
            rows += f"<tr><th class=mxrh>{a}</th>{cells}</tr>"
        head = "".join(f"<th>{b}</th>" for b in keys)
        grids += (f"<div class=mxgrid data-m='{metric}' "
                  f"style='display:{'block' if mi == 0 else 'none'}'>"
                  f"<div class=mxnote><b>{label}</b> — {note}</div>"
                  f"<div class=mxscroll><table class=mx><thead><tr><th></th>"
                  f"{head}</tr></thead><tbody>{rows}</tbody></table></div></div>")
    tabs = "".join(
        "<button class='mxtab%s' data-m='%s'>%s</button>"
        % (" on" if i == 0 else "", m, m)
        for i, (m, _, _) in enumerate(METRICS))
    tiptxt = (" Rê chuột lên ô để xem đủ năm chỉ số." if tip else
              f" Lưới {len(keys)} ô nên không có tooltip: đổi tab để đọc từng"
              " chỉ số.")
    return f"""
<h3 style='margin:26px 0 4px;color:#facc15;font-size:15px'>Ma trận ghép cặp —
mọi cặp ô</h3>
<p class=note style='margin:2px 0'>Ô là <b>dòng trừ cột</b>, ghép cặp trên từng
mã: xanh nghĩa là dòng hơn cột. Bảng <code>vs</code> ở trên chỉ hiện một mốc mỗi
lần; bảng này hiện tất cả, nên nhìn được <b>hình dạng</b> — ô thắng có nối thành
vùng liền hay chỉ rải rác.<br>
{len(per)} mã · {len(keys)} ô · <b>{tot}</b> cặp · <b>{sig}</b> cặp có
p&lt;0.05, ngẫu nhiên sẽ có khoảng <b>{tot*0.05:.0f}</b> — nên vài ô đậm lẻ tẻ
không nói lên gì, chỉ một khối đậm liền nhau mới đáng đọc.<br>
<b>Trung vị và tổng có thể trái dấu</b>: một ngưỡng thắng ở nhiều mã hơn vẫn có
thể lỗ tổng, nếu một mã lệch rất lớn. Đổi tab để thấy cả hai.{tiptxt}</p>
<div class=mxtabs>{tabs}</div>{grids}
<style>
.mxtabs{{margin:6px 0}}
.mxtab{{background:#1e293b;border:1px solid #334155;color:#94a3b8;
 border-radius:5px;padding:2px 10px;cursor:pointer;font-size:12px;margin-right:5px}}
.mxtab.on{{background:#334155;color:#e2e8f0;font-weight:700}}
.mxnote{{color:#94a3b8;font-size:12px;margin:4px 0}}
.mxscroll{{overflow-x:auto;max-width:100%}}
table.mx{{border-collapse:collapse;font-size:11px;
 font-variant-numeric:tabular-nums;margin:0}}
table.mx th,table.mx td{{border:1px solid #1e293b;padding:1px 5px;
 text-align:right;white-space:nowrap}}
table.mx thead th{{background:#111c30;color:#94a3b8}}
table.mx th.mxrh{{background:#111c30;color:#94a3b8;text-align:left}}
td.mxdiag{{background:#1e293b}} td.na{{background:#0d1526}}
table.mx tbody tr:hover td{{background:#16203a}}
</style>
<script>
document.querySelectorAll('.mxtab').forEach(function (b) {{
  b.onclick = function () {{
    document.querySelectorAll('.mxtab').forEach(function (x) {{
      x.classList.toggle('on', x === b); }});
    document.querySelectorAll('.mxgrid').forEach(function (g) {{
      g.style.display = g.dataset.m === b.dataset.m ? 'block' : 'none'; }});
  }};
}});
</script>"""


def section(name, data, idx):
    per, keys = data["per"], data["keys"]
    meta = data["meta"]
    grids = ""
    for mi, (metric, label, note) in enumerate(METRICS):
        rows = ""
        for a in keys:
            cells = "".join("<td class=diag></td>" if a == b
                            else cell_html(pair(per, a, b), metric)
                            for b in keys)
            rows += f"<tr><th class=rh>{a}</th>{cells}</tr>"
        head = "".join(f"<th>{b}</th>" for b in keys)
        grids += (
            f"<div class=grid data-m='{metric}' "
            f"style='display:{'block' if mi == 0 else 'none'}'>"
            f"<div class=gnote><b>{label}</b> — {note}</div>"
            f"<div class=scroll><table class=mx><thead><tr><th></th>{head}</tr>"
            f"</thead><tbody>{rows}</tbody></table></div></div>")

    sig = 0
    tot = 0
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            c = pair(per, a, b)
            if c:
                tot += 1
                sig += c["p"] < 0.05
    expect = tot * 0.05
    cfg = meta.get("config", {})
    ctx = " · ".join(
        f"{k}={cfg.get(k)}" for k in
        ("PERCENT_SELL", "PERCENT_BUY", "MIN_SIGNAL3", "SELL_MIN_BREADTH",
         "BREADTH_SIGNAL", "BREADTH_UNIVERSE") if k in cfg)
    return f"""
<h2 id=s{idx}>{name}</h2>
<div class=meta>{len(per)} mã · {len(keys)} ô · {tot} cặp ·
<b>{sig}</b> cặp có p&lt;0.05, ngẫu nhiên sẽ có khoảng <b>{expect:.0f}</b>
{('· ' + ctx) if ctx else ''}</div>
<div class=tabs>{''.join(
    f"<button data-s={idx} data-m='{m}' class='{'on' if i == 0 else ''}'>{m}</button>"
    for i, (m, _, _) in enumerate(METRICS))}</div>
<div class=sec data-s='{idx}'>{grids}</div>"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = "--keep-excluded" in sys.argv
    drop = set() if keep else {s.upper() for s in
                               getattr(config, "EXCLUDE_SYMBOLS", [])}

    files = sorted(HERE.glob("sweep_*_raw.json"))
    if args:
        files = [f for f in files if any(a in f.name for a in args)]
    if not files:
        raise SystemExit("khong tim thay sweep nao")

    secs, nav, n, skipped = "", "", 0, []
    for f in files:
        d = load(f)
        if not d or len(d["keys"]) < 2:
            print(f"  bo qua {f.name}: khong du o de ghep cap")
            continue
        if len(d["keys"]) > MAX_KEYS:
            skipped.append((f.name[len("sweep_"):-len("_raw.json")], len(d["keys"])))
            print(f"  bo qua {f.name}: {len(d['keys'])} o > {MAX_KEYS}")
            continue
        d["per"] = {k: v for k, v in d["per"].items() if k.upper() not in drop}
        name = f.name[len("sweep_"):-len("_raw.json")]
        secs += section(name, d, n)
        nav += f"<a href='#s{n}'>{name}</a>"
        print(f"  {name}: {len(d['keys'])} o, {len(d['per'])} ma")
        n += 1

    skipnote = ("" if not skipped else
                "<div class=note style='color:#facc15'><b>Không vẽ "
                + str(len(skipped)) + " sweep</b> vì lưới quá lớn để đọc: "
                + ", ".join(f"{a} ({b} ô, {b*(b-1)//2:,} cặp)" for a, b in skipped)
                + ". Chúng là lưới 2D — một ma trận phẳng không phải cách đọc "
                + "chúng.</div>")

    HTML = f"""<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>Ma trận ghép cặp — mọi sweep</title><style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;
 margin:0;padding:24px;line-height:1.55}}
.wrap{{max-width:1500px;margin:0 auto}}
h1{{font-size:21px;margin:0 0 4px}}
h2{{font-size:16px;margin:34px 0 4px;border-bottom:1px solid #1e293b;
 padding-bottom:5px;color:#facc15}}
.sub,.meta{{color:#64748b;font-size:12.5px}}
.note{{color:#94a3b8;font-size:13px;max-width:1000px;margin:8px 0}}
.box{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:12px 16px;margin:12px 0}}
.nav a{{color:#60a5fa;text-decoration:none;margin-right:12px;font-size:12.5px}}
.tabs{{margin:8px 0 4px}}
.tabs button{{background:#1e293b;border:1px solid #334155;color:#94a3b8;
 border-radius:5px;padding:2px 10px;cursor:pointer;font-size:12px;margin-right:5px}}
.tabs button.on{{background:#334155;color:#e2e8f0;font-weight:700}}
.gnote{{color:#94a3b8;font-size:12px;margin:4px 0}}
.scroll{{overflow-x:auto;max-width:100%}}
table.mx{{border-collapse:collapse;font-size:11px;
 font-variant-numeric:tabular-nums}}
table.mx th,table.mx td{{border:1px solid #1e293b;padding:1px 5px;
 text-align:right;white-space:nowrap}}
table.mx thead th{{background:#111c30;color:#94a3b8;position:sticky;top:0}}
table.mx th.rh{{background:#111c30;color:#94a3b8;position:sticky;left:0;
 text-align:left}}
td.diag{{background:#1e293b}} td.na{{background:#0d1526}}
table.mx tbody tr:hover td{{background:#16203a}}
</style></head><body><div class=wrap>

<h1>Ma trận ghép cặp — mọi sweep</h1>
<div class=sub>{n} sweep · mỗi ô là <b>dòng trừ cột</b>, ghép cặp trên từng mã
{'· đã bỏ ' + ', '.join(sorted(drop)) if drop else '· giữ đủ mọi mã'}</div>
<div class="nav sub" style='margin:10px 0'>{nav}</div>

<div class=box>
<b>Vì sao cần bảng này</b>
<div class=note>Báo cáo sweep chỉ hiện ghép cặp với <b>một</b> mốc mỗi lần —
bấm một dòng thì cột <code>vs</code> tính lại. Phép so đó đúng, nhưng nhìn từng
dòng một thì không thấy được <b>hình dạng</b>: một ô thắng mốc live có thắng cả
hàng xóm của nó không, các ô thắng có nối liền thành vùng hay rải rác, và lưới
có phân biệt được gì hay không.</div>
<div class=note><b>Đọc ô</b>: xanh = dòng hơn cột, đỏ = dòng kém cột. Đường chéo
để trống. Với <i>trung vị</i> và <i>trung bình</i>, ma trận phản đối xứng — ô
(a,b) là số đối của (b,a). Với <i>số mã</i> và <i>p</i> thì không, vì chúng đếm
mã chứ không cộng hiệu.</div>
<div class=note><b>In đậm = p &lt; 0.05.</b> Nhưng lưới N ô có N(N−1)/2 cặp —
406 cặp với lưới 29 ô của PERCENT_SELL — nên ở mức 5% sẽ có <b>khoảng hai chục
ô đậm do ngẫu nhiên</b>. Vài ô đậm rải rác không nói lên điều gì; một khối đậm
liền nhau mới đáng đọc. Dòng tóm tắt dưới mỗi tiêu đề ghi sẵn số cặp đậm thực tế
và số cặp ngẫu nhiên sẽ cho.</div>
<div class=note><b>Trung vị và tổng có thể trái dấu, và cả hai đều được hiện.</b>
Một ngưỡng có thể thắng ở nhiều mã hơn mà vẫn lỗ tổng: so với PERCENT_SELL 55,
ngưỡng 65 tốt hơn ở 31/52 mã nhưng tổng vẫn âm 863 điểm vì riêng HCM lệch −950.
Không con số nào trong hai là "đúng"; chính cặp số đó mới là kết quả.</div>
<div class=note>Rê chuột lên ô để xem đủ cả năm chỉ số cùng lúc.</div>
{skipnote}
</div>
{secs}

<script>
document.querySelectorAll('.tabs button').forEach(function (b) {{
  b.onclick = function () {{
    var s = b.dataset.s, m = b.dataset.m;
    document.querySelectorAll(".tabs button[data-s='" + s + "']")
      .forEach(function (x) {{ x.classList.toggle('on', x === b); }});
    document.querySelectorAll(".sec[data-s='" + s + "'] .grid")
      .forEach(function (g) {{ g.style.display = g.dataset.m === m ? 'block' : 'none'; }});
  }};
}});
</script>
</div></body></html>"""
    OUT.write_text(HTML, encoding="utf-8")
    print(f"\n{OUT}")


if __name__ == "__main__":
    main()
