"""
Utilitários de agendamento — calculate_next_run mantido aqui por simplicidade.
O parser de tasks.md foi removido: tasks vivem agora no SQLite (scheduled_tasks).
"""

import re
from datetime import datetime, timedelta
from typing import Optional


def calculate_next_run(
    frequency: str,
    time_str: str,
    weekday: Optional[str] = None,
    day: Optional[str] = None,
) -> Optional[str]:
    if frequency == 'on_demand':
        return None

    now = datetime.now()
    try:
        h, m = map(int, time_str.split(':'))
    except (ValueError, AttributeError):
        h, m = now.hour, now.minute

    if frequency in ('once', 'daily'):
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.strftime('%Y-%m-%d %H:%M:%S')

    if frequency == 'weekly':
        days_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6,
        }
        target_wd = days_map.get((weekday or 'monday').lower(), 0)
        days_ahead = target_wd - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and (now.hour > h or (now.hour == h and now.minute >= m))):
            days_ahead += 7
        candidate = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
        return candidate.strftime('%Y-%m-%d %H:%M:%S')

    if frequency == 'monthly':
        target_day = int(day or '1')
        try:
            candidate = now.replace(day=target_day, hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            candidate = now.replace(day=1, hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate.replace(
                year=now.year + 1 if now.month == 12 else now.year,
                month=1 if now.month == 12 else now.month + 1,
            )
        return candidate.strftime('%Y-%m-%d %H:%M:%S')

    m_min = re.match(r'every_(\d+)m', frequency)
    if m_min:
        return (now + timedelta(minutes=int(m_min.group(1)))).strftime('%Y-%m-%d %H:%M:%S')

    m_hr = re.match(r'every_(\d+)h', frequency)
    if m_hr:
        return (now + timedelta(hours=int(m_hr.group(1)))).strftime('%Y-%m-%d %H:%M:%S')

    m_day = re.match(r'every_(\d+)d', frequency)
    if m_day:
        base = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return (base + timedelta(days=int(m_day.group(1)))).strftime('%Y-%m-%d %H:%M:%S')

    # fallback: daily
    candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.strftime('%Y-%m-%d %H:%M:%S')
