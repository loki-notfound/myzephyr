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

**v2.3.0-sec.2** (draft, not tagged)

| # | Tag | Monero commit | Class | Component | Summary |
|---|---|---|---|---|---|
| SB-015 | v2.3.0-sec.2 | `b99d15f08` | privacy | wallet2 | non-monotonic output distribution from the node rejected |
| SB-016 | v2.3.0-sec.2 | `bbd635075` | dos | wallet2 | fast_refresh honours the max_blocks bound |
| SB-017 | v2.3.0-sec.2 | `c86fd739d` | funds | wallet2 | unchecked RPC status strings from the node filtered |
| SB-018 | v2.3.0-sec.2 | `144b3f9e6` | funds | wallet2 | untrusted node status filtered in sweep unmixable |
| SB-019 | v2.3.0-sec.2 | `52b33f4fb` | dos | common (both) | message writer console output sanitised (terminal escape injection) |
| SB-020 | v2.3.0-sec.2 | `98bc2ec5e` | dependency | depends (both) | unbound 1.19.1 → 1.25.1 (depends) |
| SB-021 | v2.3.0-sec.2 | `c4e54fe5e` | dependency | depends (both) | OpenSSL 3.0.13 → 3.0.19 (depends) |
| SB-022 | v2.3.0-sec.2 | `0d49006c9` | dependency | depends (build) | autoconf cross-compile mode explicit (depends) |
| SB-023 | v2.3.0-sec.2 | `6b629b376` | dependency | randomx (daemon) | RandomX v1.2.2: correct hashes on ARM64/RISC-V JIT |
| SB-024 | v2.3.0-sec.2 | `8d0b73e50` | dependency | depends (both) | OpenSSL 3.0.19 → 3.0.21 (depends) |
| SB-025 | v2.3.0-sec.2 | `b4b5bfbb0` | dependency | randomx (daemon) | RandomX v1.2.3 (depends) |
| SB-026 | v2.3.0-sec.2 | `342c3a0fd` | memory | build (Windows, both) | Windows: TryAcquireSRWLockShared no longer implicitly declared (UB) |
| SB-027 | v2.3.0-sec.2 | `2a10eceae` | dependency | depends (both) | unbound 1.25.1 → 1.25.2 (depends) |
| SB-028 | v2.3.0-sec.2 | `91c32b55c` | dependency | depends (both) | OpenSSL 3.0.21 → 3.0.22 (depends) |
| SB-029 | v2.3.0-sec.2 | `0c29b3ce3` | dependency | depends (both) | unbound 1.25.2 → 1.26.1 (depends) |
| SB-030 | v2.3.0-sec.2 | `af88effd9` | privacy | daemon (rpc) | get_transaction_pool not served in restricted RPC mode |
| SB-031 | v2.3.0-sec.2 | `7de175802` | privacy | daemon (rpc) | get_alt_blocks_hashes not served in restricted RPC mode |
| SB-032 | v2.3.0-sec.2 | `98b350f7a` | memory | epee (both) | levin header reads no longer unaligned/aliased |
| SB-033 | v2.3.0-sec.2 | `4f6652f35` | dos | daemon (zmq) | aggregate ZMQ receive size capped |
| SB-034 | v2.3.0-sec.2 | `d1508916b` | dos | daemon (zmq) | ZMQ-RPC server recovers from oversized requests |

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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). done 2026-11-06 (local run; `evidence/native/2026-11-05/sync-from-local-node.md`): the sec.2 daemon, which carries this fix, synced mainnet from height 0 to 901,872 from an upstream v2.3.0 node, parsing every block and transaction with zero rejections and block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015.
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: webwallet harness (every RPC call exercises this parser).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`), including `select_outputs.exact_unlock_block_tiny`, the test this pick corrects, which passes on the branch; done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: webwallet harness (send flow).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). done 2026-11-07 (local run; `evidence/wasm/2026-11-07/harness-results.md`): wallet keys and cache saved by the fork WASM opened by upstream's prebuilt WASM and the other way round (cross-open both ways, upstream's real dist).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: webwallet harness (full scan from the restore height).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: webwallet harness (refresh and reorg simulation with a mocked node).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`).
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
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 54aa43b12 + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec1-build-manifest.json`, `harness-results.md`); native build of security/v2.3.0 (54aa43b12; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): offline zephyrd with --enable-dns-blocklist: upstream v2.3.0 loads only the root trust anchor DS 20326, fails DNSSEC validation of every blocklist and update TXT record and applies no blocklist; wip/sec.2 (16018bb0b, with this commit; `dns_utils` identical to e9cf10f79) loads DS 20326 and DS 38696, validates the records (4 of 7 matching from 6 valid) and adds 431 addresses to the blocklist (`dnssec-check.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr e9cf10f79 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`).
- **Notes:** ZephyrProtocol issue #66 (2026-06-10) points at this file. The release binaries' `contrib/depends` pin of unbound 1.19.1 is a separate matter, planned for `-sec.2`. The pick's removal hunk was pre-applied in the base (POLICY §5); the post-image of `get_builtin_ds` is byte-identical to upstream's.

### SB-015 — Wallet rejects a non-monotonic output distribution from the node

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `b99d15f08d80a8cad6dee88628192ba0411544fb` (2026-06-02, "wallet2: reject non-monotonic rct output distributions"), released in Monero v0.18.5.1
- **Class:** privacy
- **Component:** `src/wallet/wallet2.cpp`, `wallet2::get_outs`
- **Affects:** transaction construction. The cumulative RCT output distribution (`get_output_distribution`) comes from the node and drives decoy selection; it was used without checking that it never decreases.
- **Impact:** a malicious or broken node can return a distribution that decreases somewhere, which skews the gamma picker towards or away from particular outputs (weakening ring privacy) or feeds negative-size windows into it. The wallet now refuses such a distribution with "Daemon reports non-monotonic rct output distribution".
- **Compatibility statement:** no consensus, relay, wire or file-format change: wallet-side only (`src/wallet/`), no change to what the wallet sends or stores. A correct node returns a cumulative, hence non-decreasing, distribution, so only malformed answers are refused; that Zephyr's per-asset distribution has the same shape is exercised by the harness send flow (pending).
- **Conflict resolution:** context-only in `src/wallet/wallet2.cpp` (trailer `Conflicts:` in the commit)
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 16018bb0b + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec2-build-manifest.json`, `harness-results.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr 1c1982aa7 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: harness send flow against a Zephyr node (exercises the per-asset distribution).
- **Notes:** complements SB-005 (`0b7967907`, empty window) on the same data. The two added lines keep upstream's indentation byte for byte.

### SB-016 — `fast_refresh` honours the `max_blocks` bound

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `bbd6350751876f24ad21eb70cbfb12670659e927` (2026-08-05, "wallet2: honor max_blocks bound during fast_refresh hash pulls"), released in Monero v0.18.5.3
- **Class:** dos
- **Component:** `src/wallet/wallet2.cpp`, `src/wallet/wallet2.h`, `wallet2::fast_refresh` / `wallet2::refresh`
- **Affects:** callers of `wallet2::refresh` that pass a `max_blocks` bound, typically single-threaded callers that want refresh to return regularly. The hash-only fast path before `start_height` ignored the bound and pulled hashes until it reached `start_height`.
- **Impact:** a refresh meant to be bounded could run for as long as the node keeps answering hash requests, leaving a single-threaded caller unresponsive. With the fix a bounded refresh stops after three hash pulls and resumes on the next call. In Zephyr's tree (simplewallet, wallet API, wallet RPC) and in zephyr-cpp no caller passes `max_blocks`; with the default (no bound) behaviour is unchanged.
- **Compatibility statement:** no consensus, relay, wire or file-format change: wallet-side only (`src/wallet/`), no change to what the wallet sends or stores. Same RPC calls in the same order; only the number of calls per `refresh` invocation is bounded when a bound is given.
- **Conflict resolution:** context-only in `src/wallet/wallet2.h` (trailer `Conflicts:` in the commit)
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 16018bb0b + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec2-build-manifest.json`, `harness-results.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr 1c1982aa7 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`).
- **Notes:** none

### SB-017 — Unchecked status strings from the node are filtered

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `c86fd739dceca593346ca3d3d3db835d1308e7ed` (2026-09-13, "wallet2: filter unchecked RPC error statuses"), released in Monero v0.18.5.3
- **Class:** funds
- **Component:** `src/wallet/wallet2.cpp` (`get_rct_distribution`, `set_tx_key`, `get_spend_proof`, `check_spend_proof`, `get_public_nodes`)
- **Affects:** wallet users on an untrusted node. Five RPC call sites passed the node's `status` string unfiltered into the exception text the user sees; elsewhere wallet2 already filters it through `get_rpc_status`, which replaces anything but the known statuses with `<error>` unless the node is trusted.
- **Impact:** an untrusted node could place arbitrary text in wallet error messages (for example instructions to send funds somewhere), a social-engineering vector. The fix routes these five sites through `get_rpc_status` like the rest of wallet2.
- **Compatibility statement:** no consensus, relay, wire or file-format change: wallet-side only (`src/wallet/`), no change to what the wallet sends or stores. Only the text of error messages changes, and only for untrusted nodes.
- **Conflict resolution:** context-only in `src/wallet/wallet2.cpp` (trailer `Conflicts:` in the commit)
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 16018bb0b + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec2-build-manifest.json`, `harness-results.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr 1c1982aa7 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): CLI wallet with `--untrusted-daemon` against a fake daemon whose `/get_public_nodes` status carries escape sequences and a newline: upstream v2.3.0 prints the status raw, wip/sec.2 (16018bb0b) prints `<error>` and no daemon text (`console-sanitising.md`, section "Third run: untrusted daemon").
- **Notes:** Zephyr removed Monero's RPC-payment code; the resolution keeps that absent and does not add `check_rpc_cost`.

### SB-018 — Untrusted status in sweep-unmixable output selection is filtered

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `144b3f9e644c0b1d4ad994b99edf6c355b38e533` (2026-09-30, "wallet2: sanitize untrusted daemon status in sweep unmixable"), released in Monero v0.18.5.3
- **Class:** funds
- **Component:** `src/wallet/wallet2.cpp`, `wallet2::select_available_outputs_from_histogram`
- **Affects:** wallet users on an untrusted node, in the output-histogram call used when selecting unmixable outputs. The node's status string went unfiltered into the exception text.
- **Impact:** as for SB-017: an untrusted node could put arbitrary text into an error message the user reads. The fix filters it through `get_rpc_status`.
- **Compatibility statement:** no consensus, relay, wire or file-format change: wallet-side only (`src/wallet/`), no change to what the wallet sends or stores.
- **Conflict resolution:** context-only in `src/wallet/wallet2.cpp` (trailer `Conflicts:` in the commit)
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): webwallet WASM build from zephyr 16018bb0b + zephyr-cpp ac3bb4de3 + zephyr-javascript 9d022ded, guards 1–4 OK; harness smoke test (keys from seed, 40-block sync to tip, reserve info, serialisation, reopen) OK (`sec2-build-manifest.json`, `harness-results.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/wasm/2026-11-07/): the WASM built from the published commits (zephyr 1c1982aa7 + zephyr-cpp 56abaf948 + zephyr-javascript 9d022ded) is byte-identical to the 2026-11-05 build when built at the same path; harness smoke test and cross-open both ways with upstream's prebuilt dist (9d022ded, keys `a541c83c`) OK (`harness-results.md`). Pending: same filter as SB-017, not exercised.
- **Notes:** same pattern as SB-017.

### SB-019 — Console output of the message writer is sanitised

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `52b33f4fb01bd54d936a016cbc63a4850daa3441` (2026-09-13, "common: sanitize message writer console output"), released in Monero v0.18.5.3
- **Class:** dos
- **Component:** `src/common/scoped_message_writer.h`, `external/easylogging++`, both daemon and CLI wallet
- **Affects:** users of the command-line tools (`zephyrd` console, `zephyr-wallet-cli`). Text written through the message writer can contain data from peers or nodes (for example error strings); the writer printed it to `std::cout` directly, bypassing the sanitising that easylogging already applies to log lines on the console.
- **Impact:** terminal control and escape sequences from untrusted data could rewrite what the user sees on the console (hide or fake output). The fix runs the console copy through easylogging's existing `sanitize` (control characters other than tab, newline and carriage return are replaced) and prints a placeholder for invalid UTF-8.
- **Compatibility statement:** no consensus, relay, wire or file-format change; console output only. Not part of the WASM (no console).
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/wasm/2026-11-05/ and evidence/native/2026-11-05/): builds (the WASM links the changed header; harness passed, `harness-results.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): CLI wallet against a fake daemon whose `/get_public_nodes` status carries ESC and BEL sequences and a newline: upstream v2.3.0 prints the escape bytes raw, wip/sec.2 (16018bb0b) replaces them with `?`, keeping newline, tab and carriage return by design (`console-sanitising.md`, section "Second design").
- **Notes:** none

### SB-020 — unbound 1.19.1 → 1.25.1 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `98bc2ec5e6896bfa210eafc42f8849431c9eb5d2` (2025-11-02, "depends: unbound: update to 1.25.1"), released in Monero v0.18.5.1
- **Class:** dependency
- **Component:** `contrib/depends/packages/unbound.mk` (+ reproducibility patch), release binaries
- **Affects:** the release binaries built with `contrib/depends` (daemon and CLI wallet): they resolve and DNSSEC-validate DNS checkpoints, seed nodes, the DNS blocklist, OpenAlias and the update check with this library.
- **Impact:** unbound 1.19.1 is affected by CVE-2026-33278, possible arbitrary code execution during DNSSEC validation (affects 1.19.1–1.25.0); an attacker who can answer the binary's DNS queries can reach it.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum, plus a patch that hardcodes the configure date for reproducible builds.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** 16 NLnet Labs advisories are fixed in 1.19.2 … 1.25.1, all of them affecting 1.19.1: CVE-2024-1931 (High, fixed in 1.19.2: Denial of service when trimming EDE text on positive replies); CVE-2024-33655 (Low, fixed in 1.20.0: Unbound vulnerable to the "DNSBomb" pulsing DoS amplification attack); CVE-2024-8508 (Medium, fixed in 1.21.1: Unbounded name compression could lead to Denial of Service); CVE-2025-5994 (High, fixed in 1.23.1; only builds compiled and configured for ECS: Cache poisoning via the ECS-enabled Rebirthday Attack); CVE-2025-11411 (Medium, fixed in 1.24.1, completed in 1.24.2: Possible domain hijacking via promiscuous records in the authority section); CVE-2026-32792 (Medium, fixed in 1.25.1: Packet of death with DNSCrypt); CVE-2026-33278 (Critical, fixed in 1.25.1: Possible arbitrary code execution during DNSSEC validation); CVE-2026-40622 (Medium, fixed in 1.25.1: Another "ghost domain names" attack variant); CVE-2026-41292 (Medium, fixed in 1.25.1: Long list of incoming EDNS options degrades performance); CVE-2026-42534 (Medium, fixed in 1.25.1: Jostle logic bypass degrades resolution performance); CVE-2026-42923 (Medium, fixed in 1.25.1: Degradation of service with unbounded NSEC3 hash calculations); CVE-2026-42944 (High, fixed in 1.25.1: Heap overflow with multiple NSID, COOKIE, PADDING EDNS options); CVE-2026-42959 (High, fixed in 1.25.1: Crash during DNSSEC validation of malicious content); CVE-2026-42960 (Medium, fixed in 1.25.1: Possible cache poisoning via promiscuous records for the authority section); CVE-2026-44390 (Medium, fixed in 1.25.1: Unbounded name compression in certain cases causes degradation of service); CVE-2026-44608 (Medium, fixed in 1.25.1: Use after free and crash under special conditions in RPZ code). Continued by SB-027 and SB-029. Source: NLnet Labs, Unbound security advisories and release notes (read 2026-11-05).

### SB-021 — OpenSSL 3.0.13 → 3.0.19 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `c4e54fe5e0bdb9cd8b460dd7836ad61855d54ad1` (2026-01-29, "depends: openssl: update to 3.0.19"), released in Monero v0.18.4.6
- **Class:** dependency
- **Component:** `contrib/depends/packages/openssl.mk`, release binaries
- **Affects:** the release binaries: TLS to remote nodes and the wallet RPC, and the daemon's RPC SSL support.
- **Impact:** OpenSSL 3.0.13 is affected by the 16 advisories fixed in 3.0.14 … 3.0.19 that apply to it (one more in the list only affects 3.0.16 and later), the highest rated High: CVE-2025-15467 (stack buffer overflow in CMS (Auth)EnvelopedData parsing). Which of them are reachable through Zephyr's use of TLS has not been assessed per CVE.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum within the 3.0 LTS series.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** Fixed in 3.0.14 … 3.0.19: CVE-2024-2511 (Low, fixed in OpenSSL 3.0.14: Unbounded memory growth with session handling in TLSv1.3); CVE-2024-4603 (Low, fixed in OpenSSL 3.0.14: Excessive time spent checking DSA keys and parameters); CVE-2024-4741 (Low, fixed in OpenSSL 3.0.14: Use After Free with SSL_free_buffers); CVE-2024-5535 (Low, fixed in OpenSSL 3.0.15: SSL_select_next_proto buffer overread); CVE-2024-6119 (Moderate, fixed in OpenSSL 3.0.15: Possible denial of service in X.509 name checks); CVE-2024-13176 (Low, fixed in OpenSSL 3.0.16: Timing side-channel in ECDSA signature computation); CVE-2024-9143 (Low, fixed in OpenSSL 3.0.16: Low-level invalid GF(2^m) parameters lead to OOB memory access); CVE-2025-9230 (Moderate, fixed in OpenSSL 3.0.18: Out-of-bounds read & write in RFC 3211 KEK Unwrap); CVE-2025-9232 (Low, fixed in OpenSSL 3.0.18; affects 3.0.16 and later only, not 3.0.13: Out-of-bounds read in HTTP client no_proxy handling); CVE-2025-15467 (High, fixed in OpenSSL 3.0.19: Stack buffer overflow in CMS (Auth)EnvelopedData parsing); CVE-2025-68160 (Low, fixed in OpenSSL 3.0.19: Heap out-of-bounds write in BIO_f_linebuffer on short writes); CVE-2025-69418 (Low, fixed in OpenSSL 3.0.19: Unauthenticated/unencrypted trailing bytes with low-level OCB function calls); CVE-2025-69419 (Low, fixed in OpenSSL 3.0.19: Out of bounds write in PKCS12_get_friendlyname() UTF-8 conversion); CVE-2025-69420 (Low, fixed in OpenSSL 3.0.19: Missing ASN1_TYPE validation in TS_RESP_verify_response() function); CVE-2025-69421 (Low, fixed in OpenSSL 3.0.19: NULL Pointer Dereference in PKCS12_item_decrypt_d2i_ex function); CVE-2026-22795 (Low, fixed in OpenSSL 3.0.19: Missing ASN1_TYPE validation in PKCS#12 parsing); CVE-2026-22796 (Low, fixed in OpenSSL 3.0.19: ASN1_TYPE Type Confusion in the PKCS7_digest_from_attributes() function). Continued by SB-024 and SB-028. Source: OpenSSL, vulnerabilities in OpenSSL 3.0 (read 2026-11-05).

### SB-022 — autoconf packages in depends are configured in explicit cross-compile mode

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `0d49006c9d1740b2909d5173157e621e6a38ede1` (2026-05-09, "depends: explicitely enable cross-compile mode for autoconf"), released in Monero v0.18.5.1
- **Class:** dependency
- **Component:** `contrib/depends/funcs.mk`, release binaries
- **Affects:** the `contrib/depends` build of every autoconf-based package (unbound, libusb and others). Without `--build`, autoconf has to guess whether it is cross-compiling.
- **Impact:** a wrong guess makes configure probe the build host instead of the target. Build-integrity fix without a known exploit; Monero ships it with the dependency updates in this series.
- **Compatibility statement:** no consensus, relay, wire or file-format change; build scripts only.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** no CVE; part of Monero's depends series.

### SB-023 — RandomX v1.2.1 → v1.2.2: correct hashes on ARM64 and RISC-V

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `6b629b37659d1846f4731255a2a2b2ef7b811f53` (2026-05-10, "Updated RandomX to v1.2.2"), released in Monero v0.18.5.1
- **Class:** dependency
- **Component:** `external/randomx` (submodule), daemon
- **Affects:** nodes running on ARM64 or RISC-V with the RandomX JIT. RandomX v1.2.2 fixes `ISUB_R` in the ARM/RISC-V JIT; earlier versions could produce an invalid hash for about 1 in 268 million inputs on those platforms.
- **Impact:** an affected node computes a wrong proof-of-work hash for a rare block and can disagree with the rest of the network about it (reject a valid block or stall). x86 results are unchanged.
- **Compatibility statement:** POLICY §4.1 checked: consensus rules are unchanged; the fix makes the ARM64/RISC-V JIT produce the reference hash that every other platform already computes. No relay, wire or file-format change. `git submodule update --init external/randomx` resolves the new pointer.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) compiles external/randomx at 12f2c2ff (v1.2.3) and runs Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** submodule pointer `102f8acf` → `6c4340ba` (RandomX "Prepare v1.2.2 release"). Not a §2 class strictly (correctness of PoW on ARM); Monero shipped it in release-v0.18.

### SB-024 — OpenSSL 3.0.19 → 3.0.21 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `8d0b73e509fa60538eb86e8af1e970faa91a88a6` (2026-06-09, "depends: openssl: update to 3.0.21"), released in Monero v0.18.5.1
- **Class:** dependency
- **Component:** `contrib/depends/packages/openssl.mk`, release binaries
- **Affects:** as SB-021.
- **Impact:** OpenSSL 3.0.19 is affected by the 16 advisories fixed in 3.0.20 and 3.0.21, the highest rated High: CVE-2026-45447 (heap use after free in `PKCS7_verify`). Reachability through Zephyr's use of TLS has not been assessed per CVE.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** Fixed in 3.0.20 … 3.0.21: CVE-2026-28387 (Low, fixed in OpenSSL 3.0.20: Potential Use-after-free in DANE Client Code); CVE-2026-28388 (Low, fixed in OpenSSL 3.0.20: NULL Pointer Dereference When Processing a Delta CRL); CVE-2026-28389 (Low, fixed in OpenSSL 3.0.20: Possible NULL Dereference When Processing CMS KeyAgreeRecipientInfo); CVE-2026-28390 (Low, fixed in OpenSSL 3.0.20: Possible NULL Dereference When Processing CMS KeyTransportRecipientInfo); CVE-2026-31789 (Low, fixed in OpenSSL 3.0.20: Heap Buffer Overflow in Hexadecimal Conversion); CVE-2026-31790 (Moderate, fixed in OpenSSL 3.0.20: Incorrect Failure Handling in RSA KEM RSASVE Encapsulation); CVE-2026-34180 (Low, fixed in OpenSSL 3.0.21: Heap Buffer Over-read in ASN.1 Content Parsing); CVE-2026-34182 (Moderate, fixed in OpenSSL 3.0.21: CMS AuthEnvelopedData Processing May Accept Forged Messages); CVE-2026-42766 (Low, fixed in OpenSSL 3.0.21: Possible NULL Dereference in Password-Based CMS Decryption); CVE-2026-42767 (Low, fixed in OpenSSL 3.0.21: NULL Pointer Dereference in CRMF EncryptedValue Decryption); CVE-2026-42770 (Low, fixed in OpenSSL 3.0.21: FFC-DH Peer Validation Uses Attacker-Supplied q); CVE-2026-45445 (Moderate, fixed in OpenSSL 3.0.21: AES-OCB IV Ignored on EVP_Cipher() Path); CVE-2026-45446 (Low, fixed in OpenSSL 3.0.21: Incorrect Tag Processing for Empty Messages in AES-GCM-SIV and AES-SIV modes); CVE-2026-45447 (High, fixed in OpenSSL 3.0.21: Heap Use-After-Free in the PKCS7_verify() Function); CVE-2026-7383 (Low, fixed in OpenSSL 3.0.21: Possible Heap Buffer Overflow in ASN.1 Multibyte String Conversion); CVE-2026-9076 (Low, fixed in OpenSSL 3.0.21: Out-of-Bounds Read in CMS Password-Based Decryption). Source: OpenSSL, vulnerabilities in OpenSSL 3.0 (read 2026-11-05).

### SB-025 — RandomX v1.2.2 → v1.2.3

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `b4b5bfbb0a7635bbe70a6378acf3e27658610f96` (2026-07-17, "external: update randomx to v1.2.3"), released in Monero v0.18.5.3
- **Class:** dependency
- **Component:** `external/randomx` (submodule)
- **Affects:** builds of the daemon and wallet that compile RandomX.
- **Impact:** no security change of its own: v1.2.3 raises the CMake minimum to 3.10 so that current CMake versions still configure RandomX. Taken because Monero ships v1.2.3 on release-v0.18 and later Monero picks assume it.
- **Compatibility statement:** no consensus, relay, wire or file-format change: the RandomX source is identical apart from the CMake minimum. `git submodule update --init external/randomx` resolves `12f2c2ff` (v1.2.3).
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) compiles external/randomx at 12f2c2ff (v1.2.3) and runs Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** submodule pointer `6c4340ba` → `12f2c2ff`; build-only update.

### SB-026 — Windows builds declare `TryAcquireSRWLockShared` instead of guessing it

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `342c3a0fd42584385c76743bb165ff6a75584c1e` (2026-07-23, "Fix TryAcquireSRWLockShared being implicitly defined and causing UB"), released in Monero v0.18.5.3
- **Class:** memory
- **Component:** `CMakeLists.txt` (MinGW defines and flags); affects `src/crypto/rx-slow-hash.c`
- **Affects:** 64-bit Windows release builds (MinGW). `WINVER`/`_WIN32_WINNT` were only set for 32-bit builds, so `TryAcquireSRWLockShared` (used through `CTHR_RWLOCK_TRYLOCK_READ` in the RandomX dataset path of `rx-slow-hash.c`) was implicitly declared with an `int` return, while the real function returns a one-byte `BOOLEAN`.
- **Impact:** undefined behaviour: the caller can read garbage in the upper bits and treat a failed try-lock as success, using the RandomX dataset while another thread initialises it (wrong hash or crash on Windows nodes and wallets). The fix targets Windows 7 for all MinGW builds and makes an implicit declaration a build error.
- **Compatibility statement:** no consensus, relay, wire or file-format change; build flags for Windows only.
- **Conflict resolution:** none
- **Test evidence:** Pending: fork CI `depends` job, Windows targets, and the build matrix; the WASM is not affected (no Windows build).
- **Notes:** none

### SB-027 — unbound 1.25.1 → 1.25.2 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `2a10eceae0f34c350107876e1d4c9a6314e69d27` (2026-07-24, "depends: unbound: update to 1.25.2"), released in Monero v0.18.5.3
- **Class:** dependency
- **Component:** `contrib/depends/packages/unbound.mk`, release binaries
- **Affects:** as SB-020.
- **Impact:** unbound 1.25.2 is a security release of its own: it fixes 24 NLnet Labs advisories that affect 1.25.1, the highest rated High (CVE-2026-32665, CVE-2026-40691, CVE-2026-44690, CVE-2026-55973; see Notes).
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** Fixed in 1.25.2: CVE-2026-14586 (Medium, fixed in 1.25.2: Assertion in libngtcp2 when under pressure in high concurrency DNS-over-QUIC environments); CVE-2026-32665 (High, fixed in 1.25.2: Remote DNS-over-QUIC denial of service due to 'quic-size' budget bypass); CVE-2026-40691 (High, fixed in 1.25.2: Packet of death for DNSCrypt over TCP); CVE-2026-41637 (Low, fixed in 1.25.2: Degradation of resolution service from improperly accounted client-terminated DNS-over-QUIC queries); CVE-2026-42955 (Low, fixed in 1.25.2: Extra fix for CVE-2026-40622 to also clamp the TTL of A/AAAA records disallowing a one-time 'ghost domain' delegation renewal via glue records); CVE-2026-44621 (Medium, fixed in 1.25.2: Libunbound applications configured with 'unwanted-reply-threshold' could eventually be abruptly terminated); CVE-2026-44687 (Low, fixed in 1.25.2: Off-by-one error in 'harden-below-nxdomain' logic can shadow a stub/forward zone by a legitimate parent's NXDOMAIN); CVE-2026-44690 (High, fixed in 1.25.2: Cross-zone wildcard cache poisoning via RRSIG.labels manipulation); CVE-2026-46582 (Low, fixed in 1.25.2: A wildcard replay, as another piece of data, triggers poisoning in the serve expired reply path); CVE-2026-50045 (Medium, fixed in 1.25.2: 'max-global-quota' reset by DNSSEC validation restarts); CVE-2026-50046 (Medium, fixed in 1.25.2: Possible heap use-after-free in an error path when a DoT forwarded query is jostled out); CVE-2026-50243 (Medium, fixed in 1.25.2: 'response-ip'/'rpz' can rewrite BOGUS answers instead of returning SERVFAIL); CVE-2026-50248 (Medium, fixed in 1.25.2: BOGUS configured primary hostname accepted for XFR in auth/rpz zones); CVE-2026-50251 (Medium, fixed in 1.25.2: Attacker supplied '0.0.0.0'/'::' glue triggers defensive full-cache flush); CVE-2026-50252 (Medium, fixed in 1.25.2: Possible cache poisoning attack by mapping source port population per thread); CVE-2026-52863 (Medium, fixed in 1.25.2: Memory corruption could lead to crash and denial of service); CVE-2026-54478 (Low, fixed in 1.25.2: DNS Cookie bypass when combined with proxy-protocol use); CVE-2026-55708 (Low, fixed in 1.25.2: Privacy/configuration issue when adding local data in views through 'unbound-control'); CVE-2026-55717 (Medium, fixed in 1.25.2: 'serve-expired-client-timeout' and 'response-ip' CNAME redirect could lead to a crash); CVE-2026-55973 (High, fixed in 1.25.2: 'dns-error-reporting: yes' leads to stack buffer overflow); CVE-2026-55990 (Medium, fixed in 1.25.2: Packet of death for a DNSCrypt misconfigured Unbound); CVE-2026-55991 (Medium, fixed in 1.25.2: Remote DNS-over-QUIC (DoQ) flow-control assertion failure in libngtcp2); CVE-2026-56416 (Medium, fixed in 1.25.2: Possible heap buffer overflow when validator canonicalizes RDATA that contains domain name); CVE-2026-56444 (Medium, fixed in 1.25.2: Degradation of resolution service when 'discard-timeout' and 'serve-expired-client-timeout' are combined in unusual configuration). Source: NLnet Labs, Unbound security advisories and release notes (read 2026-11-05).

### SB-028 — OpenSSL 3.0.21 → 3.0.22 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `91c32b55c27e2a2202639c50d60c55d7472efaef` (2026-08-25, "depends: openssl: update to 3.0.22"), released in Monero v0.18.5.3
- **Class:** dependency
- **Component:** `contrib/depends/packages/openssl.mk`, release binaries
- **Affects:** as SB-021.
- **Impact:** OpenSSL 3.0.21 is affected by the 5 advisories fixed in 3.0.22, the highest rated Moderate: CVE-2026-63072, CVE-2026-63076; this brings the release build to the OpenSSL version Monero ships. Reachability through Zephyr's use of TLS has not been assessed per CVE.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** Fixed in 3.0.22: CVE-2026-54874 (Low, fixed in OpenSSL 3.0.22: Excessive Memory Use Buffering DTLS Records for a Future Epoch); CVE-2026-63072 (Moderate, fixed in OpenSSL 3.0.22: Heap Buffer Overflow in CMS Key Unwrapping); CVE-2026-63074 (Low, fixed in OpenSSL 3.0.22: CMP Indefinite Cache Growth of ExtraCerts); CVE-2026-63076 (Moderate, fixed in OpenSSL 3.0.22: Invalid Pointer Dereference in CMP Server via Crafted protectionAlg); CVE-2026-75803 (Low, fixed in OpenSSL 3.0.22: AEAD Forgeries with Empty Ciphertext When Using EVP_Cipher()). OpenSSL 3.0.23 fixes six more (CVE-2026-84782 rated High); Monero ships 3.0.22 and this fork follows Monero. Source: OpenSSL, vulnerabilities in OpenSSL 3.0 (read 2026-11-05).

### SB-029 — unbound 1.25.2 → 1.26.1 in the release build

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `0c29b3ce3b15a410d5e1dc10ebfb8d83d1bc0c04` (2026-09-23, "depends: unbound: update to 1.26.1"), released in Monero v0.18.5.3
- **Class:** dependency
- **Component:** `contrib/depends/packages/unbound.mk`, release binaries
- **Affects:** as SB-020.
- **Impact:** unbound before 1.26.1 is affected by CVE-2026-81642, a heap overflow while digesting DNSKEY records, possibly leading to code execution.
- **Compatibility statement:** no consensus, relay, wire or file-format change; a build-dependency version and its checksum.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the two packages build from the pins locally: openssl 3.0.22 and unbound 1.26.1 (with expat 2.6.0) fetched, verified against their pinned sha256 and built with `contrib/depends` for x86_64-linux-gnu (`depends-build.md`). Pending: a full `depends` daemon build (release binaries built from `contrib/depends`), which awaits the release builder, and the build matrix; the WASM is not affected (the webwallet build pins its own OpenSSL and boost, and has no resolver).
- **Notes:** 1.26.0 fixed no advisory. Fixed in 1.26.1 (9): CVE-2026-77860 (Low, fixed in 1.26.1: 'serve-expired' can bypass Unbound 'wait-limit'); CVE-2026-77955 (Medium, fixed in 1.26.1: Possible ZONEMD verification bypass window); CVE-2026-78227 (Medium, fixed in 1.26.1: Use-after-free in DoQ stream output buffer on reset re-transmission); CVE-2026-80225 (Medium, fixed in 1.26.1: Possible degradation of service from continuous queries on the same TCP/DoT connection); CVE-2026-81634 (High, fixed in 1.26.1: Possible heap buffer overflow during DNSSEC canonicalization); CVE-2026-81642 (Critical, fixed in 1.26.1: Heap buffer overflow and possible Remote Code Execution when digesting DNSKEY); CVE-2026-82717 (High, fixed in 1.26.1: CNAME synthesis could lead to heap corruption); CVE-2026-82720 (Medium, fixed in 1.26.1: Use-after-free in DoH stream cleanup code path); CVE-2026-85501 (Medium, fixed in 1.26.1: Retrap: Novel Vulnerabilities to launch Algorithmic Complexity Attacks on DNSSEC). Monero itself is one unbound release behind (1.26.2 of 2026-10-21, five further advisories); this fork follows Monero. Source: NLnet Labs, Unbound security advisories and release notes (read 2026-11-05).

### SB-030 — `get_transaction_pool` is not served in restricted mode

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `af88effd9a82ca715c12ce6ea021fdbc1cbb3102` (2026-07-25, "rpc: disable get_transaction_pool in restricted mode"), released in Monero v0.18.5.3
- **Class:** privacy
- **Component:** `src/rpc/core_rpc_server.h`, daemon
- **Affects:** public (restricted-RPC) nodes, such as the community nodes the wallets connect to. `/get_transaction_pool` returned the full pool, including per-transaction relay metadata (`receive_time`, `relayed`, `last_relayed_time`, `double_spend_seen`), to anyone.
- **Impact:** any client of a public node could watch the pool in detail and use arrival times and relay metadata to link transactions to the node that first saw them. Restricted nodes now refuse the endpoint, as they already do for other operator-only calls; the pool hashes endpoints stay available.
- **Compatibility statement:** POLICY §4.2 checked: the request and response schemas are unchanged; the endpoint is no longer served by nodes running with `--restricted-rpc` (unrestricted nodes are unchanged). No wallet in the release set calls it: searched 2026-11-05 in zephyr `src/wallet`, zephyr-cpp `src`, zephyr-wallet `client/src` and `zephyr-desktop-app/src`; zephyr-javascript exposes it as ``getTxPool`` in its daemon API, unused by the app.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): offline native zephyrd with --restricted-rpc on 127.0.0.1: `GET /get_transaction_pool` answers `HTTP/1.1 404 Not found` on wip/sec.2 (16018bb0b) and `HTTP/1.1 200 Ok` on upstream v2.3.0, while `/get_transaction_pool_hashes.bin` and `/get_info` answer `HTTP/1.1 200 Ok` on both (`daemon-checks.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** an endpoint that disappears for restricted clients is an availability change on the RPC surface, limited to public nodes; operators who need it run without `--restricted-rpc` or use an unrestricted port.

### SB-031 — `get_alt_blocks_hashes` is not served in restricted mode

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `7de175802a48caa7b96e516138de6cdc914bdc76` (2026-05-15, "rpc: restrict get_alt_blocks_hashes"), released in Monero v0.18.5.1
- **Class:** privacy
- **Component:** `src/rpc/core_rpc_server.h`, daemon
- **Affects:** public (restricted-RPC) nodes. `/get_alt_blocks_hashes` lists the alternative blocks the node knows.
- **Impact:** it exposes the node's own view of competing chain tips, which public clients do not need; Monero moved it to the operator-only set. Restricted nodes now refuse the endpoint.
- **Compatibility statement:** POLICY §4.2 checked: the request and response schemas are unchanged; the endpoint is no longer served by nodes running with `--restricted-rpc` (unrestricted nodes are unchanged). No wallet in the release set calls it: searched 2026-11-05 in zephyr `src/wallet`, zephyr-cpp `src`, zephyr-wallet `client/src` and `zephyr-desktop-app/src`; zephyr-javascript exposes it as ``getAltBlockHashes`` in its daemon API, unused by the app.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): offline native zephyrd with --restricted-rpc on 127.0.0.1: `GET /get_alt_blocks_hashes` answers `HTTP/1.1 404 Not found` on wip/sec.2 (16018bb0b) and `HTTP/1.1 200 Ok` on upstream v2.3.0, while `/get_transaction_pool_hashes.bin` and `/get_info` answer `HTTP/1.1 200 Ok` on both (`daemon-checks.md`); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** as SB-030.

### SB-032 — Levin header reads no longer unaligned or aliased

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `98b350f7a15997f5866c413c16b07e2ee6348922` (2026-05-20, "contrib: fix unaligned&aliased levin buffer reads"), released in Monero v0.18.5.1
- **Class:** memory
- **Component:** `contrib/epee/include/net/levin_protocol_handler_async.h`, daemon and wallet
- **Affects:** every levin connection, which in practice means the daemon's p2p port, reachable by any peer. The signature and the `bucket_head2` header were read by casting the receive buffer to a struct pointer, which is an unaligned and strict-aliasing-violating access.
- **Impact:** undefined behaviour on peer-controlled data: wrong header values after optimisation, or a fault on platforms that trap on unaligned loads. The fix copies the bytes with `memcpy` into a properly typed header before use.
- **Compatibility statement:** no consensus or relay change; POLICY §4.2 checked: the levin wire format is read identically (same bytes, same byte-order handling), only the way the bytes reach the struct changes. No file-format change.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** none

### SB-033 — ZMQ receive caps the total size of a multipart message

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `4f6652f356f804403f46ecbbb8b90c1c03abbc64` (2026-06-09, "net: cap aggregate ZMQ receive size"), released in Monero v0.18.5.1
- **Class:** dos
- **Component:** `src/net/zmq.cpp`, `src/net/zmq.h`, `src/rpc/zmq_server.cpp`, daemon
- **Affects:** nodes with ZMQ-RPC enabled (default bind 127.0.0.1; exposed only when the operator binds it publicly). `ZMQ_MAXMSGSIZE` limits each frame to 10 MiB, but a multipart message was concatenated frame by frame without a total limit.
- **Impact:** a client could send many 10 MiB frames as one message and make the daemon allocate without bound. The receive now fails with `EMSGSIZE` once the total exceeds 10 MiB.
- **Compatibility statement:** no consensus, relay or file-format change; POLICY §4.2 checked: valid ZMQ requests (well under 10 MiB) are handled as before; only oversized messages, which the server never served, are refused.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): offline native zephyrd, ZMQ-RPC on 127.0.0.1: one multipart request of 11 parts x 1 MiB (each part below the 10 MiB per-frame limit) is answered on wip/sec.2 (16018bb0b) with `"error_str":"Request too large"` instead of being received, while upstream v2.3.0 receives the 11 MiB and answers `"Malformed json"`; a single 11 MiB frame gets no reply from either (refused by the per-frame ZMQ_MAXMSGSIZE both set) and both keep serving (`daemon-checks.md`, section ZMQ); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** followed by SB-034, which makes the server recover from such a message.

### SB-034 — ZMQ-RPC server recovers from oversized requests

- **Tag:** v2.3.0-sec.2
- **Origin:** monero-project/monero `d1508916b44d08fa18dc8ac74e04e9f92dbfb2c1` (2026-07-23, "rpc: recover from oversized ZMQ requests"), released in Monero v0.18.5.3
- **Class:** dos
- **Component:** `src/net/zmq.cpp`, `src/rpc/message.cpp`, `src/rpc/message.h`, `src/rpc/zmq_server.cpp`, daemon
- **Affects:** nodes with ZMQ-RPC enabled, as SB-033. A read failure on the RPC or PUB socket (other than `EAGAIN`) was thrown out of `ZmqServer::serve()`, which ends the ZMQ server loop. With SB-033's aggregate cap alone, an oversized multipart request becomes such a read failure (`EMSGSIZE`); on v2.3.0 as released that request is received whole instead (SB-033).
- **Impact:** a failing read stopped the node's ZMQ-RPC and ZMQ-PUB service until restart, and with SB-033 alone one oversized request would have done so. The server now drains the oversized message, answers it with a "Request too large" error and keeps serving; other read failures are logged instead of ending the loop, which only context termination ends.
- **Compatibility statement:** no consensus, relay or file-format change; POLICY §4.2 checked: no change for valid requests. For a request over 10 MiB, which was never served, the server now sends an error response with the new status string "Request too large" instead of going silent.
- **Conflict resolution:** none
- **Test evidence:** done 2026-11-05 (local run; files in evidence/native/2026-11-05/): offline native zephyrd, ZMQ-RPC on 127.0.0.1: after the oversized multipart request wip/sec.2 (16018bb0b) logs `ZMQ-RPC request exceeds maximum message size`, replies `"Request too large"` and answers the next `get_info` on a fresh socket; upstream v2.3.0 also kept serving in this test, since without the cap the request is received and rejected as malformed (`daemon-checks.md`, section ZMQ); native build of wip/sec.2 (16018bb0b; gcc 14.2, boost 1.83) with Monero's unit tests: 1006 passed, 0 failed (`unit-tests.md`); fork zephyrd (wip/sec.2, 16018bb0b) synced mainnet from height 0 to 901,872 (2026-11-05 to 2026-11-06) from an upstream v2.3.0 node as its only peer, every block verified including the RandomX proof of work, no block rejected, block hashes equal to the upstream node's at heights 0, 1000, 451007 and 902015 (`sync-from-local-node.md`); done 2026-11-06 (fork CI on GitHub; evidence/ci/2026-11-07/): the fork's `tests` workflow builds and runs Monero's unit tests on GitHub's ubuntu-22.04 runner (GCC 11.4.0): security/v2.3.0 e9cf10f79 1006 passed; 1c1982aa7 1005 passed plus `select_outputs.gamma` passed at its first run, on the push and on pull request #3; provenance OK on both (`fork-ci.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): fork zephyrd (wip/sec.2, 16018bb0b) on its synced data served upstream's prebuilt WASM wallet (zephyr-javascript 9d022ded): sync to the tip 902057, reserve info, balance, save and reopen OK; the wip/sec.2 CLI wallet against an upstream v2.3.0 node refreshed to 902058/902058 (`serving-upstream-wallets.md`); done 2026-11-07 (local run; files in evidence/native/2026-11-07/): the upstream v2.3.0 CLI wallet against the fork node refreshed to 902084/902084, `bc_height` 902084, no error (`serving-upstream-wallets.md`, section "3.2, second attempt").
- **Notes:** the new status string is the only new text on the ZMQ wire, and only in reply to never-valid input.
