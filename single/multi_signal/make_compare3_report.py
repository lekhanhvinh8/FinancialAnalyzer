# -*- coding: utf-8 -*-
"""
Three-way comparison report: price, breadth, hybrid.

Reads data3.json -- per-symbol results from three run_all reports, the replayed
trade lists (replay_trades.py) and weekly price series -- and writes
SO_SANH_3_cau_hinh.html beside this file.

WHY THE MARKERS SIT IN THREE ROWS rather than on the price line. Drawn on the
line, the three colours overlap exactly on the dates worth looking at, which are
the dates the whole report is about. On separate rows the reader compares by
COLUMN: a column with three marks is where all three agree, a gap in one row is
where that configuration passed.

Triangle = sell, diamond = reinvest, one colour per configuration.
"""
import json
import statistics as st
from math import comb
from pathlib import Path

S = Path(__file__).parent
D = json.load(open(S / "data3.json", encoding="utf-8"))
rows, cases, series = D["rows"], D["cases"], D["series"]

# ten hien thi, khoa trong du lieu, mau
PROFS = [("price", "price", "#60a5fa"),
         ("breadth", "breadth", "#f472b6"),
         ("hybrid", "hybrid", "#facc15")]
# khoa trong cases.json khac khoa trong rows
CASE_KEY = {"price": "price", "breadth": "breadth", "hybrid": "default"}

for r in rows:
    r["spread"] = round(max(r[k] for _, k, _ in PROFS) - min(r[k] for _, k, _ in PROFS), 1)
    r["best"] = max(PROFS, key=lambda p: r[p[1]])[0]

cases_order = sorted((r for r in rows if r["sym"] in series),
                     key=lambda r: -r["spread"])[:10]


def agg(key):
    v = [r[key] - r["dca"] for r in rows]
    return st.mean(v), st.median(v), sum(1 for x in v if x > 0), len(v)


def sign_test(a, b):
    d = [r[a] - r[b] for r in rows]
    n = len(d)
    k = sum(1 for x in d if x > 1e-9)
    dec = sum(1 for x in d if abs(x) > 1e-9)
    p = sum(comb(dec, i) for i in range(k, dec + 1)) / 2 ** dec if dec else 1.0
    return st.mean(d), st.median(d), k, dec, p


def spark(sym, w=620, h=132):
    pts = series[sym]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    lo, hi = min(ys), max(ys)
    rng = (hi - lo) or 1

    def X(i):
        return 38 + i * (w - 48) / max(len(xs) - 1, 1)

    def Y(v):
        return h - 18 - (v - lo) / rng * (h - 34)

    path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", X(i), Y(v))
                    for i, v in enumerate(ys))

    def at(date):
        for i, d in enumerate(xs):
            if d >= date:
                return i, ys[i]
        return len(xs) - 1, ys[-1]

    # Ba profile ve tren ba HANG rieng ngay duoi duong gia. Ve chong len duong
    # gia thi ba mau se de len nhau o dung nhung ngay dang chu y nhat -- ma do
    # lai chinh la thu can nhin ro.
    marks = []
    for row, (lab, key, colour) in enumerate(PROFS):
        yb = 16 + row * 9          # hang danh dau cua profile nay
        c = cases[sym][CASE_KEY[key]]
        for d, _, _ in c["sells"]:              # TAM GIAC = ban
            x = X(at(d)[0])
            marks.append("<path d='M%.1f,%.1f l3.2,5.6 h-6.4 z' fill='%s'/>"
                         % (x, yb, colour))
        for d, _, _ in c["reinv"]:              # THOI = reinvest
            x = X(at(d)[0])
            marks.append("<path d='M%.1f,%.1f l3,3 l-3,3 l-3,-3 z' fill='%s' "
                         "opacity='.75'/>" % (x, yb, colour))
        marks.append("<text x='2' y='%.0f' fill='%s' font-size='7.5'>%s</text>"
                     % (yb + 5, colour, lab))
    yrs = ""
    for yr in range(2016, 2027, 2):
        i, _ = at("%d-01-01" % yr)
        yrs += ("<text x='%.0f' y='%d' fill='#64748b' font-size='8.5' "
                "text-anchor='middle'>%d</text>" % (X(i), h - 3, yr))
    return ("<svg viewBox='0 0 %d %d' style='width:100%%;height:auto'>"
            "<text x='2' y='%d' fill='#94a3b8' font-size='9'>%s</text>"
            "<text x='2' y='%d' fill='#94a3b8' font-size='9'>%s</text>"
            "<path d='%s' fill='none' stroke='#22c55e' stroke-width='1.1'/>"
            "%s%s</svg>"
            % (w, h, 52, "{:,.0f}".format(hi), h - 20, "{:,.0f}".format(lo),
               path, "".join(marks), yrs))


def trade_lines(sym):
    out = ""
    for lab, key, colour in PROFS:
        c = cases[sym][CASE_KEY[key]]
        s = " · ".join("{} @{:,.0f} <b>{:+.0f}%</b>".format(d, p, g)
                       for d, p, g in c["sells"]) or "—"
        r = " · ".join("{} @{:,.0f}".format(d, p) for d, p, _ in c["reinv"]) or "—"
        out += ("<div class=tl><span class=tag style='background:{c}22;color:{c}'>"
                "{lab}</span><div><div><span class=k>bán</span> {s}</div>"
                "<div><span class=k>mua lại</span> {r}</div></div></div>"
                .format(c=colour, lab=lab, s=s, r=r))
    return out


CASES_HTML = ""
for r in cases_order:
    sym = r["sym"]
    cells = " · ".join(
        "<span style='color:{c}'>{lab} {v:,.0f}%</span>".format(c=col, lab=lab, v=r[key])
        for lab, key, col in PROFS)
    CASES_HTML += (
        "<div class=case><div class=chead><b style='font-size:15px'>{sym}</b>"
        "<span>DCA {dca:,.0f}% · {cells} · chênh <b>{sp:,.0f}</b></span></div>"
        "{sp2}{tl}</div>".format(sym=sym, dca=r["dca"], cells=cells,
                                 sp=r["spread"], sp2=spark(sym), tl=trade_lines(sym)))

TABLE = ""
for r in rows:
    best = max(PROFS, key=lambda p: r[p[1]])[1]
    tds = ""
    for lab, key, col in PROFS:
        w = "font-weight:700;color:%s" % col if key == best else "color:#e2e8f0"
        tds += "<td class=n style='%s'>%s</td>" % (w, "{:,.1f}".format(r[key]))
    TABLE += ("<tr><td><b>{s}</b></td><td class=n>{dca:,.1f}</td>{tds}"
              "<td class=n style='color:#94a3b8'>{sp:,.1f}</td>"
              "<td class=s>{a}</td><td class=s>{b}</td><td class=s>{c}</td></tr>"
              .format(s=r["sym"], dca=r["dca"], tds=tds, sp=r["spread"],
                      a="%d/%d/%d" % (r["price_b"], r["price_s"], r["price_r"]),
                      b="%d/%d/%d" % (r["breadth_b"], r["breadth_s"], r["breadth_r"]),
                      c="%d/%d/%d" % (r["hybrid_b"], r["hybrid_s"], r["hybrid_r"])))

KPI = ""
for lab, key, col in PROFS:
    m, med, w, n = agg(key)
    KPI += ("<div><span class=lab>{lab}</span>"
            "<span class=val style='color:{c}'>{m:+.1f}%</span>"
            "<span class=lab>trung vị {med:+.1f} · thắng DCA {w}/{n}</span>"
            "<span class=lab>bán {s} · reinvest {r}</span></div>"
            .format(lab=lab, c=col, m=m, med=med, w=w, n=n,
                    s=sum(x[key + "_s"] for x in rows),
                    r=sum(x[key + "_r"] for x in rows)))

PAIRS = ""
for a, b in (("breadth", "price"), ("hybrid", "price"), ("hybrid", "breadth")):
    m, med, k, dec, p = sign_test(a, b)
    col = "#4ade80" if p < 0.05 else "#94a3b8"
    PAIRS += ("<tr><td>{a} − {b}</td><td class=n>{m:+.2f}</td>"
              "<td class=n>{med:+.2f}</td><td class=n>{k}/{dec}</td>"
              "<td class=n style='color:{c}'>{p:.3f}</td></tr>"
              .format(a=a, b=b, m=m, med=med, k=k, dec=dec, p=p, c=col))

wins = {lab: sum(1 for r in rows if r["best"] == lab) for lab, _, _ in PROFS}

HTML = """<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>price vs breadth vs hybrid</title><style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;
 margin:0;padding:28px;line-height:1.65}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:17px;margin:36px 0 8px;border-bottom:1px solid #1e293b;padding-bottom:6px}}
p{{margin:8px 0}} .sub{{color:#64748b;font-size:13px;margin-bottom:18px}}
.note{{color:#94a3b8;font-size:13.5px;max-width:920px}}
table{{border-collapse:collapse;font-size:13px;width:100%;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:4px 9px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td.s{{text-align:right;color:#64748b;font-size:11.5px}}
.box{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:14px 18px;margin:14px 0}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}}
.kpi span{{display:block}} .kpi .lab{{color:#64748b;font-size:12px}}
.kpi .val{{font-size:21px;font-weight:700;line-height:1.25}}
.case{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:10px 14px;margin:12px 0}}
.chead{{display:flex;justify-content:space-between;align-items:baseline;
 font-size:13px;color:#94a3b8;flex-wrap:wrap;gap:8px}}
.tl{{display:flex;gap:10px;font-size:12px;color:#cbd5e1;margin-top:4px}}
.tag{{border-radius:4px;padding:1px 7px;font-size:11px;height:19px;flex:none}}
.k{{color:#64748b;display:inline-block;width:56px}}
.leg{{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:#94a3b8;
 margin:6px 0 14px}}
</style></head><body><div class=wrap>

<h1>price vs breadth vs hybrid — so sánh từng mã</h1>
<div class=sub>52 mã · cùng mốc DCA, cùng khoảng đánh giá<br>
price = 20260905_154540 · breadth = 20260905_160146 · hybrid = 20260905_145624</div>

<div class=box>
<b>Ba cấu hình khác nhau ở chỗ nào</b>
<table style='margin-top:8px'><thead><tr><th style='text-align:left'>cấu hình</th>
<th style='text-align:left'>mua</th><th style='text-align:left'>bán</th>
<th style='text-align:left'>reinvest</th></tr></thead><tbody>
<tr><td style='color:#60a5fa'><b>price</b></td><td>giá &lt; 60</td>
<td>giá &gt; 75</td><td>giá &lt; 10</td></tr>
<tr><td style='color:#f472b6'><b>breadth</b></td><td>rổ ≤ 60</td>
<td>rổ &gt; 70</td><td>rổ ≤ 10</td></tr>
<tr><td style='color:#facc15'><b>hybrid</b></td><td>rổ ≤ 60</td>
<td><b>giá &gt; 75 VÀ rổ &gt; 70</b></td><td>rổ ≤ 10</td></tr>
</tbody></table>
<p class=note style='margin-bottom:0'>hybrid chính là <code>config.py</code> mặc
định hiện tại. Lưu ý ngưỡng giá ở arm bán là <b>75</b> chứ không phải 70 — cả ba
arm còn giữ nguyên các cổng signal1 và signal3.</p>
</div>

<div class=box><div class=kpi>{KPI}</div></div>

<p class=note><b>Ba con số nói ba chuyện khác nhau.</b> breadth cao nhất về
trung bình, hybrid cao nhất về <b>tỉ lệ thắng DCA</b> ({hw}/52), còn price cao
nhất về <b>trung vị</b>. Thêm điều kiện giá vào arm bán cắt số lệnh bán từ 79
xuống 43 — hybrid là cấu hình bán ít nhất trong ba.</p>

<div class=box>
<b>Ghép cặp từng mã</b> — cách so duy nhất hợp lệ giữa hai cấu hình.
<table style='margin-top:8px'><thead><tr><th style='text-align:left'>so sánh</th>
<th>TB</th><th>trung vị</th><th>thắng</th><th>p</th></tr></thead>
<tbody>{PAIRS}</tbody></table>
<p class=note style='margin-bottom:0'><b>breadth − price đạt p = 0.046</b>,
qua được mốc 0.05 — nhưng chỉ vừa đủ, và chỉ khi loại mã hoà (VNDIAMOND) theo
đúng cách kiểm định dấu làm. Nếu đếm cả mã hoà thì 32/52 cho p = 0.063. Một mã
đổi phe là đủ lật kết luận, nên đây là bằng chứng yếu chứ không phải bằng chứng
mạnh. Hai cặp còn lại không đạt: hybrid − price p = 0.080, hybrid − breadth
p = 0.832.<br>Số mã tốt nhất chia cho: price {wp}, breadth {wb}, hybrid {wh}.</p>
</div>

<h2>Xem tận mắt: mười mã chênh lệch lớn nhất</h2>
<div class=leg>
<span>▬ đường xanh lá = giá theo tuần</span>
<span style='color:#60a5fa'>▲ tam giác = bán</span>
<span style='color:#f472b6'>◆ thoi = reinvest</span>
<span>mỗi cấu hình một hàng dấu riêng, một màu riêng</span>
</div>
<p class=note>Ba hàng dấu nằm ngay dưới mép trên, không chồng lên đường giá —
vì ba màu sẽ đè lên nhau đúng ở những ngày đáng chú ý nhất, mà đó lại là chỗ
cần nhìn rõ. Đọc theo <b>cột dọc</b>: nơi cả ba hàng cùng có dấu là nơi ba cấu
hình đồng ý.</p>
{CASES_HTML}

<h2>Bảng đầy đủ, theo thứ tự chữ cái</h2>
<p class=note>Ô in đậm là cấu hình tốt nhất của mã đó. Ba cột cuối là số lệnh
mua/bán/reinvest.</p>
<table><thead><tr><th>mã</th><th>DCA</th>
<th style='color:#60a5fa'>price</th><th style='color:#f472b6'>breadth</th>
<th style='color:#facc15'>hybrid</th><th>chênh</th>
<th>b/s/r price</th><th>b/s/r breadth</th><th>b/s/r hybrid</th>
</tr></thead><tbody>{TABLE}</tbody></table>

<h2>Kết luận</h2>
<p class=note><b>1. hybrid không phải là "tốt hơn cả hai" — nó là bảo thủ hơn
cả hai.</b> Bắt arm bán thoả cả giá lẫn rổ khiến số lệnh bán giảm còn 43, ít
nhất trong ba cấu hình. Hệ quả: tỉ lệ thắng DCA cao nhất (47/52) vì hiếm khi
bán sai, nhưng trung vị thấp nhất ({hmed:+.1f}) vì cũng hiếm khi bán đúng.</p>
<p class=note><b>2. So với breadth, hybrid ăn thua đúng ở chỗ lệnh bán bị
loại là lệnh tốt hay lệnh xấu.</b> Được nhiều nhất: SHB +157, SSI +86, VHC +81,
VND +77. Mất nhiều nhất: STB −130, VCS −118, HPG −107, VN30 −96. Nhìn ba hàng
dấu sẽ thấy ngay — ở những mã hybrid thua, hàng vàng thiếu đúng một tam giác mà
hàng hồng có. Cộng lại thì hai chiều gần triệt tiêu nhau: trung bình −5.63,
trung vị 0.00, 17/39.</p>
<p class=note><b>3. Chỉ một trong ba cặp đạt ý nghĩa, và vừa sát mốc.</b>
breadth hơn price với p = 0.046; hybrid không hơn được cặp nào (0.080 và 0.832).
Số mã "tốt nhất" chia {wp}/{wb}/{wh}. Trên dữ liệu này, chọn giữa breadth và
hybrid là chọn theo <i>tính chất</i> mong muốn — bán nhiều hay ít, chấp nhận sai
nhiều lần nhỏ hay sai ít lần lớn — chứ không phải theo bằng chứng thống kê.</p>
<p class=note><b>4. Cả breadth lẫn hybrid vẫn dùng chung một lịch thị trường.</b>
Ba hàng dấu cho thấy: hàng hồng và hàng vàng luôn thẳng cột với nhau ở cùng vài
ngày, chỉ khác ở chỗ hàng vàng thưa hơn. Nên rủi ro "sai đồng loạt trên cả 52
mã" áp dụng cho cả hai, không riêng breadth.</p>

</div></body></html>""".format(
    KPI=KPI, PAIRS=PAIRS, CASES_HTML=CASES_HTML, TABLE=TABLE,
    hw=agg("hybrid")[2], hmed=agg("hybrid")[1],
    wp=wins["price"], wb=wins["breadth"], wh=wins["hybrid"])

out = (Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal")
       / "SO_SANH_3_cau_hinh.html")
out.write_text(HTML, encoding="utf-8")
print(out)
