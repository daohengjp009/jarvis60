"""Tool: seconds_to_hms
Task: Write a function seconds_to_hms(n) that converts seconds to a string 'H:MM:SS', e.g. 3661 -> '1:01:01'.
Born after 1 attempt(s)."""

def seconds_to_hms(n):
    h = n // 3600
    m = (n % 3600) // 60
    s = n % 60
    return f"{h}:{m:02d}:{s:02d}"
