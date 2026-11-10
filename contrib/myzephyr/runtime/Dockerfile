# Debian 11 arm64 runtime userland for the strict offline start of the Linux AArch64
# zephyrd (native-runtime job on ubuntu-24.04-arm), below the runner's glibc 2.39.
#
# Runtime only: the base image plus python3 for zephyrd-check.py; no compiler and no
# build packages. zephyrd itself needs only glibc (NEEDED: libm.so.6, libpthread.so.0,
# libc.so.6, ld-linux-aarch64.so.1), which the base image has.
#
# Base: docker.io/library/debian:11 (bullseye), the linux/arm64/v8 manifest of the same
# index whose linux/amd64 manifest is the Linux builder's base (contrib/myzephyr/linux):
#   index sha256:6f519a81440354a85eb592c5f32109ab80605f6b892455983a6f618bf87fabe9
#   (resolved 2026-11-08; its arm64 entry read 2026-11-10)
# Like the amd64 image, it names the snapshot 20260824T000000Z in /etc/apt/sources.list
# and carries Debian 11.11 with libc6 2.31-13+deb11u14 (glibc 2.31); 96 packages.
# python3 comes from that one signed snapshot.debian.org timestamp, never from the live
# mirrors; apt verifies every InRelease against the Debian archive keyring in the base
# image. The bullseye-security InRelease at this timestamp has a Valid-Until in the
# past, so check-valid-until=no is set on that one source line only (as in the builder).
# The build fails unless the result is arm64 with exactly that libc6.
FROM docker.io/library/debian@sha256:32fc609441a9c8417b2bb5faa62a60afd6af19013e8e82fdeed5d08dc7ac1ad9

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
    apt-get install -y --no-install-recommends python3; \
    test "$(dpkg --print-architecture)" = arm64; \
    test "$(dpkg-query -W -f '${Version}' libc6)" = 2.31-13+deb11u14; \
    { echo "snapshot ${SNAPSHOT}"; cat /etc/apt/sources.list; \
      for f in /var/lib/apt/lists/*_InRelease; do \
        echo "== ${f##*/} $(sha256sum "$f" | cut -d' ' -f1)"; \
        grep -E '^(Origin|Suite|Codename|Version|Date|Valid-Until):' "$f"; \
      done; } > /runtime-apt-state.txt; \
    dpkg-query -W -f '${Package}\t${Version}\t${Architecture}\n' | sort > /runtime-packages.tsv; \
    rm -rf /var/lib/apt/lists/*
