"""Geminiが作った chat2_input_v2_raw.json を検査し、チャット2・3に渡すファイルを作る。
使い方: このフォルダに chat2_input_v2_raw.json を置いて  python validate_v2.py
出力   : chat2_input_v2.json(検査済み) / 01_dict_v2.txt(使われたIDだけの辞書) / validate_report.txt
検査   : 辞書にないID、元の文に無いID、入れ忘れた単語(=チャット1側の抜け)、スコアの範囲、idsの混入"""
import json, re
SCORES = ["emotion", "positivity", "urgency", "certainty", "irony", "formality", "emphasis"]
SKIP_POS = {"PUNCT"}
SKIP_WORDS = {"a", "an", "the"}   # 入れ忘れ検査の対象外(冠詞だけ)

def load_json(p):
    t = open(p, encoding="utf-8").read().strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    return json.loads(t)

dic = {}
for l in open("01_dict.txt", encoding="utf-8"):
    l = l.strip()
    if "=" in l:
        i, rest = l.split("=", 1); dic[int(i)] = rest
pos = lambda i: re.search(r"\((\w+)\)$", dic[i]).group(1)
lines = [[int(x) for x in l.split()] for l in open("02_ids.txt", encoding="utf-8") if l.strip()]

raw = load_json("chat2_input_v2_raw.json")
report, used_all, clean = [], set(), {"version": "0.2", "sentences": []}
if len(raw["sentences"]) != len(lines):
    report.append(f"行数が違う: json={len(raw['sentences'])} / ids={len(lines)}")

def ids_in(c):
    s = set()
    for k in ("subject_ids", "intent_ids", "object_ids", "negation_ids", "time_ids"):
        s.update(c.get(k, []))
    for m in c.get("modifiers", []):
        s.update([m.get("id"), m.get("target_id")])
    return s

for n, s in enumerate(raw["sentences"], 1):
    if "ids" in s: report.append(f"{n}行: idsが混入している(消した)")
    used = set()
    for c in s.get("clauses", []):
        used |= ids_in(c)
    for r in s.get("relations", []):
        used.add(r.get("id"))
    used.discard(None)
    unknown = sorted(i for i in used if i not in dic)
    if unknown: report.append(f"{n}行: 辞書にないID {unknown}")
    if n - 1 < len(lines):
        line = set(lines[n - 1])
        outside = sorted(i for i in used if i in dic and i not in line)
        if outside: report.append(f"{n}行: この文に無いIDが入っている {outside}")
        need = [i for i in line if i in dic and pos(i) not in SKIP_POS and dic[i].split("(")[0].lower() not in SKIP_WORDS]
        miss = sorted(set(i for i in need if i not in used))
        if miss: report.append(f"{n}行: 入れ忘れ(チャット1側の抜け) " + ", ".join(dic[i] for i in miss))
    sc = s.get("scores", {})
    for k in SCORES:
        if k not in sc or not (0 <= sc[k] <= 1): report.append(f"{n}行: scores.{k} が無い/範囲外")
    used_all |= {i for i in used if i in dic}
    clean["sentences"].append({"line": n, "clauses": s.get("clauses", []), "relations": s.get("relations", []), "scores": sc})

json.dump(clean, open("chat2_input_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open("01_dict_v2.txt", "w", encoding="utf-8") as f:
    for i in sorted(used_all): f.write(f"{i}={dic[i]}\n")
out = ["【検査結果】"] + (report or ["問題なし"]) + [f"辞書: 全{len(dic)}語 → 使われた{len(used_all)}語に絞った"]
open("validate_report.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
