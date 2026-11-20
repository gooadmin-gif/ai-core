"""原文と再現した文のペアを、判定用ファイルにまとめる。
使い方: python judge_make.py [出力ファイル名(省略時 chat2_output_en.txt)]   例: python judge_make.py chat3_output_jp.txt
出力   : judge_input.txt（判定用の新規チャットに渡す）"""
import re, sys
src = sys.argv[1] if len(sys.argv) > 1 else "chat2_output_en.txt"
orig = [l.strip() for l in open("03_original.txt", encoding="utf-8") if l.strip()]
prod = {}
for l in open(src, encoding="utf-8"):
    m = re.match(r"^\s*(?:Line\s*)?(\d+)\s*[.)：:]\s*(.*)$", l, flags=re.I)
    if m:
        prod[int(m.group(1))] = re.sub(r"\s*\*?\s*[（(]\s*※.*?[）)]\s*\*?\s*$", "", m.group(2)).strip().strip('"“” ')
with open("judge_input.txt", "w", encoding="utf-8") as f:
    for n, o in enumerate(orig, 1):
        f.write(f"{n}. 原文: {o}\n   再現: {prod.get(n, '(無し)')}\n")
print(f"judge_input.txt を作った（{len(orig)}行、元: {src}）")
