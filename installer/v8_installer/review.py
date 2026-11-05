"""The backend owns the human-readable summary, including destructive changes."""
from .plan import GIB, MIB
from .desktop import profile
from .i18n import current


def summary(plan):
    fr = current() == "fr"
    def label(a, b):
        return a if fr else b
    lines = [label("01  DISQUE ET PARTITIONS", "01  DISK AND PARTITIONS"),
             f"{plan.disk.path}  ·  {plan.disk.model}  ·  {plan.disk.size / GIB:.1f} GiB",
             label("Identité : ", "Identity: ") + plan.disk.identity,
             f"Mode: {plan.mode}"]
    if plan.mode == "wipe":
        lines.append(label("TOUT LE DISQUE SERA EFFACÉ", "THE ENTIRE DISK WILL BE ERASED"))
        for p in plan.disk.partitions:
            lines.append(f"  DELETE {p.path} {p.fs} {p.size / GIB:.2f} GiB")
    actions = {"keep": label("CONSERVER", "KEEP"), "create": label("CRÉER", "CREATE"),
               "format": label("FORMATER", "FORMAT"), "delete": label("SUPPRIMER", "DELETE")}
    for p in plan.partitions:
        lines.append(f"  {actions[p.action]}  {p.path or label('(nouvelle)', '(new)')}  ·  {p.size / GIB:.2f} GiB")
        lines.append(f"    {p.fs or '-'}  →  {p.mount or '-'}  ·  {p.start / MIB:g} MiB")
    esp = next(p for p in plan.partitions if p.mount == "/efi")
    lines += ["", label("ESP : ", "ESP: ") + (label("conservée sans formatage", "preserved without formatting") if esp.action == "keep" else label("nouvelle ou formatée", "new or formatted")),
              "EFI/systemd, EFI/BOOT, EFI/v8, loader/entries/v8.conf",
              "", label("02  SYSTÈME", "02  SYSTEM"),
              f"{plan.kernel}  ·  Btrfs  ·  systemd-boot",
              f"UKI={plan.uki}  ·  LUKS2={plan.luks}  ·  Plymouth={plan.plymouth}",
              f"{plan.username}@{plan.hostname}  ·  {plan.locale}",
              f"Console: {plan.keyboard}  ·  XKB: {plan.xkb}  ·  {plan.timezone}",
              label("Compte root : ", "Root account: ") + (label("actif", "enabled") if plan.root_enabled else label("verrouillé", "locked")),
              profile(plan.desktop)["name"] + " | " + (profile(plan.desktop)["display_manager"] or "TTY"),
              f"GPU: {plan.graphics} | CPU: {plan.hardware.get('cpu', 'unknown')}",
              "", label("03  SERVICES ET LOGICIELS", "03  SERVICES AND SOFTWARE"),
              label("Réseau : ", "Network: ") + plan.network + "  ·  " + label("Instantanés : ", "Snapshots: ") + plan.snapshots,
              *([label("Timeshift : instantané quotidien, 5 conservés (racine Btrfs).", "Timeshift: daily snapshots, retain 5 (Btrfs root).")]
                if plan.snapshots == 'timeshift' else []),
              f"Bluetooth: {plan.bluetooth}  ·  ZRAM: {plan.zram}",
              label("Les services non choisis seront désactivés, même si le bureau nécessite leurs paquets.", "Unselected services stay disabled even if the desktop requires their packages."),
              (f"Swap: {'/home/.archhelper-swap/swapfile' if plan.swap_location == 'home' else '/swap/swapfile'} ({plan.swap_gib} GiB)" +
               (label(' — partition /home séparée non chiffrée', ' — separate /home partition is not encrypted') if plan.swap_location == 'home' and any(p.mount == '/home' for p in plan.partitions) else '')) if plan.swap_gib else "Swap: off",
              label("Dépôt CachyOS : ", "CachyOS repository: ") + (label("activé", "enabled") if plan.cachyos else label("désactivé", "disabled")),
              label("Paquets supplémentaires : ", "Additional packages: ") + (', '.join(plan.extra_packages) if plan.extra_packages else '-'),
              "", label("Pas de redimensionnement automatique. Pas de reprise après formatage interrompu.", "No automatic shrinking. No resume after interrupted formatting."),
              f"Plan: {plan.fingerprint}"]
    return "\n".join(lines)
