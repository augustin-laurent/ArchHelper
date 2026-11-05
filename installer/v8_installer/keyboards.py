"""Keyboard names accepted by the live system and by the target's XKB stack."""
from pathlib import Path
import xml.etree.ElementTree as ET

from .plan import PlanError

KEYMAPS = Path('/usr/share/kbd/keymaps')
XKB_PATHS = (Path(__file__).with_name('xkb-evdev.xml'),
             Path('/usr/share/xkeyboard-config-2/rules/evdev.xml'),
             Path('/usr/share/X11/xkb/rules/evdev.xml'))


def console_names():
    names = set()
    for path in KEYMAPS.rglob('*.map*'):
        name = path.name.split('.map', 1)[0]
        if name and 'include' not in path.relative_to(KEYMAPS).parts and path.is_file():
            names.add(name)
    return names


def xkb_names():
    try:
        path = next(path for path in XKB_PATHS if path.is_file())
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError, StopIteration) as exc:
        raise PlanError('XKB keyboard catalog unavailable') from exc
    choices = set()
    for layout in root.findall('./layoutList/layout'):
        name = layout.findtext('./configItem/name')
        if not name:
            continue
        choices.add(name)
        for variant in layout.findall('./variantList/variant/configItem/name'):
            if variant.text:
                choices.add(name + ':' + variant.text)
    return choices


def validate(console, graphical):
    if console not in console_names() or graphical not in xkb_names():
        raise PlanError('Unsupported console or graphical keyboard layout')


def split(graphical):
    layout, _, variant = graphical.partition(':')
    return layout, variant
