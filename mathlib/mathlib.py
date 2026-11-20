"""mathlib v1.1: 四則演算（add / sub / mul / div）＋ 出力指定（桁数・丸め方）

方針（v0から引き継ぎ）
- 内部は fractions.Fraction で常に厳密に持つ（floatは受け付けない）
- ルールは純粋関数（同じ入力なら同じ結果）
- 実行は構造化データ(plan)で行い、途中結果を trace(JSON) に全部残す
- AIが取り出した値は「元の文のどこから取ったか(source)」で検証する

v1で追加
- mul / div ルール。div は定義域（0で割らない）を持つ
- 出力指定 plan["output"]: 計算は最後まで厳密、丸めは出力時にだけ行う
    {"format": "fraction"|"decimal"|"percent", "places": 1,
     "rounding": "half_up", "source": "小数第1位まで四捨五入"}
  丸め方の既定は DEFAULT_ROUNDING（四捨五入=half_up）。変えたい時は指定する。
"""
import json
import re
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

DEFAULT_ROUNDING = "half_up"
ROUNDING_MODES = ("half_up", "half_even", "down", "up", "floor", "ceil")
MAX_PLACES = 15
OUTPUT_FORMATS = ("fraction", "decimal", "percent")
RESERVED_IDS = {"out"}

MODE_JA = {
    "half_up": "四捨五入",
    "half_even": "偶数丸め",
    "down": "切り捨て(0方向)",
    "up": "切り上げ(0から遠い方向)",
    "floor": "切り下げ(-∞方向)",
    "ceil": "切り上げ(+∞方向)",
}
# 問題文のキーワード → 許される丸め方（sourceとの整合チェック用）
ROUNDING_KEYWORDS = {
    "四捨五入": {"half_up"},
    "切り捨て": {"down", "floor"},
    "切捨て": {"down", "floor"},
    "切り上げ": {"up", "ceil"},
    "切上げ": {"up", "ceil"},
    "偶数丸め": {"half_even"},
    "銀行丸め": {"half_even"},
}


# ---------------------------------------------------------------
# エラー
# ---------------------------------------------------------------
class MathLibError(Exception):
    def __init__(self, code, message, **detail):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self):
        return {"code": self.code, "message": self.message, "detail": self.detail}


# ---------------------------------------------------------------
# foundation: 数の表現
# ---------------------------------------------------------------
def to_number(x):
    """入力を Fraction に変換。floatは誤差が混ざるので拒否する。
    小数は文字列で渡す（"0.1" -> 1/10）。"""
    if isinstance(x, bool):
        raise MathLibError("INVALID_TYPE", "boolは数として受け付けない", got=repr(x))
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, Fraction):
        return x
    if isinstance(x, str):
        try:
            return Fraction(unicodedata.normalize("NFKC", x).strip())
        except (ValueError, ZeroDivisionError):
            raise MathLibError("INVALID_NUMBER", f"数として読めない: {x!r}", got=x)
    raise MathLibError(
        "INVALID_TYPE",
        "整数か文字列で渡すこと（floatは誤差が混ざるので不可。小数は文字列で）",
        got=repr(x),
    )


def fmt(n):
    """厳密な分数表記"""
    return str(n.numerator) if n.denominator == 1 else f"{n.numerator}/{n.denominator}"


def disp(n):
    """式の中で表示する用（負数は括弧）"""
    s = fmt(n)
    return f"({s})" if n < 0 else s


# ---------------------------------------------------------------
# foundation: 丸め（Fractionのまま厳密に行う。floatもDecimalも使わない）
# ---------------------------------------------------------------
def round_q(x, mode):
    """Fraction x を整数に丸める。"""
    if mode not in ROUNDING_MODES:
        raise MathLibError(
            "OUTPUT_ROUNDING_INVALID", f"未対応の丸め方: {mode!r}", available=list(ROUNDING_MODES)
        )
    fl = x.numerator // x.denominator  # floor
    rem = x - fl
    if rem == 0:
        return fl
    if mode == "floor":
        return fl
    if mode == "ceil":
        return fl + 1
    if mode == "down":  # 0方向
        return fl if x > 0 else fl + 1
    if mode == "up":  # 0から遠い方向
        return fl + 1 if x > 0 else fl
    half = Fraction(1, 2)
    if rem > half:
        return fl + 1
    if rem < half:
        return fl
    # ちょうど半分
    if mode == "half_up":  # 0から遠い方へ（四捨五入）
        return fl + 1 if x > 0 else fl
    return fl if fl % 2 == 0 else fl + 1  # half_even


def fmt_scaled(q, places):
    """整数 q を 10^places で割った値を、桁数ぴったりの文字列にする。"""
    sign = "-" if q < 0 else ""
    s = str(abs(q)).rjust(places + 1, "0")
    if places == 0:
        return sign + s
    return f"{sign}{s[:-places]}.{s[-places:]}"


def to_decimal(n, places=10):
    """出力指定がない時の近似小数（四捨五入）。割り切れない時は is_approx=True。"""
    q = round_q(n * 10**places, "half_up")
    text = fmt_scaled(q, places)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return {"value": text, "is_approx": Fraction(q, 10**places) != n, "places": places}


# ---------------------------------------------------------------
# rules: 純粋関数 + 定義域 + 検算 + メタ情報
# ---------------------------------------------------------------
def _no_domain(ins):
    return None


RULES = {
    "add": {
        "description": "2つの数を足す（a + b）",
        "arity": 2,
        "symbol": "+",
        "conditions": "なし",
        "depends_on": ["交換法則", "結合法則", "0は加法の単位元"],
        "run": lambda a, b: a + b,
        "domain": _no_domain,
        "check": lambda ins, r: r - ins[1] == ins[0],  # 結果からbを引くとaに戻る
        "example": {"inputs": [3, 5], "result": "8"},
    },
    "sub": {
        "description": "1つ目から2つ目を引く（a - b）",
        "arity": 2,
        "symbol": "-",
        "conditions": "なし",
        "depends_on": ["加法の逆元"],
        "run": lambda a, b: a - b,
        "domain": _no_domain,
        "check": lambda ins, r: r + ins[1] == ins[0],  # 結果にbを足すとaに戻る
        "example": {"inputs": [3, 5], "result": "-2"},
    },
    "mul": {
        "description": "2つの数を掛ける（a × b）",
        "arity": 2,
        "symbol": "×",
        "conditions": "なし",
        "depends_on": ["交換法則", "結合法則", "1は乗法の単位元", "0との積は0", "分配法則"],
        "run": lambda a, b: a * b,
        "domain": _no_domain,
        # 結果をbで割るとaに戻る（b=0の時は結果が0であること）
        "check": lambda ins, r: (r / ins[1] == ins[0]) if ins[1] != 0 else r == 0,
        "example": {"inputs": [3, 5], "result": "15"},
    },
    "div": {
        "description": "1つ目を2つ目で割る（a ÷ b）。分数のまま厳密に返る",
        "arity": 2,
        "symbol": "÷",
        "conditions": "2つ目は0以外",
        "depends_on": ["乗法の逆元（0を除く）"],
        "run": lambda a, b: a / b,
        "domain": lambda ins: None if ins[1] != 0 else ("DIV_BY_ZERO", "0では割れない"),
        "check": lambda ins, r: r * ins[1] == ins[0],  # 結果にbを掛けるとaに戻る
        "example": {"inputs": [7, 2], "result": "7/2"},
    },
}


def list_rules():
    """目録（AIが最初に見る）。関数は含めない。"""
    return [
        {
            "name": name,
            "description": r["description"],
            "arity": r["arity"],
            "conditions": r["conditions"],
            "depends_on": r["depends_on"],
            "example": r["example"],
        }
        for name, r in RULES.items()
    ]


# ---------------------------------------------------------------
# validator: 元の文との対応チェック
# ---------------------------------------------------------------
_NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?(?:/\d+)?")


def _norm(s):
    return unicodedata.normalize("NFKC", s)


def _check_source(vid, num, source, text):
    if not source:
        raise MathLibError("SOURCE_MISSING", f"{vid}: source（元の文の該当部分）が必要", id=vid)
    if _norm(source) not in _norm(text):
        raise MathLibError(
            "SOURCE_NOT_IN_TEXT", f"{vid}: sourceが元の文に見当たらない", id=vid, source=source
        )
    tokens = _NUM_TOKEN.findall(_norm(source))
    ok = False
    for t in tokens:
        try:
            if Fraction(t) == abs(num):
                ok = True
                break
        except (ValueError, ZeroDivisionError):
            continue
    if not ok:
        raise MathLibError(
            "VALUE_NOT_IN_SOURCE",
            f"{vid}: 値{fmt(num)}がsource内の数字と一致しない",
            id=vid,
            value=fmt(num),
            source=source,
            numbers_in_source=tokens,
        )


# ---------------------------------------------------------------
# 出力指定（output）
# ---------------------------------------------------------------
def resolve_output(spec, text):
    """outputを検証して、確定した指定(dict)を返す。"""
    if not isinstance(spec, dict):
        raise MathLibError("OUTPUT_INVALID", "outputはオブジェクトで書く")
    f = spec.get("format")
    if f not in OUTPUT_FORMATS:
        raise MathLibError(
            "OUTPUT_FORMAT_INVALID", f"formatが不正: {f!r}", available=list(OUTPUT_FORMATS)
        )
    source = spec.get("source")
    if text is not None:
        if not source:
            raise MathLibError(
                "OUTPUT_SOURCE_MISSING", "output.source（桁数・形式を指定している元の文の部分）が必要"
            )
        if _norm(source) not in _norm(text):
            raise MathLibError(
                "OUTPUT_SOURCE_NOT_IN_TEXT", "output.sourceが元の文に見当たらない", source=source
            )
    if f == "fraction":
        if text is not None and "分数" not in _norm(source):
            raise MathLibError(
                "OUTPUT_FRACTION_NOT_IN_SOURCE",
                "fractionを使う根拠（「分数で」など）がsourceにない。指定がなければoutputは付けない",
                source=source,
            )
        return {"format": "fraction", "source": source}

    places = spec.get("places")
    if isinstance(places, bool) or not isinstance(places, int) or not (0 <= places <= MAX_PLACES):
        raise MathLibError(
            "OUTPUT_PLACES_INVALID",
            f"places は 0〜{MAX_PLACES} の整数で必ず書く（桁数を自分で決めないこと）",
            got=repr(places),
        )
    rounding = spec.get("rounding")
    mode = rounding if rounding is not None else DEFAULT_ROUNDING
    if mode not in ROUNDING_MODES:
        raise MathLibError(
            "OUTPUT_ROUNDING_INVALID", f"roundingが不正: {mode!r}", available=list(ROUNDING_MODES)
        )

    if text is not None:
        ns = _norm(source)
        digits = [int(t) for t in re.findall(r"\d+", ns)]
        if digits and places not in digits:
            raise MathLibError(
                "OUTPUT_PLACES_MISMATCH",
                f"places={places} がsource内の数字{digits}と一致しない",
                places=places,
                source=source,
            )
        kws = [k for k in ROUNDING_KEYWORDS if k in ns]
        if kws:
            allowed = set().union(*(ROUNDING_KEYWORDS[k] for k in kws))
            if mode not in allowed:
                raise MathLibError(
                    "OUTPUT_ROUNDING_MISMATCH",
                    f"sourceの「{'・'.join(kws)}」と rounding={mode} が合わない"
                    f"（{DEFAULT_ROUNDING}は省略時の既定）",
                    rounding=mode,
                    allowed=sorted(allowed),
                    source=source,
                )
        elif mode != DEFAULT_ROUNDING:
            raise MathLibError(
                "OUTPUT_ROUNDING_NOT_IN_SOURCE",
                f"rounding={mode} を指定する根拠がsourceにない（指定がなければ省略する）",
                rounding=mode,
                source=source,
            )
    return {"format": f, "places": places, "rounding": mode, "source": source}


def format_output(final, o):
    """厳密値 final を、確定したoutput指定で整形する。"""
    if o["format"] == "fraction":
        return {
            "exact": fmt(final),
            "display": fmt(final),
            "output": {"format": "fraction"},
            "is_rounded": False,
            "rounding_error": "0",
        }
    percent = o["format"] == "percent"
    scale = 10 ** o["places"]
    base = final * 100 if percent else final
    q = round_q(base * scale, o["rounding"])
    shown = fmt_scaled(q, o["places"]) + ("%" if percent else "")
    rounded_ratio = Fraction(q, scale) / (100 if percent else 1)
    err = rounded_ratio - final
    # 検算: 誤差は1単位(半分単位)以内
    unit = Fraction(1, scale) / (100 if percent else 1)
    bound = unit / 2 if o["rounding"] in ("half_up", "half_even") else unit
    if abs(err) > bound:
        raise MathLibError("CHECK_FAILED", "出力の丸め誤差が許容範囲を超えた", error=fmt(err))
    return {
        "exact": fmt(final),
        "display": shown,
        "output": {k: o[k] for k in ("format", "places", "rounding")},
        "is_rounded": err != 0,
        "rounding_error": fmt(err),
    }


# ---------------------------------------------------------------
# runner: planを実行して trace を作る
# ---------------------------------------------------------------
def run_plan(plan, text=None):
    """
    plan = {
      "values": [{"id":"v1","value":"3","source":"3個"}, ...],
      "steps":  [{"id":"s1","rule":"add","inputs":["v1","v2"]}, ...],
      "output": {"format":"decimal","places":1,"rounding":"half_up","source":"..."}   # 任意
    }
    text を渡すと、各値とoutputのsourceを元の文と照合する。
    戻り値: {"ok":True,"answer":{...},"trace":[...]} / {"ok":False,"error":{...},"trace":[...]}
    """
    nodes = {}
    trace = []
    warnings = []
    try:
        for v in plan.get("values", []):
            vid = v.get("id")
            if not vid or vid in nodes or vid in RESERVED_IDS:
                raise MathLibError("BAD_ID", f"idが空・重複・予約語: {vid!r}", id=vid)
            num = to_number(v.get("value"))
            if text is not None:
                _check_source(vid, num, v.get("source"), text)
            nodes[vid] = num
            trace.append(
                {"id": vid, "type": "value", "value": fmt(num), "source": v.get("source")}
            )

        steps = plan.get("steps", [])
        if not steps:
            raise MathLibError("NO_STEPS", "stepsが空")

        for s in steps:
            sid = s.get("id")
            if not sid or sid in nodes or sid in RESERVED_IDS:
                raise MathLibError("BAD_ID", f"idが空・重複・予約語: {sid!r}", id=sid)
            rule = RULES.get(s.get("rule"))
            if rule is None:
                raise MathLibError(
                    "UNKNOWN_RULE",
                    f"未登録のルール: {s.get('rule')!r}",
                    available=list(RULES),
                )
            refs = s.get("inputs", [])
            if len(refs) != rule["arity"]:
                raise MathLibError(
                    "BAD_ARITY",
                    f"{s['rule']}は入力{rule['arity']}個が必要（{len(refs)}個渡された）",
                    id=sid,
                )
            for r in refs:
                if r not in nodes:
                    raise MathLibError("UNKNOWN_REF", f"{sid}: 参照先{r!r}が存在しない", id=sid)
            ins = [nodes[r] for r in refs]
            dom = rule["domain"](ins)
            if dom:
                raise MathLibError(dom[0], f"{sid}: {dom[1]}", id=sid, rule=s["rule"])
            result = rule["run"](*ins)
            if not rule["check"](ins, result):
                raise MathLibError("CHECK_FAILED", f"{sid}: 検算に失敗", id=sid)
            nodes[sid] = result
            trace.append(
                {
                    "id": sid,
                    "type": "step",
                    "rule": s["rule"],
                    "inputs": refs,
                    "input_values": [fmt(x) for x in ins],
                    "value": fmt(result),
                    "expr": f"{disp(ins[0])} {rule['symbol']} {disp(ins[1])} = {disp(result)}",
                    "check": "ok",
                    "depends_on": rule["depends_on"],
                }
            )

        used = {r for s_ in steps for r in s_.get("inputs", [])}
        for v in plan.get("values", []):
            if v["id"] not in used:
                warnings.append(
                    {
                        "code": "UNUSED_VALUE",
                        "id": v["id"],
                        "message": f"{v['id']}（{v.get('value')}）はどのステップでも使われていない",
                    }
                )

        final = nodes[steps[-1]["id"]]
        if plan.get("output") is None:
            answer = {"exact": fmt(final), "decimal": to_decimal(final)}
        else:
            o = resolve_output(plan["output"], text)
            answer = format_output(final, o)
            trace.append(
                {
                    "id": "out",
                    "type": "output",
                    "value": answer["display"],
                    "exact": answer["exact"],
                    "format": o["format"],
                    "places": o.get("places"),
                    "rounding": o.get("rounding"),
                    "source": o.get("source"),
                    "is_rounded": answer["is_rounded"],
                    "rounding_error": answer["rounding_error"],
                    "check": "ok",
                }
            )
        return {"ok": True, "answer": answer, "trace": trace, "warnings": warnings}
    except MathLibError as e:
        return {"ok": False, "error": e.to_dict(), "trace": trace, "warnings": warnings}


# ---------------------------------------------------------------
# 人間向けの表示（正本はtrace、これは自動生成）
# ---------------------------------------------------------------
def explain(result):
    lines = []
    for t in result["trace"]:
        if t["type"] == "value":
            src = f"  （元の文:「{t['source']}」）" if t.get("source") else ""
            lines.append(f"{t['id']} = {t['value']}{src}")
        elif t["type"] == "step":
            lines.append(
                f"{t['id']}: {t['expr']}  [{t['rule']} / 検算:{t['check']} / 根拠:{'・'.join(t['depends_on'])}]"
            )
        else:  # output
            if t["format"] == "fraction":
                lines.append(f"出力: 分数のまま {t['value']}")
            else:
                unit = "%" if t["format"] == "percent" else ""
                lines.append(
                    f"出力: 小数第{t['places']}位{('（' + unit + '）') if unit else ''}、"
                    f"{MODE_JA[t['rounding']]} → {t['value']}"
                    f"  （厳密値 {t['exact']} / 丸め誤差 {t['rounding_error']}）"
                )
    if result["ok"]:
        a = result["answer"]
        if "display" in a:
            lines.append(f"答え: {a['display']}  （厳密値 {a['exact']}）")
        else:
            approx = "（近似）" if a["decimal"]["is_approx"] else ""
            lines.append(f"答え: {a['exact']}  ≒ {a['decimal']['value']}{approx}")
    else:
        e = result["error"]
        lines.append(f"エラー[{e['code']}]: {e['message']}")
    for w in result.get("warnings", []):
        lines.append(f"警告[{w['code']}]: {w['message']}")
    return "
".join(lines)


# ---------------------------------------------------------------
# CLI
#   python mathlib/mathlib.py --rules
#   python mathlib/mathlib.py plan.json "元の文"
# ---------------------------------------------------------------
def main(argv):
    if len(argv) >= 2 and argv[1] == "--rules":
        print(json.dumps(list_rules(), ensure_ascii=False, indent=2))
        return 0
    if len(argv) < 2:
        print("usage: python mathlib/mathlib.py --rules | python mathlib/mathlib.py plan.json [元の文]")
        return 1
    plan_path = Path(argv[1])
    with plan_path.open(encoding="utf-8") as f:
        plan = json.load(f)
    text = argv[2] if len(argv) >= 3 else None
    result = run_plan(plan, text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("
--- 人間向け ---")
    print(explain(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
