# Linux x86_64 builder for zephyrd via contrib/depends.
#
# Base: docker.io/library/debian:11 (bullseye), linux/amd64 manifest, pinned by
# digest. Index digest when resolved (2026-11-08):
#   sha256:6f519a81440354a85eb592c5f32109ab80605f6b892455983a6f618bf87fabe9
# Packages come from one fixed, signed snapshot.debian.org timestamp (the one the
# base image itself names in /etc/apt/sources.list), not from the live mirrors.
# apt verifies every InRelease against the Debian archive keyring shipped in the
# base image; signature checking is never disabled.
#
# The bullseye-security InRelease at this timestamp carries
# "Valid-Until: Sun, 30 Aug 2026 23:23:27 UTC", which is in the past by design
# for a dated snapshot. check-valid-until=no is therefore set on that one source
# line only; the signature is still verified. bullseye and bullseye-updates carry
# no Valid-Until field and need no exception.
#
# Package list: the "x86_64 Linux" entry of .github/workflows/depends.yml plus
# g++-9. ccache is left out. build-in-container.sh compiles the target code with
# gcc-9/g++-9 (9.3.0): with bullseye's default GCC 10, libstdc++'s
# std::condition_variable timed waits call pthread_cond_clockwait, which raises
# the imported glibc symbol version to GLIBC_2.30; GCC 9 does not use it.
FROM docker.io/library/debian@sha256:c0a2ad73611131275b0e9a2e7544cfe3725f4268d4085d8c6f61fdd55aef7917

ARG SNAPSHOT=20260824T000000Z
ENV DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    TZ=UTC

RUN set -eu; \
    rm -f /etc/apt/sources.list.d/*; \
    { \
      echo "deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://snapshot.debian.org/archive/debian/${SNAPSHOT} bullseye main"; \
      echo "deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://snapshot.debian.org/archive/debian/${SNAPSHOT} bullseye-updates main"; \
      echo "deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${SNAPSHOT} bullseye-security main"; \
    } > /etc/apt/sources.list; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "120";\n' > /etc/apt/apt.conf.d/80-retries; \
    apt-get update; \
    apt-get install -y \
      build-essential libtool cmake autotools-dev automake pkg-config \
      bsdmainutils curl git ca-certificates \
      gperf python3-zmq libdbus-1-dev libharfbuzz-dev \
      g++-9; \
    { echo "snapshot ${SNAPSHOT}"; cat /etc/apt/sources.list; \
      for f in /var/lib/apt/lists/*_InRelease; do \
        echo "== ${f##*/} $(sha256sum "$f" | cut -d' ' -f1)"; \
        grep -E '^(Origin|Suite|Codename|Version|Date|Valid-Until):' "$f"; \
      done; } > /builder-apt-state.txt; \
    dpkg-query -W -f '${Package}\t${Version}\t${Architecture}\n' | sort > /builder-packages.tsv; \
    rm -rf /var/lib/apt/lists/*
