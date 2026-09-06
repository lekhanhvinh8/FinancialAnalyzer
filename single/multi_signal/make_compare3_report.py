# -*- coding: utf-8 -*-
"""
Bao cao so sanh ba cau hinh, dung tu ba thu muc run cua run_all.

    python -m single.multi_signal.make_compare3_report \
        20260905_154540 20260905_160146 20260905_145624

Thu tu: price, breadth, hybrid. Moi thu muc la mot lan chay run_all da co
report_all.html. Khong truyen gi thi lay lai data3.json da dung lan truoc.

TU DUNG LAY DU LIEU. Ban dau script nay doc mot data3.json duoc tao boi mot
lenh roi, va lenh do khong bao gio duoc luu -- nen bao cao khong the dung lai
duoc. Gio no tu doc ba report, tu chay lai tung ma de lay danh sach lenh, va tu
lay chuoi gia; data3.json chi con la cache.
"""
import json
import statistics as st
import subprocess
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

S = Path(__file__).parent
CHARTS = S / "charts"
DATA = S / "data3.json"

# Ma dua vao phan "xem tan mat". Chon truoc de khoi phai chay lai ca 52 ma:
# moi ma ton ~15 giay x 3 cau hinh.
CASE_SYMS = ["SHB", "STB", "VND", "HCM", "SSI", "GMD", "LPB", "VCS", "HPG",
             "FPT", "EIB", "REE", "VHC"]


def _all_data(run_dir):
    import re
    p = CHARTS / run_dir / "report_all.html"
    if not p.exists():
        raise SystemExit(f"khong thay {p}")
    m = re.search(r"const ALL_DATA\s*=\s*(\[.*?\]);",
                  p.read_text(encoding="utf-8"), re.S)
    return {r["sym"]: r for r in json.loads(m.group(1))}


def build_data(price_dir, breadth_dir, hybrid_dir):
    """Doc ba report, chay lai cac ma mau, lay chuoi gia -- roi ghi data3.json."""
    import pandas as pd
    import database as db

    R = {"price": _all_data(price_dir), "breadth": _all_data(breadth_dir),
         "hybrid": _all_data(hybrid_dir)}
    syms = sorted(set.intersection(*(set(v) for v in R.values())))
    print(f"  {len(syms)} ma chung tu ba report")

    # Danh sach lenh: chay lai tung ma duoi ca ba cau hinh.
    print(f"  chay lai {len(CASE_SYMS)} ma de lay tung lenh ...", flush=True)
    out = subprocess.run(
        [sys.executable, "-m", "single.multi_signal.replay_trades"] + CASE_SYMS,
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit("replay_trades that bai:\n" + (out.stderr or "")[-2000:])
    cases = json.loads(out.stdout.strip().splitlines()[-1])

    series = {}
    for sym in cases:
        d = db.load_daily_prices(sym)["close"]
        d.index = pd.to_datetime(d.index)
        w = d.resample("W").last().dropna()
        w = w[w.index >= "2015-01-01"]
        series[sym] = [[str(t)[:10], round(float(v), 1)] for t, v in w.items()]

    rows = []
    for s in syms:
        r = {"sym": s, "dca": R["price"][s]["i"], "eb": R["price"][s]["eb"]}
        for k in R:
            r[k] = R[k][s]["m"]
            r[k + "_b"] = R[k][s]["b"]
            r[k + "_s"] = R[k][s]["s"]
            r[k + "_r"] = R[k][s]["r"]
        rows.append(r)

    data = {"rows": rows, "cases": cases, "series": series,
            "dirs": {"price": price_dir, "breadth": breadth_dir,
                     "hybrid": hybrid_dir}}
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  du lieu -> {DATA}")
    return data


if len(sys.argv) == 4:
    D = build_data(*sys.argv[1:])
elif len(sys.argv) == 1:
    if not DATA.exists():
        raise SystemExit(
            "chua co data3.json. Chay:\n"
            "  python -m single.multi_signal.make_compare3_report "
            "<thu-muc-price> <thu-muc-breadth> <thu-muc-hybrid>")
    D = json.load(open(DATA, encoding="utf-8"))
else:
    raise SystemExit("dung: make_compare3_report [price_dir breadth_dir hybrid_dir]")

rows, cases, series = D["rows"], D["cases"], D["series"]
DIRS = D.get("dirs", {})

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

for r in rows:
    r["hb"] = round(r["hybrid"] - r["breadth"], 1)

# data-v tren moi o: gia tri THO de JS sap xep. Sap xep theo text hien thi se
# hong ngay o cot dau tien -- "1,146.2" dung truoc "364.0" theo thu tu chuoi.
TABLE = ""
for r in rows:
    best = max(PROFS, key=lambda p: r[p[1]])[1]
    tds = ""
    for lab, key, col in PROFS:
        w = "font-weight:700;color:%s" % col if key == best else "color:#e2e8f0"
        tds += ("<td class=n data-v='%s' style='%s'>%s</td>"
                % (r[key], w, "{:,.1f}".format(r[key])))
    hb = r["hb"]
    hbc = "#4ade80" if hb > 50 else "#f87171" if hb < -50 else "#94a3b8"
    hbw = "font-weight:700" if abs(hb) > 50 else ""
    TABLE += ("<tr><td data-v='{s}'><b>{s}</b></td>"
              "<td class=n data-v='{dca}'>{dca:,.1f}</td>{tds}"
              "<td class=n data-v='{hb}' style='color:{hbc};{hbw}'>{hb:+,.1f}</td>"
              "<td class=n data-v='{sp}' style='color:#94a3b8'>{sp:,.1f}</td>"
              "<td class=s data-v='{ps}'>{a}</td><td class=s data-v='{bs}'>{b}</td>"
              "<td class=s data-v='{hs}'>{c}</td></tr>"
              .format(s=r["sym"], dca=r["dca"], tds=tds, sp=r["spread"],
                      hb=hb, hbc=hbc, hbw=hbw,
                      ps=r["price_s"], bs=r["breadth_s"], hs=r["hybrid_s"],
                      a="%d/%d/%d" % (r["price_b"], r["price_s"], r["price_r"]),
                      b="%d/%d/%d" % (r["breadth_b"], r["breadth_s"], r["breadth_r"]),
                      c="%d/%d/%d" % (r["hybrid_b"], r["hybrid_s"], r["hybrid_r"])))

hbs = sorted(((r["hb"], r["sym"]) for r in rows), reverse=True)
HB_BIG = [(v, sy) for v, sy in hbs if abs(v) > 50]
hb_same = sum(1 for v, _ in hbs if abs(v) <= 1e-9)
hb_mid = sum(1 for v, _ in hbs if 10 < abs(v) <= 50)
hb_pos = sum(v for v, _ in hbs if v > 0)
hb_neg = sum(v for v, _ in hbs if v < 0)
hb_absmean = st.mean(abs(v) for v, _ in hbs)
hb_absmed = st.median(abs(v) for v, _ in hbs)
HB_ROWS = "".join(
    "<tr><td><b>{sy}</b></td><td class=n style='color:{c}'>{v:+,.0f}</td></tr>"
    .format(sy=sy, v=v, c="#4ade80" if v > 0 else "#f87171") for v, sy in HB_BIG)

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

# CAC CON SO TRONG PHAN CHU CUNG SINH TU DU LIEU. Ban dau chung duoc go tay, va
# lan dung lai dau tien voi du lieu moi thi chu van noi "cat tu 79 xuong 43" khi
# so that la 50, va van noi hybrid-price khong dat y nghia khi no da dat. Mot
# bao cao co the tao lai nhung chu thi khong -- day la cung mot loi voi
# data3.json, o mot lop khac.
SELLS = {k: sum(r[k + "_s"] for r in rows) for _, k, _ in PROFS}
BP = sign_test("breadth", "price")
HP = sign_test("hybrid", "price")
HB = sign_test("hybrid", "breadth")
_hb = sorted(((r["hybrid"] - r["breadth"], r["sym"]) for r in rows), reverse=True)
HB_UP = ", ".join("%s %+.0f" % (sy, v) for v, sy in _hb[:4])
HB_DOWN = ", ".join("%s %+.0f" % (sy, v) for v, sy in _hb[-4:][::-1])
_sig = [(a, b, t) for a, b, t in (("breadth", "price", BP), ("hybrid", "price", HP),
                                  ("hybrid", "breadth", HB)) if t[4] < 0.05]
if not _sig:
    SIG_LINE = "Không cặp nào đạt p &lt; 0.05."
else:
    SIG_LINE = ("Đạt p &lt; 0.05: "
                + "; ".join("<b>%s − %s</b> (p = %.3f)" % (a, b, t[4])
                            for a, b, t in _sig)
                + ". Còn lại: "
                + "; ".join("%s − %s p = %.3f" % (a, b, t[4])
                            for a, b, t in (("breadth", "price", BP),
                                            ("hybrid", "price", HP),
                                            ("hybrid", "breadth", HB))
                            if t[4] >= 0.05)
                + ".")

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
<div class=sub>{nsym} mã · cùng mốc DCA, cùng khoảng đánh giá<br>
price = {dp} · breadth = {db} · hybrid = {dh}</div>

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
trung bình, hybrid cao nhất về <b>tỉ lệ thắng DCA</b> ({hw}/{nsym}), còn price
cao nhất về <b>trung vị</b>. Thêm điều kiện giá vào arm bán cắt số lệnh bán từ
{sb} xuống {sh} — hybrid là cấu hình bán ít nhất trong ba.</p>

<div class=box>
<b>Ghép cặp từng mã</b> — cách so duy nhất hợp lệ giữa hai cấu hình.
<table style='margin-top:8px'><thead><tr><th style='text-align:left'>so sánh</th>
<th>TB</th><th>trung vị</th><th>thắng</th><th>p</th></tr></thead>
<tbody>{PAIRS}</tbody></table>
<p class=note style='margin-bottom:0'>{sigline} Các p-value này loại
mã hoà theo đúng cách kiểm định dấu làm; đếm cả mã hoà thì mẫu số là {nsym} và
p lớn hơn. Ở cỡ mẫu này một vài mã đổi phe là đủ lật kết luận, nên đây là bằng
chứng yếu chứ không phải bằng chứng mạnh.<br>Số mã tốt nhất chia cho:
price {wp}, breadth {wb}, hybrid {wh}.</p>
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

<h2>breadth và hybrid khác nhau đến đâu</h2>
<p class=note>Trên tổng thể hai cấu hình gần như không phân biệt được: trung vị
chênh <b>{hbmed:+.2f}</b>, {hbk}/{hbdec}, p = {hbp:.3f}. Nhưng đó là kết quả
của <b>triệt tiêu</b>, không phải của <b>giống nhau</b>.</p>
<div class=box><div class=kpi>
<div><span class=lab>giống hệt nhau</span><span class=val>{hb_same}</span>
 <span class=lab>trên 52 mã</span></div>
<div><span class=lab>lệch 10–50 điểm</span><span class=val>{hb_mid}</span></div>
<div><span class=lab>lệch trên 50 điểm</span>
 <span class=val style='color:#facc15'>{hb_nbig}</span></div>
<div><span class=lab>|chênh| mỗi mã</span><span class=val>{hb_absmean:.1f}</span>
 <span class=lab>trung vị {hb_absmed:.1f}</span></div>
</div></div>
<p class=note>Cộng riêng từng chiều: <b style='color:#4ade80'>+{hb_pos:,.0f}</b>
ở các mã hybrid thắng và <b style='color:#f87171'>{hb_neg:,.0f}</b> ở các mã
hybrid thua, còn lại {hb_tot:+,.0f}. <b>{hb_nbig} mã lệch trên 50 điểm</b> — nên
“chỉ VCS là ngoại lệ” không đúng: VCS chỉ đứng thứ hai từ dưới.</p>
<table style='max-width:330px'><thead><tr><th style='text-align:left'>mã</th>
<th>hybrid − breadth</th></tr></thead><tbody>{HB_ROWS}</tbody></table>
<p class=note><b>Vì sao phải phân biệt hai chuyện này.</b> Nếu hai cấu hình thật
sự giống nhau thì chọn cái nào cũng được. Thực tế chúng khác nhau nhiều ở từng
mã nhưng vừa vặn cân bằng nhau <i>trên đúng 52 mã này</i> — và sự cân bằng đó là
tính chất của <b>mẫu</b>, không phải của chiến lược. Đổi rổ hoặc đổi giai đoạn
thì hai chiều không có lý do gì phải tiếp tục triệt tiêu.</p>

<h2>Bảng đầy đủ</h2>
<p class=note>Mặc định theo thứ tự chữ cái. <b>Bấm tiêu đề cột bất kỳ để sắp
xếp</b>, bấm lần nữa để đảo chiều. Ô in đậm là cấu hình tốt nhất của mã đó; cột
<b>hybrid−breadth</b> in đậm khi lệch quá 50 điểm. Ba cột cuối là số lệnh
mua/bán/reinvest — sắp xếp theo chúng là sắp xếp theo số lệnh bán.</p>
<table id=full><thead><tr><th>mã</th><th>DCA</th>
<th style='color:#60a5fa'>price</th><th style='color:#f472b6'>breadth</th>
<th style='color:#facc15'>hybrid</th><th>hybrid−breadth</th><th>chênh 3 bên</th>
<th>b/s/r price</th><th>b/s/r breadth</th><th>b/s/r hybrid</th>
</tr></thead><tbody>{TABLE}</tbody></table>
<script>
(function () {{
  var tb = document.querySelector('#full tbody');
  var ths = Array.prototype.slice.call(document.querySelectorAll('#full th'));
  var last = -1, asc = false;
  ths.forEach(function (th, i) {{
    th.style.cursor = 'pointer';
    th.title = 'bam de sap xep';
    th.onclick = function () {{
      asc = (last === i) ? !asc : (i === 0);
      last = i;
      var rs = Array.prototype.slice.call(tb.rows);
      rs.sort(function (a, b) {{
        var x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
        var nx = parseFloat(x), ny = parseFloat(y), c;
        if (!isNaN(nx) && !isNaN(ny)) {{ c = nx - ny; }}
        else {{ c = String(x).localeCompare(String(y)); }}
        return asc ? c : -c;
      }});
      rs.forEach(function (r) {{ tb.appendChild(r); }});
      ths.forEach(function (t) {{
        t.innerHTML = t.innerHTML.replace(/ (\u25B2|\u25BC)$/, '');
      }});
      th.innerHTML += asc ? ' \u25B2' : ' \u25BC';
    }};
  }});
}})();
</script>

<h2>Kết luận</h2>
<p class=note><b>1. hybrid không phải là "tốt hơn cả hai" — nó là bảo thủ hơn
cả hai.</b> Bắt arm bán thoả cả giá lẫn rổ khiến số lệnh bán giảm còn {sh}, ít
nhất trong ba cấu hình. Hệ quả: tỉ lệ thắng DCA cao nhất (47/52) vì hiếm khi
bán sai, nhưng trung vị thấp nhất ({hmed:+.1f}) vì cũng hiếm khi bán đúng.</p>
<p class=note><b>2. So với breadth, hybrid ăn thua đúng ở chỗ lệnh bán bị
loại là lệnh tốt hay lệnh xấu.</b> Được nhiều nhất: {hbup}. Mất nhiều nhất:
{hbdown}. Nhìn ba hàng dấu sẽ thấy ngay — ở những mã hybrid thua, hàng vàng
thiếu đúng một tam giác mà hàng hồng có. Cộng lại thì hai chiều gần triệt tiêu
nhau: trung bình {hbmean:+.2f}, trung vị {hbmed:+.2f}, {hbk}/{hbdec}.</p>
<p class=note><b>3. Chỉ một trong ba cặp đạt ý nghĩa, và vừa sát mốc.</b>
breadth − price p = {bpp:.3f}, hybrid − price p = {hpp:.3f}, hybrid − breadth
p = {hbp:.3f}. Số mã "tốt nhất" chia {wp}/{wb}/{wh}. Trên dữ liệu này, chọn giữa
breadth và hybrid là chọn theo <i>tính chất</i> mong muốn — bán nhiều hay ít,
chấp nhận sai nhiều lần nhỏ hay sai ít lần lớn — chứ không phải theo bằng chứng
thống kê.</p>
<p class=note><b>4. Cả breadth lẫn hybrid vẫn dùng chung một lịch thị trường.</b>
Ba hàng dấu cho thấy: hàng hồng và hàng vàng luôn thẳng cột với nhau ở cùng vài
ngày, chỉ khác ở chỗ hàng vàng thưa hơn. Nên rủi ro "sai đồng loạt trên cả 52
mã" áp dụng cho cả hai, không riêng breadth.</p>

</div></body></html>""".format(
    KPI=KPI, PAIRS=PAIRS, CASES_HTML=CASES_HTML, TABLE=TABLE,
    hw=agg("hybrid")[2], hmed=agg("hybrid")[1], nsym=len(rows),
    sb=SELLS["breadth"], sh=SELLS["hybrid"], sigline=SIG_LINE,
    bpp=BP[4], hpp=HP[4], hbp=HB[4], hbmean=HB[0], hbmed=HB[1],
    hbk=HB[2], hbdec=HB[3], hbup=HB_UP, hbdown=HB_DOWN,
    dp=DIRS.get("price", "?"), db=DIRS.get("breadth", "?"),
    dh=DIRS.get("hybrid", "?"),
    wp=wins["price"], wb=wins["breadth"], wh=wins["hybrid"],
    hb_same=hb_same, hb_mid=hb_mid, hb_nbig=len(HB_BIG), hb_absmean=hb_absmean,
    hb_absmed=hb_absmed, hb_pos=hb_pos, hb_neg=hb_neg, hb_tot=hb_pos + hb_neg,
    HB_ROWS=HB_ROWS)

out = S / "SO_SANH_3_cau_hinh.html"
out.write_text(HTML, encoding="utf-8")
print(out)
