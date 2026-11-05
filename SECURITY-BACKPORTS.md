# Security backports

Base: `ZephyrProtocol/zephyr` v2.3.0 (`67c5f53b878fef41fb5e74c4382d5b7a2f37fd8a`). Policy:
https://github.com/zephyr-backports/zephyr-backports (docs/POLICY.md). Each entry is one cherry-picked
Monero commit; the commit in this repository carries `(cherry picked from commit <sha>)`.

| # | Tag | Monero commit | Class | Component | Summary |
|---|---|---|---|---|---|
| SB-001 | v2.3.0-sec.1 | `74c313420` | memory | epee (both) | size overflow checked before the copy in `byte_slice` |
| SB-002 | v2.3.0-sec.1 | `1d3d30c50` | memory | crypto (both) | Cryptonight v1 helper throws instead of exiting on short input |
| SB-003 | v2.3.0-sec.1 | `7a7c42ffb` | memory | serialization (both) | truncated varint at end of input is an error, not a value |
| SB-004 | v2.3.0-sec.1 | `dedae5272` | memory | epee JSON (both) | off-by-one over-read in `\u` escape parsing |
| SB-005 | v2.3.0-sec.1 | `0b7967907` | dos | wallet2 | decoy picker rejects an empty output window instead of dividing by zero |
| SB-006 | v2.3.0-sec.1 | `72d91039e` | memory | wallet2 | cached transfer indices validated before use |
| SB-007 | v2.3.0-sec.1 | `987a2a77d` | memory | wallet2 | bounds check on additional derivations from on-chain `tx_extra` |
| SB-008 | v2.3.0-sec.1 | `ef7bdda92` | funds | wallet2 | block hash from the node validated before the hash chain is rebuilt |
| SB-009 | v2.3.0-sec.1 | `d9236332a` | dos | wallet2 (native) | refresh error handlers wait for worker threads |
| SB-010 | v2.3.0-sec.1 | `e62963ceb` | dos | dns_utils (both) | DNSSEC root trust anchor KSK-2024 added |

## Advisories

### SB-001 — `byte_slice`: size overflow checked before the copy

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `74c313420c1d22c5c8eecb8430fd5fe7a89143d7` (2024-11-19, "Fix memcpy in byte_slice constructor"), released in Monero v0.18.4.0
- **Class:** memory
- **Component:** epee (`contrib/epee/src/byte_slice.cpp`), both daemon and wallet
- **Affects:** every code path that concatenates buffers into a `byte_slice` (levin and HTTP transport, RPC responses). The sum of the source sizes was checked only after the `memcpy` into a buffer sized from that sum.
- **Impact:** with inputs whose sizes together overflow `size_t`, the allocation is too small and the copy writes past it before the check runs. Practical exploitation needs absurdly large inputs; the fix moves the overflow check before the allocation and makes the condition impossible rather than merely unlikely.
- **Compatibility statement:** no consensus, relay, wire or file-format change (one file in epee; only the overflow path behaves differently, by throwing `bad_alloc` earlier). POLICY §4 rules 1–5: not applicable beyond that.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests.
- **Notes:** none

### SB-002 — Cryptonight v1 helper throws instead of exiting on short input

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `1d3d30c5076200a308de4764491ace1d8a4d52af` (2025-07-11, "crypto: check+throw for Cryptonight v1 invalid input"), released in Monero v0.18.4.1. Reported to Monero by ADA Logics and the MAGIC Monero Fund.
- **Class:** memory (process termination on invalid input)
- **Component:** `src/crypto/hash.h`, both
- **Affects:** callers of `crypto::cn_slow_hash` with `variant = 1` and fewer than 43 input bytes; the low-level implementation aborts the process in that case. The fix checks first and throws an exception.
- **Impact:** a caller that can be reached with attacker-chosen short input would terminate the process. In Zephyr every block's proof of work is RandomX (`get_block_longhash` calls `rx_slow_hash` directly for all block versions) and the wallet calls `cn_slow_hash` with variant 0 only (key derivation in `chacha.h`, legacy seed passphrase), so no Zephyr path reaches variant 1 today. The hardening is kept because it is API-level and cost-free.
- **Compatibility statement:** no consensus change (Zephyr never computes a Cryptonight-v1 hash for a block), no relay, wire or file-format change; valid inputs produce identical results.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests.
- **Notes:** none

### SB-003 — Truncated varint at end of input is an error, not a value

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `7a7c42ffba1da6bd3f7bfd5a09ef9ae7275537a6` (2026-05-22, "serialization: handle EOF at varint boundary"), released in Monero v0.18.5.1
- **Class:** memory
- **Component:** `src/serialization/binary_archive.h`, both
- **Affects:** binary deserialisation of transactions and blocks (from peers, from the node, from the wallet cache). When the input ended exactly where a varint was expected, `read_varint` consumed zero bytes and the archive still reported success, leaving the field with its previous value and the parser positioned at end of data.
- **Impact:** malformed blobs could parse as "good" with uninitialised or stale field values, feeding later code with inconsistent structures. The fix requires at least one byte to have been read.
- **Compatibility statement:** POLICY §4.4 applies: this is stricter parsing. A varint of zero bytes is not a valid encoding, so no object that upstream accepts as valid can change outcome; the full-chain scan from height 0 (POLICY §6.4) is part of the evidence for this tag.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests (serialization tests); full-chain scan from height 0, zero rejections required.
- **Notes:** none

### SB-004 — Off-by-one over-read in JSON `\u` escape parsing

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `dedae5272d9d311464e8b25a5c57701591ac4eb1` (2026-06-01, "fix off-by-one over-read in match_string2 unicode escape parsing"), released in Monero v0.18.5.1
- **Class:** memory
- **Component:** epee JSON parser (`contrib/epee/src/parserse_base_utils.cpp`), both
- **Affects:** every JSON-RPC request and response parsed by the daemon or the wallet (node answers to the wallet, client requests to the node). A `\u` escape at the very end of the buffer passed the length check with one byte too few and the parser read one byte past the end.
- **Impact:** one-byte over-read on malformed JSON from an untrusted peer or node; a crash or an information leak of one byte depending on the allocation. The check now requires five remaining bytes (`u` plus four hex digits).
- **Compatibility statement:** no consensus, relay, wire or file-format change. Valid JSON always has at least a closing quote after the escape, so only never-valid input is affected.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests; webwallet harness (every RPC call exercises this parser).
- **Notes:** none

### SB-005 — Decoy picker rejects an empty output window

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `0b7967907f82867d2884c559396543212600509e` (2026-07-10, "wallet2: guard gamma picker against zero-output windows"), on Monero master. Monero master counterpart of release-v0.18 `7507aed69f4753767711d52747a02e6860b01297` (POLICY §2): it adds the same guard and corrects the master-only unit test `select_outputs.exact_unlock_block_tiny`, which Zephyr carries, to a cumulative distribution. The release-v0.18 form was released in Monero v0.18.5.3
- **Class:** dos (and privacy)
- **Component:** `src/wallet/wallet2.cpp`, `gamma_picker`; `tests/unit_tests/output_selection.cpp`
- **Affects:** transaction construction. The output-distribution data the node returns defines the window the gamma picker draws decoys from; a window with zero outputs led to a division by zero in `average_output_time`.
- **Impact:** a node can answer `get_output_distribution` so that the wallet hangs or loops while selecting decoys, or selects degenerate decoys. The wallet now throws before using such a window.
- **Compatibility statement:** no consensus, relay, wire or file-format change; wallet-internal check on data from the node.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`), including `select_outputs.exact_unlock_block_tiny`, the test this pick corrects, which passes on the branch. Pending: fork CI build and unit tests; webwallet harness (send flow).
- **Notes:** the monotonicity check on the same data (`b99d15f08`) needs a context-only resolution and is planned for `-sec.2`.

### SB-006 — Cached transfer indices validated before use

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `72d91039eb5c67c7912ef8328299e8e28d9effb0` (2026-07-22, "wallet2: validate cached transfer indices"), released in Monero v0.18.5.3. Reported to Monero by hacksandhops.
- **Class:** memory
- **Component:** `src/wallet/wallet2.cpp` (`process_new_transaction`, `load_wallet_cache`, `get_spend_proof`)
- **Affects:** the wallet's key-image and public-key caches map to indices into `m_transfers`. A corrupt or crafted wallet cache, or an inconsistent state after a partial load, put an index beyond the vector's size into use without a check.
- **Impact:** out-of-bounds read or write on the transfer vector while scanning a transaction, loading the cache or building a spend proof. The fix validates every cached index on load and at the three use sites and throws a wallet error instead.
- **Compatibility statement:** no consensus, relay or wire change; no file-format change (the cache format is unchanged; a cache with out-of-range indices was already corrupt and now fails to load cleanly instead of misbehaving).
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests; cross-open of wallet files both ways with the upstream binary.
- **Notes:** none

### SB-007 — Bounds check on additional derivations from on-chain `tx_extra`

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `987a2a77d3e4b4d3781e70bc70031ff254313557` (2026-07-22, "wallet2: bounds check additional derivations in is_out_to_acc"), released in Monero v0.18.5.3
- **Class:** memory
- **Component:** `src/wallet/wallet2.cpp`, `is_out_to_acc`
- **Affects:** scanning of transactions whose `tx_extra` carries additional public keys; the wallet indexes the derived additional derivations by output index. A transaction with fewer additional keys than outputs, which anyone can put on chain, made the index run past the vector.
- **Impact:** out-of-bounds read during chain scanning, triggered by on-chain data. The wallet now throws for such a transaction.
- **Compatibility statement:** no consensus, relay, wire or file-format change; wallet-side check only. The transaction itself remains as valid or invalid as upstream says.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests; webwallet harness (full scan from the restore height).
- **Notes:** none

### SB-008 — Block hash from the node validated before the hash chain is rebuilt

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `ef7bdda92af255270a61e4ea4c6c7fe098a70dd0` (2026-09-19, "wallet2: validate block hash when repairing empty hashchain"), released in Monero v0.18.5.3
- **Class:** funds (and privacy)
- **Component:** `src/wallet/wallet2.cpp`, `trim_hashchain`
- **Affects:** when the wallet repairs an empty hash chain it asks the node for a block header and uses its hash as the new chain start. The hex-to-hash conversion result was ignored.
- **Impact:** a malicious node could return a non-hex "hash" and have the wallet refill its hash chain with garbage, steering later refreshes and reorg detection. The conversion is now checked and the wallet errors out on an invalid hash.
- **Compatibility statement:** no consensus, relay, wire or file-format change; wallet-side validation of node data.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests; webwallet harness (refresh and reorg simulation with a mocked node).
- **Notes:** none

### SB-009 — Refresh error handlers wait for worker threads

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `d9236332a59bb090b0fa74e808237c26189564b0` (2026-08-21, "wallet2: fix data races in refresh error handlers"), released in Monero v0.18.5.3
- **Class:** dos
- **Component:** `src/wallet/wallet2.cpp`, `refresh`
- **Affects:** native (threaded) wallets. Two error handlers in the refresh loop reset wallet state while the block-parsing threads of the previous iteration could still be writing to it.
- **Impact:** data race leading to corrupted wallet state or a crash when a refresh error coincides with in-flight parsing. The handlers now wait for the worker threads first.
- **Compatibility statement:** no consensus, relay, wire or file-format change; threading only. In the WebAssembly build the wallet is single-threaded and the change is inert.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests.
- **Notes:** none

### SB-010 — DNSSEC root trust anchor KSK-2024 added

- **Tag:** v2.3.0-sec.1
- **Origin:** monero-project/monero `e62963ceb83d18cd93261c1b6e9e80f7aa09ff3f` (2024-12-01, "dns_util: add new DNSSEC trust anchor"), released in Monero v0.18.5.4
- **Class:** dos (loss of DNSSEC validation)
- **Component:** `src/common/dns_utils.cpp`, both daemon and wallet
- **Affects:** every DNSSEC-validated lookup: DNS checkpoints, seed nodes, the DNS blocklist, OpenAlias, the update check. The built-in trust anchors listed KSK-2017 (key tag 20326) only; the retired KSK-2010 entry had already been removed in Zephyr's base (Monero `6b6162888`, 2022). ICANN switched root-zone signing to KSK-2024 (key tag 38696) on 2026-10-11 and reported the rollover complete on 2026-10-15; KSK-2017 is revoked in January 2027.
- **Impact:** since 2026-10-11 a v2.3.0 binary cannot validate any DNSSEC answer; functions that require validation fail or fall back to unvalidated behaviour, and the protection that DNSSEC gave those lookups is gone. The fix adds the KSK-2024 DS record; upstream's removal of the KSK-2010 entry was already present in the base, so the cherry-pick applied that part as a no-op.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a static trust-anchor list.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) and cross-open both ways with upstream's prebuilt dist (9d022ded) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`). Pending: fork CI build and unit tests; `zephyrd` with `--enable-dns-blocklist` or an OpenAlias lookup validating successfully against the live root.
- **Notes:** ZephyrProtocol issue #66 (2026-06-10) points at this file. The release binaries' `contrib/depends` pin of unbound 1.19.1 is a separate matter, planned for `-sec.2`. The pick's removal hunk was pre-applied in the base (POLICY §5); the post-image of `get_builtin_ds` is byte-identical to upstream's.
