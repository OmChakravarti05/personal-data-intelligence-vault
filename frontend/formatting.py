from datetime import datetime


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def local_time(iso: str | None) -> str:
    """Convert an API timestamp to this computer's local time."""
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")