# gib-dd: crowd-sourced token due diligence on Gibwork, from the terminal

**Gibwork Developer Hackathon entry (non-web-app track). Toolset: Gibwork CLI (`@gibwork/cli` 0.2.4, which wraps `@gibwork/sdk` 0.2.0).**

## The problem
New Solana tokens launch every minute. Automated scanners (mine included: [solana-token-check](https://github.com/aman3110-pixel/solana-token-check)) can flag *symptoms* such as an active mint authority, tiny liquidity or a pair that is a few minutes old, but they can't answer the human questions behind them. Who holds that authority? Is the LP locked? Does the "official" X account actually list this mint? Today that research is done ad hoc in Telegram chats, unpaid and unverified.

## The use case
`gib-dd` turns a machine scan into a **paid, evidence-based research bounty on Gibwork**, and then helps review the answers:

```
mint ──► scan (RPC + DexScreener, read-only) ──► red flags ──► research questions
     ──► task.json (valid Gibwork CreateTaskInput) ──► `gibwork task create` (dry-run by default, spend cap)
     ──► `gibwork submission list` ──► evidence checklist scoring ──► approve/reject *suggestions*
```

* Each red flag maps to a specific question (e.g. "Tiny pool" becomes "Where is liquidity held, is the LP locked/burned, link the lock tx").
* Acceptance criteria are generated with the bounty: exact mint mentioned, explorer evidence links, numbered answers Q1..Qn, and no promo or referral links.
* The reviewer scores every submission against those criteria and prints the exact `gibwork submission approve|reject` command. **It never approves, rejects or pays on its own.** A human runs the command.

It's useful for a community educator, a DAO risk team, or an AI agent that has to answer "is this token legit?" and needs humans for the parts it can't verify.

## Safety design
* **Dry-run by default.** `post` only prints the CLI command unless you pass `--live`.
* **Spend cap.** `--max-usdc` (default 10) is enforced in both `scan` and `post`, before the CLI is called.
* **No keys in this tool.** gib-dd never reads, stores or passes a private key. The Gibwork CLI loads its own keypair (`GIBWORK_KEYPAIR_PATH`, `--keypair` or a profile) and asks for confirmation before signing.
* **Stage environment by default.** Use `--environment production` explicitly.
* The scan is read-only (public RPC + DexScreener). Education only, not financial advice.

## Setup
Requirements: Python 3.9+ (stdlib only) and Node.js 22+ for the Gibwork CLI.
```bash
git clone https://github.com/aman3110-pixel/gib-dd.git && cd gib-dd
npm install --global @gibwork/cli      # or let gib-dd fall back to `npx -y @gibwork/cli`
python3 -m unittest discover -s tests  # 5 tests, offline
```
Optional env: `RPC_URL` (your own Solana RPC), `GIBWORK_BIN` (path to the gibwork binary).
Wallet (only for `--live` / `review` against the API), handled by the Gibwork CLI:
```bash
chmod 600 ~/.config/gibwork/id.json
gibwork --profile stage config set keypair-path ~/.config/gibwork/id.json
gibwork --profile stage wallet doctor
```

## Usage
```bash
python3 gib_dd.py demo                                   # offline, no wallet, no network
python3 gib_dd.py scan <MINT> --reward 10 --deadline-days 5 --out runs/x
python3 gib_dd.py post runs/x --max-usdc 10              # dry-run: prints the gibwork command
python3 gib_dd.py post runs/x --max-usdc 10 --live       # Gibwork CLI shows quote + asks to confirm
python3 gib_dd.py review runs/x <TASK_ID>                # pulls submissions via the CLI and scores them
python3 gib_dd.py review runs/x --from-file subs.json    # same, from a saved `gibwork --json submission list` file
```
Outputs in the run folder: `scan.json`, `task.json`, `checklist.json`, `report.md`, `review.json`, plus `post-result.json` after a live post.

## Sample output
`samples/demo-output.txt` is a full offline demo run. `samples/scan-sample.json` is a real read-only scan of a just-launched pump.fun token (captured 2026-10-22, picked at random, **not** a recommendation). `samples/submissions-sample.json` contains **fictional** submissions used only to demonstrate review scoring.

Compatibility check: the generated `task.json` passes the Gibwork CLI's own input validation (`gibwork --json --yes task create --from task.json` reaches the wallet step, `CREDENTIAL_ERROR` with no key configured, while a malformed file fails with `USAGE_ERROR: Invalid task input`).

## Limits (honest)
* The review scoring is a heuristic checklist, not a fact-checker. It catches missing evidence and promo, not subtle lies.
* Holder concentration needs an RPC that allows `getTokenLargestAccounts` (the public one rate-limits it).
* The live post/review path depends on Gibwork's API and an active platform wallet. It was not exercised with real funds in this prototype.

## License
MIT. `token_check.py` is vendored from solana-token-check (same author, MIT).
