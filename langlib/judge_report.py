"""判定AIが返したJSON(judge_output.json)を集計する。
使い方: judge_output.json に判定結果を貼って  python judge_report.py"""
import json, re
from collections import Counter
t = open("judge_output.json", encoding="utf-8").read().strip()
t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
rows = json.loads(t)
CRIT = {"negation", "subject", "time", "cause", "limit"}
crit_n = sum(1 for r in rows if CRIT & set(r.get("lost", [])))
inv_n = sum(1 for r in rows if r.get("inverted"))
avg = sum(r["meaning"] for r in rows) / (2 * len(rows))
c = Counter(x for r in rows for x in r.get("lost", []))
out = [f"意味スコア平均 {avg:.0%}（2=同じ, 1=近い, 0=違う）／ 意味が逆になった行 {inv_n}/{len(rows)}／ 重要要素が落ちた行 {crit_n}/{len(rows)}",
       "落ちた要素の内訳: " + (", ".join(f"{k}×{v}" for k, v in c.most_common()) or "なし"), ""]
for r in rows:
    out.append(f"{r['line']:>2}行 meaning={r['meaning']} inverted={r.get('inverted')} lost={r.get('lost')}")
open("judge_report.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
