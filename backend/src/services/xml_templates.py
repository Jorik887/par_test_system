from pathlib import Path
import re
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent
XML_TEMPLATES_DIR = BASE_DIR / "paragraph" / "xml_templates"
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class XmlTemplateInfo:
    """
    РџСЂРѕСЃС‚РµР№С€РµРµ РѕРїРёСЃР°РЅРёРµ XML-С€Р°Р±Р»РѕРЅР°.
    РџРѕРєР° Р±РµР· Р‘Р”, РїСЂРѕСЃС‚Рѕ СЂР°Р±РѕС‚Р°РµРј СЃ С„Р°Р№Р»Р°РјРё.
    """
    def __init__(self, filename: str, alias: str, description: str | None = None):
        # Dlya sebya: servisnyy helper (init).
        self.filename = filename
        self.alias = alias
        self.description = description

    def dict(self):
        # Dlya sebya: servisnaya operaciya "dict".
        return {
            "filename": self.filename,
            "alias": self.alias,
            "description": self.description,
        }


def list_xml_templates() -> List[XmlTemplateInfo]:
    # Dlya sebya: servisnaya operaciya "list xml templates".
    templates: List[XmlTemplateInfo] = []

    if not XML_TEMPLATES_DIR.exists():
        return templates

    for path in XML_TEMPLATES_DIR.glob("*.xml"):
        alias = path.stem
        templates.append(XmlTemplateInfo(filename=path.name, alias=alias))

    return templates


def load_xml_template(alias: str) -> str:
    # Dlya sebya: servisnaya operaciya "load xml template".
    safe_alias = str(alias or "").strip()
    if not safe_alias or not _ALIAS_RE.fullmatch(safe_alias):
        raise ValueError(f"Invalid XML template alias: {alias!r}")

    root_dir = XML_TEMPLATES_DIR.resolve()
    path = (XML_TEMPLATES_DIR / f"{safe_alias}.xml").resolve()
    if root_dir not in path.parents:
        raise ValueError(f"Template path is outside xml_templates dir: {path}")
    if not path.exists():
        raise FileNotFoundError(f"XML template not found: {path}")

    return path.read_text(encoding="utf-8")
