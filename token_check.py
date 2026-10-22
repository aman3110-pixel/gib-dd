#!/usr/bin/env python3
"""token_check.py - free, read-only Solana token safety check (CRYPTO, CLEARLY).
Uses only public endpoints: DexScreener API + Solana JSON-RPC. No wallet, no keys, no signing.
Usage: python3 token_check.py <MINT> [<MINT> ...]   (env RPC_URL to use your own RPC)
Education only. A clean result is NOT a safety guarantee. NFA.  License: MIT
"""
import json, os, sys, time, urllib.error, urllib.request

RPC = os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com")

def _get(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "solana-token-check/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=25))

def rpc(method, params, tries=3):
    for i in range(tries):
        try:
            r = _get(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]

def check(mint):
    flags, notes = [], []
    acct = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    if not acct:
        return {"mint": mint, "error": "account not found"}
    data = acct.get("data")
    if not isinstance(data, dict) or (data.get("parsed") or {}).get("type") != "mint":
        return {"mint": mint, "error": "not an SPL token mint account"}
    info = data["parsed"]["info"]
    program = acct["owner"]
    supply = float(info["supply"]) / 10 ** info["decimals"]
    if info.get("mintAuthority"):
        flags.append("Mint authority is ACTIVE: more tokens can be created")
    if info.get("freezeAuthority"):
        flags.append("Freeze authority is ACTIVE: holders' tokens can be frozen")
    if program != "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
        notes.append("Token-2022 program: also check extensions (transfer fee/hook, permanent delegate)")
    top1 = top10 = None
    try:
        la = rpc("getTokenLargestAccounts", [mint])["value"]
        amts = [float(a.get("uiAmount") or 0) for a in la]
        if supply and amts:
            top1, top10 = amts[0] / supply * 100, sum(amts[:10]) / supply * 100
            notes.append("Top accounts may include the liquidity pool or a burn/lock address: check them on an explorer")
            if top10 > 50:
                flags.append(f"Top 10 accounts hold {top10:.1f}% of supply")
    except Exception as e:
        notes.append(f"Holder check unavailable on this RPC ({str(e)[:60]})")
    allp = [p for p in (_get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}").get("pairs") or [])
            if p.get("chainId") == "solana"]
    # DexScreener also returns pairs where this mint is the QUOTE token (e.g. X/USDC);
    # their price/mcap describe the other token, so only use pairs where it is the base.
    pairs = [p for p in allp if (p.get("baseToken") or {}).get("address") == mint]
    mkt = {}
    if not pairs and allp:
        notes.append(f"Only used as a quote token in {len(allp)} DexScreener pair(s): no market data for this mint itself")
    elif not pairs:
        flags.append("No DEX pair found on DexScreener")
    else:
        p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0))
        liq = sum((x.get("liquidity") or {}).get("usd") or 0 for x in pairs)  # all Solana pairs
        mcap = p.get("marketCap") or p.get("fdv") or 0
        age_h = (time.time() * 1000 - (p.get("pairCreatedAt") or 0)) / 3.6e6 if p.get("pairCreatedAt") else None
        tx = (p.get("txns") or {}).get("h24") or {}
        mkt = dict(symbol=p["baseToken"]["symbol"], dex=p.get("dexId"), pair_url=p.get("url"),
                   price_usd=p.get("priceUsd"), mcap_usd=mcap, liquidity_usd_all_pairs=round(liq),
                   pair_age_hours=round(age_h, 1) if age_h is not None else None,
                   buys_24h=tx.get("buys"), sells_24h=tx.get("sells"))
        if liq < 10_000:
            flags.append(f"Tiny pool: only ${liq:,.0f} liquidity, small sells move the price a lot")
        if mcap and liq / mcap < 0.05:
            msg = f"Liquidity is {liq / mcap * 100:.1f}% of market cap (${liq:,.0f} vs ${mcap:,.0f})"
            # large caps also trade on CEXs, so a low on-chain ratio is a note, not a red flag
            (notes if mcap > 50_000_000 else flags).append(msg)
        if (tx.get("buys") or 0) + (tx.get("sells") or 0) < 20:
            flags.append("Almost no trading in the last 24h")
        if age_h is not None and age_h < 24:
            flags.append(f"Pair is only {age_h:.1f}h old")
        if len(pairs) > 1:
            notes.append(f"{len(pairs)} Solana pairs found: confirm the mint, not just the ticker")
    return dict(mint=mint, supply=supply, top1_pct=top1, top10_pct=top10, **mkt, red_flags=flags, notes=notes)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for m in sys.argv[1:]:
        try:
            r = check(m)
        except Exception as e:  # network/RPC errors: report and continue with the next mint
            r = {"mint": m, "error": str(e)[:200]}
        print(json.dumps(r, indent=1))
        print(f"-> {len(r.get('red_flags', []))} red flag(s). Education only, not a safety guarantee. NFA.\n")
