The one change to the daemon since upstream v2.3.0: a fresh node finds peers again. The two mainnet seeds compiled into v2.3.0 no longer accept connections, so I added the official public node and one more fallback node. Consensus, P2P protocol, RPC and the database format are untouched. To replace an upstream `zephyrd`: stop it, swap the binary, start it again with the same data directory and options.

New since `v2.3.0-sec.2-my.1`: the archives carry the release name, the release holds only the five archives and the signed `SHA256SUMS`, and the build leaves out the two wallet-only parts.
