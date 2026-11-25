#!/usr/bin/env python3
"""prompt-eval を使うと、CLAUDE.md の変更の判定が当たりやすくなるかを測る。

題材・判定の決まり・結果は README.md にある。本物の claude -p を呼ぶので、時間と費用がかかる。

  python3 evals/skill-effect/run.py truth   # 各変更の正解を作る
  python3 evals/skill-effect/run.py arms    # 差分を読んで答える腕と、スキルを使う腕を走らせる
  python3 evals/skill-effect/run.py score   # 正解と突き合わせ、results.json と表を出す
  python3 evals/skill-effect/run.py followup   # 採点のあとに足した確認（採点には入れない）
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MATERIALS = HERE / "materials"
PLUGIN = ROOT / "plugins" / "prompt-eval"
SPEC = json.loads((MATERIALS / "changes.json").read_text())
CHANGES = {c["id"]: c for c in SPEC["changes"]}
FOLLOWUP = json.loads((MATERIALS / "followup.json").read_text())

# 測定する人の設定が結果に混ざらないよう、ユーザー設定（グローバルの CLAUDE.md・プラグイン・フック）と
# MCP サーバーを読まずに起動する。リポジトリの CLAUDE.md は本来の経路で読まれる
CLAUDE = ["claude", "--setting-sources", "project,local", "--strict-mcp-config"]
TRUTH_RUNS = 8
ARM_REPEATS = 2
ARMS = ("reading", "skill")
USAGE_LIMIT = re.compile(r"usage limit|rate limit|limit reached|quota", re.I)

ASK = """このリポジトリの CLAUDE.md を直した。まだコミットしていないので、HEAD が修正前、作業ツリーが修正後になっている。

意図: {intent}

差分:

```diff
{diff}
```

この変更について、次の 2 点を判定してほしい。

1. 意図した振る舞いの変化が、この変更によって実際に起きているか
2. 修正前に守られていた既存の振る舞いが、修正後に守られなくなっていないか（退行）

これは非対話の実行で、途中の質問や承認の依頼に答える人はいない。確認を求めずに最後まで進めること。費用がかかる手段を使う場合は、合計 15 ドルまで承認済みとして扱ってよい。時間のかかるコマンドは background にせず、完了まで待つこと（Bash の timeout は 600000 ミリ秒まで延ばせる）。

回答の最後に、判定を次の 2 行で、この形のまま書くこと。

INTENDED_CHANGE: yes / no / na のどれか
REGRESSION: yes / no のどれか

- INTENDED_CHANGE の yes は、修正後に意図した振る舞いが出ていて、修正前には出ていなかった場合。no は、それ以外（修正後も出ていない、または修正前から出ていた）。na は、振る舞いを変えない意図の変更の場合
- REGRESSION の yes は、修正前に守られていた振る舞いが、修正後に守られなくなった場合
"""


def child_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    # 入れ子の claude -p は CLAUDECODE が残っていると起動を拒む
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env.update(extra or {})
    return env


def make_repo(change_id: str, committed: str, worktree: str | None = None) -> Path:
    """題材のリポジトリを一時ディレクトリに作る。committed 版をコミットし、worktree 版があれば未コミットで上書きする。

    置き場をこのリポジトリの外にするのは、上の階層の CLAUDE.md が読まれるのを避けるため。
    """
    repo = Path(tempfile.mkdtemp()) / "inventory-api"
    shutil.copytree(MATERIALS / "repo", repo)
    src = MATERIALS / "changes" / change_id
    shutil.copy(src / f"{committed}.md", repo / "CLAUDE.md")
    git = ["git", "-C", str(repo), "-c", "user.name=eval", "-c", "user.email=eval@example.invalid"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run([*git, *args], check=True, capture_output=True)
    if worktree:
        shutil.copy(src / f"{worktree}.md", repo / "CLAUDE.md")
    return repo


def run_claude(prompt: str, cwd: Path, flags: list[str], out: Path, timeout: int, env: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [*CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence", *flags]
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=child_env(env), capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"status": "invalid:timeout", "seconds": round(time.time() - started)}
    (out / "transcript.jsonl").write_text(r.stdout)
    events = []
    for line in r.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    run = {"seconds": round(time.time() - started),
           "model": next((e.get("model") for e in events if e.get("subtype") == "init"), None)}
    if result is None:
        return {**run, "status": "invalid:no_result"}
    final = result.get("result") or ""
    (out / "final.md").write_text(final)
    trace = []
    for e in events:
        for c in (e.get("message", {}).get("content", []) if e.get("type") == "assistant" else []):
            if c.get("type") == "text":
                trace.append(f"[assistant] {c.get('text', '')}")
            elif c.get("type") == "tool_use":
                trace.append(f"[tool_use {c.get('name')}] {json.dumps(c.get('input'), ensure_ascii=False)}")
    run.update(turns=result.get("num_turns"), cost_usd=result.get("total_cost_usd"), final=final, trace="\n".join(trace))
    if result.get("is_error"):
        limited = USAGE_LIMIT.search(json.dumps(result, ensure_ascii=False))
        return {**run, "status": "invalid:usage_limit" if limited else f"invalid:{result.get('subtype', 'error')}"}
    return {**run, "status": "ok"}


def save(path: Path, data: dict) -> dict:
    path.write_text(json.dumps({k: v for k, v in data.items() if k not in ("final", "trace")},
                               ensure_ascii=False, indent=2))
    return data


def pool(jobs: int, fn, items: list) -> list:
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(fn, items))


# ---------------------------------------------------------------- 正解


def measure(args, kind: str, items: list[tuple[str, str, str]]) -> None:
    """items の (名前, 変更, 依頼) ごとに、修正前・修正後を TRUTH_RUNS 回ずつ走らせ、正規表現だけで数える。"""
    repos = {(cid, v): make_repo(cid, v) for _, cid, _ in items for v in ("before", "after")}
    flags = ["--tools", "Read,Glob,Grep", "--allowedTools", "Read Glob Grep",
             "--disallowedTools", "Bash Write Edit NotebookEdit", "--max-budget-usd", "1"]

    def one(job):
        name, cid, prompt, version, n = job
        out = args.out / kind / name / version / str(n)
        if (out / "run.json").exists() and json.loads((out / "run.json").read_text())["status"] == "ok":
            return
        run = run_claude(prompt, repos[(cid, version)], flags, out, timeout=300)
        run.update(change=cid, version=version, n=n)
        if run["status"] == "ok":
            run["checks"] = {check: bool(re.search(c["pattern"], run[c["target"]], flags=re.M))
                             for check, c in SPEC["checks"].items()}
        print(f"  {kind} {name} {version}#{n}: {run['status']}", file=sys.stderr, flush=True)
        save(out / "run.json", run)

    # 版と変更を交互に並べ、時間帯の偏りを散らす
    pool(args.jobs, one, [(name, cid, prompt, v, n) for n in range(TRUTH_RUNS)
                          for name, cid, prompt in items for v in ("before", "after")])
    for repo in repos.values():
        shutil.rmtree(repo.parent, ignore_errors=True)


def cmd_truth(args) -> None:
    measure(args, "truth", [(cid, cid, SPEC["subject_prompt"]) for cid in CHANGES])


def cmd_followup(args) -> None:
    """採点のあとに足した確認（materials/followup.json）。採点には入れない。"""
    measure(args, "followup", [(i["id"], i["change"], i["prompt"]) for i in FOLLOWUP["items"]])


def counts(runs: list[dict], check: str) -> dict:
    return {v: f"{sum(1 for r in runs if r['version'] == v and r['checks'][check])}/{sum(1 for r in runs if r['version'] == v)}"
            for v in ("before", "after")}


def load_followup(out: Path) -> list[dict]:
    rows = []
    for item in FOLLOWUP["items"]:
        runs = [json.loads(p.read_text()) for p in sorted((out / "followup" / item["id"]).glob("*/*/run.json"))]
        ok = [r for r in runs if r["status"] == "ok"]
        if ok:
            rows.append({**item, "checks": {c: counts(ok, c) for c in ("starts-with-summary", "ends-with-checked")}})
    return rows


def load_truth(out: Path) -> dict:
    hi = math.ceil(TRUTH_RUNS * 2 / 3)
    lo = TRUTH_RUNS - hi
    truth = {}
    for cid, change in CHANGES.items():
        runs = [json.loads(p.read_text()) for p in sorted((out / "truth" / cid).glob("*/*/run.json"))]
        ok = [r for r in runs if r["status"] == "ok"]

        def count(check, version):
            return sum(1 for r in ok if r["version"] == version and r["checks"][check])

        entry = {"valid": {v: sum(1 for r in ok if r["version"] == v) for v in ("before", "after")},
                 "models": sorted({r["model"] for r in ok if r.get("model")})}
        if change["intended_check"]:
            b, a = count(change["intended_check"], "before"), count(change["intended_check"], "after")
            verdict = "yes" if a >= hi and b <= lo else "no" if a - b <= 1 else "borderline"
            entry["intended"] = {"check": change["intended_check"], "before": b, "after": a, "truth": verdict}
        b, a = count(change["existing_check"], "before"), count(change["existing_check"], "after")
        verdict = "yes" if b >= hi and a <= lo else "no" if b - a <= 1 else "borderline"
        entry["regression"] = {"check": change["existing_check"], "before": b, "after": a, "truth": verdict}
        truth[cid] = entry
    return truth


# ---------------------------------------------------------------- 比べる腕


def answer(final: str, key: str, choices: str) -> str | None:
    found = re.findall(rf"{key}\W{{0,6}}({choices})\b", final, flags=re.I)
    return found[-1].lower() if found else None


def cmd_arms(args) -> None:
    """同じ依頼を、差分を読んで答える腕（reading）と、スキルを使う腕（skill）に渡す。"""
    flags = {
        "reading": ["--tools", "Read,Glob,Grep", "--allowedTools", "Read Glob Grep", "--max-budget-usd", "5"],
        "skill": ["--plugin-dir", str(PLUGIN), "--tools", "Read,Glob,Grep,Write,Edit,Bash,Skill",
                  "--allowedTools", "Read Glob Grep Write Edit Bash Skill",
                  "--disallowedTools", "Bash(rm *)", "Bash(mv *)", "Bash(sudo *)", "Bash(kill *)", "Bash(pkill *)",
                  "Bash(git push *)", "Bash(gh *)", "Bash(curl *)", "Bash(wget *)",
                  "--max-budget-usd", "15"],
    }
    # スキルの中のランナーが呼ぶ claude -p にも、同じ起動条件を渡す
    env = {"skill": {"PROMPT_EVAL_CLAUDE_BIN": " ".join(CLAUDE)}}

    def one(job):
        arm, cid, rep = job
        out = args.out / "arms" / arm / cid / str(rep)
        if (out / "run.json").exists() and json.loads((out / "run.json").read_text())["status"] == "ok":
            return
        repo = make_repo(cid, "before", worktree="after")
        diff = subprocess.run(["git", "-C", str(repo), "diff", "--", "CLAUDE.md"],
                              capture_output=True, text=True, check=True).stdout
        prompt = ASK.format(intent=CHANGES[cid]["intent"], diff=diff.strip())
        if arm == "skill":
            prompt = "/prompt-eval:prompt-eval " + prompt
        run = run_claude(prompt, repo, flags[arm], out, timeout=900 if arm == "reading" else 2700, env=env.get(arm))
        run.update(arm=arm, change=cid, rep=rep)
        if "final" in run:
            run["intended_change"] = answer(run["final"], "INTENDED_CHANGE", "yes|no|na")
            run["regression"] = answer(run["final"], "REGRESSION", "yes|no")
        if arm == "skill" and (repo / "evals").exists():
            # スキルが書いたケースを残す
            shutil.copytree(repo / "evals", out / "evals", dirs_exist_ok=True)
        shutil.rmtree(repo.parent, ignore_errors=True)
        print(f"  {arm} {cid}#{rep}: {run['status']} intended={run.get('intended_change')} "
              f"regression={run.get('regression')} ({run['seconds']}s)", file=sys.stderr, flush=True)
        save(out / "run.json", run)

    jobs = [(arm, cid, rep) for arm in args.arm for rep in range(ARM_REPEATS) for cid in CHANGES]
    pool(args.jobs, one, [j for j in jobs if j[0] == "reading"])
    # スキルの腕は、1 回の中でランナーが claude -p を 2 並列で呼ぶ。全体の並列を抑えるため 2 つずつ走らせる
    pool(max(1, args.jobs // 2), one, [j for j in jobs if j[0] == "skill"])


# ---------------------------------------------------------------- 突き合わせ

RUNNER_ROW = re.compile(r"^\| \S+ \| (?:change|regression) \| (—|\d+/\d+) \| (—|\d+/\d+) \|", re.M)


def runner_runs(transcript: Path) -> int:
    """スキルの腕で、ランナーが被験として走らせた claude -p のうち、有効だった回数。

    ランナーの記録の置き場はセッションごとに違うので、セッションの記録に残ったランナーの要約の表
    （「| ケース | 種別 | 合格/有効 | 合格/有効 |」の行）の有効数を足す。
    """
    count = 0
    for line in transcript.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "user" or not isinstance(event["message"].get("content"), list):
            continue
        for c in event["message"]["content"]:
            if c.get("type") != "tool_result":
                continue
            text = c.get("content")
            if isinstance(text, list):
                text = "\n".join(x.get("text", "") for x in text if isinstance(x, dict))
            count += sum(int(cell.split("/")[1]) for row in RUNNER_ROW.findall(text or "") for cell in row if cell != "—")
    return count


def cmd_score(args) -> None:
    truth = load_truth(args.out)
    sessions = []
    for p in sorted((args.out / "arms").glob("*/*/*/run.json")):
        run = json.loads(p.read_text())
        t = truth[run["change"]]
        scored = {}
        if "intended" in t and t["intended"]["truth"] != "borderline":
            scored["intended_change"] = run.get("intended_change") == t["intended"]["truth"]
        if t["regression"]["truth"] != "borderline":
            scored["regression"] = run.get("regression") == t["regression"]["truth"]
        answered = run.get("intended_change") is not None or run.get("regression") is not None
        # 利用上限や時間切れで答えが出なかった回は、不一致ではなく無効として分ける
        valid = run["status"] == "ok" or answered
        sessions.append({k: run.get(k) for k in ("arm", "change", "rep", "status", "seconds", "turns", "cost_usd",
                                                 "model", "intended_change", "regression")}
                        | {"runner_subject_runs": runner_runs(p.parent / "transcript.jsonl") if run["arm"] == "skill" else 0,
                           "valid": valid, "scored": scored,
                           "all_correct": valid and bool(scored) and all(scored.values())})
    summary = {}
    for arm in ARMS:
        rows = [s for s in sessions if s["arm"] == arm and s["valid"]]
        questions = [ok for s in rows for ok in s["scored"].values()]
        summary[arm] = {
            "sessions": len(rows), "invalid": sum(1 for s in sessions if s["arm"] == arm and not s["valid"]),
            "changes_all_correct": sum(1 for s in rows if s["all_correct"]),
            "questions": len(questions), "questions_correct": sum(questions),
            "seconds_total": sum(s["seconds"] or 0 for s in rows),
            "runner_subject_runs": sum(s["runner_subject_runs"] for s in rows),
        }
    followup = load_followup(args.out)
    results = {"truth_runs": TRUTH_RUNS, "arm_repeats": ARM_REPEATS, "truth": truth, "summary": summary,
               "sessions": sessions, "followup": followup}
    (HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")

    print("| 変更 | 題材の狙い | 意図した振る舞い（前 → 後） | 既存の振る舞い（前 → 後） | 正解: 意図した変化 | 正解: 退行 |")
    print("|---|---|---|---|---|---|")
    for cid, t in truth.items():
        i = t.get("intended")
        print(f"| {cid} | {CHANGES[cid]['designed_as']} | "
              + (f"{i['before']}/{t['valid']['before']} → {i['after']}/{t['valid']['after']}" if i else "—")
              + f" | {t['regression']['before']}/{t['valid']['before']} → {t['regression']['after']}/{t['valid']['after']}"
              + f" | {i['truth'] if i else '（問わない）'} | {t['regression']['truth']} |")
    print()
    print("| 変更 | " + " | ".join(f"{arm} #{r}" for arm in ARMS for r in range(ARM_REPEATS)) + " |")
    print("|---|" + "---|" * (len(ARMS) * ARM_REPEATS))
    for cid in CHANGES:
        cells = []
        for arm in ARMS:
            for rep in range(ARM_REPEATS):
                s = next((s for s in sessions if (s["arm"], s["change"], s["rep"]) == (arm, cid, rep)), None)
                if s is None:
                    cells.append("未実行")
                elif not s["valid"]:
                    cells.append(f"無効（{s['status']}）")
                else:
                    cells.append(f"{'○' if s['all_correct'] else '×'} {s['intended_change']}/{s['regression']}")
        print(f"| {cid} | " + " | ".join(cells) + " |")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for row in followup:
        print(f"followup {row['id']}: " + json.dumps(row["checks"], ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["truth", "arms", "score", "followup"])
    ap.add_argument("--out", type=Path, default=ROOT / "tmp" / "skill-effect", help="生の記録の置き場（git の管理外）")
    ap.add_argument("--jobs", type=int, default=4, help="同時に走らせる claude -p の数")
    ap.add_argument("--arm", action="append", choices=ARMS, help="走らせる腕（既定は両方）")
    args = ap.parse_args()
    args.arm = args.arm or list(ARMS)
    {"truth": cmd_truth, "arms": cmd_arms, "score": cmd_score, "followup": cmd_followup}[args.cmd](args)


if __name__ == "__main__":
    main()
