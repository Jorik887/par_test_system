from pathlib import Path
import re

XML_TEMPLATES_DIR = Path(__file__).resolve().parent / "xml_templates"
_MOJIBAKE_MARK_RE = re.compile(r"[РѓС“Р‰РЉР‹РЊРЋРЏС’С“С™СљС›СњСћСџ]|(?:Р .|РЎ.)")
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _decode_xml_bytes(data: bytes) -> str:
    # Dlya sebya: shag Paragraph-sloya (decode xml bytes).
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251")

    if _MOJIBAKE_MARK_RE.search(text):
        try:
            return data.decode("cp1251")
        except UnicodeDecodeError:
            return text
    return text


def load_xml_template(alias: str) -> str:
    # Dlya sebya: shag Paragraph-sloya (load xml template).
    safe_alias = str(alias or "").strip()
    if not safe_alias or not _ALIAS_RE.fullmatch(safe_alias):
        raise ValueError(f"Invalid XML template alias: {alias!r}")

    template_path = (XML_TEMPLATES_DIR / f"{safe_alias}.xml").resolve()
    root_dir = XML_TEMPLATES_DIR.resolve()
    if root_dir not in template_path.parents:
        raise ValueError(f"Template path is outside xml_templates dir: {template_path}")

    if template_path.exists():
        data = template_path.read_bytes()
        return _decode_xml_bytes(data)
    raise FileNotFoundError(f"РЁР°Р±Р»РѕРЅ {safe_alias}.xml РЅРµ РЅР°Р№РґРµРЅ!")


def generate_create_user_dict_v1() -> str:
    # Dlya sebya: shag Paragraph-sloya (generate create user dict v1).
    return load_xml_template("create_user_dict_v1")


def generate_remove_user_dict() -> str:
    # Dlya sebya: shag Paragraph-sloya (generate remove user dict).
    try:
        return load_xml_template("remove_user_dict")
    except FileNotFoundError:
        return load_xml_template("remove_from_user_dict")


def generate_query_user_dict() -> str:
    # Dlya sebya: shag Paragraph-sloya (generate query user dict).
    return load_xml_template("query_user_dict")
