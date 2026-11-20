"""チャットが作った英文と原文を比べ、何が落ちたかを一覧にする。
使い方: chat2_output_en.txt に出力を1行1文で貼り(行頭の「1.」などは自動で外す)  python diff_report.py
出力   : diff_report.html / 画面に要約"""
import re, difflib, html
from collections import Counter

tok = lambda s: re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+|[^\sA-Za-z\d]", s)
isword = lambda t: t[0].isalnum()
strip_no = lambda s: re.sub(r"^\s*(?:Line\s*)?\d+\s*[.)：:]\s*", "", s.strip(), flags=re.I).strip('"“” ')

orig = [l.strip() for l in open("03_original.txt", encoding="utf-8") if l.strip()]
# 行頭が「番号.」の行だけ拾い、番号で対応づける（前置きの文があってもズレない）
_prod = {}
for l in open("chat2_output_en.txt", encoding="utf-8"):
    m = re.match(r"^\s*(?:Line\s*)?(\d+)\s*[.)：:]\s*(.*)$", l, flags=re.I)
    if m:
        t = re.sub(r"\s*\*?\s*[（(]\s*※.*?[）)]\s*\*?\s*$", "", m.group(2)).strip().strip('"“” ')
        _prod[int(m.group(1))] = t
prod = [_prod.get(i, "") for i in range(1, 100)]

rows, recalls = [], []
for n, o in enumerate(orig, 1):
    p = prod[n - 1] if n - 1 < len(prod) else ""
    ot, pt = tok(o), tok(p)
    ow, pw = Counter(t.lower() for t in ot if isword(t)), Counter(t.lower() for t in pt if isword(t))
    missing, extra = ow - pw, pw - ow
    recall = 1 - sum(missing.values()) / max(1, sum(ow.values()))
    recalls.append(recall)
    sm = difflib.SequenceMatcher(a=ot, b=pt, autojunk=False)
    marked = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            marked.append(" ".join(pt[b1:b2]))
        else:
            if b2 > b1: marked.append(f"<b style='color:#c00'>{html.escape(' '.join(pt[b1:b2]))}</b>")
            if a2 > a1: marked.append(f"<s style='color:#06c'>{html.escape(' '.join(ot[a1:a2]))}</s>")
    rows.append((n, o, p, " ".join(marked), recall, dict(missing), dict(extra), o.lower() == p.lower()))

exact = sum(r[7] for r in rows)
words_ok = sum([t.lower() for t in tok(r[1]) if isword(t)] == [t.lower() for t in tok(r[2]) if isword(t)] for r in rows)
with open("diff_report.html", "w", encoding="utf-8") as f:
    f.write("<meta charset='utf-8'><style>td,th{border:1px solid #999;padding:4px;vertical-align:top}table{border-collapse:collapse}</style>")
    f.write(f"<h3>完全一致 {exact}/{len(orig)} ／ 語・語順一致(句読点無視) {words_ok}/{len(orig)} ／ 単語の再現率 平均 {sum(recalls)/len(recalls):.0%}</h3>")
    f.write("<p>赤＝原文に無い語(増えた) ／ 青の取り消し線＝原文にあって落ちた語</p>")
    f.write("<table><tr><th>行</th><th>原文</th><th>再現</th><th>差分</th><th>再現率</th><th>落ちた語</th><th>増えた語</th></tr>")
    for n, o, p, m, rc, ms, ex, same in rows:
        bg = "#dfd" if same else ""
        f.write(f"<tr style='background:{bg}'><td>{n}</td><td>{html.escape(o)}</td><td>{html.escape(p)}</td><td>{m}</td>"
                f"<td>{rc:.0%}</td><td>{html.escape(', '.join(ms))}</td><td>{html.escape(', '.join(ex))}</td></tr>")
    f.write("</table>")
print(f"完全一致 {exact}/{len(orig)} ／ 語・語順一致(句読点無視) {words_ok}/{len(orig)} ／ 再現率(平均) {sum(recalls)/len(recalls):.0%}")
for n, o, p, m, rc, ms, ex, same in rows:
    print(f"{n:>2}行 {rc:>4.0%} 落ちた語: {', '.join(ms) or '-'}")
print("→ diff_report.html を開いてな")
