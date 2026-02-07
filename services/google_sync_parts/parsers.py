import re


def parse_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def parse_motohours_to_hours(val):
    """Парсить мотогодини з Sheet у float годин. Підтримує 'HH:MM(:SS)' та числа."""
    if val is None:
        return None

    s = str(val).strip()
    if not s:
        return None

    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                hh = int(parts[0])
                mm = int(parts[1])
                return float(hh) + (float(mm) / 60.0)
            if len(parts) == 3:
                hh = int(parts[0])
                mm = int(parts[1])
                ss = int(parts[2])
                return float(hh) + (float(mm) / 60.0) + (float(ss) / 3600.0)
        except Exception:
            return None

    f = parse_float(s)
    if f is None:
        return None

    # some sheets may store days (e.g., 5.2 means 5 days and 4.8 hours)
    if 1.0 < f < 31.0 and (f * 24.0) > 100.0:
        return f * 24.0

    return f
