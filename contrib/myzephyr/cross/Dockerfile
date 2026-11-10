# Cross builders for zephyrd via contrib/depends: Linux AArch64, macOS x86_64 and
# Windows x86_64. Same base image digest and the same signed snapshot.debian.org
# timestamp as ../linux/Dockerfile (see there for the snapshot and Valid-Until notes);
# only the package list differs per target. The Linux x86_64 builder is unchanged.
#
#   TARGET=aarch64-linux-gnu    gcc-9/g++-9 aarch64 cross compilers (9.3.0, as the
#                               Linux x86_64 build uses GCC 9 to stay at GLIBC_2.29);
#                               one header of that compiler is fixed, see the last RUN
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

# Linux AArch64 only. The snapshot's libgcc-9-dev-arm64-cross (9.3.0-22cross1) ships an
# arm_acle.h that opens extern "C" twice and closes it once, so every C++ file that
# includes it (RandomX) ends inside an extern "C" block: GCC PR target/100985, fixed on
# the gcc-9 branch by commit 8c92fcb13a4979232787f0476bf7469ccbb03617 ("aarch64: Fix
# mismatched extern "C" block [PR100985]", first released in GCC 9.5.0). That fix is
# applied here unchanged: it deletes lines 101-104 (#ifdef __cplusplus, extern "C" {,
# #endif and the blank line after them). The input must be the packaged file, byte-equal
# to the gcc-9 branch file before the fix (and to GCC 9.4.0's); the result must be
# byte-equal to the fixed file (and to GCC 9.5.0's). Any other input fails the image
# build. The compilers stay the snapshot's packages; the record goes into
# /builder-apt-state.txt and from there into the manifest's builder section.
RUN set -eu; \
    if [ "${TARGET}" = aarch64-linux-gnu ]; then \
      h=/usr/lib/gcc-cross/aarch64-linux-gnu/9/include/arm_acle.h; \
      before=661077f9f87c2d402030ab91224efef2bfa8d810630e433fb51768fbcbb1a53c; \
      after=532c806d237232431c45ca0a31a97ad5dfbafba7f68425e6056baa3ff44d5a75; \
      echo "${before}  ${h}" | sha256sum -c -; \
      sed -i '101,104d' "${h}"; \
      echo "${after}  ${h}" | sha256sum -c -; \
      { echo "patched ${h} of $(dpkg -S "${h}" | cut -d: -f1) $(dpkg-query -W -f '${Version}' libgcc-9-dev-arm64-cross)"; \
        echo "patched sha256 before ${before}"; \
        echo "patched sha256 after ${after}"; \
        echo "patched reason GCC PR target/100985, gcc-9 commit 8c92fcb13a4979232787f0476bf7469ccbb03617, lines 101-104 deleted"; \
      } >> /builder-apt-state.txt; \
    fi
