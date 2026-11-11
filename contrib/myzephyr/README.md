# myzephyr build and test tooling

Personal builds of the Zephyr daemon by the maintainer; not part of zephyr-backports.
This directory holds the build recipe and checks used by
`.github/workflows/daemon-release-baseline.yml`.

## When it runs and what is built

`run-identity.py` holds the table of runs this pipeline accepts; anything else fails in
the first step of every job (and again in every manifest and verifier):

| event | ref | built commit (`MYZ_BUILD_SHA`) | `GITHUB_SHA` |
|---|---|---|---|
| `push` | `refs/heads/ci/daemon-release-baseline` | `GITHUB_SHA` | the built commit |
| `push` | `refs/heads/my/<name>` | `GITHUB_SHA` | the built commit |
| `pull_request` into `my/<name>` | `refs/pull/<number>/merge` | the pull request's head commit | GitHub's test merge commit, never built |

In every row `GITHUB_WORKFLOW_SHA` equals `GITHUB_SHA`. For a pull request GitHub runs the
workflow file of its test merge commit; `ci-checkout.sh` proves that this merge commit has
exactly the parents base and head and the head's tree, so the workflow and scripts that
run are the head's, and that the base is an ancestor of the head (the pull request lands
by fast-forward). A pull request from a branch under `my/` or from
`ci/daemon-release-baseline` is refused, because that branch has its own push run: one
push starts one run. Pull requests from forks get a read-only token and no secrets; the
workflow uses none, and `contents: read` is its only permission.

Every job checks out exactly the built commit with `fetch-depth: 1` and `fetch-tags:
false` (with `fetch-depth: 0` actions/checkout fetches every tag), then `ci-checkout.sh`
completes the history with `git fetch --no-tags --unshallow` and fails if any tag is in
the checkout. That commit must be the signed zephyr-backports base tag plus own commits:

- the base tag object, its name, its commit and its signature by the backports key
  (primary fingerprint `FB39 94F0 997C A6F0 43D7  2491 9EFF 03F5 27D2 40A1`) are
  checked independently of the pushed head, and the base must be an ancestor of it;
- every commit above the base is checked one by one: one parent (no merges), the
  trailer `Origin: myzephyr`, a good signature by the maintainer key (primary
  fingerprint `31DA 39AB 43E0 CA67 F1F3  A661 BA2A FF22 DF8A 4A13`), and changes only
  to `src/p2p/net_node.h`, `src/p2p/net_node.inl`, the GoogleTest build recipe
  `contrib/depends/packages/gtest.mk`, `README.md`, the workflow and this directory;
  a commit changes either source (daemon or that build recipe) or
  tooling/documentation;
- no tag may point at the head; submodules must be at their recorded commits; the
  checkout must be clean. (`verify-source.sh --release-tag NAME` is the other mode: it
  requires exactly that maintainer-signed tag `v*-sec.*-my.*` at the head; the release
  script uses it on the already built commit, nothing is built from such a checkout.)

Both fingerprints are pinned in the workflow; the key files in `keys/` hold the
public keys only and must contain exactly the pinned primary key. Signatures are
checked by calling gpg directly, with the same binary and a temporary keyring for
import and verification, on the payload and signature split from each object exactly
as git splits them (`split-signed.sh`); git's own gpg call is not used, so the check
is the same under Git Bash on Windows as on Linux and macOS.

The version the binary reports follows from the commit, as in
`cmake/GitVersion.cmake`: `<version>-<first 9 hex digits of the commit>`, because no
build checkout has a tag. (GitVersion.cmake prints `<version>-release` when any tag
points at the commit; that string is refused by `zephyrd-check.py`, `check-embedded.py`,
both schemas and both verifiers.) The workflow derives the expected string the same way
and compares it with `zephyrd --version`. Built first, tagged afterwards: the binaries
of the push run on the landed head are the released ones, and the release tag is put on
that commit later without rebuilding anything. To reproduce the published version string,
build the tagged commit from a checkout without tags (`git clone --no-tags`, or delete
the tag locally): with the tag present the build would print `<version>-release`.

## Files

| file | purpose |
|---|---|
| `linux/Dockerfile` | Linux x86_64 builder: Debian 11 base pinned by digest, packages from one signed snapshot.debian.org timestamp, target code compiled with GCC 9 |
| `linux/run-builder.sh` | builds the image and runs the build as a non-root user (Docker or rootless Podman) |
| `linux/build-in-container.sh` | `contrib/depends` and CMake inside the image; `release` (target `daemon`, `CMAKE_SKIP_RPATH=ON`) or `tests` (`TESTS=1`, Debug, `unit_tests`, `test_notifier`) |
| `linux/run-unit-tests.sh` | runs the built `unit_tests` natively (`native`, used by CI) or in the image (`docker`/`podman`, diagnosis); records the environment (root filesystem device and the sysfs rotational attributes, binary hashes, interpreter and libraries), the test inventory, log and XML report; a missing prerequisite stops before any test is listed or run |
| `cross/Dockerfile`, `cross/run-builder.sh`, `cross/build-in-container.sh` | cross builders from the same base image digest and snapshot as `linux/`: Linux AArch64 (`aarch64-linux-gnu`, the snapshot's GCC 9.3 cross compiler with one hash-guarded header fix, see "Other platforms"), macOS x86_64 (`x86_64-apple-darwin`, depends' hash-pinned clang 9.0.0 and Xcode 12.2 SDK) and Windows x86_64 (`x86_64-w64-mingw32`, MinGW-w64 with the posix thread model); target `daemon`, Release |
| `check-macho.py`, `check-pe.py` | static checks of the macOS Mach-O and the Windows PE binary with fixed expectations (architecture, minimum OS, subsystem, linked libraries); pure Python, nothing is executed |
| `check-embedded.py` | the expected version string and the four mainnet IP seeds are embedded (used where the binary cannot run on the build machine) |
| `make-cross-manifest.py`, `manifest-cross.schema.json` | build manifest of a cross build (`myzephyr/daemon-cross-build-manifest/2`); the target fixes the format and binary name |
| `run-identity.py` | the run-identity table above: `check` as the first step of every job (writes `MYZ_PULL_REQUEST`), and the module the manifest writers and verifiers use |
| `ci-checkout.sh` | completes a depth-1 checkout without tags, checks the run identity and, for a pull request, the test merge commit; refuses any tag in the checkout; writes the checkout record the manifest cites |
| `verify-cross-artifact.py` | checks a downloaded cross artifact like `verify-artifact.py` does (whose workflow, source and base checks it reuses), with the verifier's own static and embedded reports |
| `unit-test-summary.py` | judges a unit-test run: every enabled test executed, no failure or skip, reference count (a different count is "review-required", not a pass) |
| `verify-source.sh`, `split-signed.sh` | the source checks above; `split-signed.sh` takes the signed payload and the signature from a tag or commit object as git 2.56 does, and refuses objects git would not hand to gpg |
| `check-elf.sh` | runtime requirements of the Linux x86_64 binary, or with `--arch aarch64` of the Linux AArch64 one (machine, interpreter): no RPATH/RUNPATH, glibc symbol versions at most 2.29, no shared C++ runtime |
| `make-manifest.py`, `manifest.schema.json` | build manifest (`myzephyr/daemon-build-manifest/3`): source commit with `tags_at_head: none` and the fetch mode, signed base, workflow run (with the pull request for a pull-request run), recipe, builder, packages, ELF requirements, artifact hash |
| `verify-artifact.py` | checks a downloaded release artifact against trusted inputs (see below) |
| `zephyrd-check.py` | bounded offline-start and default-discovery checks with strict RPC assertions on every sample |
| `link-inventory.sh` | runs in the builder after the build: re-runs the daemon's link with the linker's trace option, assigns every used input (object, archive member, start file) to its owner (a depends package by its cached build tarball, the source tree, or a Debian package of the image by `dpkg -S`) and copies the licence texts (top of the hash-stamped depends source, `/usr/share/doc/<package>/copyright`, the tree's licence files); anything it cannot establish is an `unresolved` line |
| `release/make-release-set.py`, `release/release-target.schema.json` | the release set of one run: an archive per platform, a manifest per platform (`myzephyr/daemon-release-target/1`) and `SHA256SUMS` (see "Release set") |
| `release/draft-release.sh`, `release/check-release-set.py` | run locally by the owner after the tag exists, never in CI: checks the run, the tag (`verify-source.sh --release-tag`), GitHub's digest of the release-set artifact and the set itself, then makes a draft release (`--dry-run` prints the command instead); see "Release set" |
| `release/compare-pr-run.py` | on a push run: the binary hashes of the pull-request run of the same commit, read from its hash marker artifacts' names, side by side in the run summary; reported, never a gate |
| `runtime/Dockerfile` | runtime-only Debian 11 arm64 userland (the arm64 manifest of the Linux builder base's index, python3 from the same snapshot) for a second offline start of the AArch64 binary |
| `tests/` | self-tests of `zephyrd-check.py` (stub daemon; `platform-selftest.py` checks the start and stop mechanics on Linux, macOS and Windows and prints diagnostics when a stub is not ready), of `verify-source.sh` (`verify-source-selftest.sh`: a repository and keys made by the test, the split compared with git's own, single changes that must fail), of `unit-test-summary.py` (small invented fixtures), of the preflight of `run-unit-tests.sh` (stub commands and a stub test executable), of `verify-artifact.py` (`artifact-fixture/`: the metadata of run 42543200624's release artifact, with placeholder bytes for the binary) and of the cross-target checks (`cross-selftest.py`, `cross-fixture/`: metadata measured on local cross builds, from which small synthetic ELF, Mach-O and PE files are made); `run-identity-selftest.py` (each row of the table and one changed value per case) and `ci-checkout-selftest.sh` (a local origin with tags and merge refs over a file URL); `link-inventory-selftest.sh` (a small tree linked by the runner's gcc and GNU ld) and `release-set-selftest.py` (synthetic artifacts; also the run comparison against a stub API) |
| `keys/zephyr-backports-release.asc` | public key that signs the zephyr-backports tags |
| `keys/myzephyr-maintainer.asc` | public key that signs the own commits |

## Release set

The `package` job needs every build and runtime job of the run. It downloads the four
artifacts, verifies each again with its own checkout and checks, and makes one archive per
platform (`linux-x86_64`, `linux-aarch64`, `macos-x86_64`, `windows-x86_64`) with the fixed
layout `zephyrd-<version string>-<platform>/`: the binary, the tree's `LICENSE`,
`THIRD-PARTY-LICENSES/` and `README.txt`. File names carry the version string the binary
reports, never a tag. Linux and macOS get `.tar.gz` (GNU tar `--format=gnu --sort=name
--mtime=@SOURCE_DATE_EPOCH --owner=0 --group=0 --numeric-owner --mode=u+rwX,go+rX,go-w`, gzip
without name or time), Windows a `.zip` with fixed entry times and modes; SOURCE_DATE_EPOCH is
the commit time. Each archive is read back and must hold exactly the staged files and the
binary whose hash the build manifest names. A manifest per platform records archive and
binary hashes, the verified build manifest, source, base, own commits, the run, what the
hosted runners tested, and the licence list. `SHA256SUMS` lists the archives and manifests,
never itself. The set is one artifact, `release-set-<commit>`, kept 90 days on pushes to
`my/**`.

`THIRD-PARTY-LICENSES/` comes from the build's link inventory (`link-inventory.sh`), whose
hash the build manifest records (`build.link_inventory_sha256`, checked by the verifiers).
The list is "complete" only if the traced re-link was identical, nothing is unresolved,
every used input's owner has a text and every depends source hash equals its pin in
`contrib/depends/packages/`; otherwise the set is written with status "incomplete" and the
reasons (manifest, `INDEX.txt`, `README.txt`, a warning in the job log), and the release
script refuses it. The list is reviewed before any release.

`release/draft-release.sh <tag> <run-id>` is run locally after the owner has pushed the
signed tag on the already proven commit; nothing is rebuilt. It requires a successful push
run of this workflow on `my/v2.3.0` whose head commit is the tag's commit (the branch head
or an ancestor of it), verifies the tag in a fresh clone without tags (annotated, signed by
the pinned maintainer key, name `v*-sec.*-my.*`), downloads the run's `release-set-<commit>`
artifact and checks GitHub's digest, `SHA256SUMS`, every manifest (commit, run and attempt,
version string without `release`, complete licences) and every archive, refuses if a
release for the tag exists, and runs `gh release create --draft --verify-tag` with exactly
those files and notes made from the manifests. It never publishes and never signs;
`--dry-run` prints the command and file list. `tests/draft-release-selftest.py` runs it
against a stubbed `gh` with throwaway keys and a synthetic repository.

## Unit tests

The `tests` build is compiled in the builder image, like the release build. The
workflow then runs that same `unit_tests` binary natively on the runner
(`run-unit-tests.sh native`), from `build/tests`, with `test_notifier` next to it and
`--data-dir tests/data`. Some tests read the host: `is_hdd.linux_os_root` needs
`/sys/dev/block/<major>:<minor>/queue/rotational` (or the parent device's) for the
device of `/`, which a container root filesystem does not have. The environment record
`unit-tests-environment.txt` in the artifact names that device, both attribute paths and
the SHA256 of both test binaries. All enabled tests run; nothing is filtered or skipped.

Before any test is listed or run, a preflight checks the prerequisites and stops with
exit 2 and a `PREREQUISITE` line when one is missing: a root user, a failing `id`,
`stat`, `sha256sum`, `readelf` or `ldd` (each judged by its exit status and its complete
output, never by empty output), a missing program interpreter, or a shared library the
loader reports as not found. The two modes differ in one point:

- `native` is the acceptance mode. If neither rotational attribute of the root device
  can be read as a number (the first readable path decides, as in `tools::is_hdd`),
  `is_hdd.linux_os_root` cannot pass on that host, so the run stops there and no test is
  started. Nothing is faked: the detector and sysfs are used as they are.
- `docker`/`podman` are diagnostic. The same finding is a `PRECONDITION` line and the
  full suite still runs and is judged, so the container failure stays reproducible. A
  diagnostic run is not an acceptance result.

`tests/unit-preflight-selftest.py` checks these paths in tooling CI with stub commands
(first in `PATH`) and a stub test executable that records any invocation; every failing
prerequisite must stop the script before that stub is invoked. Its fixture device, sysfs
values and container engine are invented and say nothing about any real host.

## Verifying a downloaded artifact

The jobs that use the release artifact verify it in three separate steps:

1. `verify-source.sh` on their own checkout of the built commit: signatures of the
   base tag and of every own commit, history, no tag at the head, submodules, clean tree;
2. `check-elf.sh` on the downloaded `zephyrd` (static inspection; nothing is executed);
3. `verify-artifact.py`, which accepts the artifact only if its files and manifest
   agree with those two results, with `zephyrd-check.py expected-version` of the same
   checkout, with the recipe files of that checkout, with the base policy pinned in the
   workflow, and with the job's own run context: `GITHUB_REPOSITORY`, `GITHUB_REF`,
   `GITHUB_WORKFLOW_REF`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_EVENT_NAME`,
   `GITHUB_SHA` for `workflow.sha` and `workflow.workflow_sha`, `MYZ_BUILD_SHA` for
   `source.commit`, and the pull request read from the job's own event payload. That
   context must itself be a row of the run-identity table. None of these values is read
   from the artifact.

`verify-artifact.py` checks the layout (regular files only, no symlinks), `SHA256SUMS`
(exactly `zephyrd`, `manifest.json`, `expected-version.txt`, `source-identity.txt`,
plain names, no duplicates, matching hashes), the manifest as strict JSON against
`manifest.schema.json`, every recorded check being true, the ELF state (`passed`,
permitted interpreter and libraries, no RPATH/RUNPATH, GLIBC at most 2.29), size,
hash, target and version, and the build records in `build-logs/`. A manifest with
`local_build` is never accepted as CI provenance. Checksums and a manifest are not a
signature: they bind the artifact to a verified source and run, not to a maintainer.

The run attempt must match: re-running only the jobs that download the artifact, with
the artifact of an earlier attempt, is rejected; re-run the whole workflow.

To verify an artifact by hand, run `verify-source.sh` (with the workflow's values,
including `--base-repository`) and `check-elf.sh` yourself, then pass their outputs and
the run's values as reported by GitHub, not by the manifest; `verify-artifact.py --help`
lists the options.

## Local replay

From a clean checkout of the branch head, with the base tag fetched into a ref:

```sh
git fetch --no-tags https://github.com/zephyr-backports/zephyr.git \
  +refs/tags/v2.3.0-sec.2:refs/myzephyr-base/v2.3.0-sec.2
# verify-source.sh with the values from the workflow's env block, then:
contrib/myzephyr/linux/run-builder.sh podman release <checkout> <new-log-dir>
contrib/myzephyr/check-elf.sh <checkout>/build/release/bin/zephyrd <report>
```

Use separate checkouts for `release` and `tests`; the build script refuses to mix
them. The Linux binary is compiled with GCC 9 from the snapshot: with GCC 10,
libstdc++'s timed condition-variable waits import `pthread_cond_clockwait@GLIBC_2.30`,
above the glibc 2.29 that upstream's v2.3.0 Linux daemon needs.

The inherited build, depends, tests and provenance workflows (upstream's matrices and the
zephyr-backports policy of Monero cherry-picks only) exclude pushes to
`ci/daemon-release-baseline` and to `my/**` and pull requests into `my/**`; with only a
branch filter on push they never start on a tag push, also not on a `v*-sec.*-my.*` tag.
The dedicated workflow runs the build and test gates there. Other branches and pull
requests keep their existing triggers. The inherited `gitian.yml` still starts on every
tag push.

A local replay is a different checkout than CI's: it gets `--local` manifests, which no
verifier accepts as CI provenance.

## Other platforms

Upstream v2.3.0 ships daemons for Linux x86_64, Linux AArch64, macOS x86_64 (minimum
10.13) and Windows x86_64. The workflow builds Linux AArch64, macOS x86_64 and Windows
x86_64 with `contrib/depends` in the cross builder (`cross-build`) and inspects them
statically: an AArch64 ELF position-independent executable with the interpreter
`/lib/ld-linux-aarch64.so.1`, upstream's NEEDED set, glibc symbol versions at most 2.29
and no RPATH/RUNPATH or shared C++ runtime (`check-elf.sh --arch aarch64`); a thin x86_64
Mach-O with minimum macOS 10.13.0 that links only OS frameworks and libc++/libSystem; and
a PE32+ x86-64 console executable that imports only Windows system DLLs (no MinGW
runtime DLL). The binary is not executed on the build machine: the
expected version and the mainnet seeds are checked as embedded strings, and the manifest
carries no version output.

`native-runtime` then takes each artifact to a hosted runner of its platform
(`ubuntu-24.04-arm`, `macos-15-intel`, `windows-2022`), verifies the source and the artifact itself like the
Linux consumer jobs, runs `--version`, the strict offline start and the default discovery
with `zephyrd-check.py`. On Windows the clean-stop request is `CTRL_BREAK_EVENT` to the
daemon, started in its own process group, which zephyrd handles like Ctrl+C; on Linux and
macOS it is SIGTERM. A daemon that has to be killed is a failed cleanup everywhere.

These runners prove a start on those images only (Ubuntu 24.04 on AArch64, macOS 15 on
Intel, Windows Server 2022). On the AArch64 runner the binary also gets a strict offline
start in a runtime-only Debian 11 arm64 userland (glibc 2.31, `runtime/Dockerfile`), as
the x86_64 binary does in the Debian 11 builder userland; the job records that image's
glibc version. Other AArch64 distributions, macOS 10.13 to 14, Apple Silicon (Rosetta)
and Windows 10 are not covered.

Linux AArch64 compiler header: the snapshot's GCC 9.3 cross compiler
(`libgcc-9-dev-arm64-cross` 9.3.0-22cross1) ships an `arm_acle.h` whose `extern "C"`
block is opened twice and closed once, so RandomX does not compile with it. This is GCC
PR target/100985, fixed on the gcc-9 branch by commit
`8c92fcb13a4979232787f0476bf7469ccbb03617` (first released in GCC 9.5.0). The cross
builder applies exactly that change to the packaged header, checking the file's SHA256
before (the packaged file) and after (the fixed gcc-9 file); any other input fails the
image build, and `builder-apt-state.txt`, hence the manifest, records it. A newer cross
compiler would raise the glibc requirement above upstream's 2.29.
