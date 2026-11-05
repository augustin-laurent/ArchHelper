#!/bin/bash
# Guest only. Never run on an installed host.
set -euo pipefail
[[ $(id -u) == 0 && $(uname -m) == x86_64 ]]
[[ $(cat /etc/v8-build-vm) == v8-isolated-builder-v1 && -f /input/sources.lock.json && -d /output ]]
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends libarchive-tools gnupg ca-certificates
archive=/input/work/builder/archlinux-bootstrap-2026.10.01-x86_64.tar.zst
[[ $(sha256sum "$archive" | cut -d' ' -f1) == 0c9c97b7a58a8a023c9e07f84cb307a9e8006e65d8fc4c17b83ddc8010b45c10 ]]
export GNUPGHOME=/srv/v8-verify-x86
install -d -m700 "$GNUPGHOME"
gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys 3E80CA1A8B89F69CBA57D98A76A5EF9054449A5C
gpg --batch --status-fd=1 --verify "$archive.sig" "$archive" | tee /output/bootstrap-signature.txt
grep -q 'VALIDSIG 3E80CA1A8B89F69CBA57D98A76A5EF9054449A5C' /output/bootstrap-signature.txt
root=/srv/v8-arch-x86
if [[ ! -f $root/.v8-extracted ]]; then
  mkdir -p "$root"
  bsdtar -xpf "$archive" --strip-components=1 -C "$root"
  touch "$root/.v8-extracted"
fi
mkdir -p "$root/input" "$root/output" "$root/proc" "$root/sys" "$root/dev" "$root/run"
mountpoint -q "$root/input" || mount --bind /input "$root/input"
mountpoint -q "$root/output" || mount --bind /output "$root/output"
mountpoint -q "$root/proc" || mount -t proc proc "$root/proc"
for fs in sys dev run; do
  mountpoint -q "$root/$fs" || mount --rbind "/$fs" "$root/$fs"
  mount --make-rslave "$root/$fs"
done
rm -f "$root/etc/resolv.conf"
cp -L /etc/resolv.conf "$root/etc/resolv.conf"
printf 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n' >"$root/etc/pacman.d/mirrorlist"
if [[ ! -f $root/.v8-keyring ]]; then
  chroot "$root" pacman-key --init
  chroot "$root" pacman-key --populate archlinux
  touch "$root/.v8-keyring"
fi
cp /etc/v8-build-vm "$root/etc/v8-build-vm"
exec chroot "$root" /bin/bash /input/scripts/build-release-inside-arch.sh
