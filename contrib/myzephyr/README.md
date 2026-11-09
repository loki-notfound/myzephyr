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
| `linux/run-unit-tests.sh` | runs `unit_tests` in the image, records the test inventory, log and XML report |
| `unit-test-summary.py` | judges a unit-test run: every enabled test executed, no failure or skip, reference count (a different count is "review-required", not a pass) |
| `verify-source.sh` | the source checks above |
| `check-elf.sh` | runtime requirements: no RPATH/RUNPATH, glibc symbol versions at most 2.29, no shared C++ runtime |
| `make-manifest.py`, `manifest.schema.json` | build manifest: source commit and tags, signed base, workflow run, recipe, builder, packages, ELF requirements, artifact hash |
| `verify-artifact.py` | checks a downloaded artifact's hashes and that its manifest names the commit under test |
| `zephyrd-check.py` | bounded offline-start and default-discovery checks with strict RPC assertions on every sample |
| `tests/` | self-tests of `zephyrd-check.py` (stub daemon) and of `unit-test-summary.py` (small invented fixtures) |
| `keys/zephyr-backports-release.asc` | public key that signs the zephyr-backports tags |
| `keys/myzephyr-maintainer.asc` | public key that signs the own commits |

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

Only Linux x86_64 is built so far. Native runtime checks for Linux ARM64, Intel
macOS and Windows are the next step, on the GitHub-hosted runners
`ubuntu-24.04-arm`, `macos-15-intel` and `windows-2022`.

The inherited build, depends, tests and provenance workflows exclude pushes to
`ci/daemon-release-baseline`. The dedicated workflow runs this branch's build and
test gates. Other branches and pull requests keep their existing triggers.
