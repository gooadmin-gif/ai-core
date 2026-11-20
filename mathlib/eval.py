#!/usr/bin/env python3
"""eval.py: mathlib v1.1 の評価スクリプト

ディレクトリ構成（ai-core/mathlib/eval.py）対応版:
  - ai-core ルート（%userprofile%\ai-core）から `python mathlib\eval.py ...` で実行可能
  - `mathlib/` フォルダ内から `python eval.py ...` でも実行可能
  - パッケージとしての import（`from mathlib import eval`）にも対応

できること
  1. 回答ファイル(responses.jsonl)を採点して集計する（APIキー不要）
  2. Gemini APIを呼んで回答を集めてから採点する（--call-api）
  3. 「AI単独で答えさせた場合」(baseline)と正答率を比較する

使い方（ai-core ルートからの例）
  # 動作確認（ダミーデータ）
  python mathlib\eval.py --problems test\eval_problems_sample.json --responses demo_responses.jsonl \
                        --baseline demo_baseline.jsonl

  # Gemini APIで実行（問題ごと3回、エラー時は最大2回やり直し）
  set GEMINI_API_KEY=...
  python mathlib\eval.py --problems test\eval_problems.json --call-api --model <モデル名> \
                        --repeat 3 --repair 2
  # AI単独のベースライン
  python mathlib\eval.py --problems test\eval_problems.json --call-api --task baseline --model <モデル名>
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

try:
    from .mathlib import explain, run_plan
except ImportError:
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from mathlib import explain, run_plan  # noqa: E402

PLACEHOLDER = "（ここに問題文）"
BASELINE_PROMPT = (
    "次の問題を解いてください。最後の行に「答え: <値>」の形で答えだけを書いてください"
    "（分数は a/b、小数は小数のまま）。\n問題: {text}"
)

SUCCESS = {"correct", "correct_unsupported"}
LABEL = {
    "correct": "正解",
    "correct_unsupported": "正しくunsupportedと返した",
    "silent_wrong": "★無音の誤答（okなのに答えが違う）",
    "blocked": "ライブラリが弾いた（安全側）",
    "false_unsupported": "解ける問題をunsupportedにした",
    "parse_fail": "JSONとして読めない",
}


def resolve_default_prompt() -> str:
    """gemini_prompt.md を mathlib/ または ai-core ルートから探索する。"""
    for candidate in (HERE / "gemini_prompt.md", ROOT / "gemini_prompt.md"):
        if candidate.exists():
            return str(candidate)
    return str(HERE / "gemini_prompt.md")


# ---------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{i} JSONとして読めない: {e}")
    return rows


def load_answers(path):
    """AIの回答を1つのJSON配列にしたファイルを読む。
    [{"id":"q01","plan":{...}}, {"id":"q16","unsupported":"理由"}, ...]
    前後に説明文やコードブロックの囲みがあっても、最初の[ から最後の ] までを読む。"""
    with open(path, encoding="utf-8") as f:
        s = f.read()
    a, b = s.find("["), s.rfind("]")
    if a < 0 or b <= a:
        raise SystemExit(f"{path}: JSON配列（[ ... ]）が見つからない")
    try:
        items = json.loads(s[a : b + 1])
    except json.JSONDecodeError as ex:
        raise SystemExit(f"{path}: JSONとして読めない: {ex}")
    recs = []
    for it in items:
        if not isinstance(it, dict) or "id" not in it:
            raise SystemExit(f"{path}: 各要素に id が必要: {it!r}")
        if "plan" in it:
            raw = json.dumps(it["plan"], ensure_ascii=False)
        elif "unsupported" in it:
            raw = json.dumps({"unsupported": it["unsupported"]}, ensure_ascii=False)
        else:
            raise SystemExit(f"{it['id']}: plan か unsupported のどちらかが必要")
        recs.append({"id": it["id"], "run": 1, "attempt": 1, "raw": raw})
    return recs


def write_trace_file(path, trials):
    """ライブラリが実際に出した途中経過を、人が読める形で書き出す。"""
    out_p = Path(path)
    if out_p.parent and str(out_p.parent) != ".":
        out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as f:
        for t in trials:
            f.write(f"## {t['id']}（run{t['run']}）結果: {LABEL.get(t['final']['outcome'], t['final']['outcome'])}\n")
            f.write(f"問題: {t['text']}\n")
            f.write((t["final"].get("explain") or f"（planなし: {t['final']['outcome']}）") + "\n\n")


def load_problems(path):
    problems = load_json(path)
    seen = set()
    for p in problems:
        for k in ("id", "text", "expect"):
            if k not in p:
                raise SystemExit(f"問題に {k} がない: {p}")
        if p["id"] in seen:
            raise SystemExit(f"idが重複: {p['id']}")
        seen.add(p["id"])
        t = p["expect"].get("type")
        if t not in ("solve", "unsupported"):
            raise SystemExit(f"{p['id']}: expect.type は solve か unsupported")
        if t == "solve" and "exact" not in p["expect"]:
            raise SystemExit(f"{p['id']}: solve には expect.exact が必要")
        p.setdefault("category", "none")
    return problems


# ---------------------------------------------------------------
# AIの出力 → 採点
# ---------------------------------------------------------------
def extract_json(raw):
    """出力からJSONオブジェクトを取り出す（コードフェンスや前後の文章を許容）"""
    if not isinstance(raw, str):
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


def score_attempt(problem, raw):
    exp = problem["expect"]
    plan = extract_json(raw)
    if not isinstance(plan, dict):
        return {"outcome": "parse_fail"}

    if "unsupported" in plan:
        ok = exp["type"] == "unsupported"
        return {
            "outcome": "correct_unsupported" if ok else "false_unsupported",
            "reason": plan.get("unsupported"),
        }

    try:
        res = run_plan(plan, problem["text"])
    except Exception as e:  # planの形が想定外でライブラリが落ちた場合
        return {
            "outcome": "blocked",
            "error_code": "LIB_EXCEPTION",
            "error": {"code": "LIB_EXCEPTION", "message": repr(e)},
        }

    if not res["ok"]:
        return {
            "outcome": "blocked",
            "error_code": res["error"]["code"],
            "error": res["error"],
            "explain": explain(res),
        }

    got = res["answer"]["exact"]
    rules = [t["rule"] for t in res["trace"] if t["type"] == "step"]
    if exp["type"] == "unsupported":
        return {
            "outcome": "silent_wrong",
            "got": got,
            "expected": "(unsupported)",
            "rules": rules,
            "explain": explain(res),
            "warnings": res.get("warnings", []),
        }
    got_display = res["answer"].get("display")
    correct = Fraction(got) == Fraction(exp["exact"])
    if correct and "display" in exp:
        correct = got_display == exp["display"]  # 桁数・丸め・形式まで合っているか
    return {
        "outcome": "correct" if correct else "silent_wrong",
        "got": got,
        "got_display": got_display,
        "expected": exp["exact"],
        "expected_display": exp.get("display"),
        "rules": rules,
        "rules_match": rules == exp.get("rules") if "rules" in exp else None,
        "explain": explain(res),
        "warnings": res.get("warnings", []),
    }


def extract_answer(raw):
    """ベースライン用: 「答え: X」を優先、なければ最後の数字"""
    s = unicodedata.normalize("NFKC", raw or "")
    pat = r"-?\d+(?:\.\d+)?(?:/\d+)?"
    m = re.findall(r"答え\s*[:：]\s*(" + pat + ")", s)
    if m:
        return m[-1]
    nums = re.findall(pat, s)
    return nums[-1] if nums else None


def score_baseline(problem, raw):
    tok = extract_answer(raw)
    if tok is None:
        return False
    exp = problem["expect"]
    target = exp.get("display", exp["exact"])
    try:
        return Fraction(tok) == Fraction(target.rstrip("%"))
    except (ValueError, ZeroDivisionError):
        return False


# ---------------------------------------------------------------
# 試行(trial)の組み立て
# ---------------------------------------------------------------
def _sum_or_none(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) if vals else None


def build_trials(problems, records):
    pmap = {p["id"]: p for p in problems}
    groups = defaultdict(list)
    for r in records:
        if r.get("id") not in pmap:
            print(f"[警告] 問題セットにないid: {r.get('id')}", file=sys.stderr)
            continue
        groups[(r["id"], r.get("run", 1))].append(r)

    trials = []
    for (pid, run), recs in sorted(groups.items()):
        p = pmap[pid]
        recs.sort(key=lambda r: r.get("attempt", 1))
        scored = [score_attempt(p, r.get("raw", "")) for r in recs]
        trials.append(
            {
                "id": pid,
                "run": run,
                "category": p["category"],
                "text": p["text"],
                "attempts": len(recs),
                "first": scored[0],
                "final": scored[-1],
                "tokens": _sum_or_none([(r.get("tokens") or {}).get("total") for r in recs]),
                "latency": _sum_or_none([r.get("latency_sec") for r in recs]),
            }
        )
    return trials


# ---------------------------------------------------------------
# 集計
# ---------------------------------------------------------------
def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "0/0"


def aggregate(problems, trials):
    n = len(trials)
    first = Counter(t["first"]["outcome"] for t in trials)
    final = Counter(t["final"]["outcome"] for t in trials)

    blocked_first = [t for t in trials if t["first"]["outcome"] == "blocked"]
    repaired = [t for t in blocked_first if t["final"]["outcome"] in SUCCESS]

    by_cat = defaultdict(lambda: {"n": 0, "success": 0, "silent_wrong": 0})
    for t in trials:
        c = by_cat[t["category"]]
        c["n"] += 1
        c["success"] += t["final"]["outcome"] in SUCCESS
        c["silent_wrong"] += t["final"]["outcome"] == "silent_wrong"

    errors = Counter(t["first"].get("error_code") for t in trials if t["first"]["outcome"] == "blocked")

    answered_ids = {t["id"] for t in trials}
    unanswered = [p["id"] for p in problems if p["id"] not in answered_ids]

    toks = [t["tokens"] for t in trials if t["tokens"] is not None]
    lats = [t["latency"] for t in trials if t["latency"] is not None]

    return {
        "n_trials": n,
        "first_success": sum(first[k] for k in SUCCESS),
        "final_success": sum(final[k] for k in SUCCESS),
        "first_outcomes": dict(first),
        "final_outcomes": dict(final),
        "silent_wrong": [
            {"id": t["id"], "run": t["run"], "text": t["text"], **t["final"]}
            for t in trials
            if t["final"]["outcome"] == "silent_wrong"
        ],
        "repair": {"needed": len(blocked_first), "fixed": len(repaired)},
        "by_category": dict(by_cat),
        "first_error_codes": dict(errors),
        "with_warnings": [
            {"id": t["id"], "run": t["run"], "warnings": t["final"]["warnings"]}
            for t in trials
            if t["final"].get("warnings")
        ],
        "unanswered": unanswered,
        "avg_tokens": sum(toks) / len(toks) if toks else None,
        "avg_latency_sec": sum(lats) / len(lats) if lats else None,
    }


def rules_match_rate(problems, trials):
    pmap = {p["id"]: p for p in problems}
    tgt = [
        t
        for t in trials
        if pmap[t["id"]]["expect"]["type"] == "solve"
        and t["final"].get("rules_match") is not None
    ]
    return sum(1 for t in tgt if t["final"]["rules_match"]), len(tgt)


def compare_baseline(problems, trials, base_records):
    pmap = {p["id"]: p for p in problems}
    solve = {p["id"] for p in problems if p["expect"]["type"] == "solve"}
    base_hits = base_n = 0
    base_tokens = []
    base_ids = set()
    for r in base_records:
        p = pmap.get(r.get("id"))
        if not p or p["id"] not in solve:
            continue
        base_ids.add(p["id"])
        base_n += 1
        base_hits += score_baseline(p, r.get("raw", ""))
        tk = (r.get("tokens") or {}).get("total")
        if isinstance(tk, (int, float)):
            base_tokens.append(tk)
    lib = [t for t in trials if t["id"] in base_ids]
    lib_hits = sum(t["final"]["outcome"] == "correct" for t in lib)
    lib_silent = sum(t["final"]["outcome"] == "silent_wrong" for t in lib)
    lib_tokens = [t["tokens"] for t in lib if t["tokens"] is not None]
    return {
        "problems": len(base_ids),
        "baseline_correct": base_hits,
        "baseline_n": base_n,
        "library_correct": lib_hits,
        "library_n": len(lib),
        "library_silent_wrong": lib_silent,
        "baseline_avg_tokens": sum(base_tokens) / len(base_tokens) if base_tokens else None,
        "library_avg_tokens": sum(lib_tokens) / len(lib_tokens) if lib_tokens else None,
    }


# ---------------------------------------------------------------
# レポート表示
# ---------------------------------------------------------------
def print_report(agg, rm, cmp_):
    n = agg["n_trials"]
    print("=" * 60)
    print(f"評価結果  試行数: {n}", end="")
    if agg["unanswered"]:
        print(f"  （未回答の問題: {', '.join(agg['unanswered'])}）", end="")
    print("\n" + "=" * 60)

    sw = agg["silent_wrong"]
    print(f"\n★ 無音の誤答: {len(sw)} 件  ← 最優先で0を目指す指標")
    for s in sw:
        got = s.get("got_display") or s.get("got")
        want = s.get("expected_display") or s.get("expected")
        print(f"   - {s['id']}(run{s['run']}): 出力={got} / 期待={want}"
              f" / 使用ルール={s.get('rules')}")
        print(f"       問題: {s['text']}")

    if agg["with_warnings"]:
        print(f"\n[警告] 使われていない値があった試行: {len(agg['with_warnings'])} 件（取り違えのサインになりうる）")
        for w in agg["with_warnings"]:
            ids = "、".join(x["id"] for x in w["warnings"])
            print(f"   - {w['id']}(run{w['run']}): {ids}")

    print(f"\n[一発成功率]  {pct(agg['first_success'], n)}")
    print(f"[最終正解率]  {pct(agg['final_success'], n)}")
    rp = agg["repair"]
    if rp["needed"]:
        print(f"[自力修正]    弾かれた {rp['needed']} 件中 {rp['fixed']} 件を修正して正解")
    if rm[1]:
        print(f"[ルール選択]  期待ルールと一致 {pct(rm[0], rm[1])}")

    print("\n[結果の内訳]  （最終 / 一発目）")
    for k, label in LABEL.items():
        f, o = agg["final_outcomes"].get(k, 0), agg["first_outcomes"].get(k, 0)
        if f or o:
            print(f"   {label}: {f} / {o}")

    print("\n[カテゴリ別]  （最終正解 / 無音の誤答）")
    for cat, c in sorted(agg["by_category"].items()):
        print(f"   {cat}: {pct(c['success'], c['n'])} / 無音誤答 {c['silent_wrong']}")

    if agg["first_error_codes"]:
        print("\n[弾かれた理由（一発目）]")
        for code, cnt in sorted(agg["first_error_codes"].items(), key=lambda x: -x[1]):
            print(f"   {code}: {cnt}")

    if agg["avg_tokens"] is not None or agg["avg_latency_sec"] is not None:
        print("\n[コスト（1試行あたり平均）]")
        if agg["avg_tokens"] is not None:
            print(f"   トークン: {agg['avg_tokens']:.0f}")
        if agg["avg_latency_sec"] is not None:
            print(f"   応答時間: {agg['avg_latency_sec']:.1f}秒")

    if cmp_:
        print("\n[AI単独との比較]  （solve型の問題のみ）")
        print(f"   AI単独    : 正答 {pct(cmp_['baseline_correct'], cmp_['baseline_n'])}")
        print(f"   ライブラリ: 正答 {pct(cmp_['library_correct'], cmp_['library_n'])}"
              f" / 無音の誤答 {cmp_['library_silent_wrong']}")
        if cmp_["baseline_avg_tokens"] and cmp_["library_avg_tokens"]:
            print(f"   平均トークン: AI単独 {cmp_['baseline_avg_tokens']:.0f}"
                  f" / ライブラリ {cmp_['library_avg_tokens']:.0f}")
        print("   ※AI単独は「答え:」行か最後の数字を答えとみなす簡易採点")

    if n < 30:
        print("\n注意: 試行数が少ないので、割合より失敗の中身（上の詳細）を見ること")


# ---------------------------------------------------------------
# Gemini API 実行（REST直叩き。キーは環境変数 GEMINI_API_KEY）
# ---------------------------------------------------------------
def read_prompt_template(path):
    """gemini_prompt.md の中から、API用プロンプト（{PLACEHOLDER}を含むコードブロック）を取り出す。
    コードブロックは行頭の ``` で数えて切り出す（ブロックの間の文章を拾わないため）。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    blocks, cur = [], None
    for ln in lines:
        if ln.startswith("```"):
            if cur is None:
                cur = []
            else:
                blocks.append("\n".join(cur))
                cur = None
        elif cur is not None:
            cur.append(ln)
    hits = [b for b in blocks if PLACEHOLDER in b]
    if len(hits) != 1 or hits[0].count(PLACEHOLDER) != 1:
        raise SystemExit(
            f"{path} から、{PLACEHOLDER}を1つだけ含むコードブロックを1つだけ取り出せなかった"
            f"（見つかった数: {len(hits)}）"
        )
    return hits[0]


def call_gemini(prompt, model, api_key, temperature):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    cands = data.get("candidates") or []
    parts = (cands[0].get("content") or {}).get("parts") if cands else None
    text = "".join(p.get("text", "") for p in (parts or []))
    u = data.get("usageMetadata") or {}
    tokens = {
        "input": u.get("promptTokenCount"),
        "output": u.get("candidatesTokenCount"),
        "thinking": u.get("thoughtsTokenCount"),
        "total": u.get("totalTokenCount"),
    }
    return text, tokens


def run_api(problems, args, out_path):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("環境変数 GEMINI_API_KEY を設定してください")
    template = read_prompt_template(args.prompt_file) if args.task == "plan" else None
    max_attempts = 1 + (args.repair if args.task == "plan" else 0)

    out_p = Path(out_path)
    if out_p.parent and str(out_p.parent) != ".":
        out_p.parent.mkdir(parents=True, exist_ok=True)

    with out_p.open("a", encoding="utf-8") as out:
        for p in problems:
            for run in range(1, args.repeat + 1):
                if args.task == "plan":
                    base = template.replace(PLACEHOLDER, p["text"])
                else:
                    base = BASELINE_PROMPT.format(text=p["text"])
                prompt = base
                for attempt in range(1, max_attempts + 1):
                    t0 = time.time()
                    try:
                        text, tokens = call_gemini(prompt, args.model, key, args.temperature)
                        err = None
                    except Exception as e:
                        text, tokens, err = "", {}, str(e)
                    rec = {
                        "id": p["id"],
                        "run": run,
                        "attempt": attempt,
                        "model": args.model,
                        "task": args.task,
                        "raw": text,
                        "tokens": tokens,
                        "latency_sec": round(time.time() - t0, 2),
                    }
                    if err:
                        rec["api_error"] = err
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"  {p['id']} run{run} attempt{attempt}: "
                          f"{'API失敗 ' + err if err else 'ok'}", file=sys.stderr)
                    if args.task != "plan":
                        break
                    s = score_attempt(p, text)
                    if s["outcome"] != "blocked":
                        break
                    prompt = (
                        base
                        + f"\n\n---\n前回のあなたの出力:\n{text}\n\n"
                        + "ライブラリからのエラー:\n"
                        + json.dumps(s["error"], ensure_ascii=False)
                        + "\n\nエラーを踏まえてplanを修正し、JSONのみ出力してください。"
                    )
                if args.sleep:
                    time.sleep(args.sleep)


# ---------------------------------------------------------------
# main
# ---------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="mathlib 評価スクリプト")
    ap.add_argument("--problems", required=True, help="問題セット(JSON)")
    ap.add_argument("--responses", help="採点する回答ファイル(jsonl, planタスク)")
    ap.add_argument("--baseline", help="AI単独の回答ファイル(jsonl)。比較用")
    ap.add_argument("--call-api", action="store_true", help="Gemini APIで回答を集める")
    ap.add_argument("--task", choices=["plan", "baseline"], default="plan")
    ap.add_argument("--model", help="--call-api時に必須（Geminiのモデル名）")
    ap.add_argument("--repeat", type=int, default=1, help="同じ問題を何回投げるか")
    ap.add_argument("--repair", type=int, default=0, help="弾かれた時の最大やり直し回数")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--sleep", type=float, default=0.0, help="問題ごとの待ち秒数")
    ap.add_argument("--prompt-file", default=resolve_default_prompt())
    ap.add_argument("--out", help="API回答の保存先(jsonl)")
    ap.add_argument("--report", default="eval_report.json", help="集計結果の保存先")
    ap.add_argument("--answers", help="AIの回答をまとめたJSON配列ファイル（[{id, plan}, ...]）")
    ap.add_argument("--trace-out", metavar="OUT", help="ライブラリが出した途中経過を書き出す")
    ap.add_argument("--export-questions", metavar="OUT",
                    help="idと問題文だけのJSONを書き出して終了（AIに渡す用）")
    args = ap.parse_args()

    problems = load_problems(args.problems)

    if args.export_questions:
        # 画面コピペ実験用: id と問題文だけ（expect・categoryは含めない）
        out_p = Path(args.export_questions)
        if out_p.parent and str(out_p.parent) != ".":
            out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump([{"id": p["id"], "text": p["text"]} for p in problems],
                      f, ensure_ascii=False, indent=2)
        print(f"問題文だけのファイルを {args.export_questions} に書き出した"
              "（これだけをAIに渡す。元の問題ファイルは渡さない）")
        return

    responses_path, baseline_path = args.responses, args.baseline

    if args.call_api:
        if not args.model:
            raise SystemExit("--call-api には --model が必要")
        out = args.out or f"{args.task}_responses_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        print(f"API実行 → {out}", file=sys.stderr)
        run_api(problems, args, out)
        if args.task == "plan":
            responses_path = out
        else:
            baseline_path = out

    if not responses_path and not baseline_path and not args.answers:
        raise SystemExit("--answers か --responses か --baseline か --call-api のどれかが必要")

    trials = []
    agg = rm = None
    records = None
    if args.answers:
        records = load_answers(args.answers)
    elif responses_path:
        records = load_jsonl(responses_path)
    if records is not None:
        trials = build_trials(problems, records)
        if not trials:
            raise SystemExit("採点できる回答がない")
        agg = aggregate(problems, trials)
        rm = rules_match_rate(problems, trials)
        if args.trace_out:
            write_trace_file(args.trace_out, trials)
            print(f"途中経過を {args.trace_out} に書き出した（ライブラリが実際に出したもの）")

    cmp_ = None
    if baseline_path:
        base = load_jsonl(baseline_path)
        if trials:
            cmp_ = compare_baseline(problems, trials, base)
        else:
            solve = {p["id"]: p for p in problems if p["expect"]["type"] == "solve"}
            hits = sum(score_baseline(solve[r["id"]], r.get("raw", "")) for r in base if r.get("id") in solve)
            n = sum(1 for r in base if r.get("id") in solve)
            print(f"AI単独: 正答 {pct(hits, n)}")

    if agg:
        print_report(agg, rm, cmp_)
        rep_p = Path(args.report)
        if rep_p.parent and str(rep_p.parent) != ".":
            rep_p.parent.mkdir(parents=True, exist_ok=True)
        with rep_p.open("w", encoding="utf-8") as f:
            json.dump(
                {"aggregate": agg, "rules_match": rm, "baseline_comparison": cmp_, "trials": trials},
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n詳細を {args.report} に保存した")


if __name__ == "__main__":
    main()
