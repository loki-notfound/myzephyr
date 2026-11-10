# myzephyr build and test tooling

Personal builds of the Zephyr daemon by the maintainer; not part of zephyr-backports.
This directory holds the build recipe and checks used by
`.github/workflows/daemon-release-baseline.yml`.

## What is built

The workflow builds the commit that was pushed (`GITHUB_SHA`), not a separate
checkout. That commit must be the signed zephyr-backports base tag plus own commits:

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
- tags at the head must be signed by the maintainer key; submodules must be at their
  recorded commits; the checkout must be clean.

Both fingerprints are pinned in the workflow; the key files in `keys/` hold the
public keys only and must contain exactly the pinned primary key.

The version the binary reports follows from the commit, as in
`cmake/GitVersion.cmake`: `<version>-release` when a tag points at the commit,
otherwise `<version>-<first 9 hex digits of the commit>`. The workflow derives the
expected string the same way and compares it with `zephyrd --version`.

## Files

| file | purpose |
|---|---|
| `linux/Dockerfile` | Linux x86_64 builder: Debian 11 base pinned by digest, packages from one signed snapshot.debian.org timestamp, target code compiled with GCC 9 |
| `linux/run-builder.sh` | builds the image and runs the build as a non-root user (Docker or rootless Podman) |
| `linux/build-in-container.sh` | `contrib/depends` and CMake inside the image; `release` (target `daemon`, `CMAKE_SKIP_RPATH=ON`) or `tests` (`TESTS=1`, Debug, `unit_tests`, `test_notifier`) |
| `linux/run-unit-tests.sh` | runs the built `unit_tests` natively (`native`, used by CI) or in the image (`docker`/`podman`, diagnosis); records the environment (root filesystem device and the sysfs rotational attributes, binary hashes, interpreter and libraries), the test inventory, log and XML report; a missing prerequisite stops before any test is listed or run |
| `cross/Dockerfile`, `cross/run-builder.sh`, `cross/build-in-container.sh` | cross builders from the same base image digest and snapshot as `linux/`: macOS x86_64 (`x86_64-apple-darwin`, depends' hash-pinned clang 9.0.0 and Xcode 12.2 SDK) and Windows x86_64 (`x86_64-w64-mingw32`, MinGW-w64 with the posix thread model); target `daemon`, Release. The `aarch64-linux-gnu` option exists to reproduce the known build failure only (see "Other platforms") |
| `check-macho.py`, `check-pe.py` | static checks of the macOS Mach-O and the Windows PE binary with fixed expectations (architecture, minimum OS, subsystem, linked libraries); pure Python, nothing is executed |
| `check-embedded.py` | the expected version string and the three mainnet seeds are embedded (used where the binary cannot run on the build machine) |
| `make-cross-manifest.py`, `manifest-cross.schema.json` | build manifest of a cross build (`myzephyr/daemon-cross-build-manifest/1`); the target fixes the format and binary name |
| `verify-cross-artifact.py` | checks a downloaded cross artifact like `verify-artifact.py` does (whose workflow, source and base checks it reuses), with the verifier's own static and embedded reports |
| `unit-test-summary.py` | judges a unit-test run: every enabled test executed, no failure or skip, reference count (a different count is "review-required", not a pass) |
| `verify-source.sh` | the source checks above |
| `check-elf.sh` | runtime requirements: no RPATH/RUNPATH, glibc symbol versions at most 2.29, no shared C++ runtime |
| `make-manifest.py`, `manifest.schema.json` | build manifest: source commit and tags, signed base, workflow run, recipe, builder, packages, ELF requirements, artifact hash |
| `verify-artifact.py` | checks a downloaded release artifact against trusted inputs (see below) |
| `zephyrd-check.py` | bounded offline-start and default-discovery checks with strict RPC assertions on every sample |
| `tests/` | self-tests of `zephyrd-check.py` (stub daemon; `platform-selftest.py` checks the start and stop mechanics on Linux, macOS and Windows), of `unit-test-summary.py` (small invented fixtures), of the preflight of `run-unit-tests.sh` (stub commands and a stub test executable), of `verify-artifact.py` (`artifact-fixture/`: the metadata of run 42543200624's release artifact, with placeholder bytes for the binary) and of the cross-target checks (`cross-selftest.py`, `cross-fixture/`: metadata measured on local cross builds, from which small synthetic Mach-O and PE files are made) |
| `keys/zephyr-backports-release.asc` | public key that signs the zephyr-backports tags |
| `keys/myzephyr-maintainer.asc` | public key that signs the own commits |

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

1. `verify-source.sh` on their own checkout of the pushed commit: signatures of the
   base tag and of every own commit, history, tags at the head, submodules, clean tree;
2. `check-elf.sh` on the downloaded `zephyrd` (static inspection; nothing is executed);
3. `verify-artifact.py`, which accepts the artifact only if its files and manifest
   agree with those two results, with `zephyrd-check.py expected-version` of the same
   checkout, with the recipe files of that checkout, with the base policy pinned in the
   workflow, and with the job's own run context: `GITHUB_REPOSITORY`, `GITHUB_REF`,
   `GITHUB_WORKFLOW_REF`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, and `GITHUB_SHA` for
   `source.commit`, `workflow.sha` and `workflow.workflow_sha`. None of these values is
   read from the artifact.

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

The inherited build, depends, tests and provenance workflows exclude pushes to
`ci/daemon-release-baseline`. The dedicated workflow runs this branch's build and
test gates. Other branches and pull requests keep their existing triggers.

## Other platforms

Upstream v2.3.0 ships daemons for Linux x86_64, Linux AArch64, macOS x86_64 (minimum
10.13) and Windows x86_64. The workflow builds macOS x86_64 and Windows x86_64 with
`contrib/depends` in the cross builder (`cross-build`) and inspects them statically:
a thin x86_64 Mach-O with minimum macOS 10.13.0 that links only OS frameworks and
libc++/libSystem, and a PE32+ x86-64 console executable that imports only Windows system
DLLs (no MinGW runtime DLL). The binary is not executed on the build machine: the
expected version and the mainnet seeds are checked as embedded strings, and the manifest
carries no version output.

`native-runtime` then takes each artifact to a hosted runner of its platform
(`macos-15-intel`, `windows-2022`), verifies the source and the artifact itself like the
Linux consumer jobs, runs `--version`, the strict offline start and the default discovery
with `zephyrd-check.py`. On Windows the clean-stop request is `CTRL_BREAK_EVENT` to the
daemon, started in its own process group, which zephyrd handles like Ctrl+C; on Linux and
macOS it is SIGTERM. A daemon that has to be killed is a failed cleanup everywhere.

These runners prove a start on those images only (macOS 15 on Intel, Windows Server
2022). macOS 10.13 to 14, Apple Silicon (Rosetta), Windows 10 and older ARM64
distributions are not covered by them.

Linux AArch64 is not built yet: the snapshot's GCC 9.3 cross compiler ships an
`arm_acle.h` whose `extern "C"` block is opened twice and closed once, and RandomX does
not compile with it. A newer cross compiler would raise the glibc requirement above
upstream's 2.29; the fix is pending review.
