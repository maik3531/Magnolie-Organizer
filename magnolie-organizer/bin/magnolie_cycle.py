"""Explicit bleeding-marker statistics; no medical inference or persistent events."""
from datetime import date, timedelta
from statistics import median
import math

BLEEDING_TYPES = {'bleeding-light', 'bleeding-medium', 'bleeding-heavy'}


def estimate_cycle(data):
    data = data if isinstance(data, dict) else {}
    markers = data.get('zyklusmarker') if isinstance(data.get('zyklusmarker'), list) else []
    ids = {entry.get('id') for entry in markers
           if isinstance(entry, dict) and isinstance(entry.get('id'), str) and entry.get('art') in BLEEDING_TYPES}
    dates = set()
    marks = data.get('tagmarken') if isinstance(data.get('tagmarken'), list) else []
    for mark in marks:
        if not isinstance(mark, dict) or not isinstance(mark.get('zyklusIds'), list) or not any(isinstance(value, str) and value in ids for value in mark['zyklusIds']): continue
        try:
            day = date.fromisoformat(mark.get('datum', ''))
            if day.isoformat() == mark['datum']: dates.add(day)
        except (ValueError, TypeError): pass
    starts = []; previous = None
    for day in sorted(dates):
        if previous is None or (day - previous).days > 3: starts.append(day)
        previous = day
    intervals = [(b - a).days for a, b in zip(starts, starts[1:])]
    valid = [value for value in intervals if 14 <= value <= 60][-12:]
    length = math.floor(median(valid) + .5) if len(valid) >= 2 else None
    predicted = None
    if length is not None:
        try: predicted = (starts[-1] + timedelta(days=length)).isoformat()
        except OverflowError: pass
    earlier = [value for value in intervals[:-1] if 14 <= value <= 60][-12:]
    baseline = math.floor(median(earlier) + .5) if len(earlier) >= 2 else None
    return {'starts': [day.isoformat() for day in starts], 'intervals': intervals,
            'length': length, 'predicted': predicted, 'baseline': baseline,
            'latest': intervals[-1] if intervals else None}


def cycle_reminders(data, translate=lambda text: text):
    _ = translate
    settings = data.get('einstellungen') if isinstance(data, dict) else None
    settings = settings.get('kalender') if isinstance(settings, dict) else None
    settings = settings if isinstance(settings, dict) else {}
    options = settings.get('zyklusErinnerungen') if isinstance(settings.get('zyklusErinnerungen'), dict) else {}
    if settings.get('zykluskalenderAn') is not True or not (options.get('prognose') is True or options.get('abweichung') is True): return []
    stats = estimate_cycle(data)
    result = []
    if options.get('prognose') is True and stats['predicted']:
        lead = options.get('vorlauf', 1)
        lead = lead if type(lead) is int and 0 <= lead <= 30 else 1
        result.append({'id': 'cycle-estimate:' + stats['starts'][-1] + ':' + stats['predicted'],
            'datum': stats['predicted'], 'zeit': '08:00',
            'titel': _('Estimated next period'), 'standardErinnerung': False,
            'individuelleErinnerungTage': lead})
    threshold = options.get('abweichungTage', 7)
    threshold = threshold if type(threshold) is int and 1 <= threshold <= 30 else 7
    if options.get('abweichung') is True and stats['baseline'] is not None and abs(stats['latest'] - stats['baseline']) >= threshold:
        result.append({'id': 'cycle-deviation:' + stats['starts'][-1] + ':' + str(stats['latest']),
            'datum': stats['starts'][-1], 'zeit': '08:00',
            'titel': _('Cycle interval changed'), 'standardErinnerung': False,
            'individuelleErinnerungTage': 0})
    return result
