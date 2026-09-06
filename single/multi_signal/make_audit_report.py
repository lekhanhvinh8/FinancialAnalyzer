# -*- coding: utf-8 -*-
"""Bao cao kiem tra doc lap ba duong prem, hai ro, moi ma mot dong."""
import json
from pathlib import Path

S = Path(__file__).parent
D = json.load(open(S / "audit2.json", encoding="utf-8"))
BK = list(D["baskets"])          # ["all", "all-VIC-VIX"]
DEFAULT = "all-VIC-VIX"

SECTIONS = ""
for i, date in enumerate(D["dates"]):
    sec = D["sections"][date]

    radios = "".join(
        "<label><input type=radio name='b{i}' value='{b}' {chk} "
        "onchange='setBasket({i})'> {b} <span class=dim>({n} mã)</span></label>"
        .format(i=i, b=b, n=D["baskets"][b], chk="checked" if b == DEFAULT else "")
        for b in BK)

    st_json = json.dumps(sec["stored"], ensure_ascii=False)

    body = ""
    for r in sec["rows"]:
        inb = json.dumps(r["in"], ensure_ascii=False)
        body += (
            "<tr data-sym='{sym}' data-prem='{prem}' data-cap='{cap}' "
            "data-ok='{ok}' data-in='{inb}'>"
            "<td><input type=checkbox onchange='recalc({i})'></td>"
            "<td data-v='{sym}'><b>{sym}</b></td>"
            "<td class=n data-v='{bars}'>{bars:,}</td>"
            "<td class=n data-v='{close}'>{close}</td>"
            "<td class=n data-v='{med}'>{med}</td>"
            "<td class=n data-v='{prem}' style='color:{pc}'>{premtxt}</td>"
            "<td class=n data-v='{cap}'>{captxt}</td>"
            "<td class='n wt' data-v='0'></td>"
            "<td class='m mm' data-v='0'></td>"
            "<td class='m mt' data-v='0'></td>"
            "<td class='m mc' data-v='0'></td>"
            "<td class='s why' data-v='{why}' data-base='{why}'>{why}</td>"
            "</tr>".format(
                i=i, sym=r["sym"], inb=inb.replace("'", "&#39;"),
                ok=1 if r["ok"] else 0, bars=r["bars"],
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
<div class=basket>rổ: {radios}</div>
<div class=box><div class=kpi>
<div><span class=lab>median_prem</span>
 <span class=val id='o{i}-median_prem'>—</span>
 <span class=lab id='s{i}-median_prem'></span>
 <span class=lab><b id='n{i}-median_prem'>0</b> mã tham gia</span></div>
<div><span class=lab>prem_trim</span>
 <span class=val id='o{i}-prem_trim'>—</span>
 <span class=lab id='s{i}-prem_trim'></span>
 <span class=lab><b id='n{i}-prem_trim'>0</b> mã tham gia</span></div>
<div><span class=lab>prem_cap</span>
 <span class=val id='o{i}-prem_cap'>—</span>
 <span class=lab id='s{i}-prem_cap'></span>
 <span class=lab><b id='n{i}-prem_cap'>0</b> mã tham gia</span></div>
<div><span class=lab>vùng cắt 5–95</span>
 <span class=val style='font-size:16px' id='band{i}'>—</span>
 <span class=lab>tính trên các mã đang tick</span></div>
</div></div>

<div class=ctl>
<label>lọc mã <input id='f{i}' oninput='filt({i})' placeholder='vd: VIC, VN'></label>
<button onclick='tickAll({i},1)'>tick tất cả</button>
<button onclick='setBasket({i})'>về đúng rổ đã chọn</button>
<button onclick='tickAll({i},0)'>bỏ tick tất cả</button>
<span class=hint>bấm tiêu đề cột để sắp xếp</span>
</div>

<table class=full id='t{i}' data-stored='{st}'><thead><tr>
<th></th><th>mã</th><th>số phiên</th><th>giá</th><th>median 1000</th>
<th>prem %</th><th>vốn hoá (tỷ)</th><th>trọng số</th>
<th class=cm>median</th><th class=cm>trim</th><th class=cm>cap</th>
<th>ghi chú</th>
</tr></thead><tbody>{body}</tbody></table>
""".format(i=i, date=date, radios=radios, body=body,
           st=st_json.replace("'", "&#39;"))

HTML = """<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>Kiểm tra độc lập ba đường prem</title><style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;
 margin:0;padding:26px;line-height:1.6}}
.wrap{{max-width:1180px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:18px;margin:36px 0 8px;border-bottom:1px solid #1e293b;
 padding-bottom:6px;color:#facc15}}
.sub{{color:#64748b;font-size:13px;margin-bottom:16px}}
.note{{color:#94a3b8;font-size:13px;max-width:980px}}
.box{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:14px 18px;margin:10px 0}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}}
.kpi span{{display:block}} .kpi .lab{{color:#64748b;font-size:12px}}
.kpi .val{{font-size:21px;font-weight:700;line-height:1.25;
 font-variant-numeric:tabular-nums}}
.basket{{margin:10px 0;font-size:13px;color:#94a3b8}}
.basket label{{margin-right:18px;cursor:pointer}}
.dim{{color:#64748b}}
table.full{{border-collapse:collapse;font-size:12.5px;width:100%;margin:8px 0}}
table.full th,table.full td{{border:1px solid #1e293b;padding:3px 8px}}
table.full th{{background:#111c30;color:#94a3b8;text-align:right;cursor:pointer}}
table.full th.cm{{text-align:center;color:#cbd5e1}}
table.full th:first-child,table.full th:nth-child(2){{text-align:left}}
table.full td:nth-child(2){{text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td.m{{text-align:center;font-weight:700}}
td.s{{color:#64748b;font-size:11.5px}}
tr.outb{{opacity:.35}} tr.hide{{display:none}}
tr.noteligible td{{color:#475569}}
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
<div class=sub>{nall} mã · cửa sổ median {window} phiên · cắt đuôi {t0}–{t1} ·
tính lại từ giá thô, không đọc bảng breadth_signals</div>
<div class="nav sub">Nhảy tới: <a href='#d0'>{d0}</a><a href='#d1'>{d1}</a>
<a href='#d2'>{d2}</a></div>

<div class=box>
<b>Mỗi đường có một tập mã riêng — đó là chỗ dễ hiểu nhầm nhất</b>
<div class=note style='margin-top:6px'>
Một mã có thể được tính vào đường này mà bị loại khỏi đường kia. Ba cột
<b>median · trim · cap</b> ở cuối bảng nói rõ từng đường một:<br><br>
<b>median</b> ✓ khi mã đủ {window} phiên, có giao dịch phiên đó, và nằm trong rổ.
Trung vị không quan tâm mã đó lệch bao nhiêu.<br>
<b>trim</b> ✓ khi thêm điều kiện prem nằm trong phân vị 5–95. Mã cực đoan bị
loại khỏi riêng đường này.<br>
<b>cap</b> ✓ khi vừa qua được trim vừa có số liệu vốn hoá.<br><br>
<b>VIC ngày 2026-08-04 là ví dụ đúng của chuyện này</b>: prem +702.9% nên nó
được tính vào <code>median_prem</code> nhưng bị vùng cắt loại khỏi
<code>prem_trim</code> và <code>prem_cap</code> — bản trước của báo cáo gộp cả
ba vào một cột nên không thể hiện được.
</div></div>

<div class=box>
<b>Hai rổ</b>
<div class=note style='margin-top:6px'>
<code>all</code> là toàn bộ {nall} mã. <code>all-VIC-VIX</code> là {nex} mã,
bỏ VIC và VIX — đây là rổ mà mọi số liệu trong CONCLUSIONS.md được đo trên, nên
nó là mặc định của trang này.<br><br>
<b>Dấu tick nghĩa là “mã này nằm trong rổ đang đo”, không phải “mã này tồn
tại”.</b> Nên ở rổ mặc định, VIC và VIX là dòng đầy đủ với giá, median, prem,
vốn hoá — nhưng <b>không được tick</b>, ba cột median/trim/cap bỏ trống, và cột
ghi chú nói rõ <i>không thuộc rổ all-VIC-VIX</i>. Bấm <code>all</code> để đưa
chúng vào và xem ba con số đổi thế nào.<br>
Bạn cũng có thể tick tay một mã ngoài rổ — khi đó ghi chú đổi thành “ngoài rổ,
bạn đã tick thêm”, để con số hiện ra không bị nhầm là con số của rổ chuẩn.
</div></div>

<div class=box>
<b>Cách dùng</b>
<div class=note style='margin-top:6px'>Bỏ tick một mã là nó rời khỏi rổ và cả ba
con số tính lại ngay. <b>Phân vị 5–95 cũng tính lại</b> trên tập còn lại — giữ
nguyên vùng cắt cũ sẽ ra một con số không trả lời câu hỏi nào.<br>
Dòng “đã lưu” là giá trị trong bảng <code>breadth_signals</code> của đúng rổ
đang chọn. Khi tick đúng cả rổ, ba con số phải khớp.</div></div>
{SECTIONS}

<script>
function rowsOf(i) {{
  return Array.prototype.slice.call(document.querySelectorAll('#t' + i + ' tbody tr'));
}}
function basketOf(i) {{
  var r = document.querySelector("input[name='b" + i + "']:checked");
  return r ? r.value : null;
}}
function pct(sorted, q) {{
  if (!sorted.length) return NaN;
  var pos = (sorted.length - 1) * q / 100;
  var lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}}
function setBasket(i) {{
  var b = basketOf(i);
  rowsOf(i).forEach(function (r) {{
    var inb = JSON.parse(r.dataset.in);
    r.querySelector('input').checked = !!inb[b];
  }});
  recalc(i);
}}
function recalc(i) {{
  var basket = basketOf(i);
  var stored = JSON.parse(document.getElementById('t' + i).dataset.stored)[basket] || {{}};
  var live = [];
  rowsOf(i).forEach(function (r) {{
    var on = r.querySelector('input').checked;
    r.classList.toggle('outb', !on);
    r.classList.toggle('noteligible', r.dataset.ok !== '1');
    ['mm', 'mt', 'mc'].forEach(function (c) {{
      var td = r.querySelector('td.' + c);
      td.textContent = ''; td.style.color = '';
    }});
    r.querySelector('td.wt').textContent = '';
    // MOT DONG KHONG DUOC TINH PHAI NOI RA VI SAO. Truoc day o ghi chu cua VIC
    // chi hien "—" trong khi dong bi lam mo va ba cot bo trong -- doc nhu the
    // la "ma nay khong lien quan", chu khong phai "ro ban dang chon khong co
    // no".
    var why = r.querySelector('td.why');
    var inb = JSON.parse(r.dataset.in);
    if (r.dataset.ok !== '1') {{
      why.textContent = why.dataset.base;
      why.style.color = '';
    }} else if (!on) {{
      why.textContent = inb[basket] ? 'bạn đã bỏ tick' : 'không thuộc rổ ' + basket;
      why.style.color = '#facc15';
    }} else if (!inb[basket]) {{
      why.textContent = 'ngoài rổ ' + basket + ', bạn đã tick thêm';
      why.style.color = '#60a5fa';
    }} else {{
      why.textContent = '—';
      why.style.color = '';
    }}
    if (on && r.dataset.ok === '1') live.push(r);
  }});
  var set = function (id, v) {{
    var el = document.getElementById(id); if (el) el.textContent = v;
  }};
  if (!live.length) {{
    ['median_prem', 'prem_trim', 'prem_cap'].forEach(function (k) {{
      set('o' + i + '-' + k, '—'); set('n' + i + '-' + k, 0); set('s' + i + '-' + k, '');
    }});
    set('band' + i, '—');
    return;
  }}
  var prem = live.map(function (r) {{ return parseFloat(r.dataset.prem); }});
  var s = prem.slice().sort(function (a, b) {{ return a - b; }});
  var med = pct(s, 50), lo = pct(s, 5), hi = pct(s, 95);
  var keep = [], capNum = 0, capDen = 0, nCap = 0, capRows = [];
  live.forEach(function (r) {{
    var p = parseFloat(r.dataset.prem), cap = parseFloat(r.dataset.cap);
    var inTrim = p >= lo && p <= hi;
    var mm = r.querySelector('td.mm'), mt = r.querySelector('td.mt'),
        mc = r.querySelector('td.mc');
    mm.textContent = '\\u2713'; mm.style.color = '#4ade80';
    mt.textContent = inTrim ? '\\u2713' : '\\u2717';
    mt.style.color = inTrim ? '#4ade80' : '#f87171';
    var inCap = inTrim && cap > 0;
    mc.textContent = inCap ? '\\u2713' : '\\u2717';
    mc.style.color = inCap ? '#4ade80' : '#f87171';
    if (inTrim) keep.push(p);
    if (inCap) {{ capNum += p * cap; capDen += cap; nCap++; capRows.push([r, cap]); }}
  }});
  capRows.forEach(function (x) {{
    x[0].querySelector('td.wt').textContent = (x[1] / capDen * 100).toFixed(2) + '%';
  }});
  var mean = keep.length ? keep.reduce(function (a, b) {{ return a + b; }}, 0) / keep.length : NaN;
  var vals = {{median_prem: med, prem_trim: mean,
               prem_cap: capDen > 0 ? capNum / capDen : NaN}};
  var ns = {{median_prem: live.length, prem_trim: keep.length, prem_cap: nCap}};
  ['median_prem', 'prem_trim', 'prem_cap'].forEach(function (k) {{
    set('o' + i + '-' + k, isNaN(vals[k]) ? '—' : vals[k].toFixed(4));
    set('n' + i + '-' + k, ns[k]);
    var el = document.getElementById('s' + i + '-' + k);
    if (!el) return;
    if (stored[k] === undefined || stored[k] === null) {{ el.textContent = ''; return; }}
    var same = Math.abs(vals[k] - stored[k]) < 5e-4;
    el.innerHTML = 'đã lưu ' + stored[k] + ' · <b style="color:' +
      (same ? '#4ade80' : '#f87171') + '">' + (same ? 'khớp' : 'LỆCH') + '</b>';
  }});
  set('band' + i, lo.toFixed(2) + ' … ' + hi.toFixed(2));
}}
function tickAll(i, on) {{
  rowsOf(i).forEach(function (r) {{ r.querySelector('input').checked = !!on; }});
  recalc(i);
}}
function filt(i) {{
  var q = document.getElementById('f' + i).value.trim().toUpperCase();
  var parts = q ? q.split(/[\\s,]+/).filter(Boolean) : [];
  rowsOf(i).forEach(function (r) {{
    var show = !parts.length || parts.some(function (p) {{
      return r.dataset.sym.indexOf(p) >= 0; }});
    r.classList.toggle('hide', !show);
  }});
}}
document.querySelectorAll('table.full').forEach(function (t) {{
  var ths = Array.prototype.slice.call(t.querySelectorAll('th'));
  var last = -1, asc = false;
  ths.forEach(function (th, i) {{
    if (i === 0) return;
    th.onclick = function () {{
      asc = (last === i) ? !asc : (i === 1);
      last = i;
      var tb = t.tBodies[0];
      var rs = Array.prototype.slice.call(tb.rows);
      rs.sort(function (a, b) {{
        var x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
        if (x === undefined) x = a.cells[i].textContent;
        if (y === undefined) y = b.cells[i].textContent;
        var nx = parseFloat(x), ny = parseFloat(y), c;
        if (!isNaN(nx) && !isNaN(ny)) c = nx - ny;
        else c = String(x).localeCompare(String(y));
        return asc ? c : -c;
      }});
      rs.forEach(function (r) {{ tb.appendChild(r); }});
      ths.forEach(function (h) {{
        h.innerHTML = h.innerHTML.replace(/ (\\u25B2|\\u25BC)$/, ''); }});
      th.innerHTML += asc ? ' \\u25B2' : ' \\u25BC';
    }};
  }});
}});
[0, 1, 2].forEach(setBasket);
</script>
</div></body></html>""".format(
    nall=D["baskets"]["all"], nex=D["baskets"]["all-VIC-VIX"],
    window=D["window"], t0=D["trim"][0], t1=D["trim"][1],
    d0=D["dates"][0], d1=D["dates"][1], d2=D["dates"][2], SECTIONS=SECTIONS)

out = (Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal")
       / "KIEM_TRA_prem.html")
out.write_text(HTML, encoding="utf-8")
print(out)
