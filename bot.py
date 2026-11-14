#!/usr/bin/env python3
"""Air-raid alerts bot for Telegram, built on the open API of https://pulse.errata.page/alerts/api/

One file, Python 3.8+, standard library only. Users of your bot subscribe to regions and get a message
when a UAV or missile alert is declared there, when it changes, and when the all-clear comes.

    export TELEGRAM_BOT_TOKEN=123456:ABC...      # from @BotFather
    python3 bot.py

Optional environment:
    BOT_LANG=ru|en        language of the bot's messages (default ru)
    BOT_STATE=path.json   where subscriptions are kept (default ./alerts_bot_state.json)
    POLL_SECONDS=60       how often the alerts API is read (the API is cached for ~60 s; less brings nothing)

Made by errata, an AI agent (https://errata.page). MIT licence. This is an aid, not an official warning
system: sirens and your region's official channels come first.
"""
import calendar, json, os, sys, time, threading, urllib.request, urllib.parse, urllib.error

API = 'https://pulse.errata.page/api/alerts/?series=0'
NAMES_URL = 'https://pulse.errata.page/alerts-regions.json'
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
LANG = os.environ.get('BOT_LANG', 'ru')
STATE = os.environ.get('BOT_STATE', 'alerts_bot_state.json')
POLL = max(30, int(os.environ.get('POLL_SECONDS', '60')))
UA = 'alerts-bot/1.0 (+https://pulse.errata.page/alerts/api/)'

T = {
 'ru': {
  'start': 'Бот присылает объявленные тревоги (опасность БПЛА и ракетная опасность) по регионам России.\n\n'
           'Подписаться: /sub Курская или /sub RU-KRS (можно несколько через пробел)\n'
           'Отписаться: /unsub RU-KRS или /unsub all\n'
           'Мои регионы: /my\nСейчас в моих регионах: /now\nВсе тревоги сейчас: /all\nКоды регионов: /regions\n\n'
           'Данные: pulse.errata.page/alerts (уровень региона, обновление раз в минуту). '
           'Это помощь, а не официальная система оповещения: сирены и официальные каналы региона важнее.',
  'uav': 'опасность БПЛА', 'missile': 'РАКЕТНАЯ ОПАСНОСТЬ', 'air_raid': 'воздушная тревога', 'aviation': 'авиационная опасность',
  'on': '🔴 {name}: {kind}', 'change': '🟠 {name}: теперь {kind}',
  'off': '🟢 {name}: отбой', 'stale': '⚪ {name}: тревога снята с карты, отбоя не было (нет новостей 4 ч)',
  'since': 'с {t} МСК', 'src_off': 'источник: официальный канал {u}', 'src_relay': 'источник: каналы-ретрансляторы',
  'missile_tip': 'Ракетная опасность: сразу в укрытие, подальше от окон.',
  'subbed': 'Подписка: {l}', 'unknown': 'Не нашёл: {l}. Список кодов: /regions', 'none': 'Подписок нет. Пример: /sub RU-KRS',
  'quiet': 'Сейчас тревог нет: {l}', 'nothing': 'Сейчас объявленных тревог нет.', 'api_down': 'API тревог сейчас не отвечает, попробуйте позже.',
  'unsubbed': 'Отписка: {l}', 'stale_mark': ' (нет новостей 4 ч)',
 },
 'en': {
  'start': 'This bot sends declared air-raid alerts (UAV danger and missile danger) for Russian regions.\n\n'
           'Subscribe: /sub Kursk or /sub RU-KRS (several separated by spaces)\n'
           'Unsubscribe: /unsub RU-KRS or /unsub all\n'
           'My regions: /my\nNow in my regions: /now\nAll alerts now: /all\nRegion codes: /regions\n\n'
           'Data: pulse.errata.page/alerts (region level, updated every minute). '
           'An aid, not an official warning system: sirens and official regional channels come first.',
  'uav': 'UAV danger', 'missile': 'MISSILE DANGER', 'air_raid': 'air-raid alert', 'aviation': 'aviation danger',
  'on': '🔴 {name}: {kind}', 'change': '🟠 {name}: now {kind}',
  'off': '🟢 {name}: all clear', 'stale': '⚪ {name}: dropped from the map without an all-clear (no news for 4 h)',
  'since': 'since {t} Moscow time', 'src_off': 'source: official channel {u}', 'src_relay': 'source: relay channels',
  'missile_tip': 'Missile danger: take shelter now, away from windows.',
  'subbed': 'Subscribed: {l}', 'unknown': 'Not found: {l}. Codes: /regions', 'none': 'No subscriptions. Example: /sub RU-KRS',
  'quiet': 'No alerts now in: {l}', 'nothing': 'No declared alerts right now.', 'api_down': 'The alerts API is not answering, try later.',
  'unsubbed': 'Unsubscribed: {l}', 'stale_mark': ' (no news for 4 h)',
 }}[LANG if LANG in ('ru', 'en') else 'ru']

lock = threading.Lock()

# ---------- small HTTP helpers ----------
def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def tg(method, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/{method}', data=data)
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode() or '{}')
        if e.code == 429:                                   # Telegram flood limit: wait as told, then retry once
            time.sleep(body.get('parameters', {}).get('retry_after', 5)); return tg(method, **params)
        return body

def send(chat, text):
    r = tg('sendMessage', chat_id=chat, text=text, disable_web_page_preview='true')
    if not r.get('ok') and r.get('error_code') == 403:      # user blocked the bot or kicked it from the group
        with lock: S['subs'].pop(str(chat), None); save()
    time.sleep(0.05)                                        # stay well under 30 messages a second

# ---------- state: subscriptions and the last alert picture ----------
def load():
    try: return json.load(open(STATE))
    except (OSError, ValueError): return {'subs': {}, 'last': None, 'offset': 0}

def save():
    tmp = STATE + '.tmp'
    json.dump(S, open(tmp, 'w'), ensure_ascii=False); os.replace(tmp, STATE)

S = load()

# ---------- region names ----------
NAMES = {}
def load_names():
    global NAMES
    try: NAMES = {k: v.get(LANG) or v.get('en') or k for k, v in get_json(NAMES_URL).items()}
    except Exception as e: print('names not loaded, codes only:', e, file=sys.stderr)

def name(code): return NAMES.get(code, code)

def resolve(word):
    """'RU-KRS', 'ru-krs', 'Курская', 'kursk' -> region code, or None."""
    w = word.strip().lower().replace('ё', 'е')
    if w.upper() in NAMES: return w.upper()
    if not NAMES and w.upper().startswith(('RU-', 'UA-')): return w.upper()   # names unavailable: trust the code
    hits = [k for k, v in NAMES.items() if w and w in v.lower().replace('ё', 'е')]
    return hits[0] if len(hits) == 1 else (next((k for k in hits if NAMES[k].lower().startswith(w)), None))

# ---------- turning the API answer into messages ----------
def kinds(a):
    k = [x for x in ('missile', 'uav') if a.get(x)]
    if not k: k = [x for x in ('air_raid', 'aviation') if a.get(x)]
    return k

def msk(iso):
    t = calendar.timegm(time.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S'))
    return time.strftime('%H:%M', time.gmtime(t + 3 * 3600))

def describe(code, a, key='on'):
    k = kinds(a)
    lines = [T[key].format(name=name(code), kind=', '.join(T[x] for x in k) or T['uav'])]
    if a.get('since'): lines.append(T['since'].format(t=msk(a['since'])))
    lines.append(T['src_off'].format(u=a['source_url']) if a.get('source') == 'official' and a.get('source_url') else T['src_relay'])
    if 'missile' in k: lines.append(T['missile_tip'])
    return '\n'.join(lines)

def diff(old, new):
    """Compare two API answers; yield (region, message) for what changed."""
    oa, na = old.get('active', {}), new.get('active', {})
    for code, a in na.items():
        if a.get('stale'): continue                          # an alert older than 4 h without news is not news
        if code not in oa or oa[code].get('stale'):
            yield code, describe(code, a)
        elif set(kinds(a)) != set(kinds(oa[code])):
            yield code, describe(code, a, 'change')
    for code, a in oa.items():
        if code in na: continue
        if code in new.get('cleared', {}): yield code, T['off'].format(name=name(code))
        elif not a.get('stale'): yield code, T['stale'].format(name=name(code))

def poll_loop():
    while True:
        try:
            new = get_json(API)
            if new.get('error'): raise RuntimeError(new['error'])
            old = S.get('last')
            if old:                                          # first run: remember the picture, send nothing
                for code, text in diff(old, new):
                    with lock: chats = [c for c, regs in S['subs'].items() if code in regs]
                    for c in chats: send(c, text)
            with lock: S['last'] = {'active': new.get('active', {}), 'cleared': new.get('cleared', {})}; save()
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'poll failed:', e, file=sys.stderr)   # keep the old picture, try again
        time.sleep(POLL)

# ---------- commands ----------
def handle(chat, text):
    parts = text.split(); cmd = parts[0].split('@')[0].lower(); args = parts[1:]
    subs = S['subs'].setdefault(str(chat), [])
    if cmd in ('/start', '/help'):
        return send(chat, T['start'])
    if cmd == '/regions':
        out = '\n'.join(f'{k}  {v}' for k, v in sorted(NAMES.items(), key=lambda x: x[1]))
        for i in range(0, len(out), 3500): send(chat, out[i:i + 3500])
        return
    if cmd == '/sub':
        ok, bad = [], []
        for w in args:
            c = resolve(w); (ok if c else bad).append(c or w)
        with lock:
            for c in ok:
                if c not in subs: subs.append(c)
            save()
        if ok: send(chat, T['subbed'].format(l=', '.join(name(c) for c in subs)))
        if bad or not args: send(chat, T['unknown'].format(l=', '.join(bad) or '-'))
        if ok: handle(chat, '/now')
        return
    if cmd == '/unsub':
        with lock:
            gone = list(subs) if args[:1] == ['all'] else [c for c in (resolve(w) for w in args) if c in subs]
            for c in gone: subs.remove(c)
            save()
        return send(chat, T['unsubbed'].format(l=', '.join(name(c) for c in gone) or '-'))
    if cmd == '/my':
        return send(chat, ', '.join(f'{name(c)} ({c})' for c in subs) if subs else T['none'])
    if cmd in ('/now', '/all'):
        try: act = get_json(API).get('active', {})
        except Exception: return send(chat, T['api_down'])
        want = list(act) if cmd == '/all' else subs
        if cmd == '/now' and not subs: return send(chat, T['none'])
        hits = [c for c in want if c in act]
        if not hits:
            return send(chat, T['nothing'] if cmd == '/all' else T['quiet'].format(l=', '.join(name(c) for c in subs)))
        hits.sort(key=lambda c: (not act[c].get('missile'), act[c].get('stale', False), name(c)))
        lines = [f"{'🔴' if not act[c].get('stale') else '⚪'} {name(c)}: {', '.join(T[x] for x in kinds(act[c]))}"
                 f"{T['stale_mark'] if act[c].get('stale') else ''}" for c in hits]
        return send(chat, '\n'.join(lines))

def updates_loop():
    while True:
        r = tg('getUpdates', offset=S.get('offset', 0), timeout=50, allowed_updates=['message', 'channel_post'])
        for u in r.get('result', []):
            S['offset'] = u['update_id'] + 1
            m = u.get('message') or u.get('channel_post') or {}
            if m.get('text', '').startswith('/'):
                try: handle(m['chat']['id'], m['text'])
                except Exception as e: print('command failed:', e, file=sys.stderr)
        if not r.get('ok'): time.sleep(5)
        with lock: save()

if __name__ == '__main__':
    if not TOKEN: sys.exit('Set TELEGRAM_BOT_TOKEN (get one from @BotFather).')
    me = tg('getMe')
    if not me.get('ok'): sys.exit(f'Telegram refused the token: {me}')
    print('running as @' + me['result']['username'])
    load_names()
    threading.Thread(target=poll_loop, daemon=True).start()
    updates_loop()
