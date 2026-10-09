# NEARBY SHARE -- AirDrop style receive port for prompts sent from phones and other desktops.
# Runs as its own tiny server on SHARE_PORT. It can only say hello, take an offer and report
# that offer's status; it never touches the library or /api. Accepting happens on the
# loopback-only main app (see register_local_routes), so nothing lands without a click.
import ipaddress
import secrets
import socket
import threading
import time

from flask import Flask, jsonify, request

SHARE_PORT = 47800
OFFER_TTL = 180            # seconds an offer waits for Accept or Decline
MAX_BODY = 256 * 1024      # bytes per offer
MAX_PENDING = 20
RATE_WINDOW, RATE_MAX = 60, 10

share_app = Flask('prompt_library_share')
share_app.config['MAX_CONTENT_LENGTH'] = MAX_BODY

_lock = threading.Lock()
_offers = {}               # offer_id -> dict
_hits = {}                 # remote ip -> [timestamps]
_state = {'enabled': True, 'device_id': None, 'name': None}
_peers = {}                # ip -> {'deviceId', 'name', 'type', 'seen'}; devices that contacted us


def _remember(ip, device_id, name, kind):
    if not ip or not device_id or device_id == _state['device_id']:
        return
    with _lock:
        _peers[ip] = {'deviceId': _text(device_id, 80), 'name': _text(name, 60) or ip,
                      'type': _text(kind, 20) or 'phone', 'seen': time.time()}
        for old in [k for k, v in _peers.items() if time.time() - v['seen'] > 86400]:
            del _peers[old]


def _private(addr):
    try:
        ip = ipaddress.ip_address((addr or '').split('%')[0])
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def _expire():
    now = time.time()
    for oid, o in list(_offers.items()):
        if o['status'] == 'pending' and now - o['created'] > OFFER_TTL:
            o['status'] = 'expired'
        if now - o['created'] > OFFER_TTL * 4:
            del _offers[oid]


def _text(v, limit):
    return str(v or '').strip()[:limit]


def _list(v):
    if isinstance(v, str):
        v = v.split(',')
    if not isinstance(v, list):
        return []
    return [_text(x, 60) for x in v if _text(x, 60)][:20]


def _meta(v):
    # Keep only the variable type fields the app understands, with hard size limits
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    if not isinstance(v, dict):
        return {}
    out = {}
    for name, m in list(v.items())[:50]:
        if not isinstance(m, dict) or len(str(name)) > 120:
            continue
        opts = m.get('options')
        entry = {
            'type': _text(m.get('type'), 30) or 'text',
            'default': _text(m.get('default'), 500),
            'visible': m.get('visible') is not False,
            'options': [_text(o, 100) for o in opts[:50] if _text(o, 100)] if isinstance(opts, list) else [],
        }
        if m.get('multi'):
            entry['multi'] = True
        if m.get('wrap') in ('quotes', 'codefence', 'xml'):
            entry['wrap'] = m['wrap']
        if m.get('size') in ('short', 'medium', 'tall'):
            entry['size'] = m['size']
        out[str(name)] = entry
    return out


def configure(device_id, name, enabled=True):
    _state.update(device_id=device_id, name=name, enabled=bool(enabled))


@share_app.before_request
def _gate():
    if not _private(request.remote_addr):
        return jsonify({'error': 'Local network only'}), 403
    if not _state['enabled'] and request.path != '/share/hello':
        return jsonify({'error': 'This library is not receiving'}), 403
    return None


@share_app.after_request
def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@share_app.route('/share/hello', methods=['GET'])
def hello():
    a = request.args
    _remember(request.remote_addr, a.get('from'), a.get('name'), a.get('type'))
    return jsonify({
        'app': 'prompt-library', 'version': 1, 'type': 'desktop',
        'deviceId': _state['device_id'], 'name': _state['name'] or socket.gethostname(),
        'receiving': _state['enabled'],
    })


@share_app.route('/share/offer', methods=['POST'])
def offer():
    ip = request.remote_addr or ''
    now = time.time()
    data = request.get_json(silent=True) or {}
    p = data.get('prompt') or {}
    content = str(p.get('content') or '')
    if not content.strip():
        return jsonify({'error': 'Prompt text is required'}), 400
    with _lock:
        _expire()
        hits = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_MAX:
            return jsonify({'error': 'Too many requests, wait a minute'}), 429
        _hits[ip] = hits + [now]
        if sum(1 for o in _offers.values() if o['status'] == 'pending') >= MAX_PENDING:
            return jsonify({'error': 'Too many waiting offers'}), 429
        oid = secrets.token_urlsafe(12)
        _remember_later = (ip, data.get('fromId'), data.get('fromName'), data.get('fromType'))
        _offers[oid] = {
            'id': oid, 'status': 'pending', 'created': now, 'ip': ip,
            'fromId': _text(data.get('fromId'), 80),
            'fromName': _text(data.get('fromName'), 60) or 'A nearby device',
            'fromType': _text(data.get('fromType'), 20) or 'phone',
            'prompt': {
                'title': _text(p.get('title'), 200) or 'Untitled',
                'description': _text(p.get('description'), 2000),
                'content': content[:MAX_BODY],
                'categories': _list(p.get('categories')),
                'tags': _list(p.get('tags')),
                'variable_meta': _meta(p.get('variable_meta')),
            },
        }
    _remember(*_remember_later)
    return jsonify({'offerId': oid, 'status': 'pending', 'expiresIn': OFFER_TTL})


@share_app.route('/share/offer/<oid>', methods=['GET'])
def offer_status(oid):
    with _lock:
        _expire()
        o = _offers.get(oid)
    if not o:
        return jsonify({'status': 'expired'})
    return jsonify({'status': o['status']})


def pending():
    with _lock:
        _expire()
        return [{k: o[k] for k in ('id', 'fromName', 'fromType', 'prompt', 'created')}
                for o in sorted(_offers.values(), key=lambda o: o['created']) if o['status'] == 'pending']


def resolve(oid, accept):
    with _lock:
        _expire()
        o = _offers.get(oid)
        if not o or o['status'] != 'pending':
            return None
        o['status'] = 'accepted' if accept else 'declined'
        return o


# ---- sending: desktop to phone, desktop to desktop ----
import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('10.255.255.255', 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _lan_ips():
    # Windows often has WSL, Hyper-V, VPN or VirtualBox adapters; scan every private network, real WiFi first
    found = []
    for ip in [_lan_ip()] + _host_ips():
        try:
            a = ipaddress.ip_address(ip or '')
        except ValueError:
            continue
        if a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local and ip not in found:
            found.append(ip)
    return found


def _host_ips():
    out = []
    try:
        out += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:
        out += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return out


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(ip, path, body=None, timeout=4.0):
    if not _private(ip) or not ipaddress.ip_address(ip).version == 4:
        raise ValueError('Not a local address')
    url = f'http://{ip}:{SHARE_PORT}{path}'
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method='POST' if data else 'GET',
                                 headers={'Content-Type': 'application/json'})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(512 * 1024) or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(64 * 1024) or b'{}')
        except ValueError:
            return e.code, {}


def _hello_path():
    q = urllib.parse.urlencode({'from': _state['device_id'] or '', 'name': _state['name'] or '', 'type': 'desktop'})
    return '/share/hello?' + q


def probe(ip, timeout=0.8):
    try:
        code, d = _call(ip, _hello_path(), timeout=timeout)
        # phone builds up to 0.7.0 match the path exactly and 404 on the query string; retry plain
        if code == 404:
            code, d = _call(ip, '/share/hello', timeout=timeout)
    except Exception:
        return None
    if code == 200 and d.get('app') == 'prompt-library' and d.get('deviceId') != _state['device_id']:
        return {'ip': ip, 'name': d.get('name') or ip, 'type': d.get('type') or 'desktop',
                'receiving': d.get('receiving') is not False}
    return None


def scan():
    """Find other Prompt Libraries: devices that contacted us first, then every private /24 this machine is on."""
    mine = _lan_ips()
    nets = []
    for ip in mine:
        base = ip.rsplit('.', 1)[0]
        if base not in nets:
            nets.append(base)
    nets = nets[:4]
    with _lock:
        known = list(_peers.keys())
    targets = known + [f'{n}.{i}' for n in nets for i in range(1, 255)]
    targets = [t for i, t in enumerate(targets) if t not in mine and t not in targets[:i]]
    with ThreadPoolExecutor(max_workers=96) as pool:
        found = [d for d in pool.map(probe, targets) if d]
    unique = {}
    for d in found:
        unique.setdefault(d['ip'], d)
    return {'devices': sorted(unique.values(), key=lambda d: d['name'].lower()),
            'ip': mine[0] if mine else None, 'networks': [n + '.x' for n in nets]}


def send(ip, prompt):
    return _call(ip, '/share/offer', {
        'fromId': _state['device_id'], 'fromName': _state['name'] or socket.gethostname(),
        'fromType': 'desktop', 'prompt': prompt,
    }, timeout=5.0)


def sent_status(ip, oid):
    return _call(ip, '/share/offer/' + urllib.request.quote(oid, safe=''), timeout=4.0)


def serve_forever():
    try:
        _serve()
    except Exception:
        import logging, traceback
        logging.error('Nearby share could not start:\n' + traceback.format_exc())


def _serve():
    try:
        from waitress import serve
        serve(share_app, host='0.0.0.0', port=SHARE_PORT, threads=4, _quiet=True)
    except ImportError:
        share_app.run(host='0.0.0.0', port=SHARE_PORT, debug=False, use_reloader=False)
