"""config/settings.yaml を読む。依存を増やさないため、使っている範囲の YAML だけを解釈する。"""


def load_settings(path: str) -> dict:
    settings: dict = {}
    section = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, _, value = line.strip().partition(":")
            if not line.startswith(" "):
                section = settings.setdefault(key, {})
            else:
                value = value.strip()
                section[key] = int(value) if value.isdigit() else value
    return settings
