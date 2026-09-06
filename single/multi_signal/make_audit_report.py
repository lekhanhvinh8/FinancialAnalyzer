# -*- coding: utf-8 -*-
"""Bao cao kiem tra doc lap ba duong prem."""
import json
from pathlib import Path

S = Path(__file__).parent
D = json.load(open(S / "audit.json", encoding="utf-8"))

SECTIONS = ""
for i, date in enumerate(D["dates"]):
    sec = D["sections"][date]
    mine, stored = sec["mine"], sec["stored"]
    ok = [r for r in sec["rows"] if r["ok"]]
    bad = [r for r in sec["rows"] if not r["ok"]]

    def cmp_cell(key, label):
        a, b = mine[key], stored.get(key)
        same = b is not None and abs(a - b) < 5e-4
        col = "#4ade80" if same else "#f87171"
        tag = "khớp" if same else "LỆCH"
        return ("<div><span class=lab>{lab}</span>"
                "<span class=val id='out-{i}-{key}'>{a:.4f}</span>"
                "<span class=lab>đã lưu {b} · <b style='color:{c}'>{t}</b></span>"
                "</div>".format(lab=label, i=i, key=key, a=a, b=b, c=col, t=tag))

    body = ""
    for r in sec["rows"]:
        dis = "" if r["ok"] else " class=off"
        chk = "checked" if r["ok"] else "disabled"
        body += (
            "<tr{dis} data-sym='{sym}' data-prem='{prem}' data-cap='{cap}'>"
            "<td><input type=checkbox {chk} onchange='recalc({i})'></td>"
            "<td data-v='{sym}'><b>{sym}</b></td>"
            "<td class=n data-v='{bars}'>{bars:,}</td>"
            "<td class=n data-v='{close}'>{close}</td>"
            "<td class=n data-v='{med}'>{med}</td>"
            "<td class=n data-v='{prem}' style='color:{pc}'>{premtxt}</td>"
            "<td class=n data-v='{cap}'>{captxt}</td>"
            "<td class=trim data-v='0'></td>"
            "<td class=s data-v='{why}'>{why}</td></tr>".format(
                dis=dis, chk=chk, i=i, sym=r["sym"],
                bars=r["bars"],
                close="—" if r["close"] is None else "{:,.1f}".format(r["close"]),
                med="—" if r["med"] is None else "{:,.1f}".format(r["med"]),
                prem=-9999 if r["prem"] is None else r["prem"],
                premtxt="—" if r["prem"] is None else "{:+.2f}".format(r["prem"]),
                pc=("#94a3b8" if r["prem"] is None else
                    "#4ade80" if r["prem"] < 0 else "#f87171"),
                cap=-1 if r["cap"] is None else r["cap"],
                captxt="—" if r["cap"] is None else "{:,.0f}".format(r["cap"]),
                why=r["why"] or "—"))

    SECTIONS += """
<h2 id=d{i}>{date}</h2>
<div class=box><div class=kpi>{c1}{c2}{c3}
<div><span class=lab>số mã đang tính</span>
 <span class=val id='out-{i}-n'>{n}</span>
 <span class=lab>đã lưu n_symbols {sn}</span></div>
</div>
<div class=note style='margin-top:10px'>Vùng cắt đuôi hiện tại:
prem từ <b id='out-{i}-lo'>{lo:.2f}</b> đến <b id='out-{i}-hi'>{hi:.2f}</b>
(phân vị 5–95) — <b id='out-{i}-ntrim'>{ntrim}</b> mã lọt vào,
<b id='out-{i}-ncap'>{ncap}</b> trong số đó có vốn hoá nên được tính vào
prem_cap.</div></div>

<div class=ctl>
<label>lọc mã <input id='f-{i}' oninput='filt({i})' placeholder='vd: VN, HP'></label>
<button onclick='tickAll({i},1)'>tick tất cả</button>
<button onclick='tickAll({i},0)'>bỏ tick tất cả</button>
<button onclick='tickTrim({i})'>chỉ giữ phần trong vùng cắt</button>
<button onclick='tickCap({i})'>chỉ giữ mã có vốn hoá</button>
<span class=hint>bấm tiêu đề cột để sắp xếp · bỏ tick là tính lại ngay</span>
</div>

<table class=full id='t-{i}'><thead><tr>
<th></th><th>mã</th><th>số phiên</th><th>giá đóng cửa</th>
<th>median 1000</th><th>prem %</th><th>vốn hoá (tỷ)</th>
<th>trong vùng cắt</th><th>lý do loại</th>
</tr></thead><tbody>{body}</tbody></table>
""".format(i=i, date=date, n=mine["n"], sn=stored.get("n_symbols"),
           lo=mine["lo"], hi=mine["hi"], ntrim=mine["n_trim"],
           ncap=mine["n_cap"], body=body,
           c1=cmp_cell("median_prem", "median_prem"),
           c2=cmp_cell("prem_trim", "prem_trim"),
           c3=cmp_cell("prem_cap", "prem_cap"))

HTML = """<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>Kiểm tra độc lập ba đường prem</title><style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;
 margin:0;padding:26px;line-height:1.6}}
.wrap{{max-width:1120px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:18px;margin:38px 0 10px;border-bottom:1px solid #1e293b;
 padding-bottom:6px;color:#facc15}}
.sub{{color:#64748b;font-size:13px;margin-bottom:16px}}
.note{{color:#94a3b8;font-size:13px;max-width:960px}}
.box{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:14px 18px;margin:12px 0}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px}}
.kpi span{{display:block}} .kpi .lab{{color:#64748b;font-size:12px}}
.kpi .val{{font-size:21px;font-weight:700;line-height:1.25;
 font-variant-numeric:tabular-nums}}
table.full{{border-collapse:collapse;font-size:12.5px;width:100%;margin:8px 0}}
table.full th,table.full td{{border:1px solid #1e293b;padding:3px 9px}}
table.full th{{background:#111c30;color:#94a3b8;text-align:right;cursor:pointer;
 position:sticky;top:0}}
table.full th:first-child,table.full th:nth-child(2){{text-align:left}}
table.full td:nth-child(2){{text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td.s{{color:#64748b;font-size:11.5px}}
td.trim{{text-align:center}}
tr.off{{opacity:.4}} tr.hide{{display:none}}
tr.out td.trim{{color:#f87171}}
.ctl{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}}
.ctl input{{background:#0f172a;border:1px solid #334155;color:#e2e8f0;
 border-radius:5px;padding:3px 8px}}
.ctl button{{background:#1e293b;border:1px solid #334155;color:#cbd5e1;
 border-radius:5px;padding:3px 10px;cursor:pointer;font-size:12.5px}}
.ctl button:hover{{background:#293548}}
.hint{{color:#64748b;font-size:12px}}
.nav a{{color:#60a5fa;text-decoration:none;margin-right:14px}}
code{{background:#111c30;padding:1px 5px;border-radius:4px;font-size:12px}}
</style></head><body><div class=wrap>

<h1>Kiểm tra độc lập ba đường prem</h1>
<div class=sub>{uni} mã trong rổ · cửa sổ median {window} phiên · cắt đuôi
{t0}–{t1} · dữ liệu tính lại từ giá thô, không đọc bảng breadth_signals</div>
<div class="nav sub">Nhảy tới: <a href='#d0'>{d0}</a><a href='#d1'>{d1}</a>
<a href='#d2'>{d2}</a></div>

<div class=box>
<b>Ba đường được tính thế nào</b>
<div class=note style='margin-top:6px'>
1. Mỗi mã: <code>prem = (giá − median 1000 phiên) / median × 100</code>.
Mã chưa đủ 1000 phiên hoặc không giao dịch phiên đó bị loại.<br>
2. <code>median_prem</code> = trung vị của cột prem.<br>
3. <code>prem_trim</code> = bỏ các mã ngoài phân vị 5–95 của prem, rồi lấy
trung bình cộng phần còn lại.<br>
4. <code>prem_cap</code> = cũng trên phần còn lại đó, nhưng trung bình có trọng
số vốn hoá; mã thiếu vốn hoá bị loại khỏi riêng đường này.
</div></div>

<div class=box>
<b>Cách dùng</b>
<div class=note style='margin-top:6px'>Bỏ tick một mã là nó rời khỏi rổ và cả ba
con số tính lại ngay. <b>Phân vị 5–95 cũng tính lại</b> trên tập còn lại — nếu
giữ nguyên vùng cắt cũ thì kết quả không còn là “con số nếu rổ chỉ gồm các mã
này”, mà là một thứ lai không có ý nghĩa.<br>
Dòng “đã lưu” là giá trị đang nằm trong bảng <code>breadth_signals</code>. Khi
tick đủ cả rổ, ba con số phải khớp — đó là phép kiểm tra.</div></div>
{SECTIONS}

<script>
function rowsOf(i) {{
  return Array.prototype.slice.call(
    document.querySelectorAll('#t-' + i + ' tbody tr'));
}}
function pct(sorted, q) {{
  // Cung cong thuc voi numpy.percentile mac dinh (linear interpolation).
  if (!sorted.length) return NaN;
  var pos = (sorted.length - 1) * q / 100;
  var lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}}
function recalc(i) {{
  var live = rowsOf(i).filter(function (r) {{
    var cb = r.querySelector('input');
    return cb && !cb.disabled && cb.checked;
  }});
  var prem = live.map(function (r) {{ return parseFloat(r.dataset.prem); }});
  var set = function (k, v) {{
    var el = document.getElementById('out-' + i + '-' + k);
    if (el) el.textContent = v;
  }};
  rowsOf(i).forEach(function (r) {{
    r.classList.remove('out');
    var c = r.querySelector('td.trim'); if (c) c.textContent = '';
  }});
  if (!prem.length) {{
    ['median_prem', 'prem_trim', 'prem_cap'].forEach(function (k) {{ set(k, '—'); }});
    set('n', 0); set('ntrim', 0); set('ncap', 0); set('lo', '—'); set('hi', '—');
    return;
  }}
  var s = prem.slice().sort(function (a, b) {{ return a - b; }});
  var med = pct(s, 50), lo = pct(s, 5), hi = pct(s, 95);
  var keep = [], capNum = 0, capDen = 0, nCap = 0;
  live.forEach(function (r) {{
    var p = parseFloat(r.dataset.prem);
    var inTrim = p >= lo && p <= hi;
    var c = r.querySelector('td.trim');
    if (inTrim) {{ keep.push(p); if (c) c.textContent = '\\u2713'; }}
    else {{ r.classList.add('out'); if (c) c.textContent = '\\u2717'; }}
    var cap = parseFloat(r.dataset.cap);
    if (inTrim && cap > 0) {{ capNum += p * cap; capDen += cap; nCap++; }}
  }});
  var mean = keep.reduce(function (a, b) {{ return a + b; }}, 0) / keep.length;
  set('median_prem', med.toFixed(4));
  set('prem_trim', keep.length ? mean.toFixed(4) : '—');
  set('prem_cap', capDen > 0 ? (capNum / capDen).toFixed(4) : '—');
  set('n', prem.length); set('ntrim', keep.length); set('ncap', nCap);
  set('lo', lo.toFixed(2)); set('hi', hi.toFixed(2));
}}
function tickAll(i, on) {{
  rowsOf(i).forEach(function (r) {{
    var cb = r.querySelector('input');
    if (cb && !cb.disabled) cb.checked = !!on;
  }});
  recalc(i);
}}
function tickTrim(i) {{
  recalc(i);
  rowsOf(i).forEach(function (r) {{
    var cb = r.querySelector('input');
    if (cb && !cb.disabled && r.classList.contains('out')) cb.checked = false;
  }});
  recalc(i);
}}
function tickCap(i) {{
  rowsOf(i).forEach(function (r) {{
    var cb = r.querySelector('input');
    if (cb && !cb.disabled && !(parseFloat(r.dataset.cap) > 0)) cb.checked = false;
  }});
  recalc(i);
}}
function filt(i) {{
  var q = document.getElementById('f-' + i).value.trim().toUpperCase();
  var parts = q ? q.split(/[\\s,]+/).filter(Boolean) : [];
  rowsOf(i).forEach(function (r) {{
    var sym = r.dataset.sym;
    var show = !parts.length || parts.some(function (p) {{ return sym.indexOf(p) >= 0; }});
    r.classList.toggle('hide', !show);
  }});
}}
document.querySelectorAll('table.full').forEach(function (t) {{
  var ths = Array.prototype.slice.call(t.querySelectorAll('th'));
  var last = -1, asc = false;
  ths.forEach(function (th, i) {{
    if (i === 0) return;                       // cot checkbox khong sap xep
    th.onclick = function () {{
      asc = (last === i) ? !asc : (i === 1);
      last = i;
      var tb = t.tBodies[0];
      var rs = Array.prototype.slice.call(tb.rows);
      rs.sort(function (a, b) {{
        var x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
        var nx = parseFloat(x), ny = parseFloat(y), c;
        if (!isNaN(nx) && !isNaN(ny)) c = nx - ny;
        else c = String(x).localeCompare(String(y));
        return asc ? c : -c;
      }});
      rs.forEach(function (r) {{ tb.appendChild(r); }});
      ths.forEach(function (h) {{
        h.innerHTML = h.innerHTML.replace(/ (\\u25B2|\\u25BC)$/, '');
      }});
      th.innerHTML += asc ? ' \\u25B2' : ' \\u25BC';
    }};
  }});
}});
[0, 1, 2].forEach(recalc);
</script>
</div></body></html>""".format(
    uni=D["universe"], window=D["window"], t0=D["trim"][0], t1=D["trim"][1],
    d0=D["dates"][0], d1=D["dates"][1], d2=D["dates"][2], SECTIONS=SECTIONS)

out = (Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal")
       / "KIEM_TRA_prem.html")
out.write_text(HTML, encoding="utf-8")
print(out)
