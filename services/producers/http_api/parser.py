import hashlib
import json


def resolve_path(obj, path: str):
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def get_items(data, data_path: str | None) -> list:
    root = resolve_path(data, data_path) if data_path else data
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        return [root]
    if isinstance(root, str):
        return [{"_text": root}]
    return []


def build_text(item: dict, source: dict) -> str:
    if "eval" in source:
        fn = eval(source["eval"])
        return str(fn(item))
    if "text_field" in source:
        val = resolve_path(item, source["text_field"])
        return str(val) if val is not None else ""
    return json.dumps(item, ensure_ascii=False)


def get_item_id(item: dict, id_field: str | None) -> str:
    if id_field:
        val = resolve_path(item, id_field)
        if val is not None:
            return str(val)
    return hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
