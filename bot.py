import os
import sys
import json
import math
import lzma
import time
import base64
import signal
import asyncio
import hashlib
import aiohttp

from urllib.parse import parse_qs
from collections import deque

from utils.banner import show_banner

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"

MY_PROJECT = "Thunder Waves Miniapp"
BASE_URL = "https://api.thunderwaves.site/api"
REF_CODE = "EUW89NYN"

AD_NETWORK_NAMES = {
    "adsgram": "Adsgram",
    "monetag": "Monetag",
    "gigapub": "GigaPub",
    "adeixum": "Adeixum",
    "onclicka": "OnClicka",
}


def ad_network_label(network, fallback):
    key = " ".join(str(network or "").split()).lower()
    return AD_NETWORK_NAMES.get(key) or clean_text(network, fallback)


HEADERS_BASE = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://thunderwaves.site",
    "referer": "https://thunderwaves.site/",
    "user-agent": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
}

def clean_text(value, fallback):
    text = " ".join(str(value).split())
    return text if text else fallback


def log_green(msg):
    print(f"{GREEN}{BOLD}{msg}{RESET}", flush=True)


def log_yellow(msg):
    print(f"{YELLOW}{BOLD}{msg}{RESET}", flush=True)


def log_red(msg):
    print(f"{RED}{BOLD}{msg}{RESET}", flush=True)


def signal_handler(sig, frame):
    print()
    log_red("Script stopped by user")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def normalize_proxy(proxy_line):
    if not proxy_line:
        return None
    value = proxy_line.strip()
    if "://" in value:
        return value
    parts = value.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 3:
        host, port, user = parts
        return f"http://{user}@{host}:{port}"
    return f"http://{value}"


def mask_proxy(proxy_url):
    try:
        value = proxy_url.split("://")[-1]
        after_at = value.split("@")[-1]
        host_part = after_at.split(":")[0]
        port_part = after_at.split(":")[1] if ":" in after_at else ""
        octets = host_part.split(".")
        if len(octets) == 4:
            masked_host = f"{octets[0]}*****{octets[3]}"
        elif len(host_part) > 4:
            masked_host = f"{host_part[:2]}*****{host_part[-2:]}"
        else:
            masked_host = "***"
        suffix = f":{port_part}" if port_part else ""
        return f"http://user:pass@{masked_host}{suffix}"
    except Exception:
        return "http://user:pass@***:***"


def countdown(seconds, label):
    start = time.time()
    while True:
        remaining = seconds - (time.time() - start)
        if remaining <= 0:
            print(f"\r{' ' * 70}\r", end="", flush=True)
            break
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        rest = int(remaining % 60)
        print(f"\r{YELLOW}{BOLD}{label} {hours:02d}:{minutes:02d}:{rest:02d}{RESET}", end="", flush=True)
        time.sleep(1)


def load_config():
    defaults = {"settings": {"sleep_seconds": 3600}}
    if not os.path.exists("config.json"):
        return defaults
    try:
        with open("config.json") as handle:
            return json.load(handle)
    except Exception:
        return defaults


def load_data():
    if not os.path.exists("data.txt"):
        log_red("File data.txt was not found.")
        sys.exit(1)
    lines = [line.strip() for line in open("data.txt").readlines() if line.strip()]
    if not lines:
        log_red("File data.txt is empty.")
        sys.exit(1)
    return lines


def load_proxies():
    if not os.path.exists("proxy.txt"):
        return []
    try:
        return [line.strip() for line in open("proxy.txt").readlines() if line.strip()]
    except Exception:
        return []


def get_proxy(proxies, index):
    if not proxies:
        return None
    return proxies[index % len(proxies)]


def parse_account(line):
    value = line.strip()
    if "tgWebAppData=" in value:
        value = value.split("tgWebAppData=", 1)[1]
        value = value.split("&tgWebAppVersion")[0].split("&tgWebAppPlatform")[0]
        from urllib.parse import unquote
        value = unquote(value)
    user_id = ""
    username = ""
    start_param = ""
    try:
        parsed = parse_qs(value)
        raw = (parsed.get("user") or [""])[0]
        start_param = (parsed.get("start_param") or [""])[0]
        if raw:
            info = json.loads(raw)
            user_id = str(info.get("id") or "")
            username = info.get("username") or info.get("first_name") or ""
    except Exception:
        pass
    return value, user_id, username, start_param


def make_device():
    seed = hashlib.sha256(os.urandom(32)).hexdigest()
    device_id = base64.urlsafe_b64encode(bytes.fromhex(seed[:36])).decode().rstrip("=")
    fingerprint = hashlib.sha256((seed + device_id).encode()).hexdigest()[:32]
    return {"id": device_id, "fingerprint": fingerprint, "platform": "android"}


class ApiError(Exception):
    def __init__(self, message, status=0, code="", details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


class ThunderWaves:
    def __init__(self, init_data, proxy=None):
        self.init_data = init_data
        self.proxy = proxy
        self.session = None
        self.app = {}
        self.user = {}
        self.ads_watched = 0
        self.ad_dwell = 11

    async def open(self):
        connector = aiohttp.TCPConnector(ssl=False)
        self.session = aiohttp.ClientSession(connector=connector)
        return self

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    def headers(self):
        return {**HEADERS_BASE, "authorization": f"tma {self.init_data}"}

    async def request(self, path, method="GET", body=None, timeout=30):
        try:
            async with self.session.request(
                method,
                BASE_URL + path,
                headers=self.headers(),
                json=body if body is not None else None,
                proxy=self.proxy,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                raw = await response.read()
                try:
                    data = json.loads(raw)
                except Exception:
                    data = None
                if response.status >= 400:
                    error = (data or {}).get("error") or {}
                    raise ApiError(
                        str(error.get("message") or f"Request failed with {response.status}"),
                        response.status,
                        str(error.get("code") or "REQUEST_FAILED"),
                        error.get("details") or {},
                    )
                return data if data is not None else {}
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(f"Request to the server failed with {type(exc).__name__}", 0, "NETWORK_ERROR")

    async def get(self, path, timeout=30):
        return await self.request(path, "GET", None, timeout)

    async def post(self, path, body=None, timeout=30):
        return await self.request(path, "POST", {} if body is None else body, timeout)

    async def login(self, start_param):
        data = await self.post("/auth", {"startParam": start_param, "device": make_device()})
        self.app = data.get("app") or {}
        self.user = data.get("user") or {}
        return data

    async def me(self):
        data = await self.get("/me")
        self.user = data.get("user") or self.user
        return self.user

    @property
    def networks(self):
        return self.app.get("adNetworks") or {}

    @property
    def min_watch(self):
        return int((self.app.get("ads") or {}).get("minWatchSeconds") or 10)

    async def watch_ad(self, placement, extra=None, label="Next ad in", name=None):
        payload = {"placement": placement}
        if extra:
            payload.update(extra)
        attempt = 0
        while True:
            try:
                started = await self.post("/ads/start", payload)
                break
            except ApiError as exc:
                if "Next ad in" in str(exc) and attempt < 3:
                    countdown(6, label)
                    attempt += 1
                    continue
                raise
        token = started.get("token")
        network = started.get("network") or ""
        source = ad_network_label(network, "the ad network")
        if name:
            source = ad_network_label(name, source)
        minimum = int(started.get("minWatchSeconds") or self.min_watch)
        mode = (self.networks.get(network) or {}).get("clickMode")
        clicks = 1 if mode in ("reward", "require") else 0
        dwell = max(minimum + 1, self.min_watch + 1, self.ad_dwell)
        for round_number in range(3):
            started_at = time.time()
            if not started.get("test"):
                countdown(dwell, label)
            shown = int((time.time() - started_at) * 1000)
            try:
                result = await self.post("/ads/complete", {"token": token, "shown": shown, "clicks": clicks})
            except ApiError as exc:
                required = int((exc.details or {}).get("seconds") or 0)
                if exc.code == "AD_TOO_SHORT" and required >= dwell and round_number < 2:
                    dwell = required + 1
                    self.ad_dwell = dwell
                    log_yellow("The rewarded ad was closed too early and will be watched again for longer")
                    continue
                raise
            reward = int(result.get("reward") or 0)
            self.ads_watched += 1
            log_green(f"Ad view {self.ads_watched} from {source} was watched and rewarded {reward} WAVES")
            return result

    async def claim_game_reward(self, session_id, label="Next ad in"):
        total = 0
        for _ in range(4):
            try:
                result = await self.watch_ad("game", {"sessionId": session_id}, label)
            except ApiError as exc:
                message = str(exc)
                if "Nothing to collect" in message or "CLAIM_DONE" in message:
                    break
                log_yellow(f"The game reward ad was refused with {clean_text(message, 'an unknown reason')}")
                break
            total += int(result.get("reward") or 0)
            claim = result.get("claim") or {}
            if claim.get("done"):
                break
        return total


WORDS_B64 = (
'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'
)


def load_words():
    global _WORDS_CACHE
    try:
        return _WORDS_CACHE
    except NameError:
        pass
    raw = lzma.decompress(base64.b64decode(WORDS_B64)).decode("utf8")
    _WORDS_CACHE = frozenset(word for word in raw.split("\n") if word)
    return _WORDS_CACHE


def words_by_length(size):
    return [word for word in load_words() if len(word) == size]


def words_five():
    global _FIVE_CACHE
    try:
        return _FIVE_CACHE
    except NameError:
        pass
    _FIVE_CACHE = frozenset(word for word in load_words() if len(word) == 5)
    return _FIVE_CACHE



M32 = 4294967295

def _imul(a: int, b: int) -> int:
    return a * b & M32

class Rng:
    __slots__ = ('_t',)

    def __init__(self, seed: int):
        self._t = seed & M32

    @property
    def state(self) -> int:
        return self._t

    @state.setter
    def state(self, v: int):
        self._t = v & M32

    def __call__(self) -> float:
        t = self._t + 1831565813 & M32
        self._t = t
        e = t
        e = _imul(e ^ e >> 15, e | 1)
        e = (e ^ e + _imul(e ^ e >> 7, e | 61) & M32) & M32
        return ((e ^ e >> 14) & M32) / 4294967296.0

def rng(seed: int) -> Rng:
    return Rng(seed)

def rand_int(r, n: int) -> int:
    return int(r() * n)

def smoothstep(x: float) -> float:
    return x * x * (3 - 2 * x)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

stack_CFG = {'easy': dict(speed0=0.55, accel=0.012, maxSpeed=1.3, perfect=0.05, grow=0.06, perFloor=12, perPerfect=6), 'normal': dict(speed0=0.75, accel=0.02, maxSpeed=1.85, perfect=0.035, grow=0.04, perFloor=18, perPerfect=8), 'hard': dict(speed0=1.0, accel=0.03, maxSpeed=2.45, perfect=0.025, grow=0.03, perFloor=26, perPerfect=10)}
stack_P = 1.15
stack_MIN_DELTA = 120

def stack_cfg(level):
    return stack_CFG.get(level) or stack_CFG['normal']

def stack_speed(idx, level):
    c = stack_cfg(level)
    return min(c['maxSpeed'], c['speed0'] + c['accel'] * idx)

def stack_pos(idx, delta, level):
    r = stack_speed(idx, level) * delta / 1000.0
    i = 4 * stack_P
    a = (r % i + i) % i
    o = -1.15 + a if a < 2.3 else 3 * stack_P - a
    return o if idx % 2 == 0 else -o

def stack_new_state():
    return {'floors': [{'center': 0.0, 'width': 1.0}], 'combo': 0, 'perfects': 0, 'over': False}

def stack_tap(state, delta, level):
    c = stack_cfg(level)
    last = state['floors'][-1]
    idx = len(state['floors'])
    o = stack_pos(idx, delta, level)
    d = o - last['center']
    if abs(d) <= c['perfect']:
        state['combo'] += 1
        state['perfects'] += 1
        w = min(1.0, last['width'] + c['grow']) if state['combo'] >= 3 else last['width']
        state['floors'].append({'center': last['center'], 'width': w})
        return {'placed': True, 'perfect': True}
    state['combo'] = 0
    lo = max(o - last['width'] / 2, last['center'] - last['width'] / 2)
    hi = min(o + last['width'] / 2, last['center'] + last['width'] / 2)
    u = hi - lo
    if u < 0.02:
        state['over'] = True
        return {'placed': False, 'perfect': False}
    state['floors'].append({'center': (lo + hi) / 2, 'width': u})
    return {'placed': True, 'perfect': False}

def stack_reward(level, floors, perfects):
    c = stack_cfg(level)
    return floors * c['perFloor'] + perfects * c['perPerfect']

def stack_build_taps(level, cap, max_taps=400):
    c = stack_cfg(level)
    st = stack_new_state()
    taps = []
    while len(taps) < max_taps:
        idx = len(st['floors'])
        target = st['floors'][-1]['center']
        found = None
        for k in range(120, 12000):
            if abs(stack_pos(idx, k, level) - target) <= c['perfect'] * 0.7:
                found = k
                break
        if found is None:
            break
        r = stack_tap(st, found, level)
        if not r['placed']:
            break
        taps.append(found)
        floors = len(st['floors']) - 1
        if stack_reward(level, floors, st['perfects']) >= cap:
            break
    return taps

def stack_play(level, taps):
    st = stack_new_state()
    for delta in taps:
        if delta < stack_MIN_DELTA:
            continue
        r = stack_tap(st, delta, level)
        if not r['placed']:
            break
    floors = len(st['floors']) - 1
    return (floors, st['perfects'], stack_reward(level, floors, st['perfects']))
snake_CFG = {'easy': dict(size=12, tick0=210, tickMin=135, accel=3, wrap=True, rocks=0, perFood=25, maxReward=600), 'normal': dict(size=14, tick0=165, tickMin=100, accel=3, wrap=False, rocks=0, perFood=40, maxReward=1200), 'hard': dict(size=16, tick0=135, tickMin=75, accel=3, wrap=False, rocks=7, perFood=55, maxReward=2000)}
snake_DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]

def snake_cfg(level):
    return snake_CFG.get(level) or snake_CFG['normal']

def snake_new_state(level, seed):
    c = snake_cfg(level)
    r = c['size'] // 2
    st = dict(level=level, size=c['size'], wrap=c['wrap'], rng=rng(seed), snake=[[r, r], [r - 1, r], [r - 2, r]], dir=1, rocks=[], food=None, foods=0, ticks=0, ms=0.0, dead=False)
    while len(st['rocks']) < c['rocks']:
        x = int(st['rng']() * c['size'])
        y = int(st['rng']() * c['size'])
        if abs(y - r) <= 1 or any((k[0] == x and k[1] == y for k in st['rocks'])):
            continue
        st['rocks'].append([x, y])
    snake__spawn_food(st)
    return st

def snake__spawn_food(st):
    used = set(((c[0], c[1]) for c in st['snake']))
    used |= set(((c[0], c[1]) for c in st['rocks']))
    free = [(x, y) for y in range(st['size']) for x in range(st['size']) if (x, y) not in used]
    if free:
        st['food'] = list(free[int(st['rng']() * len(free))])
    else:
        st['food'] = None

def snake_tick_ms(st):
    c = snake_cfg(st['level'])
    return max(c['tickMin'], c['tick0'] - c['accel'] * st['foods'])

def snake_valid_turn(st, d):
    return isinstance(d, int) and 0 <= d <= 3 and (d != st['dir']) and ((d + 2) % 4 != st['dir'])

def snake_step(st, d=None):
    if st['dead']:
        return 'die'
    if d is not None and snake_valid_turn(st, d):
        st['dir'] = d
    st['ms'] += snake_tick_ms(st)
    st['ticks'] += 1
    dx, dy = snake_DIRS[st['dir']]
    hx, hy = st['snake'][0]
    hx += dx
    hy += dy
    if st['wrap']:
        hx = (hx + st['size']) % st['size']
        hy = (hy + st['size']) % st['size']
    elif hx < 0 or hy < 0 or hx >= st['size'] or (hy >= st['size']):
        st['dead'] = True
        return 'die'
    eat = st['food'] and st['food'][0] == hx and (st['food'][1] == hy)
    body = st['snake'] if eat else st['snake'][:-1]
    if any((c[0] == hx and c[1] == hy for c in body)) or any((c[0] == hx and c[1] == hy for c in st['rocks'])):
        st['dead'] = True
        return 'die'
    st['snake'].insert(0, [hx, hy])
    if eat:
        st['foods'] += 1
        snake__spawn_food(st)
        if st['food'] is None:
            st['dead'] = True
        return 'eat'
    st['snake'].pop()
    return None

def snake_reward(level, foods):
    c = snake_cfg(level)
    return min(c['maxReward'], foods * c['perFood'])

def snake_replay(level, seed, turns, ticks=None, revives=None):
    st = snake_new_state(level, seed)
    q = deque(turns)
    emitted = 0
    while not st['dead']:
        d = None
        while q and q[0][0] <= st['ticks']:
            tk, dd = q.popleft()
            if snake_valid_turn(st, dd):
                d = dd
                break
        snake_step(st, d)
    foods = st['foods']
    return (foods, len(st['snake']), st['ticks'], snake_reward(level, foods))

def snake__blocked(st, cell, ignore_tail=True):
    if any((c[0] == cell[0] and c[1] == cell[1] for c in st['rocks'])):
        return True
    body = st['snake'][:-1] if ignore_tail else st['snake']
    return any((c[0] == cell[0] and c[1] == cell[1] for c in body))

def snake__next_cell(st, d, from_cell=None):
    hx, hy = from_cell or st['snake'][0]
    dx, dy = snake_DIRS[d]
    nx, ny = (hx + dx, hy + dy)
    if st['wrap']:
        nx = (nx + st['size']) % st['size']
        ny = (ny + st['size']) % st['size']
    elif nx < 0 or ny < 0 or nx >= st['size'] or (ny >= st['size']):
        return None
    return (nx, ny)

def snake__neighbors(cell, wrap, size):
    for d in range(4):
        dx, dy = snake_DIRS[d]
        nx, ny = (cell[0] + dx, cell[1] + dy)
        if wrap:
            nx = (nx + size) % size
            ny = (ny + size) % size
        elif nx < 0 or ny < 0 or nx >= size or (ny >= size):
            continue
        yield (d, (nx, ny))

def snake__path(snake, rocks, target, wrap, size, tail_is_free=False):
    if target is None:
        return None
    start = snake[0]
    occ = set(snake if not tail_is_free else snake[:-1])
    occ |= set(rocks)
    if target in occ and target != start:
        return None
    q = deque([start])
    prev = {start: None}
    while q:
        cur = q.popleft()
        if cur == target:
            path = []
            while prev[cur] is not None:
                p, d = prev[cur]
                path.append(d)
                cur = p
            return path[::-1]
        for d, nxt in snake__neighbors(cur, wrap, size):
            if nxt in prev or nxt in occ:
                continue
            prev[nxt] = (cur, d)
            q.append(nxt)
    return None

def snake__sim_move(snake, d, food, rocks, wrap, size):
    nxt = None
    for dd, c in snake__neighbors(snake[0], wrap, size):
        if dd == d:
            nxt = c
            break
    if nxt is None:
        return (snake, True)
    eat = food is not None and nxt == food
    body = snake if eat else snake[:-1]
    if nxt in body or nxt in rocks:
        return (snake, True)
    ns = [nxt] + list(snake)
    if not eat:
        ns.pop()
    return (ns, False)

def snake__can_reach_tail(snake, rocks, wrap, size):
    if len(snake) < 2:
        return True
    tail = snake[-1]
    occ = set(snake[:-1]) | set(rocks)
    q = deque([snake[0]])
    seen = {snake[0]}
    while q:
        cur = q.popleft()
        if cur == tail:
            return True
        for d, nxt in snake__neighbors(cur, wrap, size):
            if nxt in seen or nxt in occ:
                continue
            seen.add(nxt)
            q.append(nxt)
    return False

def snake__free_space_from(snake, rocks, wrap, size, first_dir):
    ns, dead = snake__sim_move(snake, first_dir, None, rocks, wrap, size)
    if dead:
        return -1
    occ = set(ns) | set(rocks)
    start = ns[0]
    seen = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        for d, nxt in snake__neighbors(cur, wrap, size):
            if nxt in seen or nxt in occ:
                continue
            seen.add(nxt)
            q.append(nxt)
    return len(seen)

def snake_choose_dir(st):
    size, wrap, rocks = (st['size'], st['wrap'], [tuple(r) for r in st['rocks']])
    snake = [tuple(c) for c in st['snake']]
    food = tuple(st['food']) if st['food'] else None
    legal = [d for d in range(4) if (d + 2) % 4 != st['dir']]

    def usable(d):
        ns, dead = snake__sim_move(snake, d, food, rocks, wrap, size)
        return None if dead else ns
    path = snake__path(snake, rocks, food, wrap, size)
    if path:
        vs = snake
        vfood = food
        ok = True
        for d in path:
            before = len(vs)
            vs, dead = snake__sim_move(vs, d, vfood, rocks, wrap, size)
            if dead:
                ok = False
                break
            if len(vs) > before:
                vfood = None
        if ok and snake__can_reach_tail(vs, rocks, wrap, size) and (path[0] in legal):
            return path[0]
    tpath = snake__path(snake, rocks, snake[-1], wrap, size, tail_is_free=True)
    if tpath:
        for d in tpath:
            if d in legal and usable(d) is not None:
                return d
    best, bs = (None, -1)
    for d in legal:
        ns = usable(d)
        if ns is None:
            continue
        sp = snake__free_space_from(snake, rocks, wrap, size, d)
        if sp > bs:
            bs, best = (sp, d)
    if best is not None:
        return best
    return legal[0] if legal else st['dir']

def snake_solve(level, seed, max_ticks=20000):
    c = snake_cfg(level)
    st = snake_new_state(level, seed)
    turns = []
    while not st['dead'] and st['ticks'] < max_ticks:
        if snake_reward(level, st['foods']) >= c['maxReward']:
            break
        d = snake_choose_dir(st)
        if snake_valid_turn(st, d):
            turns.append([st['ticks'], d])
        snake_step(st, d)
    return (turns, st['ticks'], [], st['foods'], snake_reward(level, st['foods']), int(st['ms']))

g2048_CFG = {'easy': dict(size=5, fourChance=0.1, extraEvery=0, pointsPerWave=12, maxReward=1200), 'normal': dict(size=4, fourChance=0.1, extraEvery=0, pointsPerWave=8, maxReward=2500), 'hard': dict(size=4, fourChance=0.25, extraEvery=4, pointsPerWave=5, maxReward=3500)}
g2048_DIRS = ['left', 'right', 'up', 'down']
g2048_CODE = {'up': 'U', 'down': 'D', 'left': 'L', 'right': 'R'}

def g2048_cfg(level):
    return g2048_CFG.get(level) or g2048_CFG['normal']

def g2048_new_state(level, seed):
    c = g2048_cfg(level)
    st = dict(level=level, size=c['size'], board=[0] * c['size'] ** 2, score=0, rng=rng(seed), cfg=c, moves=0)
    st['spawned'] = [g2048__spawn(st), g2048__spawn(st)]
    return st

def g2048__spawn(st):
    empty = [i for i, v in enumerate(st['board']) if not v]
    if not empty:
        return -1
    n = empty[int(st['rng']() * len(empty))]
    st['board'][n] = 2 if st['rng']() < 1 - st['cfg']['fourChance'] else 4
    return n

def g2048_lines(size):
    idx = list(range(size))
    rev = idx[::-1]
    return {'left': [[r * size + c for c in idx] for r in idx], 'right': [[r * size + c for c in rev] for r in idx], 'up': [[r * size + c for r in idx] for c in idx], 'down': [[r * size + c for r in rev] for c in idx]}

def g2048_slide(board, direction, size):
    out = [0] * len(board)
    gained = 0
    for line in g2048_lines(size)[direction]:
        t = 0
        prev = 0
        for s in line:
            c = board[s]
            if not c:
                continue
            if c == prev:
                out[line[t - 1]] = c * 2
                gained += c * 2
                prev = 0
            else:
                out[line[t]] = c
                prev = c
                t += 1
    moved = any((out[i] != board[i] for i in range(len(board))))
    return (out, gained, moved)

def g2048_apply_move(st, direction):
    b, gained, moved = g2048_slide(st['board'], direction, st['size'])
    if not moved:
        return None
    st['board'] = b
    st['score'] += gained
    st['moves'] += 1
    sp = [g2048__spawn(st)]
    if st['cfg']['extraEvery'] and st['moves'] % st['cfg']['extraEvery'] == 0:
        sp.append(g2048__spawn(st))
    return {'gained': gained, 'spawned': [x for x in sp if x >= 0]}

def g2048_can_move(board, size):
    return any((g2048_slide(board, d, size)[2] for d in g2048_DIRS))

def g2048_reward(level, score):
    c = g2048_cfg(level)
    return min(c['maxReward'], score // c['pointsPerWave'])
g2048__W = dict(empty=350.0, mono=200.0, smooth=25.0, maxpos=250.0, merge=60.0)

def g2048__heuristic(board, size):
    n = len(board)
    empty = board.count(0)
    mono = 0
    for r in range(size):
        row = board[r * size:(r + 1) * size]
        inc = sum((row[i] - row[i + 1] for i in range(size - 1) if row[i + 1] > row[i]))
        dec = sum((row[i + 1] - row[i] for i in range(size - 1) if row[i] > row[i + 1]))
        mono -= min(inc, dec)
    for c in range(size):
        col = [board[r * size + c] for r in range(size)]
        inc = sum((col[i] - col[i + 1] for i in range(size - 1) if col[i + 1] > col[i]))
        dec = sum((col[i + 1] - col[i] for i in range(size - 1) if col[i] > col[i + 1]))
        mono -= min(inc, dec)
    smooth = 0
    for r in range(size):
        for c in range(size):
            v = board[r * size + c]
            if not v:
                continue
            if c + 1 < size and board[r * size + c + 1]:
                smooth -= abs(v - board[r * size + c + 1])
            if r + 1 < size and board[(r + 1) * size + c]:
                smooth -= abs(v - board[(r + 1) * size + c])
    mx = max(board)
    corners = (0, size - 1, n - size, n - 1)
    maxpos = 1.0 if board.index(mx) in corners else 0.0
    merges = 0
    for r in range(size):
        for c in range(size):
            v = board[r * size + c]
            if not v:
                continue
            if c + 1 < size and board[r * size + c + 1] == v:
                merges += v
            if r + 1 < size and board[(r + 1) * size + c] == v:
                merges += v
    return g2048__W['empty'] * (empty / n) * 100 + g2048__W['mono'] * (mono / 1000.0) + g2048__W['smooth'] * (smooth / 100.0) + g2048__W['maxpos'] * maxpos + g2048__W['merge'] * (merges / 100.0)

def g2048__expectimax(board, size, four_chance, depth, rng_pick=None, is_max=True):
    if depth == 0 or not g2048_can_move(board, size):
        return g2048__heuristic(board, size)
    if is_max:
        best = -1e+18
        for d in g2048_DIRS:
            nb, gained, moved = g2048_slide(board, d, size)
            if not moved:
                continue
            val = gained + g2048__expectimax(nb, size, four_chance, depth - 1, rng_pick, False)
            if val > best:
                best = val
        return best if best > -1e+17 else g2048__heuristic(board, size)
    empty = [i for i, v in enumerate(board) if not v]
    if not empty:
        return g2048__heuristic(board, size)
    cells = empty
    if len(cells) > 6:
        step = len(cells) / 6.0
        cells = [empty[int(k * step)] for k in range(6)]
    total = 0.0
    for i in cells:
        for val, p in ((2, 1 - four_chance), (4, four_chance)):
            nb = list(board)
            nb[i] = val
            total += p * g2048__expectimax(nb, size, four_chance, depth - 1, rng_pick, True)
    return total / len(cells)

def g2048_best_move(board, size, four_chance, depth=3):
    best, bd = (-1e+18, None)
    for d in g2048_DIRS:
        nb, gained, moved = g2048_slide(board, d, size)
        if not moved:
            continue
        val = gained + g2048__expectimax(nb, size, four_chance, depth - 1, None, False)
        if val > best:
            best, bd = (val, d)
    return bd

def g2048_solve(level, seed, depth=3, max_moves=6000):
    c = g2048_cfg(level)
    st = g2048_new_state(level, seed)
    moves = ''
    while st['moves'] < max_moves:
        if g2048_reward(level, st['score']) >= c['maxReward']:
            break
        d = g2048_best_move(st['board'], st['size'], c['fourChance'], depth)
        if d is None:
            break
        if g2048_apply_move(st, d) is None:
            break
        moves += g2048_CODE[d]
    return (moves, st['score'], max(st['board']))

def g2048_replay(level, seed, moves):
    st = g2048_new_state(level, seed)
    ok = ''
    for ch in moves:
        d = {v: k for k, v in g2048_CODE.items()}.get(ch)
        if d is None:
            continue
        if g2048_apply_move(st, d) is None:
            continue
        ok += ch
    return (st['score'], max(st['board']), ok)

racer_CFG = {'easy': dict(speed0=7, maxSpeed=14, accelEvery=2200, gap=620, minBlock=1, maxBlock=2, coinChance=0.7, perPoint=1.4, maxReward=700), 'normal': dict(speed0=9, maxSpeed=18, accelEvery=1800, gap=520, minBlock=2, maxBlock=3, coinChance=0.6, perPoint=2.0, maxReward=1400), 'hard': dict(speed0=11, maxSpeed=23, accelEvery=1400, gap=460, minBlock=2, maxBlock=4, coinChance=0.55, perPoint=2.8, maxReward=2400)}
racer_START_Y = 900

def racer_cfg(level):
    return racer_CFG.get(level) or racer_CFG['normal']

def racer_speed(level, dist):
    c = racer_cfg(level)
    return min(c['maxSpeed'], c['speed0'] + dist // c['accelEvery'])

def racer_new_state(level, seed):
    return dict(level=level, rng=rng(seed), lane=2, dist=0, ticks=0, rows=[], nextY=racer_START_Y, coins=0, crashed=False, taken=set())

def racer_gen_rows(st, upto):
    c = racer_cfg(st['level'])
    while st['nextY'] < upto:
        nb = c['minBlock'] + int(st['rng']() * (c['maxBlock'] - c['minBlock'] + 1))
        lanes = [0, 1, 2, 3, 4]
        for i in range(len(lanes) - 1, 0, -1):
            j = int(st['rng']() * (i + 1))
            lanes[i], lanes[j] = (lanes[j], lanes[i])
        cars = sorted(lanes[:nb])
        free = lanes[nb:]
        styles = [int(st['rng']() * 6) for _ in cars]
        coin = free[int(st['rng']() * len(free))] if st['rng']() < c['coinChance'] else -1
        y = st['nextY']
        st['rows'].append(dict(id=len(st['rows']), y=y, cars=cars, style=styles, coin=coin, coinY=y + c['gap'] // 2))
        st['nextY'] = y + c['gap'] + int(st['rng']() * int(c['gap'] * 0.35))

def racer_near(a, b):
    return a < b + 100 and b < a + 100

def racer_valid_lane_change(cur, new):
    return isinstance(new, int) and 0 <= new < 5 and (abs(new - cur) == 1)

def racer_tick(st, new_lane=None):
    if st['crashed']:
        return 'crash'
    if new_lane is not None and racer_valid_lane_change(st['lane'], new_lane):
        st['lane'] = new_lane
    st['dist'] += racer_speed(st['level'], st['dist'])
    st['ticks'] += 1
    racer_gen_rows(st, st['dist'] + 4000)
    got = None
    for row in st['rows']:
        if row['y'] > st['dist'] + 100:
            break
        if row['coinY'] + 100 < st['dist'] and row['y'] + 100 < st['dist']:
            continue
        if st['lane'] in row['cars'] and racer_near(row['y'], st['dist']):
            st['crashed'] = True
            return 'crash'
        if row['coin'] == st['lane'] and row['id'] not in st['taken'] and racer_near(row['coinY'], st['dist']):
            st['taken'].add(row['id'])
            st['coins'] += 1
            got = 'coin'
    while st['rows'] and st['rows'][0]['coinY'] + 200 < st['dist'] - 400:
        st['rows'].pop(0)
    return got

def racer_score(level, dist, coins):
    c = racer_cfg(level)
    return min(c['maxReward'], int((dist // 100 + coins * 10) * c['perPoint']))

def racer__clone(st):
    return dict(rows=len(st['rows']), nextY=st['nextY'], rng_state=st['rng'].state, dist=st['dist'], taken=set(st['taken']))

def racer__restore(st, snap):
    del st['rows'][snap['rows']:]
    st['nextY'] = snap['nextY']
    st['rng'].state = snap['rng_state']
    st['dist'] = snap['dist']
    st['taken'] = set(snap['taken'])

def racer__lookahead(st, lane, horizon=140):
    c = racer_cfg(st['level'])
    snap = racer__clone(st)
    d = st['dist']
    taken = set(st['taken'])
    coins = 0
    try:
        for k in range(horizon):
            d += racer_speed(st['level'], d)
            racer_gen_rows(st, d + 4000)
            for row in st['rows']:
                if row['y'] > d + 100:
                    break
                if row['coinY'] + 100 < d and row['y'] + 100 < d:
                    continue
                if lane in row['cars'] and racer_near(row['y'], d):
                    return (k, coins)
                if row['coin'] == lane and row['id'] not in taken and racer_near(row['coinY'], d):
                    taken.add(row['id'])
                    coins += 1
        return (horizon, coins)
    finally:
        racer__restore(st, snap)

def racer__timeline(st, horizon):
    snap = racer__clone(st)
    d = st['dist']
    out = []
    try:
        for _ in range(horizon):
            d += racer_speed(st['level'], d)
            racer_gen_rows(st, d + 4000)
            blocked = set()
            coin = -1
            for row in st['rows']:
                if row['y'] > d + 100:
                    break
                if row['coinY'] + 100 < d and row['y'] + 100 < d:
                    continue
                if racer_near(row['y'], d):
                    blocked.update(row['cars'])
                if row['coin'] >= 0 and row['id'] not in st['taken'] and racer_near(row['coinY'], d):
                    coin = row['coin']
            out.append((d, blocked, coin))
    finally:
        racer__restore(st, snap)
    return out

def racer_ai_lane(st, horizon=140):
    tl = racer__timeline(st, horizon)
    cur = st['lane']
    reach = [None] * (len(tl) + 1)
    reach[0] = {cur}
    last = 0
    for k, (_d, blocked, _coin) in enumerate(tl):
        nxt = set()
        for l in reach[k]:
            for nl in (l - 1, l, l + 1):
                if 0 <= nl < 5 and nl not in blocked:
                    nxt.add(nl)
        if not nxt:
            last = k
            break
        reach[k + 1] = nxt
        last = k + 1
    if last == 0:
        return cur
    best = {l: (0, None) for l in reach[last]}
    for k in range(last - 1, -1, -1):
        coin_lane = tl[k][2]
        nxt_best = {}
        for l in reach[k]:
            pick = None
            for nl in (l - 1, l, l + 1):
                if nl in best:
                    val = best[nl][0] + (1 if coin_lane == nl else 0)
                    if pick is None or val > pick[0]:
                        pick = (val, nl)
            if pick is not None:
                nxt_best[l] = pick
        best = nxt_best
    if cur not in best:
        return cur
    return best[cur][1] if best[cur][1] is not None else cur

def racer_solve(level, seed, max_ticks=20000):
    c = racer_cfg(level)
    st = racer_new_state(level, seed)
    racer_gen_rows(st, 4000)
    moves = []
    while st['ticks'] < max_ticks:
        if racer_score(level, st['dist'], st['coins']) >= c['maxReward']:
            break
        nl = racer_ai_lane(st)
        if racer_valid_lane_change(st['lane'], nl):
            moves.append([st['ticks'], nl])
        r = racer_tick(st, nl)
        if r == 'crash':
            break
    return (moves, st['ticks'], st['coins'], st['dist'], racer_score(level, st['dist'], st['coins']))

def racer_replay(level, seed, moves, max_ticks=None):
    st = racer_new_state(level, seed)
    racer_gen_rows(st, 4000)
    q = list(moves)
    limit = max_ticks or (max((m[0] for m in moves)) + 2 if moves else 1)
    while st['ticks'] <= limit:
        nl = None
        while q and q[0][0] <= st['ticks']:
            tk, ln = q.pop(0)
            if racer_valid_lane_change(st['lane'], ln):
                nl = ln
                break
        r = racer_tick(st, nl)
        if r == 'crash':
            break
    return (st['ticks'], st['coins'], st['dist'], racer_score(level, st['dist'], st['coins']))

hoops_DT = 1.0 / 60
hoops_DT_MS = 1000.0 / 60
hoops_MAX_STEPS = 320
hoops_GRAV = 42.0
hoops_HOOPS = [dict(id='low', z=28.0, y=9.0, range=8.0, points=2, dir=1), dict(id='high', z=28.0, y=16.0, range=6.5, points=3, dir=-1)]
hoops_CFG = {'easy': dict(roundMs=45000, rack=4, rim=2.7, speeds=[3.5, 2.5], perPoint=22, maxReward=600), 'normal': dict(roundMs=40000, rack=4, rim=2.35, speeds=[6, 4.5], perPoint=40, maxReward=1200), 'hard': dict(roundMs=35000, rack=3, rim=2.05, speeds=[9, 7], perPoint=60, maxReward=2000)}

def hoops_cfg(level):
    return hoops_CFG.get(level) or hoops_CFG['normal']

def hoops_board_z(level):
    return 28 + hoops_cfg(level)['rim'] + 0.7

def hoops_hoop_x(level, idx, ms):
    h = hoops_HOOPS[idx]
    a = h['range'] * 2
    o = hoops_cfg(level)['speeds'][idx] * ms / 1000.0 % (2 * a)
    s = o / a if o < a else 2 - o / a
    sm = s * s * (3 - 2 * s)
    return (-h['range'] + sm * a) * h['dir']

def hoops_init_ball(x10, x, power):
    return dict(x=x10 / 10.0, y=0.0, z=2.0, vx=x / 100.0 * 9.0, vy=20.52 + power * 0.24, vz=25.77 - power * 0.086)

def hoops_simulate(level, throw_ms, x10, x, power, record=False):
    c = hoops_cfg(level)
    bz = hoops_board_z(level)
    s = hoops_init_ball(x10, x, power)
    hit_board = False
    bounces = 0
    path = [[s['x'], s['y'], s['z']]]
    for n in range(1, hoops_MAX_STEPS + 1):
        px, py, pz = (s['x'], s['y'], s['z'])
        s['vy'] -= hoops_GRAV * hoops_DT
        s['x'] += s['vx'] * hoops_DT
        s['y'] += s['vy'] * hoops_DT
        s['z'] += s['vz'] * hoops_DT
        p = throw_ms + n * hoops_DT_MS
        if pz + 1 < bz <= s['z'] + 1 and s['vz'] > 0 and (s['y'] < 24) and (-22 < s['x'] < 22):
            s['z'] = bz - 1
            s['vz'] = -s['vz'] * 0.4
            s['vx'] *= 0.8
            hit_board = True
        for t, h in enumerate(hoops_HOOPS):
            if py > h['y'] >= s['y']:
                m = hoops_hoop_x(level, t, p)
                f = (py - h['y']) / (py - s['y']) if py != s['y'] else 0.0
                cx = px + (s['x'] - px) * f
                cz = pz + (s['z'] - pz) * f
                dx = cx - m
                dz = cz - h['z']
                dist = math.sqrt(dx * dx + dz * dz)
                if dist <= c['rim'] - 1:
                    out = 'swish' if not hit_board and dist <= (c['rim'] - 1) * 0.5 else 'make'
                    return dict(outcome=out, hoop=t, ms=n * hoops_DT_MS, steps=n, path=path)
                if dist <= c['rim'] + 1 and bounces < 3:
                    bounces += 1
                    hit_board = True
                    ex = dx / dist if dist > 0 else 1.0
                    er = dz / dist if dist > 0 else 0.0
                    ei = -1 if dist < c['rim'] else 1
                    s['y'] = h['y'] + 0.01
                    s['vy'] = abs(s['vy']) * 0.38
                    s['vx'] = s['vx'] * 0.5 + ex * ei * 5
                    s['vz'] = s['vz'] * 0.5 + er * ei * 5
        if record:
            path.append([s['x'], s['y'], s['z']])
        if s['y'] < -1 and s['vy'] < 0:
            return dict(outcome='miss', hoop=-1, ms=n * hoops_DT_MS, steps=n, path=path)
    return dict(outcome='miss', hoop=-1, ms=hoops_MAX_STEPS * hoops_DT_MS, steps=hoops_MAX_STEPS, path=path)

def hoops_throw_points(hoop, outcome, fire):
    if outcome not in ('make', 'swish'):
        return 0.0
    r = hoops_HOOPS[hoop]['points'] + (1 if outcome == 'swish' else 0)
    return round(r * (1 + min(5, fire) * 0.2) * 10) / 10

def hoops_reward(level, points):
    c = hoops_cfg(level)
    return min(c['maxReward'], int(points * c['perPoint']))

def hoops__y_z_profile(power):
    vy = 20.52 + power * 0.24
    vz = 25.77 - power * 0.086
    y, z = (0.0, 2.0)
    prof = []
    for n in range(1, hoops_MAX_STEPS + 1):
        vy -= hoops_GRAV * hoops_DT
        y += vy * hoops_DT
        z += vz * hoops_DT
        prof.append((n, y, z))
    return prof

def hoops_find_throw(level, throw_ms, hoop_idx=0):
    h = hoops_HOOPS[hoop_idx]
    c = hoops_cfg(level)
    tol = c['rim'] - 1
    best = None
    for power in range(0, 101):
        prof = hoops__y_z_profile(power)
        prev_y, prev_z = (0.0, 2.0)
        for n, y, z in prof:
            if prev_y > h['y'] >= y and z < h['z'] + tol:
                f = (prev_y - h['y']) / (prev_y - y)
                cz = prev_z + (z - prev_z) * f
                dz = cz - h['z']
                if abs(dz) <= tol:
                    tstar = n * hoops_DT_MS / 1000.0
                    p_abs = throw_ms + n * hoops_DT_MS
                    hx = hoops_hoop_x(level, hoop_idx, p_abs)
                    cand = hoops__solve_x(hx, tstar)
                    if cand is None:
                        break
                    x10, x = cand
                    r = hoops_simulate(level, throw_ms, x10, x, power)
                    if r['outcome'] != 'miss' and r['hoop'] == hoop_idx:
                        score = (1 if r['outcome'] == 'swish' else 0) - abs(dz) * 0.01
                        if best is None or score > best[0]:
                            best = (score, x10, x, power, r)
                break
            prev_y, prev_z = (y, z)
    if best is None:
        return None
    return (best[1], best[2], best[3])

def hoops__solve_x(hx, tstar):
    best = None
    for x in range(-100, 101, 5):
        vx = x / 100.0 * 9.0
        x0 = hx - vx * tstar
        x10 = round(x0 * 10)
        if -50 <= x10 <= 50:
            err = abs(x10 / 10.0 + vx * tstar - hx)
            if best is None or err < best[0]:
                best = (err, x10, x)
    if best is None:
        return None
    return (best[1], best[2])

def hoops_build_throws(level, hoops=(0, 1)):
    c = hoops_cfg(level)
    rack = c['rack']
    total_ms = c['roundMs']
    spacing = 1000
    throws = []
    t = 900
    idx = 0
    while t < total_ms - 1200:
        hi = hoops[idx % len(hoops)]
        found = hoops_find_throw(level, t, hi)
        if found:
            throws.append([int(t), found[0], found[1], found[2]])
            idx += 1
        t += spacing
    return throws

def hoops_replay(level, throws):
    fire = 0
    total = 0.0
    makes = 0
    for th in throws:
        t, x10, x, power = th
        r = hoops_simulate(level, t, x10, x, power)
        pts = hoops_throw_points(r['hoop'], r['outcome'], fire)
        if pts > 0:
            makes += 1
            fire += 1
        else:
            fire = 0
        total = round(total + pts, 1)
    return (makes, len(throws), total, hoops_reward(level, total))

shooter_T = 60000
shooter_E_CAP = 1800000
shooter_F_BOSS = 43000
shooter_P_DARTS = [12000, 24000, 36000]
shooter_D = dict(scout=dict(hp=1, points=10, speed=0.19, size=0.1), dart=dict(hp=1, points=15, speed=0.3, size=0.085), tank=dict(hp=4, points=40, speed=0.11, size=0.15), cruiser=dict(hp=10, points=90, speed=0.075, size=0.25), boss=dict(hp=24, points=150, speed=0.07, size=0.36))
shooter_O_SLOW = 0.45
shooter_RAMP = {'easy': dict(heatStep=0.1, heatCap=2.1, floorMs=240, dartGrow=2, tanksFrom=3, extraFrom=2, pairFrom=6, trioFrom=12, fireStep=0.05, fireMin=0.6, volleyFrom=6, dartFireFrom=4, scoutFireFrom=7, bulletStep=0.03, speedCap=2.3), 'normal': dict(heatStep=0.14, heatCap=2.8, floorMs=190, dartGrow=1, tanksFrom=2, extraFrom=2, pairFrom=4, trioFrom=8, fireStep=0.08, fireMin=0.45, volleyFrom=3, dartFireFrom=2, scoutFireFrom=4, bulletStep=0.04, speedCap=2.7), 'hard': dict(heatStep=0.2, heatCap=3.4, floorMs=150, dartGrow=1, tanksFrom=1, extraFrom=1, pairFrom=3, trioFrom=6, fireStep=0.1, fireMin=0.35, volleyFrom=2, dartFireFrom=0, scoutFireFrom=2, bulletStep=0.05, speedCap=3.1)}
shooter_LEVEL = {'easy': dict(speed=0.62, density=0.6, points=0.8, lives=5, bossHp=14, cruiserHp=7), 'normal': dict(speed=1.0, density=1.0, points=1.0, lives=3, bossHp=24, cruiserHp=10), 'hard': dict(speed=1.35, density=1.45, points=1.4, lives=2, bossHp=38, cruiserHp=14)}
shooter_FIRE_COOLDOWN = 165
shooter_KILL_GRACE = 170

def shooter_cfg(level):
    return shooter_LEVEL.get(level) or shooter_LEVEL['normal']

def shooter_points_of(etype, level):
    return round(shooter_D[etype]['points'] * shooter_cfg(level)['points'])

def shooter_enemy_window(etype, level):
    if etype == 'boss':
        return shooter_E_CAP
    return 1.25 / (shooter_D[etype]['speed'] * shooter_cfg(level)['speed']) * 1000 * (1 / shooter_O_SLOW)

def shooter__gen_darts_heavy(seed, level, cap, wave, ramp):
    ev = [dict(at=12000, kind='darts'), dict(at=24000, kind='tanks' if wave >= ramp['tanksFrom'] else 'darts'), dict(at=36000, kind='darts')]
    if wave >= 1:
        ev.append(dict(at=30000, kind='heavy'))
    if wave >= ramp['tanksFrom'] + 1:
        ev.append(dict(at=6000, kind='tanks'))
    if wave >= ramp['extraFrom']:
        ev.append(dict(at=18000, kind='darts'))
    if wave >= ramp['extraFrom'] + 2:
        ev.append(dict(at=49000, kind='darts'))
    if wave >= ramp['extraFrom'] + 4:
        ev.append(dict(at=54000, kind='tanks'))
    return sorted(ev, key=lambda e: e['at'])

def shooter_gen_easy(seed, level, cap=shooter_E_CAP):
    r = shooter_cfg(level)['density']
    rnd = rng(seed)
    out = []
    oid = 0

    def push(t, x, typ):
        nonlocal oid
        rr = rnd()
        drop = 'multi' if rr < 0.04 else 'wingman' if rr < 0.075 else 'slow' if rr < 0.105 else 'shield' if rr < 0.14 else None
        out.append(dict(id=oid, t=round(t), x=x, type=typ, drop=drop))
        oid += 1
    c = min(cap, shooter_E_CAP)
    l = 900.0
    u = 0
    d = 0
    f = False
    while l < c:
        e = l - u * shooter_T
        if e >= shooter_T:
            u += 1
            d = 0
            f = False
            continue
        tt = min(1.5, e / shooter_T + u * 0.25)
        if not f and e >= shooter_F_BOSS:
            push(u * shooter_T + shooter_F_BOSS, 0.5, 'boss')
            f = True
            l = u * shooter_T + shooter_F_BOSS + 2600
            continue
        if d < len(shooter_P_DARTS) and e >= shooter_P_DARTS[d]:
            base = 0.25 + rnd() * 0.5
            for k in range(5):
                push(l + abs(k - 2) * 180, min(0.92, max(0.08, base + (k - 2) * 0.12)), 'dart')
            d += 1
            l += 1400
            continue
        n = rnd()
        typ = 'tank' if n < 0.08 + tt * 0.14 else 'dart' if n < 0.36 + tt * 0.22 else 'scout'
        push(l, 0.08 + rnd() * 0.84, typ)
        l += max(320.0, (1050 - 620 * min(1.2, tt) + rnd() * 300) / r) * (1.9 if f else 1.0)
    return sorted([e for e in out if e['t'] < c], key=lambda e: (e['t'], e['id']))

def shooter__clamp_x(x):
    return min(0.92, max(0.08, x))

def shooter__events(wave, ramp):
    ev = [dict(at=12000, kind='darts'), dict(at=24000, kind='tanks' if wave >= ramp['tanksFrom'] else 'darts'), dict(at=36000, kind='darts')]
    if wave >= 1:
        ev.append(dict(at=30000, kind='heavy'))
    if wave >= ramp['tanksFrom'] + 1:
        ev.append(dict(at=6000, kind='tanks'))
    if wave >= ramp['extraFrom']:
        ev.append(dict(at=18000, kind='darts'))
    if wave >= ramp['extraFrom'] + 2:
        ev.append(dict(at=49000, kind='darts'))
    if wave >= ramp['extraFrom'] + 4:
        ev.append(dict(at=54000, kind='tanks'))
    return sorted(ev, key=lambda e: e['at'])

def shooter_gen_ramp3(seed, level, cap=shooter_E_CAP):
    lvl = shooter_cfg(level)
    ramp = shooter_RAMP.get(level) or shooter_RAMP['normal']
    density = lvl['density']
    rnd = rng(seed)
    out = []
    oid = 0

    def push(t, x, typ):
        nonlocal oid
        rr = rnd()
        drop = 'multi' if rr < 0.04 else 'wingman' if rr < 0.075 else 'slow' if rr < 0.105 else 'shield' if rr < 0.14 else None
        out.append(dict(id=oid, t=round(t), x=x, type=typ, drop=drop))
        oid += 1
    limit = min(cap, shooter_E_CAP)
    u = 900.0
    wave = 0
    evs = shooter__events(0, ramp)
    boss_done = False
    while u < limit:
        wstart = wave * shooter_T
        t = u - wstart
        if t >= shooter_T:
            wave += 1
            evs = shooter__events(wave, ramp)
            boss_done = False
            continue
        n = min(1.5, t / shooter_T + wave * 0.25)
        heat = min(ramp['heatCap'], 1 + ramp['heatStep'] * wave)
        volley = 3 if wave >= ramp['trioFrom'] else 2 if wave >= ramp['pairFrom'] else 1
        if not boss_done and t >= shooter_F_BOSS:
            push(wstart + shooter_F_BOSS, 0.5, 'boss')
            if wave >= max(1, ramp['tanksFrom']):
                typ = 'cruiser' if volley >= 2 else 'tank'
                push(wstart + shooter_F_BOSS + 900, 0.2, typ)
                push(wstart + shooter_F_BOSS + 900, 0.8, typ)
                if volley >= 3:
                    push(wstart + shooter_F_BOSS + 1500, 0.35, 'tank')
                    push(wstart + shooter_F_BOSS + 1500, 0.65, 'tank')
            boss_done = True
            u = wstart + shooter_F_BOSS + 2600
            continue
        if evs and t >= evs[0]['at']:
            ev = evs.pop(0)
            if ev['kind'] == 'darts':
                cnt = min(11, 5 + wave // ramp['dartGrow'])
                step = min(0.12, 0.8 / (cnt - 1))
                mid_off = step * (cnt - 1) / 2
                spread = 0.08 + mid_off + rnd() * max(0.0, 0.84 - 2 * mid_off)
                mid = (cnt - 1) / 2
                for k in range(cnt):
                    push(u + abs(k - mid) * 160, shooter__clamp_x(spread + (k - mid) * step), 'dart')
                u += 1300
            elif ev['kind'] == 'tanks':
                cnt = min(5, 3 + wave // 3)
                step = min(0.2, 0.8 / (cnt - 1))
                base = 0.08 + step * (cnt - 1) / 2
                spread = base + rnd() * max(0.0, 0.84 - step * (cnt - 1))
                for k in range(cnt):
                    push(u + abs(k - (cnt - 1) / 2) * 240, shooter__clamp_x(spread + (k - (cnt - 1) / 2) * step), 'tank')
                u += 1700
            else:
                xs = [0.2, 0.5, 0.8] if volley == 3 else [0.27, 0.73] if volley == 2 else [0.3 + rnd() * 0.4]
                for k, x in enumerate(xs):
                    push(u + k * 450, x, 'cruiser')
                u += 2200
            continue
        r = rnd()
        cruiser_cut = min(0.08, 0.015 * wave) if wave >= 2 else 0.0
        tank_cut = min(0.35, 0.08 + n * 0.14 + 0.015 * wave)
        dart_bound = 0.36 + n * 0.22
        typ = 'cruiser' if r < cruiser_cut else 'tank' if r < cruiser_cut + tank_cut else 'dart' if r < cruiser_cut + dart_bound else 'scout'
        push(u, 0.08 + rnd() * 0.84, typ)
        floor_ms = max(ramp['floorMs'], 320 - 20 * wave)
        gap = max(floor_ms, (1050 - 620 * min(1.2, n) + rnd() * 300) / density / heat)
        u += gap * (1.6 if boss_done else 1.0)
    return sorted([e for e in out if e['t'] < limit], key=lambda e: (e['t'], e['id']))

def shooter_gen_ramp2(seed, level, cap=shooter_E_CAP):
    lvl = shooter_cfg(level)
    density = lvl['density']
    rnd = rng(seed)
    out = []
    oid = 0

    def push(t, x, typ):
        nonlocal oid
        rr = rnd()
        drop = 'multi' if rr < 0.04 else 'wingman' if rr < 0.075 else 'slow' if rr < 0.105 else 'shield' if rr < 0.14 else None
        out.append(dict(id=oid, t=round(t), x=x, type=typ, drop=drop))
        oid += 1
    limit = min(cap, shooter_E_CAP)
    l = 900.0
    wave = 0
    evs = shooter__events2(0)
    boss_done = False
    while l < limit:
        wstart = wave * shooter_T
        t = l - wstart
        if t >= shooter_T:
            wave += 1
            evs = shooter__events2(wave)
            boss_done = False
            continue
        n = min(1.5, t / shooter_T + wave * 0.25)
        heat = min(2.2, 1 + 0.1 * wave)
        if not boss_done and t >= shooter_F_BOSS:
            push(wstart + shooter_F_BOSS, 0.5, 'boss')
            if wave >= 2:
                typ = 'cruiser' if wave >= 4 else 'tank'
                push(wstart + shooter_F_BOSS + 900, 0.2, typ)
                push(wstart + shooter_F_BOSS + 900, 0.8, typ)
            boss_done = True
            l = wstart + shooter_F_BOSS + 2600
            continue
        if evs and t >= evs[0]['at']:
            ev = evs.pop(0)
            if ev['kind'] == 'darts':
                cnt = min(9, 5 + 2 * (wave // 2))
                step = min(0.12, 0.8 / (cnt - 1))
                mid_off = step * (cnt - 1) / 2
                spread = 0.08 + mid_off + rnd() * max(0.0, 0.84 - 2 * mid_off)
                mid = (cnt - 1) / 2
                for k in range(cnt):
                    push(l + abs(k - mid) * 180, shooter__clamp_x(spread + (k - mid) * step), 'dart')
                l += 1400
            elif ev['kind'] == 'tanks':
                cnt = 4 if wave >= 6 else 3
                step = 0.2
                mid_off = step * (cnt - 1) / 2
                spread = 0.08 + mid_off + rnd() * max(0.0, 0.84 - step * (cnt - 1))
                for k in range(cnt):
                    push(l + abs(k - (cnt - 1) / 2) * 260, shooter__clamp_x(spread + (k - (cnt - 1) / 2) * step), 'tank')
                l += 1800
            else:
                if wave >= 4:
                    push(l, 0.27, 'cruiser')
                    push(l + 500, 0.73, 'cruiser')
                else:
                    push(l, 0.3 + rnd() * 0.4, 'cruiser')
                l += 2200
            continue
        r = rnd()
        cruiser_cut = min(0.06, 0.012 * wave) if wave >= 2 else 0.0
        tank_cut = min(0.32, 0.08 + n * 0.14 + 0.01 * wave)
        dart_bound = 0.36 + n * 0.22
        typ = 'cruiser' if r < cruiser_cut else 'tank' if r < cruiser_cut + tank_cut else 'dart' if r < cruiser_cut + dart_bound else 'scout'
        push(l, 0.08 + rnd() * 0.84, typ)
        floor_ms = max(200, 320 - 15 * wave)
        gap = max(floor_ms, (1050 - 620 * min(1.2, n) + rnd() * 300) / density / heat)
        l += gap * (1.9 if boss_done else 1.0)
    return sorted([e for e in out if e['t'] < limit], key=lambda e: (e['t'], e['id']))

def shooter__events2(wave):
    ev = [dict(at=12000, kind='darts'), dict(at=24000, kind='tanks' if wave >= 2 else 'darts'), dict(at=36000, kind='darts')]
    if wave >= 1:
        ev.append(dict(at=30000, kind='heavy'))
    if wave >= 3:
        ev.append(dict(at=6000, kind='tanks'))
    return sorted(ev, key=lambda e: e['at'])

def shooter_gen_schedule(seed, level, ramp=1, cap=shooter_E_CAP):
    if ramp <= 1:
        return shooter_gen_easy(seed, level, cap)
    if ramp == 2:
        return shooter_gen_ramp2(seed, level, cap)
    return shooter_gen_ramp3(seed, level, cap)


def shooter_score_of(schedule, kills, level):
    by_id = {e['id']: e for e in schedule}
    total = 0
    for k in kills:
        e = by_id.get(k['id'])
        if e:
            total += shooter_points_of(e['type'], level)
    return total

def simple_memory_moves(state):
    deck = (state.get('peek') or {}).get('deck')
    if not deck:
        return []
    by_val = {}
    for i, v in enumerate(deck):
        by_val.setdefault(v, []).append(i)
    order = []
    for v in sorted(by_val):
        order.extend(by_val[v])
    return [{'index': i} for i in order]

def simple_quickmath_answer(state):
    q = (state.get("question") or "").replace("\u2212", "-").replace("\u00d7", "*")
    try:
        val = eval(q, {"__builtins__": {}}, {})
    except Exception:
        return None
    opts = state.get('options') or []
    for o in opts:
        if abs(float(o) - float(val)) < 1e-09:
            return {'answer': o}
    return None

def simple_quickmath_play(session_call, max_steps=200):
    for _ in range(max_steps):
        st, body = session_call('GET_STATE')
        if not st:
            break
        if st.get('out') or st.get('status') not in (None, 'active'):
            break
        mv = simple_quickmath_answer(st)
        if mv is None:
            mv = {'timeout': True}
        nxt = session_call('MOVE', mv)
        if not nxt:
            break
        if nxt.get('status') != 'active':
            break
        if nxt.get('out'):
            cont = session_call('CONTINUE')
            if not cont:
                break
    return session_call('MOVE', {'end': True})
simple_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]

def simple__ttt_winner(b):
    for a, c, d in simple_LINES:
        if b[a] and b[a] == b[c] == b[d]:
            return b[a]
    return None

def simple__ttt_full(b):
    return all((x for x in b))

def simple_ttt_best(board, me='X', opp='O'):
    b = list(board)

    def score(bd, depth):
        w = simple__ttt_winner(bd)
        if w == me:
            return 10 - depth
        if w == opp:
            return depth - 10
        if simple__ttt_full(bd):
            return 0
        return None

    def rec(bd, turn, depth):
        s = score(bd, depth)
        if s is not None:
            return (s, None)
        best = None
        for i in range(9):
            if bd[i]:
                continue
            bd[i] = turn
            val, _ = rec(bd, opp if turn == me else me, depth + 1)
            bd[i] = ''
            if best is None or (turn == me and val > best[0]) or (turn == opp and val < best[0]):
                best = (val, i)
        return best
    _, mv = rec(b, me, 0)
    return mv

def simple_wordle_filter(words, guesses, reveals=None, letters=None, hint=None):
    out = []
    for w in words:
        w = w.upper()
        if len(w) != 5:
            continue
        ok = True
        for g in guesses or []:
            guess = (g.get('guess') or '').upper()
            res = g.get('result') or []
            if len(guess) != 5 or len(res) != 5:
                continue
            need = {}
            for i, r in enumerate(res):
                if r in ('correct', 'present'):
                    need[guess[i]] = need.get(guess[i], 0) + 1
            for ch, n in need.items():
                if w.count(ch) < n:
                    ok = False
                    break
            if not ok:
                break
            absent = {guess[i] for i, r in enumerate(res) if r == 'absent'}
            for ch in absent:
                if ch not in need:
                    if ch in w:
                        ok = False
                        break
                elif w.count(ch) > need[ch]:
                    ok = False
                    break
            if not ok:
                break
            for i, r in enumerate(res):
                if r == 'correct' and w[i] != guess[i]:
                    ok = False
                    break
                if r == 'present' and (w[i] == guess[i] or guess[i] not in w):
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        if hint and w[hint['pos']] != hint['letter'].upper():
            continue
        for rv in reveals or []:
            if w[rv['pos']] != rv['letter'].upper():
                ok = False
                break
        if not ok:
            continue
        for lt in letters or []:
            if lt.upper() not in w:
                ok = False
                break
        if not ok:
            continue
        out.append(w)
    return out

def simple_ws_cells(a, b, size):
    r1, c1 = divmod(a, size)
    r2, c2 = divmod(b, size)
    dr = r2 - r1
    dc = c2 - c1
    if dr and dc and (abs(dr) != abs(dc)):
        return None
    step_r = (dr > 0) - (dr < 0)
    step_c = (dc > 0) - (dc < 0)
    n = max(abs(dr), abs(dc)) + 1
    return [(r1 + step_r * k) * size + (c1 + step_c * k) for k in range(n)]

def simple_wordsearch_moves(state):
    grid = state.get('grid') or ''
    size = state.get('size') or 0
    words = [w.upper() for w in state.get('words') or []]
    found = set(((f.get('word') or '').upper() for f in state.get('found') or []))
    moves = []
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1), (0, -1), (-1, 0), (-1, -1), (-1, 1)]
    for w in words:
        if w in found:
            continue
        for r in range(size):
            for c in range(size):
                for dr, dc in dirs:
                    er = r + dr * (len(w) - 1)
                    ec = c + dc * (len(w) - 1)
                    if not (0 <= er < size and 0 <= ec < size):
                        continue
                    got = ''.join((grid[(r + dr * k) * size + (c + dc * k)] for k in range(len(w))))
                    if got == w:
                        moves.append({'from': r * size + c, 'to': er * size + ec})
    return moves
simple_WORDLIST = None

def simple__words():
    global simple_WORDLIST
    if simple_WORDLIST is None:
        simple_WORDLIST = load_words()
    return simple_WORDLIST

def simple_scramble_guess(letters, hint=None):
    pool = {}
    for ch in letters:
        ch = ch.upper()
        pool[ch] = pool.get(ch, 0) + 1
    cands = []
    for w in simple__words():
        if len(w) != len(letters):
            continue
        if hint and w[0] != hint.upper():
            continue
        need = {}
        for ch in w:
            need[ch] = need.get(ch, 0) + 1
        if all((pool.get(k, 0) >= v for k, v in need.items())):
            cands.append(w)
    return cands

def simple_scramble_move(letters, hint=None, skip_words=None):
    cands = simple_scramble_guess(letters, hint)
    if skip_words:
        cands = [w for w in cands if w not in skip_words]
    if not cands:
        return {'skip': True}
    w = cands[0]
    used = [False] * len(letters)
    order = []
    for ch in w:
        for i, l in enumerate(letters):
            if not used[i] and l.upper() == ch:
                used[i] = True
                order.append(i)
                break
    if len(order) != len(letters):
        return {'skip': True}
    return {'guess': w, 't': order, 'order': order}

def simple_spin_segment(session):
    return (session.get('state') or {}).get('segment')



def wordle_pick(state, rejected, pool):
    guesses = state.get("guesses") or []
    tried = {str(item.get("guess") or "").upper() for item in guesses}
    cands = simple_wordle_filter(pool, guesses, state.get("reveals"),
                                 state.get("letters"), state.get("hint"))
    ranked = sorted((word for word in cands if word not in rejected and word not in tried),
                    key=wordle_rank)
    if ranked:
        return ranked[0]
    probes = [word for word in WORDLE_PROBES if word not in tried and word not in rejected]
    if probes:
        return probes[0]
    left = sorted((word for word in pool if word not in tried and word not in rejected), key=wordle_rank)
    return left[0] if left else None


def wordle_rank(word):
    return -sum(WORDLE_FREQ.index(ch) if ch in WORDLE_FREQ else 99 for ch in set(word))


WORDLE_FREQ = "ETAOINRSHDLUCMPFYWGBVKXJQZ"
WORDLE_PROBES = ("CRANE", "SLATE", "AUDIO", "PILOT", "HOUSE", "TRAIN", "MOUSE", "BRAIN",
                 "CHAIR", "DREAM", "LIGHT", "STONE", "PLANT", "SHORE", "MONEY", "WATER")


async def play_wordle(client, session_id, state, pool):
    rejected = set()
    for _ in range(10):
        guesses = state.get("guesses") or []
        if len(guesses) >= int(state.get("maxGuesses") or 8):
            break
        guess = wordle_pick(state, rejected, pool)
        if not guess:
            break
        try:
            result = await client.post(f"/games/sessions/{session_id}/move", {"guess": guess})
        except ApiError as exc:
            if "word list" in str(exc).lower():
                rejected.add(guess)
                pool.discard(guess)
                continue
            raise
        state = (result.get("session") or {}).get("state") or state
        status = (result.get("session") or {}).get("status")
        if status != "active":
            return status, (result.get("session") or {}).get("reward") or 0, state.get("answer")
    return "exhausted", 0, None


async def play_game(client, game_id, level, cap):
    started = await client.post(f"/games/{game_id}/start", {"difficulty": level})
    session = started.get("session") or {}
    session_id = session.get("id")
    state = session.get("state") or {}
    detail = ""
    if game_id == "spin":
        detail = f"segment {state.get('segment')}"
    elif game_id == "2048":
        moves, score, tile = g2048_solve(level, state["seed"], depth=3)
        await client.post(f"/games/sessions/{session_id}/finish", {"moves": moves})
        detail = f"score {score} with best tile {tile}"
    elif game_id == "stack":
        taps = stack_build_taps(level, cap)
        countdown(sum(taps) / 1000.0 + 2, "Next game in")
        result = await client.post(f"/games/sessions/{session_id}/finish", {"taps": taps})
        detail = f"{len(taps)} perfect drops"
    elif game_id == "snake":
        turns, ticks, revives, foods, reward, elapsed = snake_solve(level, state["seed"])
        countdown(elapsed / 1000.0 + 2, "Next game in")
        await client.post(f"/games/sessions/{session_id}/finish",
                          {"turns": turns, "ticks": ticks, "revives": revives})
        detail = f"{foods} fruits collected"
    elif game_id == "hoops":
        throws = hoops_build_throws(level)
        countdown(max([item[0] for item in throws] or [1000]) / 1000.0 + 2, "Next game in")
        result = await client.post(f"/games/sessions/{session_id}/finish", {"throws": throws})
        detail = f"{len(throws)} shots taken"
    elif game_id == "racer":
        moves, ticks, coins, distance, reward = racer_solve(level, state["seed"])
        countdown(ticks * 0.02 + 2, "Next game in")
        await client.post(f"/games/sessions/{session_id}/finish",
                          {"moves": moves, "ticks": ticks, "revives": []})
        detail = f"{distance} metres with {coins} coins"
    elif game_id == "shooter":
        schedule = shooter_gen_schedule(state["seed"], level, state.get("v", 1))
        kills = shooter_build_kills(schedule, level, 90000, cap)
        upto = max([item["t"] for item in kills] or [1000])
        countdown(upto / 1000.0 + 2, "Next game in")
        await client.post(f"/games/sessions/{session_id}/finish", {"kills": kills})
        detail = f"{len(kills)} ships destroyed"
    elif game_id == "wordle":
        pool = set(words_five())
        status, reward, answer = await play_wordle(client, session_id, state, pool)
        detail = f"answer {answer}"
    elif game_id == "wordsearch":
        current = state
        found = 0
        for _ in range(20):
            moves = simple_wordsearch_moves(current)
            if not moves:
                break
            result = await client.post(f"/games/sessions/{session_id}/move", moves[0])
            if (result.get("result") or {}).get("found"):
                found += 1
            current = (result.get("session") or {}).get("state") or current
            if (result.get("session") or {}).get("status") != "active":
                break
        detail = f"{found} words found"
    elif game_id == "scramble":
        current = state
        failed = set()
        solved = 0
        for _ in range(60):
            letters = current.get("letters") or []
            move = simple_scramble_move(letters, current.get("hint"), skip_words=failed)
            if move.get("skip"):
                failed.clear()
                move = {"skip": True}
            result = await client.post(f"/games/sessions/{session_id}/move", move)
            payload = result.get("result") or {}
            if payload.get("right"):
                solved += 1
                failed.clear()
            elif payload.get("outcome") in ("failed", "skipped"):
                failed.clear()
            elif move.get("guess"):
                failed.add(move["guess"])
            current = (result.get("session") or {}).get("state") or current
            if (result.get("session") or {}).get("status") != "active":
                break
        detail = f"{solved} words unscrambled"
    elif game_id == "memory":
        current = state
        for move in simple_memory_moves(current):
            result = await client.post(f"/games/sessions/{session_id}/move", move)
            current = (result.get("session") or {}).get("state") or current
            if (result.get("session") or {}).get("status") != "active":
                break
        detail = f"{len(current.get('matched') or [])} pairs matched"
    elif game_id == "quickmath":
        current = state
        for _ in range(80):
            if current.get("out"):
                break
            move = simple_quickmath_answer(current) or {"timeout": True}
            result = await client.post(f"/games/sessions/{session_id}/move", move)
            current = (result.get("session") or {}).get("state") or current
            if (result.get("session") or {}).get("status") != "active":
                break
        try:
            await client.post(f"/games/sessions/{session_id}/move", {"end": True})
        except ApiError:
            pass
        detail = f"{current.get('correct')} answers correct"
    elif game_id == "tictactoe":
        board = state.get("board") or [""] * 9
        for _ in range(9):
            cell = simple_ttt_best(board)
            if cell is None:
                break
            result = await client.post(f"/games/sessions/{session_id}/move", {"cell": cell})
            session_state = (result.get("session") or {}).get("state") or {}
            board = session_state.get("board") or board
            if (result.get("session") or {}).get("status") != "active":
                break
        detail = "board resolved"
    else:
        return 0
    collected = await client.claim_game_reward(session_id, "Next ad in")
    if collected:
        log_green(f"{clean_text(game_id, 'The game')} on {clean_text(level, 'this level')} was completed with {clean_text(detail, 'a finished board')} and {collected} WAVES were collected.")
    else:
        log_yellow(f"{clean_text(game_id, 'The game')} on {clean_text(level, 'this level')} was completed with {clean_text(detail, 'a finished board')} and no reward could be verified.")
    return collected


async def run_games(client, levels):
    total = 0
    played = 0
    for game in (await client.get("/games")).get("games") or []:
        game_id = game.get("id")
        left = int(game.get("playsLeft") or 0)
        if left <= 0:
            continue
        table = {item.get("id"): item for item in (game.get("levels") or [])}
        for level in levels:
            if left <= 0:
                break
            if table and level not in table:
                continue
            cap = (table.get(level) or {}).get("maxReward") or game.get("maxReward") or 0
            try:
                total += await play_game(client, game_id, level, cap)
                played += 1
                left -= 1
            except ApiError as exc:
                log_yellow(f"Game {clean_text(game_id, 'The game')} on {clean_text(level, 'this level')} was refused by the server.")
                log_yellow(f"The server answered with the reason {clean_text(exc, 'an unknown reason')}.")
                break
    return total, played


def shooter_build_kills(schedule, level, upto_ms, cap):
    kills = []
    last = 0
    score = 0
    for item in schedule:
        moment = item["t"] + 260
        if moment < item["t"] + shooter_KILL_GRACE:
            moment = item["t"] + shooter_KILL_GRACE
        if moment - last < shooter_FIRE_COOLDOWN + 1:
            moment = last + shooter_FIRE_COOLDOWN + 1
        if moment > upto_ms:
            break
        kills.append({"id": item["id"], "t": int(moment)})
        last = moment
        score += shooter_points_of(item["type"], level)
        if score >= cap:
            break
    return kills


async def run_tasks(client):
    economy = (client.app.get("economy") or {})
    wait_for = int(economy.get("taskCheckSeconds") or 5) + 1
    claimed = 0
    skipped = 0
    for task in (await client.get("/tasks")).get("tasks") or []:
        task_id = task.get("id")
        title = task.get("title")
        ad = task.get("ad") or {}
        try:
            if ad:
                left = int(ad.get("count") or 0) - int(ad.get("progress") or 0)
                ad_label = ad_network_label(ad.get("network"), title)
                for _ in range(max(0, left)):
                    result = await client.watch_ad("task", {"taskId": task_id}, "Next ad in", ad_label)
                    claimed += int(result.get("reward") or 0)
                    if (result.get("task") or {}).get("done"):
                        break
            elif task.get("url") and task.get("status") in ("available", "started"):
                if task.get("status") == "available":
                    await client.post(f"/tasks/{task_id}/start")
                    countdown(wait_for, "Next task in")
                else:
                    remaining = int(task.get("checkRemainingMs") or 0) / 1000.0
                    if remaining > 0:
                        countdown(remaining, "Next task in")
                result = await client.post(f"/tasks/{task_id}/claim")
                claimed += int(result.get("reward") or 0)
        except ApiError as exc:
            message = str(exc)
            if "not completed yet" in message:
                skipped += 1
            elif "AD_LIMIT" in message or "already" in message.lower():
                log_yellow(f"Task {clean_text(title, 'The task')} reached its daily limit on the server.")
            else:
                log_yellow(f"Task {clean_text(title, 'The task')} could not be completed because of {clean_text(message, 'an unknown reason')}.")
    if skipped == 1:
        log_yellow("One task still needs a real channel join and was skipped.")
    elif skipped:
        log_yellow(f"{skipped} tasks still need a real channel join and were skipped.")
    return claimed


async def run_streak(client):
    streak = await client.get("/streak")
    if streak.get("claimedToday"):
        log_green(f"Daily streak is already collected for {clean_text(streak.get('streak'), 0)} days in a row.")
        return 0
    try:
        result = await client.post("/streak/claim")
        reward = int(result.get("reward") or 0)
        log_green(f"Daily streak credited {clean_text(reward, 0)} WAVES on day {clean_text(result.get('streak'), 0)}.")
        return reward
    except ApiError as exc:
        reason = clean_text(exc, "an unknown reason")
        log_yellow(f"Streak claim was skipped because of {reason}.")
        link = clean_text(streak.get("bioLink"), "")
        if link and "bio" in reason.lower():
            log_yellow(f"The invite link that must be placed in the Telegram bio")
        return 0


async def process_account(init_data, proxy):
    init_data, user_id, username, start_param = parse_account(init_data)
    if not init_data or not user_id:
        log_red("A credential line in data.txt is not valid initData.")
        return
    referral = start_param.split("_", 1)[1] if start_param.startswith("ref_") else REF_CODE
    client = ThunderWaves(init_data, proxy)
    await client.open()
    try:
        await client.login(referral)
        user = client.user
        name = user.get("username") or user.get("first_name") or username or "player"
        log_green(f"Player {clean_text(name, 'player')} signed in with {user.get('balance')} WAVES.")
        before = int(user.get("balance") or 0)
        await run_streak(client)
        claimed = await run_tasks(client)
        if claimed:
            log_green(f"All available tasks completed for this account and {claimed} WAVES were claimed.")
        else:
            log_green("Every available account task was already completed.")
        earned, played = await run_games(client, ("easy", "normal", "hard"))
        if played:
            log_green(f"{played} game rounds were played and {earned} WAVES were collected.")
        else:
            log_green("Every game round for this account was already used today.")
        await client.me()
        after = int(client.user.get("balance") or 0)
        log_green(f"Account totals {after} WAVES with {max(0, after - before)} WAVES earned in this cycle.")
    except ApiError as exc:
        log_red(f"Account processing stopped because of {clean_text(exc, 'an unknown reason')}.")
    finally:
        await client.close()


async def main_async(accounts, proxies, sleep_secs):
    cycle = 1
    while True:
        log_yellow(f"Starting automation cycle number {cycle}")

        for idx, init_data in enumerate(accounts):
            if idx > 0:
                print()

            proxy_line = get_proxy(proxies, idx)
            proxy_url = normalize_proxy(proxy_line) if proxy_line else None
            if proxy_url:
                log_yellow(f"Using proxy {mask_proxy(proxy_url)}")

            await process_account(init_data, proxy_url)

        log_yellow(f"Automation cycle number {cycle} is complete and all accounts were processed")
        cycle += 1
        countdown(sleep_secs, "Next cycle starts in")
        show_banner(MY_PROJECT)


def main():
    show_banner(MY_PROJECT)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    config = load_config()
    sleep_secs = config.get("settings", {}).get("sleep_seconds", 3600)
    accounts = load_data()
    proxies = load_proxies()
    asyncio.run(main_async(accounts, proxies, sleep_secs))


if __name__ == "__main__":
    main()
