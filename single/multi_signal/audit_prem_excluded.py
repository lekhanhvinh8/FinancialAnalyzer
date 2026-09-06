# -*- coding: utf-8 -*-
"""Bo sung muc 'hai ma bi loai khoi ro' vao bao cao kiem tra."""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\projects\Stock_Analyzer\PriceToEarn_v2")

import numpy as np
import database as db
from core.universe import resolve
import syncs.breadth as sb

W, DATES = 1000, ["2018-01-23", "2022-01-04", "2026-08-04"]
base = sorted(resolve(sb.UNIVERSE, sb.EXCLUDE))
plus = sorted(set(base) | set(sb.EXCLUDE))

px, cap = {}, {}
for s in plus:
    d = db.load_daily_prices(s)["close"]
    d.index = [str(i)[:10] for i in d.index]
    px[s] = d
    k = db.load_pe_ratios(s)
    if not k.empty and "total_market_cap" in k:
        k = k["total_market_cap"].dropna()
        k.index = [str(i)[:10] for i in k.index]
        cap[s] = k


def one(s, date):
    h = px[s][px[s].index <= date]
    if len(h) < W or h.index[-1] != date:
        return None
    med = float(h.iloc[-W:].median())
    if not med:
        return None
    c = None
    kk = cap.get(s)
    if kk is not None:
        z = kk[kk.index <= date]
        if len(z):
            c = float(z.iloc[-1]) / 1e9
    return (float(h.iloc[-1]) - med) / med * 100, c


def calc(syms, date):
    prem, w = [], []
    for s in syms:
        r = one(s, date)
        if r is None:
            continue
        prem.append(r[0])
        w.append(np.nan if r[1] is None else r[1])
    p, c = np.asarray(prem), np.asarray(w)
    lo, hi = np.percentile(p, [5, 95])
    m = (p >= lo) & (p <= hi)
    mc = m & ~np.isnan(c)
    return (len(p), float(np.median(p)), float(p[m].mean()),
            float((p[mc] * c[mc]).sum() / c[mc].sum()), float(lo), float(hi))


ROWS = ""
for date in DATES:
    a = calc(base, date)
    b = calc(plus, date)
    det = ""
    for s in sb.EXCLUDE:
        r = one(s, date)
        if r is None:
            det += "<div>{s}: chưa đủ {w} phiên hoặc không giao dịch</div>".format(s=s, w=W)
            continue
        inb = b[4] <= r[0] <= b[5]
        det += ("<div>{s}: prem <b>{p:+.1f}%</b>, vốn hoá {c} tỷ — "
                "<b style='color:{col}'>{txt}</b></div>".format(
                    s=s, p=r[0],
                    c="—" if r[1] is None else "{:,.0f}".format(r[1]),
                    col="#4ade80" if inb else "#f87171",
                    txt="nằm trong vùng cắt" if inb else "bị vùng cắt loại"))
    ROWS += ("<tr><td><b>{d}</b></td>"
             "<td class=n>{n0} → {n1}</td>"
             "<td class=n>{a0:.2f} → {b0:.2f} <b style='color:{c0}'>{d0:+.2f}</b></td>"
             "<td class=n>{a1:.2f} → {b1:.2f} <b style='color:{c1}'>{d1:+.2f}</b></td>"
             "<td class=n>{a2:.2f} → {b2:.2f} <b style='color:{c2}'>{d2:+.2f}</b></td>"
             "</tr><tr><td colspan=5 class=det>{det}</td></tr>".format(
                 d=date, n0=a[0], n1=b[0],
                 a0=a[1], b0=b[1], d0=b[1] - a[1],
                 a1=a[2], b1=b[2], d1=b[2] - a[2],
                 a2=a[3], b2=b[3], d2=b[3] - a[3],
                 c0="#94a3b8" if abs(b[1] - a[1]) < 0.5 else "#facc15",
                 c1="#94a3b8" if abs(b[2] - a[2]) < 0.5 else "#facc15",
                 c2="#94a3b8" if abs(b[3] - a[3]) < 0.5 else "#facc15",
                 det=det))

SECTION = """
<h2 id=excl>Hai mã KHÔNG có trong bảng: VIC và VIX</h2>
<p class=note>Rổ là <b>54 mã</b>, không phải toàn bộ sàn. <code>VIC</code> và
<code>VIX</code> bị loại bởi <code>EXCLUDE</code> trong
<code>syncs/breadth.py</code>. Một báo cáo kiểm tra mà không nói ra điều này là
thiếu sót — mục này bổ sung.</p>
<div class=box>
<b>Lý do được ghi lại, và vì sao nó đáng ngờ ở đây</b>
<div class=note style='margin-top:6px'>
Lý do gốc nằm ở <code>single/multi_signal/config.py</code>: VIX từng chiếm ~30%
tổng lợi nhuận của mọi lần chạy nên trung bình bám theo nó chứ không bám theo
chiến lược; VIC là trường hợp đối xứng ở phía lỗ (−458 trong một lần chạy, lớn
hơn cả tổng ròng), nên bỏ mỗi mã thắng đậm sẽ làm lệch kết quả.<br><br>
<b>Nhưng lý do đó viết cho việc TỔNG HỢP KẾT QUẢ, không phải cho việc ĐO RỔ.</b>
Ở đó câu hỏi là “mã này có bóp méo trung bình của 52 kết quả không”. Ở đây câu
hỏi khác hẳn: “mã này có phải một phần của thị trường không”. Danh sách
<code>EXCLUDE</code> được sao chép nguyên si từ <code>portfolio/</code> sang
<code>breadth/</code> rồi sang <code>syncs/breadth.py</code> mà không có lý do
riêng nào được viết ra cho lần sao chép đó.<br><br>
Điều này đáng lưu ý nhất với <code>prem_cap</code>: VIC là một trong những
doanh nghiệp vốn hoá lớn nhất sàn — ngày 2026-08-04 vốn hoá của nó là
<b>1.685.901 tỷ</b> — mà một đường “trung bình theo trọng số vốn hoá” lại không
có nó.
</div></div>

<p class=note>Đo cụ thể, nếu thêm cả hai mã vào rổ:</p>
<table class=full style='font-size:12.5px'><thead><tr>
<th style='text-align:left'>ngày</th><th>n</th>
<th>median_prem</th><th>prem_trim</th><th>prem_cap</th>
</tr></thead><tbody>{ROWS}</tbody></table>

<p class=note><b>Điều bất ngờ: ảnh hưởng nhỏ, và chính phần cắt đuôi là thứ giữ
cho nó nhỏ.</b> <code>median_prem</code> gần như không nhúc nhích (0.00 / 0.00 /
+0.05) vì trung vị bỏ qua độ lớn. Hai đường kia dịch nhiều nhất +5.18 điểm — và
lý do không dịch mạnh hơn là ở mỗi ngày, mã cực đoan lại rơi <i>ra ngoài</i>
vùng cắt 5–95: VIX +656.5% bị loại ngày 2022-01-04, VIC +702.9% bị loại ngày
2026-08-04. Nói cách khác, cơ chế cắt đuôi vốn đã tự xử lý đúng cái rủi ro mà
danh sách <code>EXCLUDE</code> được lập ra để tránh.</p>
<p class=note><b>Khuyến nghị:</b> bỏ <code>EXCLUDE</code> khỏi
<code>syncs/breadth.py</code> để rổ đúng nghĩa là thị trường, và giữ nó ở
<code>single/multi_signal/config.py</code> nơi nó có lý do riêng. Tôi chưa làm
vì việc đó thay đổi toàn bộ 2838 ngày dữ liệu và mọi kết quả đo trước đó — cần
bạn quyết.</p>
"""

p = Path(r"C:\projects\Stock_Analyzer\PriceToEarn_v2\single\multi_signal"
         r"\KIEM_TRA_prem.html")
s = p.read_text(encoding="utf-8")
anchor = "<h2 id=d0>"
assert anchor in s
s = s.replace(anchor, SECTION.format(ROWS=ROWS) + "\n" + anchor, 1)
s = s.replace("<a href='#d2'>", "<a href='#excl'>VIC / VIX bị loại</a><a href='#d2'>", 1)
s = s.replace("td.s{color:#64748b;font-size:11.5px}",
              "td.s{color:#64748b;font-size:11.5px}\n"
              "td.det{color:#94a3b8;font-size:12px;background:#0d1526}", 1)
p.write_text(s, encoding="utf-8")
print("patched", p)
