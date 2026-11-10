# Cross builders for zephyrd via contrib/depends: Linux AArch64, macOS x86_64 and
# Windows x86_64. Same base image digest and the same signed snapshot.debian.org
# timestamp as ../linux/Dockerfile (see there for the snapshot and Valid-Until notes);
# only the package list differs per target. The Linux x86_64 builder is unchanged.
#
#   TARGET=aarch64-linux-gnu    gcc-9/g++-9 aarch64 cross compilers (9.3.0, as the
#                               Linux x86_64 build uses GCC 9 to stay at GLIBC_2.29)
#   TARGET=x86_64-w64-mingw32   MinGW-w64 GCC, posix thread model
#   TARGET=x86_64-apple-darwin  the tree's hash-pinned native_clang 9.0.0 (an Ubuntu
#                               18.04 build that needs libtinfo5), cctools and libtapi
#                               are built by depends; the SDK comes from depends too
FROM docker.io/library/debian@sha256:c0a2ad73611131275b0e9a2e7544cfe3725f4268d4085d8c6f61fdd55aef7917

ARG SNAPSHOT=20260824T000000Z
ARG TARGET
ENV DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    TZ=UTC

RUN set -eu; \
    case "${TARGET}" in \
      aarch64-linux-gnu) target_packages="gcc-9-aarch64-linux-gnu g++-9-aarch64-linux-gnu" ;; \
      x86_64-w64-mingw32) target_packages="g++-mingw-w64-x86-64-posix gcc-mingw-w64-x86-64-posix" ;; \
      x86_64-apple-darwin) target_packages="libtinfo5 zlib1g-dev libbz2-dev xz-utils" ;; \
      *) echo "unknown TARGET '${TARGET}'" >&2; exit 2 ;; \
    esac; \
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
      bsdmainutils curl git ca-certificates gperf python3 \
      ${target_packages}; \
    { echo "target ${TARGET}"; echo "snapshot ${SNAPSHOT}"; cat /etc/apt/sources.list; \
      for f in /var/lib/apt/lists/*_InRelease; do \
        echo "== ${f##*/} $(sha256sum "$f" | cut -d' ' -f1)"; \
        grep -E '^(Origin|Suite|Codename|Version|Date|Valid-Until):' "$f"; \
      done; } > /builder-apt-state.txt; \
    dpkg-query -W -f '${Package}\t${Version}\t${Architecture}\n' | sort > /builder-packages.tsv; \
    rm -rf /var/lib/apt/lists/*
