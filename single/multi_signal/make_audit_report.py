# -*- coding: utf-8 -*-
"""Bao cao kiem tra doc lap nam duong prem, hai ro, moi ma mot dong."""
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
            "<td class='n wt1' data-v='0'></td>"
            "<td class='n wt2' data-v='0'></td>"
            "<td class='m mm' data-v='0'></td>"
            "<td class='m me' data-v='0'></td>"
            "<td class='m mec' data-v='0'></td>"
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
<div class=box><div class=kpi5>
<div><span class=lab>prem_median</span>
 <span class=val id='o{i}-prem_median'>—</span>
 <span class=lab id='s{i}-prem_median'></span>
 <span class=lab><b id='n{i}-prem_median'>0</b> mã</span></div>
<div><span class=lab>prem_mean <span class=tagn>không cắt</span></span>
 <span class=val id='o{i}-prem_mean'>—</span>
 <span class=lab id='s{i}-prem_mean'></span>
 <span class=lab><b id='n{i}-prem_mean'>0</b> mã</span></div>
<div><span class=lab>prem_mean_cap <span class=tagn>không cắt</span></span>
 <span class=val id='o{i}-prem_mean_cap'>—</span>
 <span class=lab id='s{i}-prem_mean_cap'></span>
 <span class=lab><b id='n{i}-prem_mean_cap'>0</b> mã</span></div>
<div><span class=lab>prem_trim <span class=tagt>cắt 5–95</span></span>
 <span class=val id='o{i}-prem_trim'>—</span>
 <span class=lab id='s{i}-prem_trim'></span>
 <span class=lab><b id='n{i}-prem_trim'>0</b> mã</span></div>
<div><span class=lab>prem_trim_cap <span class=tagt>cắt 5–95</span></span>
 <span class=val id='o{i}-prem_trim_cap'>—</span>
 <span class=lab id='s{i}-prem_trim_cap'></span>
 <span class=lab><b id='n{i}-prem_trim_cap'>0</b> mã</span></div>
<div><span class=lab>vùng cắt 5–95</span>
 <span class=val style='font-size:15px' id='band{i}'>—</span>
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
<th>prem %</th><th>vốn hoá (tỷ)</th><th>tt mean_cap</th><th>tt trim_cap</th>
<th class=cm>median</th><th class=cm>mean</th><th class=cm>mean_cap</th>
<th class=cm>trim</th><th class=cm>trim_cap</th>
<th>ghi chú</th>
</tr></thead><tbody>{body}</tbody></table>
""".format(i=i, date=date, radios=radios, body=body,
           st=st_json.replace("'", "&#39;"))

# Ba cong doc THANG tu config.py chu khong go lai: bieu do ma ve sai cong
# thi no chi con la mot buc tranh dep. Bang "ba cau hinh" ben SO_SANH da muc
# dung kieu nay mot lan roi.
from single.multi_signal import config as _cfg
GATES = [(k, float(getattr(_cfg, k)), c) for k, c in
         (("SELL_MIN_BREADTH", "#f87171"), ("BUY_MAX_BREADTH", "#38bdf8"),
          ("REINVEST_MAX_BREADTH", "#a78bfa"))
         if getattr(_cfg, k, None) is not None]
CRADIOS = "".join(
    "<label><input type=radio name=cb value='{b}' {chk}> {b} "
    "<span class=dim>({n} mã)</span></label>".format(
        b=b, n=D["baskets"][b], chk="checked" if b == DEFAULT else "")
    for b in BK)

HTML = """<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>Kiểm tra độc lập năm đường prem</title><style>
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
.kpi5{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}}
.kpi5 span{{display:block}} .kpi5 .lab{{color:#64748b;font-size:12px}}
.kpi5 .val{{font-size:19px;font-weight:700;line-height:1.25;
 font-variant-numeric:tabular-nums}}
.tagn{{display:inline!important;background:#1e293b;color:#94a3b8;
 border-radius:3px;padding:0 4px;font-size:10px}}
.tagt{{display:inline!important;background:#3b2f14;color:#facc15;
 border-radius:3px;padding:0 4px;font-size:10px}}
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
#chart{{width:100%;height:420px;display:block}}
#chart .grid{{stroke:#1e293b;stroke-width:1}}
#chart .zero{{stroke:#475569;stroke-width:1}}
#chart .gate{{stroke-dasharray:5 4;stroke-width:1}}
#chart .mark{{stroke:#64748b;stroke-dasharray:3 3;stroke-width:1}}
#chart text{{fill:#64748b;font-size:11px;font-family:system-ui,sans-serif}}
#chart .ln{{fill:none;stroke-width:.9;stroke-opacity:.9;
 stroke-linejoin:round}}
#chart .ln.off{{display:none}}
#chart.solo .ln{{stroke-opacity:.12}}
#chart.solo .ln.hi{{stroke-opacity:1;stroke-width:1.7}}
.legend{{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 2px}}
.legend button{{background:#0f172a;border:1px solid #334155;border-radius:5px;
 padding:2px 9px;cursor:pointer;font-size:12px;color:#e2e8f0;
 display:flex;align-items:center;gap:6px}}
.legend button.off{{color:#475569}}
.legend .sw{{width:12px;height:3px;border-radius:2px}}
.legend button.off .sw{{opacity:.25}}
#tip{{position:absolute;background:#0f172a;border:1px solid #334155;
 border-radius:6px;padding:6px 9px;font-size:12px;pointer-events:none;
 display:none;font-variant-numeric:tabular-nums;z-index:5;white-space:nowrap}}
#tip b{{color:#e2e8f0}} #tip .r{{display:flex;gap:8px;justify-content:space-between}}
</style></head><body><div class=wrap>

<h1>Kiểm tra độc lập năm đường prem</h1>
<div class=sub>{nall} mã · cửa sổ median {window} phiên · cắt đuôi {t0}–{t1} ·
tính lại từ giá thô, không đọc bảng breadth_signals</div>
<div class="nav sub">Nhảy tới: <a href='#d0'>{d0}</a><a href='#d1'>{d1}</a>
<a href='#d2'>{d2}</a></div>

<div class=box>
<b>Năm đường, mỗi đường một tập mã riêng — chỗ dễ hiểu nhầm nhất</b>
<div class=note style='margin-top:6px'>
Một mã có thể được tính vào đường này mà bị loại khỏi đường kia. Ba cột
<b>median · trim · cap</b> ở cuối bảng nói rõ từng đường một:<br><br>
<b>median</b> và <b>mean</b> ✓ khi mã đủ {window} phiên, có giao dịch phiên đó,
và nằm trong rổ. Hai đường này không loại bỏ ai.<br>
<b>mean_cap</b> ✓ khi thêm điều kiện có số liệu vốn hoá — vẫn không cắt đuôi.<br>
<b>trim</b> ✓ khi prem nằm trong phân vị 5–95. Mã cực đoan bị loại.<br>
<b>trim_cap</b> ✓ khi vừa qua trim vừa có vốn hoá — chặt nhất trong năm đường.<br><br>
Hai cột <b>tt mean_cap</b> và <b>tt trim_cap</b> là tỉ trọng vốn hoá của mã
trong từng đường — hai đường chia cho hai tổng khác nhau nên cùng một mã có hai
tỉ trọng khác nhau. Ô tô vàng là mã chiếm từ 25% trở lên: một mình nó quyết định
đường đó.<br><br>
<b>Đọc theo cặp thì rõ nhất:</b> <code>prem_mean</code> so với
<code>prem_trim</code> cho biết phần cắt đuôi đáng bao nhiêu;
<code>prem_mean_cap</code> so với <code>prem_trim_cap</code> cho biết điều đó ở
phiên bản có trọng số. Chênh lệch chính là mức độ rổ đang bị vài mã cực đoan
kéo đi.<br><br>
<b>VIC ngày 2026-08-04 là ví dụ đúng của chuyện này</b>: prem +702.9%, vốn hoá
1.685.901 tỷ. Nó được tính vào <code>prem_median</code>, <code>prem_mean</code>
và <code>prem_mean_cap</code>, nhưng bị vùng cắt loại khỏi
<code>prem_trim</code> và <code>prem_trim_cap</code>. Ở rổ <code>all</code>, một
mình nó đẩy <code>prem_mean_cap</code> lên <b>221.2</b> trong khi
<code>prem_trim_cap</code> chỉ <b>26.1</b> — đó là toàn bộ ý nghĩa của phần cắt
đuôi, hiện ra thành một con số.
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
<div class=box style='position:relative'>
<b>Năm đường trên cùng một biểu đồ</b>
<div class=note style='margin-top:6px'>Ba ngày ở dưới trả lời “số này có đúng
không”; ba điểm thì không cho thấy <b>hình dạng</b>. Đây là toàn bộ lịch sử của
cả năm đường, đọc thẳng từ bảng <code>breadth_signals</code> — tức đúng con số
mà chiến lược thật sự dùng, chứ không phải bản tính lại.<br>
Ba đường đứt màu xám là ba ngày được kiểm ở dưới. Ba đường ngang là ba cổng
đang chạy trong <code>config.py</code>: bán khi rổ vượt <b>{gs:g}</b>, mua khi rổ
ở hoặc dưới <b>{gb:g}</b>, tái đầu tư khi ở hoặc dưới <b>{gr:g}</b>. Rê chuột để
đọc cả năm giá trị tại một phiên; rê chuột lên <b>tên đường</b> để làm mờ bốn đường kia, bấm để ẩn hẳn.</div>
<div class=basket style='margin-top:10px'>rổ: {cradios}</div>
<div class=legend id=leg></div>
<svg id=chart></svg><div id=tip></div>
</div>

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
    ['mm', 'me', 'mec', 'mt', 'mc'].forEach(function (c) {{
      var td = r.querySelector('td.' + c);
      td.textContent = ''; td.style.color = '';
    }});
    r.querySelector('td.wt1').textContent = '';
    r.querySelector('td.wt2').textContent = '';
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
    ['prem_median', 'prem_mean', 'prem_mean_cap', 'prem_trim',
     'prem_trim_cap'].forEach(function (k) {{
      set('o' + i + '-' + k, '—'); set('n' + i + '-' + k, 0); set('s' + i + '-' + k, '');
    }});
    set('band' + i, '—');
    return;
  }}
  var prem = live.map(function (r) {{ return parseFloat(r.dataset.prem); }});
  var s = prem.slice().sort(function (a, b) {{ return a - b; }});
  var med = pct(s, 50), lo = pct(s, 5), hi = pct(s, 95);
  var keep = [], capNum = 0, capDen = 0, nCap = 0, capRows = [];
  var sum = 0, mcNum = 0, mcDen = 0, nMeanCap = 0, meanCapRows = [];
  var tick = function (td, on) {{
    td.textContent = on ? '\\u2713' : '\\u2717';
    td.style.color = on ? '#4ade80' : '#f87171';
  }};
  live.forEach(function (r) {{
    var p = parseFloat(r.dataset.prem), cap = parseFloat(r.dataset.cap);
    var inTrim = p >= lo && p <= hi, hasCap = cap > 0;
    tick(r.querySelector('td.mm'), true);      // median: moi ma hop le
    tick(r.querySelector('td.me'), true);      // mean: cung vay
    tick(r.querySelector('td.mec'), hasCap);   // mean_cap: chi can co von hoa
    tick(r.querySelector('td.mt'), inTrim);
    var inCap = inTrim && hasCap;
    tick(r.querySelector('td.mc'), inCap);
    sum += p;
    if (hasCap) {{ mcNum += p * cap; mcDen += cap; nMeanCap++;
                   meanCapRows.push([r, cap]); }}
    if (inTrim) keep.push(p);
    if (inCap) {{ capNum += p * cap; capDen += cap; nCap++; capRows.push([r, cap]); }}
  }});
  // HAI TRONG SO, KHONG PHAI MOT. prem_mean_cap va prem_trim_cap chia cho hai
  // tong khac nhau, nen mot ma co hai ti trong khac nhau -- va khoang cach giua
  // chung la thu giai thich vi sao hai duong xa nhau den the. VIC ngay
  // 2026-08-04 nam o cot trai voi ti trong ap dao, con cot phai bo trong vi no
  // da bi vung cat loai.
  meanCapRows.forEach(function (x) {{
    var w = x[1] / mcDen * 100;
    var td = x[0].querySelector('td.wt1');
    td.textContent = w.toFixed(2) + '%';
    if (w >= 25) {{ td.style.color = '#facc15'; td.style.fontWeight = '700'; }}
    else {{ td.style.color = ''; td.style.fontWeight = ''; }}
  }});
  capRows.forEach(function (x) {{
    x[0].querySelector('td.wt2').textContent = (x[1] / capDen * 100).toFixed(2) + '%';
  }});
  var mean = keep.length ? keep.reduce(function (a, b) {{ return a + b; }}, 0) / keep.length : NaN;
  var vals = {{prem_median: med, prem_mean: sum / live.length,
               prem_mean_cap: mcDen > 0 ? mcNum / mcDen : NaN,
               prem_trim: mean,
               prem_trim_cap: capDen > 0 ? capNum / capDen : NaN}};
  var ns = {{prem_median: live.length, prem_mean: live.length,
             prem_mean_cap: nMeanCap, prem_trim: keep.length,
             prem_trim_cap: nCap}};
  ['prem_median', 'prem_mean', 'prem_mean_cap', 'prem_trim',
   'prem_trim_cap'].forEach(function (k) {{
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

/* ── Nam duong tren mot bieu do ─────────────────────────────────────────
   SVG tu ve, khong thu vien: trang nay mo bang file:// nen mot CDN se lam
   bieu do trong rong khi may khong co mang, va do la thu duy nhat trong bao
   cao khong the tu kiem chung duoc.                                        */
var SER = {SER}, CDATES = {CDATES}, GATES = {GATES};
var LN = [["prem_median", "#60a5fa"], ["prem_mean", "#f472b6"],
          ["prem_mean_cap", "#fb923c"], ["prem_trim", "#4ade80"],
          ["prem_trim_cap", "#facc15"]];
var CB = '{DEFB}', OFF = {{}};

document.getElementById('leg').innerHTML = LN.map(function (l) {{
  return "<button data-k='" + l[0] + "'><span class=sw style='background:"
       + l[1] + "'></span>" + l[0] + "</button>";
}}).join('');
document.querySelectorAll('#leg button').forEach(function (b) {{
  /* Nam duong bam sat nhau gan het lich su, nen chi lam mong thoi khong du:
     re chuot len ten duong la mo han bon duong con lai. */
  b.onmouseenter = function () {{
    var c = document.getElementById('chart');
    c.classList.add('solo');
    c.querySelectorAll('path.ln').forEach(function (p) {{
      p.classList.toggle('hi', p.dataset.k === b.dataset.k); }});
  }};
  b.onmouseleave = function () {{
    document.getElementById('chart').classList.remove('solo'); }};
  b.onclick = function () {{
    OFF[b.dataset.k] = !OFF[b.dataset.k];
    b.classList.toggle('off', !!OFF[b.dataset.k]);
    drawChart();
  }};
}});
document.querySelectorAll("input[name=cb]").forEach(function (r) {{
  r.onchange = function () {{ CB = r.value; drawChart(); }};
}});

var CX = null;   /* toa do de tra ve khi re chuot */

function drawChart() {{
  var svg = document.getElementById('chart'), S = SER[CB];
  var W = svg.clientWidth || 1100, H = 420, L = 46, R = 12, T = 12, B = 26;
  var n = S.dates.length, iw = W - L - R, ih = H - T - B;

  var vals = [];
  LN.forEach(function (l) {{
    if (OFF[l[0]]) return;
    (S.lines[l[0]] || []).forEach(function (v) {{ if (v !== null) vals.push(v); }});
  }});
  GATES.forEach(function (g) {{ vals.push(g[1]); }});
  if (!vals.length) vals = [0, 1];
  var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;

  var X = function (i) {{ return L + (n < 2 ? 0 : i * iw / (n - 1)); }};
  var Y = function (v) {{ return T + ih - (v - lo) / (hi - lo) * ih; }};
  CX = {{X: X, Y: Y, n: n, L: L, iw: iw}};

  var o = '';
  /* luoi ngang + nhan truc y */
  var step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 5)));
  [1, 2, 5, 10].some(function (m) {{
    if ((hi - lo) / (step * m) <= 7) {{ step *= m; return true; }} }});
  for (var v = Math.ceil(lo / step) * step; v <= hi; v += step) {{
    o += "<line class=grid x1='" + L + "' x2='" + (W - R) + "' y1='" + Y(v).toFixed(1)
       + "' y2='" + Y(v).toFixed(1) + "'/>"
       + "<text x='" + (L - 6) + "' y='" + (Y(v) + 4).toFixed(1)
       + "' text-anchor=end>" + Math.round(v) + "</text>";
  }}
  if (lo < 0 && hi > 0)
    o += "<line class=zero x1='" + L + "' x2='" + (W - R)
       + "' y1='" + Y(0).toFixed(1) + "' y2='" + Y(0).toFixed(1) + "'/>";

  /* ba cong dang chay */
  GATES.forEach(function (g) {{
    if (g[1] < lo || g[1] > hi) return;
    o += "<line class=gate stroke='" + g[2] + "' x1='" + L + "' x2='" + (W - R)
       + "' y1='" + Y(g[1]).toFixed(1) + "' y2='" + Y(g[1]).toFixed(1) + "'/>"
       + "<rect x='" + (W - R - 118) + "' y='" + (Y(g[1]) - 16).toFixed(1)
       + "' width='116' height='14' fill='#0b1220' rx='3'/>"
       + "<text x='" + (W - R - 3) + "' y='" + (Y(g[1]) - 5).toFixed(1)
       + "' text-anchor=end fill='" + g[2] + "'>" + g[0] + " " + g[1] + "</text>";
  }});

  /* ba ngay duoc kiem o duoi */
  CDATES.forEach(function (d) {{
    var i = S.dates.indexOf(d);
    if (i < 0) return;
    o += "<line class=mark x1='" + X(i).toFixed(1) + "' x2='" + X(i).toFixed(1)
       + "' y1='" + T + "' y2='" + (T + ih) + "'/>"
       + "<text x='" + (X(i) + (X(i) > W - R - 70 ? -4 : 4)).toFixed(1)
       + "' y='" + (T + 11) + "' text-anchor='"
       + (X(i) > W - R - 70 ? 'end' : 'start') + "'>" + d + "</text>";
  }});

  /* Nhan cong ve SAU cac duong, con net ke thi ve TRUOC: nguoc lai thi mot
     doan du lieu day dac se xoa mat chu, va cai bien mat chinh la nguong. */
  var gateLabels = o.match(/<rect[^>]*\/><text[^>]*<\/text>/g) || [];
  gateLabels.forEach(function (t) {{ o = o.replace(t, ''); }});

  /* nam duong */
  LN.forEach(function (l) {{
    if (OFF[l[0]]) return;
    var a = S.lines[l[0]] || [], d = '', up = true;
    for (var i = 0; i < a.length; i++) {{
      if (a[i] === null) {{ up = true; continue; }}
      d += (up ? 'M' : 'L') + X(i).toFixed(1) + ' ' + Y(a[i]).toFixed(1) + ' ';
      up = false;
    }}
    o += "<path class=ln data-k='" + l[0] + "' stroke='" + l[1]
       + "' d='" + d + "'/>";
  }});

  /* nhan truc x: mot moc moi nam */
  var seen = {{}};
  S.dates.forEach(function (d, i) {{
    var y = d.slice(0, 4);
    if (seen[y] || i === 0) {{ seen[y] = 1; return; }}
    seen[y] = 1;
    o += "<text x='" + X(i).toFixed(1) + "' y='" + (H - 8) + "' text-anchor=middle>"
       + y + "</text>";
  }});
  o += gateLabels.join('');
  o += "<line class=cross stroke='#94a3b8' stroke-dasharray='2 3' y1='" + T
     + "' y2='" + (T + ih) + "' x1='-9' x2='-9' id='cross'/>";
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.innerHTML = o;
}}

document.getElementById('chart').addEventListener('mousemove', function (e) {{
  if (!CX) return;
  var svg = this, b = svg.getBoundingClientRect(), tip = document.getElementById('tip');
  var sc = (svg.viewBox.baseVal.width || b.width) / b.width;
  var x = (e.clientX - b.left) * sc;
  var i = Math.round((x - CX.L) / (CX.iw || 1) * (CX.n - 1));
  if (i < 0 || i >= CX.n) {{ tip.style.display = 'none'; return; }}
  var S = SER[CB], cr = svg.querySelector('#cross');
  if (cr) {{ cr.setAttribute('x1', CX.X(i)); cr.setAttribute('x2', CX.X(i)); }}
  var h = "<b>" + S.dates[i] + "</b>";
  LN.forEach(function (l) {{
    if (OFF[l[0]]) return;
    var v = (S.lines[l[0]] || [])[i];
    h += "<div class=r><span style='color:" + l[1] + "'>" + l[0] + "</span>"
       + "<b>" + (v === null || v === undefined ? '—' : v.toFixed(2)) + "</b></div>";
  }});
  tip.innerHTML = h;
  tip.style.display = 'block';
  var box = svg.parentNode.getBoundingClientRect();
  var lx = e.clientX - box.left + 14;
  if (lx + tip.offsetWidth > box.width) lx = e.clientX - box.left - tip.offsetWidth - 14;
  tip.style.left = lx + 'px';
  tip.style.top = (e.clientY - box.top + 12) + 'px';
}});
document.getElementById('chart').addEventListener('mouseleave', function () {{
  document.getElementById('tip').style.display = 'none';
}});
window.addEventListener('resize', drawChart);
drawChart();

[0, 1, 2].forEach(setBasket);
</script>
</div></body></html>""".format(
    nall=D["baskets"]["all"], nex=D["baskets"]["all-VIC-VIX"],
    window=D["window"], t0=D["trim"][0], t1=D["trim"][1],
    d0=D["dates"][0], d1=D["dates"][1], d2=D["dates"][2], SECTIONS=SECTIONS,
    cradios=CRADIOS, DEFB=DEFAULT,
    gs=dict((g[0], g[1]) for g in GATES).get("SELL_MIN_BREADTH", 0),
    gb=dict((g[0], g[1]) for g in GATES).get("BUY_MAX_BREADTH", 0),
    gr=dict((g[0], g[1]) for g in GATES).get("REINVEST_MAX_BREADTH", 0),
    SER=json.dumps(D["series"], separators=(",", ":")),
    CDATES=json.dumps(D["dates"]),
    GATES=json.dumps([[g[0].replace("_BREADTH", ""), g[1], g[2]] for g in GATES]))

out = (Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal")
       / "KIEM_TRA_prem.html")
out.write_text(HTML, encoding="utf-8")
print(out)
