# myzephyr build and test tooling

My personal builds of the Zephyr daemon; not part of zephyr-backports. This directory holds
the build recipe and the checks of `.github/workflows/daemon-release-baseline.yml`.

## Runs and source

`run-identity.py` holds the runs the pipeline accepts; anything else fails in the first step
of every job and again in every manifest and verifier:

| event | ref | built commit (`MYZ_BUILD_SHA`) |
|---|---|---|
| `push` | `ci/daemon-release-baseline` or `my/<name>` | `GITHUB_SHA` |
| `pull_request` into `my/<name>` | `refs/pull/<number>/merge` | the pull request's head, never GitHub's test merge |

For a pull request, `ci-checkout.sh` proves that the test merge commit has exactly the
parents base and head and the head's tree, so the workflow that runs is the head's. A pull
request from `my/*` or `ci/daemon-release-baseline` is refused: that branch has its own push
run. The workflow uses no secrets; `contents: read` is its only permission.

Every job checks out the built commit at depth 1 without tags; `ci-checkout.sh` completes the
history with `git fetch --no-tags --unshallow`, fetches the base tag into
`refs/myzephyr-base/`, leaves submodules at their recorded commits and fails if any tag is
present. `verify-source.sh` then requires the signed zephyr-backports base tag (primary
fingerprint `FB39 94F0 997C A6F0 43D7  2491 9EFF 03F5 27D2 40A1`) plus own commits, each with
one parent, the trailer `Origin: myzephyr`, my signature (primary fingerprint
`31DA 39AB 43E0 CA67 F1F3  A661 BA2A FF22 DF8A 4A13`) and changes only to
`src/p2p/net_node.h`, `src/p2p/net_node.inl`, `contrib/depends/packages/gtest.mk`,
`README.md`, the workflow files and this directory; no tag at the head, a clean tree.
Signatures are checked by calling gpg directly on the payload and signature split as git
splits them (`split-signed.sh`), the same on Linux, macOS and Windows. With
`--release-tag NAME` it requires exactly that signed tag at the head instead; only the
release script uses that mode.

The binary reports `<version>-<first 9 hex digits of the commit>` (`cmake/GitVersion.cmake`;
no build checkout has a tag, and `<version>-release` is refused everywhere). I build first and
tag afterwards: the binaries of the push run on the landed head are the released ones. To
reproduce a released binary, build the tagged commit from a clone without tags.

## The daemon-only configuration

The recipes configure CMake with `CMAKE_DISABLE_FIND_PACKAGE_HIDAPI=ON` and
`USE_DEVICE_TREZOR=OFF`, and on Linux x86_64 and macOS x86_64 with
`MONERO_WALLET_CRYPTO_LIBRARY=cn`. The binary then contains no hardware-wallet code (Ledger,
hidapi, libusb, libudev, and the macOS frameworks and Windows `setupapi` only the device
checks add) and no supercop assembly. The daemon selects only the default device and never
calls the wallet-crypto functions that assembly speeds up. `contrib/depends` still builds
its packages unchanged.

## Files

| file | purpose |
|---|---|
| `RELEASE` | the name of the release this commit line prepares, e.g. `v2.3.0-sec.2-my.2`; bumped by hand by the first change meant for a later release |
| `linux/Dockerfile`, `linux/run-builder.sh`, `linux/build-in-container.sh` | Linux x86_64 builder (Debian 11 by digest, one snapshot.debian.org timestamp, GCC 9) and the build in it as a non-root user: `release` (target `daemon`) or `tests` (`TESTS=1`, Debug, `unit_tests`, `test_notifier`) |
| `linux/run-unit-tests.sh` | runs the built `unit_tests` natively (CI) or in the image (diagnosis); records environment, inventory, log and XML |
| `cross/Dockerfile`, `cross/run-builder.sh`, `cross/build-in-container.sh` | cross builders from the same base and snapshot: Linux AArch64 (GCC 9.3 with one hash-guarded header fix, below), macOS x86_64 and arm64 (depends' clang and SDK; ld64 signs arm64 ad hoc), Windows x86_64 (MinGW-w64, posix threads) |
| `check-elf.sh`, `check-macho.py`, `check-pe.py` | static checks with fixed expectations: architecture, interpreter or minimum OS, linked libraries, no RPATH, glibc at most 2.29; arm64 Mach-O code signature; nothing is executed |
| `check-embedded.py` | the expected version string and the mainnet seeds are embedded (where the binary cannot run on the build machine) |
| `make-manifest.py`, `make-cross-manifest.py`, `manifest*.schema.json` | build manifests: source and fetch mode, signed base, run, recipe, builder, packages, checks, artifact hash |
| `verify-artifact.py`, `verify-cross-artifact.py` | check a downloaded artifact against the consumer's own results (below) |
| `run-identity.py`, `ci-checkout.sh` | the run table and the checkout completion above |
| `verify-source.sh`, `split-signed.sh` | the source checks above |
| `unit-test-summary.py` | judges a unit-test run: every enabled test ran, none failed or was skipped, the reference count |
| `zephyrd-check.py` | bounded offline-start and default-discovery checks with strict RPC assertions |
| `link-inventory.sh`, `link-sources.py` | after the build: re-run the daemon's link line with the linker's trace (byte-identical result required), assign every used input to its owner and copy the licence texts; anything not established is an `unresolved` line |
| `release/make-release-set.py`, `release/release-target.schema.json` | the release set of one run (below) |
| `release/draft-release.sh`, `release/check-release-set.py`, `release/WHATSNEW.md` | the draft release, run locally after the tag exists (below) |
| `release/compare-pr-run.py` | on a push run, the binary hashes of the pull-request run of the same commit, side by side; reported, not a gate |
| `runtime/Dockerfile` | runtime-only Debian 11 arm64 userland for a second offline start of the AArch64 binary |
| `tests/` | self-tests of all of the above with synthetic inputs, run by the `tooling-selftest` job |
| `keys/` | the public keys of zephyr-backports and of mine; each must hold exactly the pinned primary key |

## Release set

The `package` job needs every build and runtime job. It verifies the five artifacts again and
makes one archive per platform (`linux-x86_64`, `linux-aarch64`, `macos-x86_64`,
`macos-arm64`, `windows-x86_64`), named `zephyrd-<release>-<platform>` after `RELEASE`:
the binary, `LICENSE`, `THIRD-PARTY-LICENSES/` and a short `README.txt`. Linux and macOS get
`.tar.gz`, Windows `.zip`, with fixed times (the commit time), owners and modes; each archive
is read back and must hold exactly the staged files. `SHA256SUMS` lists the five archives;
they and its signature are the release assets. A manifest per platform beside them records
hashes, the build manifest, the run, what was tested, the licence list and the copyleft
libraries; it is the release script's input and a run artifact, not a release asset. The set
is the artifact `release-set-<commit>`, kept 90 days on pushes to `my/**`.

`THIRD-PARTY-LICENSES/` comes from the build's link inventory, whose hash the build manifest
records. It is "complete" only if the re-link was identical, nothing is unresolved, every used
owner has a text and every depends source hash equals its pin in `contrib/depends/packages/`.
A compiled-in file without a licence statement does not block (upstream ships it the same
way). `README.txt` names, for each copyleft library linked in (GNU readline, ZeroMQ), its
version, licence, upstream URL and pinned SHA256 from its depends recipe.

After the owner has pushed the signed tag on the proven commit, `release/draft-release.sh
--gate-note FILE <tag> <run-id>` runs locally; nothing is rebuilt. It requires a successful
push run on `my/v2.3.0` whose head is the tag's commit, verifies the tag in a fresh clone
without tags, requires `RELEASE` at that commit to equal the tag, checks GitHub's digest of the
release-set artifact, `SHA256SUMS`, every manifest and every archive, and refuses an existing
release. The notes come from `release/WHATSNEW.md` at the tagged commit (written by hand for
each release), the manifests and the gate note (the full sync and database resume of the
Linux x86_64 binary); an empty text or a placeholder is refused. Then `gh release create
--draft --verify-tag` with the five archives and `SHA256SUMS`. It never publishes or signs;
`--dry-run` prints the command.

## Unit tests

The `tests` build is compiled in the builder image; CI runs that `unit_tests` binary natively
on the runner (`run-unit-tests.sh native`) with `--data-dir tests/data`, because
`is_hdd.linux_os_root` reads the sysfs rotational attribute of the root device, which a
container root does not have. All enabled tests run; nothing is filtered. A preflight stops
with exit 2 before any test when a prerequisite is missing (root user, a failing `id`, `stat`,
`sha256sum`, `readelf` or `ldd`, interpreter, library, and natively an unreadable rotational
attribute). The container modes report that as a `PRECONDITION` and still run the suite, for
diagnosis only.

## Verifying a downloaded artifact

The jobs that use an artifact verify it themselves: `verify-source.sh` on their own checkout,
the static check of the binary, then `verify-artifact.py` (or `verify-cross-artifact.py`),
which accepts the artifact only if its files and manifest agree with those results, with the
recipe and expected version of that checkout, the pinned base policy and the job's own run
context (repository, ref, workflow ref, run id and attempt, event, commits, pull request),
none of it read from the artifact. Checksums and a manifest bind the artifact to a verified
source and run, not to a person; the signed `SHA256SUMS` of a release does that. Re-running
only the consumer jobs with an earlier attempt's artifact is rejected.

## Local replay

```sh
git fetch --no-tags --no-recurse-submodules https://github.com/zephyr-backports/zephyr.git \
  +refs/tags/v2.3.0-sec.2:refs/myzephyr-base/v2.3.0-sec.2
# verify-source.sh with the values of the workflow's env block, then:
contrib/myzephyr/linux/run-builder.sh podman release <checkout> <new-log-dir>
contrib/myzephyr/check-elf.sh <checkout>/build/release/bin/zephyrd <report>
```

Use separate checkouts for `release`, `tests` and each cross target. GCC 9 matters: with
GCC 10, libstdc++ imports `pthread_cond_clockwait@GLIBC_2.30`, above the glibc 2.29 of
upstream's v2.3.0 daemon. A local build gets a `--local` manifest, which no verifier accepts
as CI provenance.

The inherited build, depends, tests and provenance workflows do not run on
`ci/daemon-release-baseline`, `my/**`, `pr/**` or pull requests into `my/**`, nor on tags;
`gitian.yml` ignores the release tags `v*-sec.*-my.*`.

## Other platforms

Upstream v2.3.0 ships Linux x86_64, Linux AArch64, macOS x86_64 and Windows x86_64 daemons; I
add macOS arm64. The cross builds are checked statically (`check-elf.sh --arch aarch64`,
`check-macho.py`, `check-macho.py --arch arm64`, `check-pe.py`): upstream's libraries and
glibc 2.29 on AArch64; a thin Mach-O with minimum macOS 10.13 linking only OS libraries, for
arm64 with the ad-hoc signature Apple Silicon requires; a PE32+ console executable importing
only Windows system DLLs. `native-runtime` then runs each on a hosted runner of its platform
(`ubuntu-24.04-arm`, `macos-15-intel`, `macos-26`, `windows-2022`): own verification,
`--version`, offline start and default discovery; the AArch64 binary also starts in a Debian
11 arm64 userland. On Windows the clean stop is `CTRL_BREAK_EVENT`, elsewhere SIGTERM. Other
distributions, older macOS and Windows versions and Rosetta are not covered; neither macOS
binary is notarized.

The snapshot's GCC 9.3 AArch64 cross compiler ships an `arm_acle.h` with an unbalanced
`extern "C"` block (GCC PR target/100985), so RandomX does not compile. The cross builder
applies exactly the gcc-9 branch fix `8c92fcb13a4979232787f0476bf7469ccbb03617` to that header,
checking its SHA256 before and after; any other input fails the image build.
