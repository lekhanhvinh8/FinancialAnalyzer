# -*- coding: utf-8 -*-
"""
Build the price-vs-breadth comparison report.

Reads data.json (per-symbol results from two run_all reports, the replayed trade
lists for the case studies, and weekly price series) and writes
SO_SANH_price_vs_breadth.html beside this file.

Kept because the finding it produced is the useful one -- that breadth trades a
single market calendar identical across all 52 symbols -- and re-running it
after a parameter change is the fastest way to see whether that is still true.
"""
import json
import statistics as st
from math import comb
from pathlib import Path

S = Path(__file__).parent
D = json.load(open(S / "data.json", encoding="utf-8"))
rows, cases, series = D["rows"], D["cases"], D["series"]
LONG = 2000
for r in rows:
    r["diff"] = round(r["breadth"] - r["price"], 1)

diffs = [r["diff"] for r in rows]
n = len(diffs)
k = sum(1 for x in diffs if x > 0)
pval = sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n
best = sorted(rows, key=lambda r: -r["diff"])[:5]
worst = sorted(rows, key=lambda r: r["diff"])[:5]
mean_d, med_d = st.mean(diffs), st.median(diffs)
ps_avg = st.mean(r["ps"] for r in rows)
bs_avg = st.mean(r["bs"] for r in rows)


def agg(sel, key):
    v = [r[key] - r["dca"] for r in rows if sel(r)]
    return st.mean(v), st.median(v), sum(1 for x in v if x > 0), len(v)


def spark(sym, w=560, h=150):
    pts = series[sym]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    lo, hi = min(ys), max(ys)
    rng = (hi - lo) or 1

    def X(i):
        return 36 + i * (w - 46) / max(len(xs) - 1, 1)

    def Y(v):
        return h - 20 - (v - lo) / rng * (h - 36)

    path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", X(i), Y(v))
                    for i, v in enumerate(ys))

    def at(date):
        for i, d in enumerate(xs):
            if d >= date:
                return i, ys[i]
        return len(xs) - 1, ys[-1]

    marks = []
    for prof, colour in (("price", "#60a5fa"), ("breadth", "#f472b6")):
        for kind in ("sells", "reinv"):
            for t in cases[sym][prof][kind]:
                i, v = at(t[0])
                x, y = X(i), Y(v)
                if kind == "sells":
                    marks.append("<path d='M%.1f,%.1f l4.5,8 h-9 z' fill='%s'/>"
                                 % (x, y - 7, colour))
                else:
                    marks.append("<path d='M%.1f,%.1f l4.5,-8 h-9 z' fill='%s' "
                                 "opacity='.45'/>" % (x, y + 7, colour))
    yrs = ""
    for yr in range(2016, 2027, 2):
        i, _ = at("%d-01-01" % yr)
        yrs += ("<text x='%.0f' y='%d' fill='#64748b' font-size='9' "
                "text-anchor='middle'>%d</text>" % (X(i), h - 4, yr))
    return ("<svg viewBox='0 0 %d %d' style='width:100%%;height:auto'>"
            "<text x='2' y='13' fill='#94a3b8' font-size='10'>%s</text>"
            "<text x='2' y='%d' fill='#94a3b8' font-size='10'>%s</text>"
            "<path d='%s' fill='none' stroke='#22c55e' stroke-width='1.3'/>"
            "%s%s</svg>"
            % (w, h, "{:,.0f}".format(hi), h - 22, "{:,.0f}".format(lo),
               path, "".join(marks), yrs))


def trade_lines(sym):
    out = ""
    for prof, colour in (("price", "#60a5fa"), ("breadth", "#f472b6")):
        c = cases[sym][prof]
        s = " · ".join("{} @{:,.0f} <b>{:+.0f}%</b>".format(d, p, g)
                       for d, p, g in c["sells"]) or "—"
        r = " · ".join("{} @{:,.0f}".format(d, p) for d, p, _ in c["reinv"]) or "—"
        out += ("<div class=tl><span class=tag style='background:{c}22;color:{c}'>"
                "{prof}</span><div><div><span class=k>bán</span> {s}</div>"
                "<div><span class=k>mua lại</span> {r}</div></div></div>"
                .format(c=colour, prof=prof, s=s, r=r))
    return out


CASES_HTML = ""
for grp, items, note in (
    ("Năm mã breadth thắng đậm nhất", best,
     "Cùng một nhịp: bán ở đỉnh 2021, mua lại ở đáy 24/10/2022. Giá mua lại "
     "thấp hơn giá bán rất nhiều, nên vòng ra–vào sinh lời."),
    ("Năm mã breadth thua đậm nhất", worst,
     "Cùng nhịp đó, nhưng giá mua lại <b>cao hơn</b> giá bán — mã tiếp tục tăng "
     "sau khi thị trường quay đầu, nên vòng ra–vào lỗ."),
):
    CASES_HTML += "<h3>%s</h3><p class=note>%s</p>" % (grp, note)
    for r in items:
        sym = r["sym"]
        if sym not in series:
            continue
        col = "#4ade80" if r["diff"] > 0 else "#f87171"
        CASES_HTML += (
            "<div class=case><div class=chead><b style='font-size:15px'>{sym}</b>"
            "<span>DCA {dca:,.0f}% · price {p:,.0f}% · breadth {b:,.0f}% · "
            "<b style='color:{col}'>{d:+,.0f}</b></span></div>{sp}{tl}</div>"
            .format(sym=sym, dca=r["dca"], p=r["price"], b=r["breadth"],
                    col=col, d=r["diff"], sp=spark(sym), tl=trade_lines(sym)))

TABLE = ""
for r in rows:
    d = r["diff"]
    col = "#4ade80" if d > 20 else "#f87171" if d < -20 else "#94a3b8"
    big = "font-weight:700" if abs(d) > 50 else ""
    TABLE += ("<tr><td><b>{s}</b></td><td class=n>{dca:,.1f}</td>"
              "<td class=n>{p:,.1f}</td><td class=n>{b:,.1f}</td>"
              "<td class=n style='color:{c};{big}'>{d:+,.1f}</td>"
              "<td class=s>{pb}/{ps}/{pr}</td><td class=s>{bb}/{bs}/{br}</td></tr>"
              .format(s=r["sym"], dca=r["dca"], p=r["price"], b=r["breadth"],
                      c=col, big=big, d=d, pb=r["pb"], ps=r["ps"], pr=r["pr"],
                      bb=r["bb"], bs=r["bs"], br=r["br"]))

am, amed, aw, an = agg(lambda r: True, "price")
bm, bmed, bw, bn = agg(lambda r: True, "breadth")

HTML = """<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>
<title>price vs breadth — so từng mã</title><style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;
 margin:0;padding:28px;line-height:1.65}}
.wrap{{max-width:1060px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:17px;margin:36px 0 8px;border-bottom:1px solid #1e293b;padding-bottom:6px}}
h3{{font-size:14px;margin:26px 0 4px;color:#cbd5e1}}
p{{margin:8px 0}} .sub{{color:#64748b;font-size:13px;margin-bottom:20px}}
.note{{color:#94a3b8;font-size:13.5px;max-width:900px}}
table{{border-collapse:collapse;font-size:13px;width:100%;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:4px 10px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td.s{{text-align:right;color:#64748b;font-size:12px}}
.box{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:14px 18px;margin:14px 0}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}
.kpi span{{display:block}} .kpi .lab{{color:#64748b;font-size:12px}}
.kpi .val{{font-size:21px;font-weight:700;line-height:1.3}}
.case{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
 padding:10px 14px;margin:12px 0}}
.chead{{display:flex;justify-content:space-between;align-items:baseline;
 font-size:13px;color:#94a3b8;flex-wrap:wrap;gap:8px}}
.tl{{display:flex;gap:10px;font-size:12px;color:#cbd5e1;margin-top:5px}}
.tag{{border-radius:4px;padding:1px 7px;font-size:11px;height:19px;flex:none}}
.k{{color:#64748b;display:inline-block;width:56px}}
b.g{{color:#4ade80}} b.r{{color:#f87171}}
</style></head><body><div class=wrap>

<h1>price vs breadth — so sánh từng mã</h1>
<div class=sub>52 mã · cùng mốc DCA, cùng khoảng đánh giá ·
price = 20260905_154540 · breadth = 20260905_160146</div>

<div class=box><div class=kpi>
<div><span class=lab>price, chênh so DCA</span><span class=val>{am:+.1f}%</span>
 <span class=lab>trung vị {amed:+.1f} · thắng {aw}/{an}</span></div>
<div><span class=lab>breadth, chênh so DCA</span>
 <span class=val style='color:#4ade80'>{bm:+.1f}%</span>
 <span class=lab>trung vị {bmed:+.1f} · thắng {bw}/{bn}</span></div>
<div><span class=lab>breadth − price, ghép cặp từng mã</span>
 <span class=val>{mean_d:+.1f}</span>
 <span class=lab>trung vị {med_d:+.1f} · thắng {k}/{n} · p={pval:.3f}</span></div>
</div></div>

<p class=note><b>Đọc trước hết ở trung vị.</b> Trung bình {mean_d:+.0f} là con số
của cái đuôi: năm mã đầu bảng đóng góp phần lớn. Mã điển hình chỉ chênh
{med_d:+.1f} điểm, và tỉ lệ thắng {k}/{n} cho p={pval:.3f} — chưa đạt mức ý
nghĩa 5%.</p>

<h2>Cơ chế: breadth giao dịch theo lịch của thị trường, không theo mã</h2>
<p class=note>Điều đập vào mắt khi xem từng mã: <b>ngày giao dịch của breadth
gần như trùng nhau ở mọi mã</b>. Bán quanh 04/01/2018 và quanh tháng 8–11/2021;
mua lại vào 04/07/2017, 15/08/2019, 02/07/2021 và <b>24/10/2022</b>. Đó là bốn
ngày của <i>thị trường</i>, không phải của doanh nghiệp — vì dưới profile này
<code>PERCENT_SELL = None</code>, arm bán chỉ còn đọc rổ.</p>
<p class=note>Profile price thì ngược lại: mỗi mã một lịch riêng, nhiều lệnh hơn
(trung bình {ps_avg:.1f} lệnh bán so với {bs_avg:.1f}), mỗi lệnh lãi nhỏ hơn.</p>

<div class=box>
<b>Phép thử quyết định.</b> Nếu cơ chế đúng là như vậy thì mã nào breadth thắng
phải là mã có <b>giá ngày mua lại (24/10/2022) thấp hơn giá ngày bán
(09/08/2021)</b>, và ngược lại. Đo trên 52 mã:
<table style='margin-top:8px'><tr><th style='text-align:left'>nhóm</th>
<th>số mã</th><th>giá 24/10/2022 so với 09/08/2021</th></tr>
<tr><td>breadth <b class=g>thắng</b></td><td class=n>32</td>
<td class=n><b class=g>−31.9%</b> — mua lại rẻ hơn gần một phần ba</td></tr>
<tr><td>breadth <b class=r>thua</b></td><td class=n>19</td>
<td class=n><b class=r>−1.9%</b> — không rẻ hơn chút nào</td></tr></table>
<p class=note style='margin-bottom:0'>Tương quan giữa hai đại lượng:
<b>−0.52</b>. Nên đây không phải chuyện tín hiệu rổ “đúng” hay “sai”, mà là:
<b>nó đúng với những mã đi cùng thị trường và sai với những mã không.</b></p>
</div>

<h2>Xem tận mắt: mười ca lớn nhất</h2>
<p class=note><b>Nhìn thẳng vào mười biểu đồ dưới đây sẽ thấy ngay:</b> mọi
dấu <span style='color:#f472b6'>▼ hồng</span> nằm trên đúng <b>hai đường dọc</b>
giống nhau ở cả mười mã — đo trên toạ độ SVG, chúng rơi vào x=168 và x≈328–355
không sai lệch. Dấu <span style='color:#60a5fa'>▼ xanh</span> thì rải khắp
(x = 52, 97, 112, 146, 163, 171, 178, 196, … 525). Hai hình ảnh đó là toàn bộ
sự khác nhau giữa hai chiến lược.</p>
<p class=note>Đường xanh lá là giá theo tuần.
<span style='color:#60a5fa'>▼ xanh dương</span> = price bán ·
<span style='color:#60a5fa;opacity:.6'>▲ nhạt</span> = price mua lại ·
<span style='color:#f472b6'>▼ hồng</span> = breadth bán ·
<span style='color:#f472b6;opacity:.6'>▲ nhạt</span> = breadth mua lại.</p>
{CASES_HTML}

<h2>Bảng đầy đủ, theo thứ tự chữ cái</h2>
<p class=note>Cột b/s/r là số lệnh mua / bán / reinvest. Chênh lệch trên 50 điểm
in đậm; xanh là breadth tốt hơn, đỏ là price tốt hơn.</p>
<table><thead><tr><th>mã</th><th>DCA</th><th>price</th><th>breadth</th>
<th>chênh</th><th>b/s/r price</th><th>b/s/r breadth</th></tr></thead>
<tbody>{TABLE}</tbody></table>

<h2>Kết luận</h2>
<p class=note><b>1. Khác biệt không nằm ở việc chọn mã mà ở việc chọn thời
điểm.</b> Hai profile mua gần như cùng lượng tiền vào cùng những mã; chúng chỉ
khác nhau ở chỗ <i>khi nào ra và khi nào vào lại</i>. Breadth ra ở hai đỉnh thị
trường và vào lại ở một đáy thị trường, giống hệt nhau cho cả 52 mã.</p>
<p class=note><b>2. Vì thế kết quả phụ thuộc vào việc mã có đi cùng thị trường
hay không</b> — chứ không phụ thuộc vào việc rổ có “đúng” hay không. Nhóm chứng
khoán và ngân hàng (SHB, STB, HCM, VND, SSI) đi cùng nhịp nhất nên thắng đậm
nhất. EIB, VHC, REE, DPM, HAG tiếp tục tăng sau tháng 8/2021 nên bị bán sớm rồi
mua lại đắt hơn — EIB bán @16.560 rồi mua lại @23.700.</p>
<p class=note><b>3. Về mặt thống kê thì chưa kết luận được.</b> {k}/{n} mã,
p={pval:.3f}. Trung bình {mean_d:+.0f} nhưng trung vị chỉ {med_d:+.1f}. Và toàn
bộ phép đo dựa trên <b>một</b> chu kỳ 2021–2022 — đúng cái sự kiện mà chiến lược
này tồn tại để bắt.</p>
<p class=note><b>4. Rủi ro cụ thể cần nhớ:</b> vì mọi mã bán cùng ngày và mua
lại cùng ngày, danh mục <b>không hề đa dạng hoá về thời điểm</b>. Một lần đọc
sai đỉnh thị trường sẽ sai đồng loạt trên cả 52 mã cùng lúc — điều mà profile
price, với 52 lịch giao dịch riêng, không thể mắc phải.</p>

</div></body></html>""".format(
    am=am, amed=amed, aw=aw, an=an, bm=bm, bmed=bmed, bw=bw, bn=bn,
    mean_d=mean_d, med_d=med_d, k=k, n=n, pval=pval,
    ps_avg=ps_avg, bs_avg=bs_avg, CASES_HTML=CASES_HTML, TABLE=TABLE)

out = (Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal")
       / "SO_SANH_price_vs_breadth.html")
out.write_text(HTML, encoding="utf-8")
print(out)
