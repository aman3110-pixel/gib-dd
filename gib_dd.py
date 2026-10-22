#!/usr/bin/env python3
"""gib-dd: turn a Solana token risk scan into a crowd-sourced due-diligence bounty on Gibwork.

Terminal workflow (no web app):
  scan    run a read-only on-chain/DEX check on a mint, then write task.json + report.md
          (a Gibwork bounty that asks human researchers to verify each red flag)
  post    create the bounty with the official Gibwork CLI (`gibwork task create --from task.json`)
          DRY-RUN by default; real funding only with --live, and never above --max-usdc
  review  score submissions (`gibwork --json submission list <task-id> --all`) against the
          evidence checklist and print approve/reject *suggestions* + the exact CLI command.
          It never approves or pays on its own.
  demo    fully offline run on bundled sample data (no network, no wallet)

Keys: never read or stored by this tool. The Gibwork CLI loads its own keypair
(GIBWORK_KEYPAIR_PATH / --keypair / profile). Education only. Not financial advice.
License: MIT
"""
import argparse, datetime as dt, html, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPLORERS = ("solscan.io", "explorer.solana.com", "solana.fm", "orb.helius.dev", "dexscreener.com")
SIG_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{43,88}\b")  # base58 address / signature

# ---------- 1. scan: token check -> research questions ----------
QUESTION_FOR = [
    ("Mint authority is ACTIVE", "Who controls the mint authority? Find the authority address, whether it is a multisig/program, and any public statement about renouncing it."),
    ("Freeze authority is ACTIVE", "Who controls the freeze authority, and has it ever been used? Link any freeze transactions or confirm none exist."),
    ("Top 10 accounts hold", "Label the top 10 holder accounts (LP pool, burn/lock, CEX, team, unknown). Link each address on an explorer."),
    ("Tiny pool", "Where is liquidity held, is the LP locked or burned, and until when? Link the LP token holder / lock transaction."),
    ("Liquidity is", "Is there significant off-chain/CEX liquidity that explains the low on-chain liquidity ratio? Cite the exchange listing."),
    ("No DEX pair found", "Is this mint traded anywhere? Find any pool or confirm there is none."),
    ("Almost no trading", "Is the token abandoned? Find the last meaningful on-chain activity and the team's last public update."),
    ("Pair is only", "Who deployed the token and pool? Link the creation transactions and the deployer's other tokens."),
]
BASE_QUESTIONS = [
    "Identify the official project website / X account and show that it lists THIS exact mint address (impostor tickers are common).",
    "Summarise in 3-5 bullet points what a beginner should double-check before interacting with this token.",
]

def questions_from(report):
    qs = []
    for flag in report.get("red_flags", []):
        for key, q in QUESTION_FOR:
            if flag.startswith(key) and q not in qs:
                qs.append(q)
    for n in report.get("notes", []):
        if n.startswith("Token-2022") and "token-2022" not in " ".join(qs).lower():
            qs.append("Token-2022: list the enabled extensions (transfer fee, transfer hook, permanent delegate) and what each means for holders.")
    return qs + BASE_QUESTIONS

def build_task(report, reward, min_sub, deadline_days):
    mint, sym = report["mint"], report.get("symbol") or "this token"
    qs = questions_from(report)
    flags = report.get("red_flags") or ["none found by the automated check"]
    deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=deadline_days)).replace(microsecond=0)
    li = lambda xs: "".join(f"<li><p>{html.escape(x)}</p></li>" for x in xs)
    content = (
        f"<p><strong>Community due-diligence check for {html.escape(sym)}</strong> (mint <code>{mint}</code>).</p>"
        f"<p>An automated read-only scan (Solana RPC + DexScreener) raised these flags:</p><ul>{li(flags)}</ul>"
        f"<h3>Answer each question with evidence</h3><ol>{li(qs)}</ol>"
        "<h3>Acceptance criteria</h3><ul>"
        f"<li><p>Mentions the exact mint <code>{mint}</code>.</p></li>"
        "<li><p>Every claim links to on-chain evidence (Solscan / Solana Explorer / SolanaFM) or a primary source.</p></li>"
        "<li><p>Answers are numbered Q1..Qn to match the questions above. Unknown is an acceptable answer if you explain what you checked.</p></li>"
        "<li><p>No price predictions, no buy/sell calls, no referral links. This is research, not promotion.</p></li></ul>"
        "<p>Education only. Not financial advice.</p>")
    return {
        "title": f"Due-diligence check: verify {len(qs)} on-chain facts about {sym}"[:120],
        "content": content,
        "tags": ["Research", "Solana"],
        "payment": {"amount": f"{reward:.2f}"},
        "minSubmissionAmount": f"{min_sub:.2f}",
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
    }, qs

def write_kit(report, task, qs, out):
    os.makedirs(out, exist_ok=True)
    json.dump(report, open(os.path.join(out, "scan.json"), "w"), indent=1)
    json.dump(task, open(os.path.join(out, "task.json"), "w"), indent=1)
    json.dump({"mint": report["mint"], "questions": qs}, open(os.path.join(out, "checklist.json"), "w"), indent=1)
    md = [f"# gib-dd report: {report.get('symbol') or report['mint']}", "",
          f"- Mint: `{report['mint']}`", f"- Red flags: {len(report.get('red_flags', []))}"]
    md += [f"  - {f}" for f in report.get("red_flags", [])]
    md += ["", "## Bounty questions"] + [f"{i}. {q}" for i, q in enumerate(qs, 1)]
    md += ["", f"Reward pool: {task['payment']['amount']} USDC, min payout {task['minSubmissionAmount']}, deadline {task['deadline']}",
           "", "Education only. Not financial advice."]
    open(os.path.join(out, "report.md"), "w").write("\n".join(md) + "\n")

def cmd_scan(a):
    if a.reward > a.max_usdc:
        sys.exit(f"refused: reward {a.reward} > --max-usdc {a.max_usdc}")
    if a.from_scan:
        report = json.load(open(a.from_scan))
    else:
        sys.path.insert(0, HERE)
        import token_check
        report = token_check.check(a.mint)
    if report.get("error"):
        sys.exit(f"scan error: {report['error']}")
    task, qs = build_task(report, a.reward, a.min_submission, a.deadline_days)
    out = a.out or os.path.join("runs", report["mint"][:8])
    write_kit(report, task, qs, out)
    print(f"[scan] {len(report.get('red_flags', []))} red flag(s) -> {len(qs)} research questions")
    print(f"[scan] wrote {out}/task.json, checklist.json, report.md, scan.json")
    print(f"[next] python3 gib_dd.py post {out} --max-usdc {a.max_usdc}        # dry-run")
    return out

# ---------- 2. post: Gibwork CLI, dry-run by default ----------
def gibwork_bin():
    return os.environ.get("GIBWORK_BIN") or shutil.which("gibwork") or "npx -y @gibwork/cli"

def cmd_post(a):
    task = json.load(open(os.path.join(a.dir, "task.json")))
    amt = float(task["payment"]["amount"])
    if amt > a.max_usdc:
        sys.exit(f"refused: task amount {amt} USDC exceeds spend cap --max-usdc {a.max_usdc}")
    cmd = gibwork_bin().split() + ["--json", "--environment", a.environment, "task", "create", "--from", os.path.join(a.dir, "task.json")]
    print("[post] spend cap OK:", amt, "<=", a.max_usdc, "USDC")
    print("[post] command:", " ".join(cmd))
    if not a.live:
        print("[post] DRY-RUN (default). Nothing sent. Re-run with --live to create and fund the bounty;")
        print("       the Gibwork CLI will show its quote and ask for confirmation before signing.")
        return 0
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    open(os.path.join(a.dir, "post-result.json"), "w").write(r.stdout)
    print(r.stdout)
    return r.returncode

# ---------- 3. review: score submissions against the checklist ----------
def score(sub, mint, n_q):
    text = re.sub("<[^>]+>", " ", sub.get("content") or "")
    links = re.findall(r"https?://[^\s\"'<>]+", sub.get("content") or "")
    ev = [l for l in links if any(e in l for e in EXPLORERS)]
    answered = {int(m) for m in re.findall(r"\bQ\s?(\d{1,2})\b", text) if 0 < int(m) <= n_q}
    checks = {
        "mentions_mint": mint in text,
        "explorer_evidence": len(ev) >= max(2, n_q // 2),
        "answers_all_questions": len(answered) >= n_q,
        "no_promo": not re.search(r"\b(buy now|100x|to the moon|ref(erral)?=|guaranteed)\b", text, re.I),
        "substantive": len(text.split()) >= 120,
    }
    pts = sum(checks.values())
    verdict = "APPROVE?" if pts == len(checks) else ("NEEDS-WORK" if pts >= 3 else "REJECT?")
    missing = [k for k, v in checks.items() if not v]
    return dict(id=sub.get("id"), user=(sub.get("user") or {}).get("username"), points=pts, of=len(checks),
                answered=sorted(answered), evidence_links=len(ev), verdict=verdict, missing=missing)

def cmd_review(a):
    ck = json.load(open(os.path.join(a.dir, "checklist.json")))
    if a.from_file:
        raw = json.load(open(a.from_file))
    else:
        cmd = gibwork_bin().split() + ["--json", "--environment", a.environment, "submission", "list", a.task_id, "--all"]
        print("[review] command:", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"gibwork CLI failed ({r.returncode}): {r.stderr.strip()[:300]}")
        raw = json.loads(r.stdout)
    data = raw.get("data", raw) if isinstance(raw, dict) else raw
    subs = data.get("results", data) if isinstance(data, dict) else data
    rows = sorted((score(s, ck["mint"], len(ck["questions"])) for s in subs), key=lambda r: -r["points"])
    json.dump(rows, open(os.path.join(a.dir, "review.json"), "w"), indent=1)
    print(f"[review] {len(rows)} submission(s), {len(ck['questions'])} questions")
    print(f"{'user':<16}{'score':<7}{'Q answered':<14}{'links':<7}verdict / missing")
    for r in rows:
        print(f"{str(r['user'])[:15]:<16}{r['points']}/{r['of']:<5}{len(r['answered']):<14}{r['evidence_links']:<7}{r['verdict']} {','.join(r['missing'])}")
    task_id = a.task_id or "<task-id>"
    print("\n[review] suggestions only. A human decides. Commands to run yourself:")
    for r in rows:
        if r["verdict"] == "APPROVE?":
            print(f"  gibwork submission approve {task_id} {r['id']} --amount <decimal>")
        elif r["verdict"] == "REJECT?":
            print(f"  gibwork submission reject {task_id} {r['id']}   # missing: {', '.join(r['missing'])}")
    print(f"[review] wrote {a.dir}/review.json")

# ---------- 4. demo: offline ----------
def cmd_demo(a):
    out = a.out or os.path.join("runs", "demo")
    ns = argparse.Namespace(mint=None, from_scan=os.path.join(HERE, "samples", "scan-sample.json"), reward=10.0,
                            min_submission=2.0, deadline_days=5, out=out, max_usdc=10.0)
    print("== 1/3 scan (offline sample) =="); cmd_scan(ns)
    print("\n== 2/3 post (dry-run) =="); cmd_post(argparse.Namespace(dir=out, max_usdc=10.0, live=False, environment="stage"))
    print("\n== 3/3 review (sample submissions) ==")
    cmd_review(argparse.Namespace(dir=out, task_id="demo-task", from_file=os.path.join(HERE, "samples", "submissions-sample.json"), environment="stage"))

def main(argv=None):
    p = argparse.ArgumentParser(prog="gib-dd", description=__doc__.split("\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan"); s.add_argument("mint", nargs="?"); s.add_argument("--from-scan")
    s.add_argument("--reward", type=float, default=10.0); s.add_argument("--min-submission", type=float, default=2.0)
    s.add_argument("--deadline-days", type=int, default=5); s.add_argument("--out"); s.add_argument("--max-usdc", type=float, default=10.0)
    s.set_defaults(f=cmd_scan)
    s = sp.add_parser("post"); s.add_argument("dir"); s.add_argument("--max-usdc", type=float, default=10.0)
    s.add_argument("--live", action="store_true"); s.add_argument("--environment", default="stage", choices=["stage", "production"])
    s.set_defaults(f=cmd_post)
    s = sp.add_parser("review"); s.add_argument("dir"); s.add_argument("task_id", nargs="?"); s.add_argument("--from-file")
    s.add_argument("--environment", default="stage", choices=["stage", "production"]); s.set_defaults(f=cmd_review)
    s = sp.add_parser("demo"); s.add_argument("--out"); s.set_defaults(f=cmd_demo)
    a = p.parse_args(argv)
    if a.cmd == "scan" and not (a.mint or a.from_scan):
        p.error("scan needs a MINT or --from-scan FILE")
    r = a.f(a)
    sys.exit(r if isinstance(r, int) else 0)

if __name__ == "__main__":
    main()
