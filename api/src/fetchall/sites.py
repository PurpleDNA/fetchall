from functools import cache

from yt_dlp.extractor import gen_extractor_classes


@cache
def supported_sites() -> list[str]:
    names: dict[str, str] = {}
    for ie in gen_extractor_classes():
        if not ie.working() or ie.IE_DESC is False or ie.IE_NAME == "generic":
            continue
        base = ie.IE_NAME.split(":")[0]
        display = ie.IE_DESC if ":" not in ie.IE_NAME and isinstance(ie.IE_DESC, str) else base
        if display.islower():
            display = display[0].upper() + display[1:]
        if base.lower() not in names or ":" not in ie.IE_NAME:
            names[base.lower()] = display
    unique = {name.casefold(): name for name in names.values()}
    return sorted(unique.values(), key=str.casefold)
