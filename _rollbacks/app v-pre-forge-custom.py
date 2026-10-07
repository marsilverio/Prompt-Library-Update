from flask import Flask, request, jsonify, send_from_directory, Response, make_response
import sqlite3
import re
import hashlib
from datetime import datetime, timedelta
import json
import csv
import io
import zipfile
import sys
import os
import threading
import shutil
import vault_scanner

def _hash_key(k):
    return hashlib.sha256(k.strip().upper().encode()).hexdigest()

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
)

# PHONE SHARE -- LAN access for phone/tablet, off by default, token-gated
import secrets, socket, ipaddress
from flask import redirect

_phone = {'enabled': False, 'token': None}


def _is_loopback(addr):
    try:
        return ipaddress.ip_address((addr or '').split('%')[0]).is_loopback
    except ValueError:
        return False


def _is_private(addr):
    try:
        ip = ipaddress.ip_address((addr or '').split('%')[0])
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        return ip.is_private
    except ValueError:
        return False


def _lan_ip():
    # UDP connect sends no packets; it just picks the outbound interface
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


@app.before_request
def _phone_gate():
    if _is_loopback(request.remote_addr):
        return None
    if (not _phone['enabled'] or not _is_private(request.remote_addr)
            or request.path.startswith('/api/phone/')):
        return Response('Phone access is off. Enable it from Prompt Library on your computer.', 403)
    supplied = request.args.get('t') or request.cookies.get('plp_phone') or ''
    if not secrets.compare_digest(supplied, _phone['token'] or ''):
        return Response('Invalid or expired link. Scan the code again on your computer.', 403)
    if request.args.get('t') and request.method == 'GET':
        rest = '&'.join(f'{k}={v}' for k, v in request.args.items(multi=True) if k != 't')
        resp = redirect(request.path + ('?' + rest if rest else ''))
        resp.set_cookie('plp_phone', _phone['token'], httponly=True, samesite='Lax', max_age=86400 * 30)
        return resp
    return None


def _phone_payload():
    ip = _lan_ip()
    port = request.environ.get('SERVER_PORT', '5000')
    url = f"http://{ip}:{port}/?t={_phone['token']}" if (ip and _phone['enabled']) else None
    return {'enabled': _phone['enabled'], 'ip': ip, 'url': url}


@app.route('/api/phone/status', methods=['GET'])
def phone_status():
    return jsonify(_phone_payload())


@app.route('/api/phone/enable', methods=['POST'])
def phone_enable():
    _phone['enabled'] = True
    _phone['token'] = secrets.token_urlsafe(16)
    return jsonify(_phone_payload())


@app.route('/api/phone/disable', methods=['POST'])
def phone_disable():
    _phone['enabled'] = False
    _phone['token'] = None
    return jsonify(_phone_payload())



def get_data_dir():
    """
    Data lives in Documents/PromptLibrary — always.
    Both the frozen EXE and dev (start.bat) point here so they share the same DB.
    """
    path = os.path.join(os.path.expanduser('~'), 'Documents', 'PromptLibrary')
    os.makedirs(path, exist_ok=True)
    return path

def get_static_dir():
    """Locate the static folder whether running from source, PyInstaller, or py2app."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'static')
    if getattr(sys, 'frozen', False):
        return os.path.join(os.environ['RESOURCEPATH'], 'static')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

DATABASE   = os.path.join(get_data_dir(),   'PromptLibrary.db')
STATIC_DIR = get_static_dir()
def get_setting(key):
    """Read a single setting value from the DB. Returns None if not found."""
    conn = None
    try:
        conn = get_db()
        row  = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else None
    except Exception:
        return None
    finally:
        if conn:
            conn.close()

def set_setting(key, value):
    """Write a setting into the DB, creating or replacing as needed."""
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, value)
        )
        conn.commit()
    finally:
        conn.close()

def delete_setting(key):
    """Remove a setting from the DB."""
    conn = get_db()
    try:
        conn.execute('DELETE FROM settings WHERE key = ?', (key,))
        conn.commit()
    finally:
        conn.close()

# Keys are stored as SHA-256 hashes - never plaintext in the bundle.
# To add a new key: compute sha256(KEY.strip().upper()) and add the hex digest below.
_RAW_KEYS = [
    # Legacy/manual licence keys. Stored as hashes at runtime via _hash_key().
    '51c60ddec38f194c876a3cf92b0400c68374d8e130813357660b94b8960b1fb7',
    '03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4',
    '78426f6006c624ba7340f44f979cd07934227f30edce5b4be3b58ce938331a92',
    'cd60aa6161584e601f8d02ebd6b288c5635b3a4b6780c3eb6e3b54c22125035e',
    '2ee90cf3fb3ae94e79cfa3e89cdacdf765af3d5ee6c9c78ce412bcb304c0faa5',
    'b3eeb7cde34945a3b71e2877d587672c5c402d64862984397e2b788195bdc4d9',
]
# Sales licence keys — stored as SHA-256 hashes ONLY (plaintext lives in
# keys_PRIVATE.txt, uploaded to Payhip, and is NEVER shipped in the app).
# Generated 2026-05-23, batch of 15. To add more: generate keys, hash with
# sha256(KEY.strip().upper()), append the digests below, rebuild.
_SALES_KEY_HASHES = {
    # CAT739K
    '212645499f7c929859eaacd2cdffe9cb67b34f3b3d0136c45cdc41dc2f005f63',
    # PROMPTLIB-PRO-AND-001
    '9f728305141767db0715e209090e938ea7582aa5b0ecc25f8e392349124f980a',
    # Personal / manually-issued keys, hashed 2026-08-10.
    # Plaintext for these lives in keys_PRIVATE.txt only.
    'e32d32c75e8eb45147ec866ea074855dd8f593213f70a0cd48927aa320b978dd',
    'e25ee891aa9d3a211d48b6bb840aec6d2dd957f84431c12eabd5d3dc9a4fecd7',
    '5ec14ff5a2b5ec21e066ae8977929b1162cb51d4eab975bcdb10f61957e30755',
    'c1faad79e95d257ae64147a08aa50e2920be1d1ee68b7925891f2705a40e8ff1',
    '51fcb156ed442c84409c8e3a49d3d14d0ed810d8658483795e6e2b02ef21a1f2',
    '2f6b228714c1248e7ff870a7fbe05096dda1f20951c82d02f7f01ffe6581fd1d',
    '54422d25671d4a1de53645d4ae3e3757b1ce8f33bfe2037a05ae16f7752e8b3e',
    '0bee87191c9fe098a99f7585abf3d59cf64d2bb18e0970de2b55e2b1aabc0217',
    'f7aee97ce78c59a538d1d2a9a2c8a42bc583c4263ef837a0560748db91db38d8',
    '8931889167d1fc31010a1ec3e324d1c8ce19c990246300a6791d13f0bc5c9424',
    '454dcd7f58f263167a50f6470786fa2fbe587c1eb13bde35e67fa05928aef149',
    '435c554a2e9cd54d2d3431b8af2b5d7ba740c64f1dca92b7af8a76b05d484ef3',
    '5fa3d8e800a65f4f983f7f37230a4d6ac21ebc612fc378f2f74b419f0ef7edfd',
    '0ac37f478294f4f9a9997cea7cac877380a26626d0b64343d85732b18294ea5a',
    '88e1b911af2611f4d6c5a8975477fca4b87884886c5b0b4bb16c7a079b3a1dba',
    '23c3bebf31826568ef891d4c8f852b3875d2e5beff0ca44e02bd310c892c0923',
    '7e4e26183aacdb054b06f550fb2db860b40106ad27aa9d649e101d581f588b56',
    'd079e7e1ed0e0922106cc50fb80a27c68dcf83d7262a8ede9cd5ee976e1afced',
    '73ab66a033c267e00b7429bb256f6deb2734ebc4cd4ff5b564a8c9f9b2c8a719',
    'f77ebc83d4ee51886072e270fbdcac1df96aac78cdcd2ad96a833a9e9f599fe2',
    '517a877c6718e65c6b43bb591fe497767f9d38449a47b68269a9917ecb2ea268',
    # --- generated sales batches ---
    '5e6b749dab5356b2b46471251c2c60740179ac4135315eef8453b780fbf53f80',
    'f99096058489900dd13baae40d700948541aebb25832be529f003e482dd6fd7b',
    'd58635051ac42ad66955e35f2b5a4b8660df284ff0fc4888bb2d336af0fc75fe',
    '49d64316f06c7ec671ee17d6d07670b7e44c02735858f9fabff0dc8d28184818',
    '23f11b2f5b7ddafef2ac3d978bf29b56b48965451d81a30a027beeecff88f8af',
    'cc621dd35750de22e63b28bf1d05e15a7c6ae507b7d75e71f2af142c654a7264',
    '3ec3255c0477d7f1556376febc54f94e1c47cc8ab09d635e0b7e4d3b6752576a',
    '7cdf1d1b4c985cf2f5793f596306764ede5bcb92131d2d2c0bbec4247d364329',
    'f6e4f14e9eac458a9cd6e0d7e9022335f748c25d724193b0d369546cfdc21f41',
    'e64e15cab1cc037acbacea7ca030968a40c347e16728d7a4fed96550387ad6e8',
    '729aeb807cf6506aba26a52cace298db08bba613b1a0449da9e2cab84650bd19',
    'dc6661c998229b54464dfd2197b2325ff273f44fa50aa4b4bcea1cb96ec58078',
    '80b2912a6d6819a46d4ae8075fe98ee23ef10f9860fb2cf9bcdafdf8e114a579',
    'd9d8cb1d22b5f43cb86d01f90d9063dfb71dcb69f84fd100130d431fa516fb27',
    'bb41849ba5a0431064fef050f662d3374044697ba450d0644121cb7f5a933547',
    'ffbed790578c46ef269d27661056f0f57fe4f04c4d08ea237e69acc0ddcd1cf8',
    '96ceb3d3e3c2ed1255dd70646e425230779a26f8d535882c091dc1cd9285fb53',
    '7e2bc84af8df4a6165d280e90ce737ec27392c66fd2fdf0c414ce22126557afc',
    '8a77bfddabd2a45b86dba3888e2e1d3455d8ee5f887ca5f90d30fbea485d713b',
    '52f67341ab034d8c8f909d53f882177c09ca097348e262324ea0bfdd8bf53308',
    'c6ff822dbb7f534d2ddfa80097b3c1a2a9c31e7df112a1c210e915226584692c',
    '6d15e4be91fa7d625bb3f6d09c3c8bdbbd9075a55b34d02b1e04d8975aebc82c',
    'a68b9c5e6741d128fb6b80089cba21b99a4376282d207c587002844bb723216e',
    '285eda8eed12d9f731f9804fe7ff5f15dfccbbb859a30b143766e5ba6448d5bf',
    '36dfaa0a2799903bc9f91fed2423aa900eb74068201a01a93349dad1d1433c0d',
    
    '7343ef1e656002061bea2378b4d151ffb5f30dccd1ad610b64f2cfd330a73c30',
    'da3ffd327f7905eec3324c5ffbca8e47bf4275fcf98188deea3405dfb99c5007',
    '20e96efc3479030034e2a160256563b7d032379d2500dcf3e77786f66a4d4dae',
    'ec9de8e7519339f78fd2fff82b180cebce777ad609a9206fffeab8b8b20ded6b',
    '892f60bd4d79f9a31701c4f9fe97340535090b41ad8a374733d204d2e502a352',
    'ed9ad9b6be5a03054010fc89d8040e5c7c02bf7956e4d9449738d2e9d1748626',
    '39aa5aaae4db8b892579e1bd967ffea027c8b9ddd279f5c02aa100961f146779',
    '38ddf32753e6c7b045429205380fd36f33db550107e30ad227959f1c4743513b',
    '70c2605e3c7f8e6a000154e650887752edae09fd24f1a4a1aaea4fb442039751',
    '7374779088ca1b4371a0ac1d9053c95e5e3f66abe53fac300524fe809a7a1018',
    'd95bbe687e6f7aa19ab122fe75ddea419bc617e27db1c8bd0e88d3cec21cf415',
    '81ccc50a15cfa5ed8b0c8e0fffa5d8f3281a87e4e9d427913860160076cd8212',
    '7e139ee4db953181cbde0e588e1cf19c51062e99f89333f3ca0e43535f7fc67b',
    '0c6fbbcef3b01c617c2227ed89555177367ebf07f520da23596e3abf4c46553a',
    'c1eb3e94c7f8fa4c09a1dea3552b8169949da292fa2ba1d1172bde9d1da204c2',
    'e9c9307ad9a61ec632e9205f8dec0f98ee5834a34801cad971e4405b4151210a',
    '6dab58f3f2a5b72a9eeb3c941e5d20e0914326018beaab5873ffeca7f46c4f73',
    'b9d581b5952b14a355c0894ce283fda848bc1fb15918aea1d9405d109d57d59b',
    '555b4c29a29c45a15659672303e9adbeeb79da6266c97a7fb5457e6ee01d6dea',
    '029e2745760eff2d39ee8a377817a88c4cb4df0c84e53eacaf0c198974c6fe56',
    '46165759acd06e53f83dd1ec68b040cdf94694b5a5f4e37a2158884ba950251c',
    '7dfb9518a53d56e729b48f9d09a8480df997a6cfa8ebb092d19137b6a6cfc09f',
    'b279fef5a08ce22750c89b5c84ffaef45c6461a7bca1d02893c42f0fb799c0d7',
    '867db8eb336b6ef4e2c56b5e7251e64d29b09cd31c36ef1f7fbfeb21539d5ff4',
    '7370d659ecdc4d88de724c570a3a032adfb064105a482f677631ccf0f36cf33b',
    
    'b5dc6e2ef378f3545f8e7a47afd94066f8c3dae39a1af8803ef6d9467f15ae7e',
    'ae9c52e57e480a50ca1b8058160aa9612a56613809cd199e652c005c3a10dc68',
    '15fddf6bd24ca4e5b3d8e49d7397d0d93d6e214d371d8dee8b57083015987fed',
    'd046780c32342cc6b87e2f052b90b32a77be72d6bb907e1835f88ab32a556d2c',
    '9602b910f2c6371a9ac3cc6001107294e8bc2b17b12484c0063a9360837c46e6',
    '0d95e7854f564868958fa01623cc53f317ec82341c76855c375fd6b13f6f870b',
    '8db2ab26486668a411e930836108f61f6f08194e8337df1af60d4c505eb1c718',
    'ec4f7744908211813eec8bcb3bda4f2c42958ea0ef594e245df96a3e53d4558c',
    '92d508dcba8366ed3fe963a5585c75d71ab9e2244c96d3b0b7264e58c689bfcd',
    'fb6aa1c2ae981dc6bed26fbd4cc81d7163f8095f6227a5b87cabf3fb52c966b1',
    'a685d4bcddadf98dc10dcddf7ae46cb55c21e411c6c28eaf1ae7f9cd02673b8a',
    'cd5c39a07f0bdc5ad1b9904655c0239c088377790c16d75674fc68444bb4ba5c',
    '46311ed504ab2724f80b358e0df6dea945dabaf31c8885562f4b330e26779282',
    '5f38862c306912e4ddb24b6fb065f0abd33aa182ecbff28e5e018456b3b6ac36',
    '9c556c9aaad2c5a59773bfc32fb73e0ec16750f8b7c129981c964d94930c8023',
    '40a41da74e0902dc37a601262e3989e66d5d53cae4af082ac6793bc57ba797d6',
    '49168b0efbea40311d24123410b4e4241609b448ff035d95fd0904d2d3fc329d',
    '7724beced9cbb47b8f80e4e96cef4b68f128e8e291f69d02e5d7c1326a01cb3a',
    '28c16f33c0ad4593768affd26930b8907f2de17d5a75c1d29973f8036ed9af8b',
    'e10dbb7140e97f7c84f270c589aa82ec81c9c5b5a19ae9a599c9f72d7535de1c',
    'd38de53e481250974c758da4e2793abdcfa8d42a41500f0f5f9bfc22de69b331',
    '8f45dce515582c66654258471f2c345a58de30e5ce6095da4cea3e3518d5fb18',
    '54e0f558eccdec8d5ad1303327a37cc0cabaf46e41c98f51d869304ba65f75ae',
    'e109d8274535f996c4a57f32c18dffbd4e4480b06f868ceac34b403d2d16e32c',
    'a3762313c00a1e3f7e173059c62a3ede8ccd4c85ae42f1ac0f97c44f789a552c',
    
    '8ebcd3196f2fa5aaf25dc76997f3b792dc89af86e3915199c88ed13bd2c60a3f',
    '84f416d3291eba7725463ee45e9a7e7fa891738dcb77f5fb0f80c9fd5d8d425d',
    '9d75149c70db4971418d9939aeb45233e1d5ec912b5e9091c66b9151d9af581e',
    '379fbd3ec5c83f2bccd08decb818f6ec66fb4c9177621b067b70d86742b0c25f',
    '6489ec0dbaef05af30018f561e4d04cbc7966dcd2403073704a86d11cbe890a2',
    'bba2c895d2a0d6120216a889a66fd82795f35712339b0956474ccf88d9d46a26',
    '3a53fb7973c29f84bfe9db0b42fe3d8c984ad64b78a993c724fa01cc4c15a904',
    'd1c4d354e59a258998326362ace65394ae8e454fe0b5b3e111866d0c05b1e943',
    '61ab6ab5de421ef153c2711ea163c37d863b0c0b85136ab21508bed35fb61dc7',
    'e790a0814eabcd53c7db047d15de01aabdf0e52b357a50512c4e380c0a981cb3',
    '8f1e1c6c1d4f2141e6caa8a9b45f8600b41f98c0222c8ef68cba2f0a8b6a0ede',
    'd17eef8e24bf31b25dbb587b14c49e08b9dca897df626e4f1f9bf1578d8712c6',
    'b8626416c4bc43542a8cf03b5f3c5f4cf80a63b9072947dc6ab4632f167114c9',
    '09be924cf697c46815e3474b8c8bdb05b073cf5f93759cc296708932d1d50b3a',
    '4e3fa5a0b28d8ca456e4c577325e01644e4bc2ae52cb15fe4a197cc0798f1622',
    '68cb92942575fae87055ba57545c956a71d297e75852456176661d41c7eee510',
    'c970b929e84f8cc10caf83cc498fc761ae157243999019b4132c7b64ed100691',
    'b8ce7a2f00f442478be97c9aeaa70a14c16bffbb30a6911c4fc1df0bba2740f0',
    '12cd4ac91b85ea5c6eb9e7e21ddf85d5b7803bc0e02201a49b4a43ca48c0ec7d',
    'e761c1e4f39ca1d776fa4ec9cda6bda0ca824ff980e62877b565a6bea56e2b41',
    '3a6682ace2eb4b376e31cf14a3d1a3eaf12ad84b5655aea48347d97585a62999',
    'a31fe783545013395c88fe8bf424423101e7894df8ec833c20f20525031cac8c',
    '8e880ac6207ad89690d05961be3a1469f2461b474a9f4f763318cb79baa61647',
    'd29e5ac8fdc81580fe93c35db437a4d5804e58638704ef0804902a4d3a5dcff1',
    '6eab3667dc7dddc13c286a901c2f81e3b516b16d1a8dbc8ff2419fd08b23ba21',
    
     # Reward keys.
     # These are keys that you can give out during like competitions in Telegram.
     # They unlock some features but not all.
    
    'e580898d64a75cfb9ed7d83534f79a9078f833490feca1d05118c8cf4382f3b0',
    'cf96c024dce64b78551007125c991521ff5435dfd0e18ebae7f34cb943af2543',
    'c54e7310e544fc1da4a2abf127b101735b1da3f61f41582d230feb0fb1b1ab38',
    '5c5a7d82918616768dc0094d33daba6b01ea1b21673d595d3d9d70184c427870',
    '6f4c4e8e469026e188911bd31b849df1f2ce675fb722e7bbba79a09b892d9af8',
    'f9ff1f9e4bf42dd6f5c22b0ba4fbafa7a0a8a74548bd9196c7de141f18a669e1',
    'ad89d3b0811766a0cce3e8fc4f32d68d31ef152ba5b574d480aceda7a7fadd0c',
    '4529395fe46a7ff88dfce5b1c3463d6f6a252a96e77b00cde0b8141a87103ec1',
    'ed48db51aca526fc992b3b9722317e433537a060ba55b3dc80c5130a232653ce',
    'f75f29fc1637e4ce3737631b7bd7aea61182f5e4441775df6c4b2812939bedc1',
    'ad0f254a9c4e7b5961399770df125a9927219f7f8a74fb457c29256340b8ead0',
    'e3949853b212b7f8802b7d2f906dc914077fc76b87337a84adab6516b3650c0c',
    'edc1364ea17c53dfc4d3eb1a4e7f3b9e3db72c835de8328985a43e5637d669e3',
    '8792c32a6c2166a6d81023dcbe59c9260c4d71527ac3c484a75366340ef92a56',
    '510b0711b516908706e113e2c8901c9801cc958b15b9bdc11a655e242ea0b44f',
}
PREMIUM_KEYS = {_hash_key(k) for k in _RAW_KEYS} | _SALES_KEY_HASHES
del _RAW_KEYS  # Don't keep plaintext in memory after startup


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    # WAL mode avoids the rollback-journal + fcntl combination that caused a stale
    # -journal file to lock out all access after an unclean shutdown (2026-07-04).
    # busy_timeout gives concurrent access a retry window instead of an immediate
    # "database is locked" error.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()


    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS folders (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS prompts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT NOT NULL,
        description  TEXT,
        content      TEXT NOT NULL,
        categories   TEXT,
        tags         TEXT,
        folder_id    INTEGER,
        colour_label TEXT,
        rating       INTEGER DEFAULT 0,
        notes        TEXT,
        chain_ids    TEXT,
        variable_meta TEXT,
        chat_turns   TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used    TIMESTAMP,
        use_count    INTEGER DEFAULT 0,
        is_favorite  INTEGER DEFAULT 0,
        FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS vaults (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        path       TEXT NOT NULL UNIQUE,
        last_scan  TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Indexes for the prompts table — list view sorts by updated_at and filters
    # on these columns on every load. Without these the query planner falls
    # back to a full table scan plus a temp B-tree sort each time.
    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_updated_at   ON prompts(updated_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_folder_id   ON prompts(folder_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_is_favorite ON prompts(is_favorite)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_colour_label ON prompts(colour_label)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_rating      ON prompts(rating)')


    c.execute('''CREATE TABLE IF NOT EXISTS prompt_versions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_id  INTEGER NOT NULL,
        title      TEXT NOT NULL,
        content    TEXT NOT NULL,
        description TEXT,
        saved_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
    )''')

    # Handle existing DBs where prompt_versions was created with created_at instead of saved_at
    c.execute('PRAGMA table_info(prompt_versions)')
    ver_cols = {row[1] for row in c.fetchall()}
    if 'saved_at' not in ver_cols and 'created_at' in ver_cols:
        # Rename the table, recreate with correct column, copy data, drop old
        c.execute('ALTER TABLE prompt_versions RENAME TO prompt_versions_old')
        c.execute('''CREATE TABLE prompt_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id   INTEGER NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            description TEXT,
            saved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''INSERT INTO prompt_versions (id, prompt_id, title, content, description, saved_at)
                     SELECT id, prompt_id, title, content, NULL, created_at FROM prompt_versions_old''')
        c.execute('DROP TABLE prompt_versions_old')
    elif 'saved_at' not in ver_cols:
        c.execute('ALTER TABLE prompt_versions ADD COLUMN saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')

    c.execute('''CREATE TABLE IF NOT EXISTS variable_templates (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        description TEXT,
        variables   TEXT NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS usage_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_id  INTEGER NOT NULL,
        used_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
    )''')

    # Standalone chain workflows. Independent of prompts.
    c.execute('''CREATE TABLE IF NOT EXISTS chains (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        description  TEXT,
        nodes        TEXT NOT NULL DEFAULT '[]',
        layout       TEXT DEFAULT '{}',
        tags         TEXT,
        colour_label TEXT,
        is_favorite  INTEGER DEFAULT 0,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Curated prompt collections — pin prompts into named boards.
    c.execute('''CREATE TABLE IF NOT EXISTS boards (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        description  TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS board_pins (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        board_id   INTEGER NOT NULL,
        prompt_id  INTEGER NOT NULL,
        added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
        FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
        UNIQUE(board_id, prompt_id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_board_pins_board_id  ON board_pins(board_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_board_pins_prompt_id ON board_pins(prompt_id)')

    # ── boards column migrations ────────────────────────────────────────────
    c.execute('PRAGMA table_info(boards)')
    board_cols = {row[1] for row in c.fetchall()}
    if 'colour_label' not in board_cols:
        c.execute('ALTER TABLE boards ADD COLUMN colour_label TEXT')

    # Reusable meta-prompt blueprints. Prompts that generate prompts.
    c.execute('''CREATE TABLE IF NOT EXISTS meta_blueprints (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        description   TEXT,
        template      TEXT NOT NULL DEFAULT '',
        system        TEXT,
        variables     TEXT DEFAULT '[]',
        output_format TEXT DEFAULT 'text',
        tags          TEXT,
        is_favorite   INTEGER DEFAULT 0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # AI persona / role system prompts
    c.execute('''CREATE TABLE IF NOT EXISTS roles (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT NOT NULL,
        icon           TEXT DEFAULT '🎯',
        colour         TEXT DEFAULT '#6366f1',
        persona        TEXT NOT NULL DEFAULT '',
        tone           TEXT,
        expertise      TEXT,
        example_phrase TEXT,
        is_favorite    INTEGER DEFAULT 0,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')


    c.execute('PRAGMA table_info(prompts)')
    existing = {row[1] for row in c.fetchall()}

    migrations = [
        ('description',    'ALTER TABLE prompts ADD COLUMN description TEXT'),
        ('categories',     'ALTER TABLE prompts ADD COLUMN categories TEXT'),
        ('tags',           'ALTER TABLE prompts ADD COLUMN tags TEXT'),
        ('folder_id',      'ALTER TABLE prompts ADD COLUMN folder_id INTEGER'),
        ('use_count',      'ALTER TABLE prompts ADD COLUMN use_count INTEGER DEFAULT 0'),
        ('is_favorite',    'ALTER TABLE prompts ADD COLUMN is_favorite INTEGER DEFAULT 0'),
        ('last_used',      'ALTER TABLE prompts ADD COLUMN last_used TIMESTAMP'),
        ('colour_label',   'ALTER TABLE prompts ADD COLUMN colour_label TEXT'),
        ('rating',         'ALTER TABLE prompts ADD COLUMN rating INTEGER DEFAULT 0'),
        ('notes',          'ALTER TABLE prompts ADD COLUMN notes TEXT'),
        ('chain_ids',      'ALTER TABLE prompts ADD COLUMN chain_ids TEXT'),
        ('variable_meta',  'ALTER TABLE prompts ADD COLUMN variable_meta TEXT'),
        ('chat_turns',      'ALTER TABLE prompts ADD COLUMN chat_turns TEXT'),
        ('role_id',        'ALTER TABLE prompts ADD COLUMN role_id INTEGER'),
        ('status',                'ALTER TABLE prompts ADD COLUMN status TEXT DEFAULT \'active\''),
        ('parent_id',             'ALTER TABLE prompts ADD COLUMN parent_id INTEGER'),
        ('prompt_domain',         'ALTER TABLE prompts ADD COLUMN prompt_domain TEXT'),
        ('prompt_use_case',       'ALTER TABLE prompts ADD COLUMN prompt_use_case TEXT'),
        ('prompt_output_format',  'ALTER TABLE prompts ADD COLUMN prompt_output_format TEXT'),
        ('prompt_tone',           'ALTER TABLE prompts ADD COLUMN prompt_tone TEXT'),
        ('fork_root_id',          'ALTER TABLE prompts ADD COLUMN fork_root_id INTEGER'),
        ('fork_snapshot',         'ALTER TABLE prompts ADD COLUMN fork_snapshot TEXT'),
    ]

    # Knowledge base entries for roles (JSON array)
    c.execute('PRAGMA table_info(roles)')
    role_cols = {row[1] for row in c.fetchall()}
    if 'knowledge_base' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN knowledge_base TEXT DEFAULT '[]'")
    if 'skills' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN skills TEXT DEFAULT '[]'")
    if 'example_phrases' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN example_phrases TEXT DEFAULT '[]'")
    if 'audience' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN audience TEXT DEFAULT ''")
    if 'output_format' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN output_format TEXT DEFAULT ''")
    if 'constraints' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN constraints TEXT DEFAULT ''")
    if 'domain' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN domain TEXT DEFAULT ''")
    if 'tasks' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN tasks TEXT DEFAULT ''")
    if 'response_style' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN response_style TEXT DEFAULT ''")
    if 'goal' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN goal TEXT DEFAULT ''")
    if 'outcome' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN outcome TEXT DEFAULT ''")
    if 'opening_message' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN opening_message TEXT DEFAULT ''")
    if 'persistent_context' not in role_cols:
        c.execute("ALTER TABLE roles ADD COLUMN persistent_context TEXT DEFAULT ''")
    for col, sql in migrations:
        if col not in existing:
            c.execute(sql)

    c.execute('CREATE INDEX IF NOT EXISTS idx_prompts_fork_root_id ON prompts(fork_root_id)')

    # ── prompt_versions column migrations ───────────────────────────────────
    c.execute('PRAGMA table_info(prompt_versions)')
    pv_cols = {row[1] for row in c.fetchall()}
    pv_migrations = [
        ('version_label', 'ALTER TABLE prompt_versions ADD COLUMN version_label TEXT'),
        ('version_notes', 'ALTER TABLE prompt_versions ADD COLUMN version_notes TEXT'),
        ('is_baseline',   'ALTER TABLE prompt_versions ADD COLUMN is_baseline INTEGER DEFAULT 0'),
    ]
    for col, sql in pv_migrations:
        if col not in pv_cols:
            c.execute(sql)

    # ── Taxonomy tables ──────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS taxonomy_domains (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS taxonomy_use_cases (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_id INTEGER NOT NULL,
        name      TEXT NOT NULL,
        UNIQUE(domain_id, name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS prompt_taxonomy (
        prompt_id   INTEGER NOT NULL,
        use_case_id INTEGER NOT NULL,
        PRIMARY KEY (prompt_id, use_case_id),
        FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
        FOREIGN KEY (use_case_id) REFERENCES taxonomy_use_cases(id) ON DELETE CASCADE
    )''')

    # ── Prompt relationships table ───────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS prompt_relationships (
        prompt_a   INTEGER NOT NULL,
        prompt_b   INTEGER NOT NULL,
        rel_type   TEXT DEFAULT 'related',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (prompt_a, prompt_b)
    )''')

    # ── Component workspace tables ───────────────────────────────
    # User-authored blocks. Shipped blocks stay in static/components-data.js.
    c.execute('''CREATE TABLE IF NOT EXISTS component_blocks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        category    TEXT NOT NULL,
        body        TEXT NOT NULL,
        description TEXT DEFAULT '',
        source      TEXT NOT NULL DEFAULT 'user',
        forked_from TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # A saved canvas. prompt_id links to the plain prompt it emitted, if any.
    c.execute('''CREATE TABLE IF NOT EXISTS compositions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT NOT NULL,
        prompt_id  INTEGER,
        folder_id  INTEGER,
        tags       TEXT DEFAULT '',
        view_state TEXT NOT NULL DEFAULT '{}',
        is_draft   INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (prompt_id) REFERENCES prompts(id)  ON DELETE SET NULL,
        FOREIGN KEY (folder_id) REFERENCES folders(id)  ON DELETE SET NULL
    )''')

    # Blocks placed on a canvas. block_ref is TEXT so one column addresses both
    # shipped blocks (their JS id) and user blocks ('user:<component_blocks.id>').
    c.execute('''CREATE TABLE IF NOT EXISTS composition_blocks (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        composition_id INTEGER NOT NULL,
        block_ref      TEXT NOT NULL,
        position       INTEGER NOT NULL DEFAULT 0,
        x              REAL NOT NULL DEFAULT 0,
        y              REAL NOT NULL DEFAULT 0,
        z_index        INTEGER NOT NULL DEFAULT 0,
        collapsed      INTEGER NOT NULL DEFAULT 0,
        body_override  TEXT,
        FOREIGN KEY (composition_id) REFERENCES compositions(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_composition_blocks_cid
        ON composition_blocks (composition_id, position)''')

    c.execute('''CREATE TABLE IF NOT EXISTS composition_edges (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        composition_id   INTEGER NOT NULL,
        source_block_id  INTEGER NOT NULL,
        target_block_id  INTEGER NOT NULL,
        source_port      TEXT NOT NULL DEFAULT 'right',
        target_port      TEXT NOT NULL DEFAULT 'left',
        relation         TEXT NOT NULL DEFAULT 'sequence',
        FOREIGN KEY (composition_id) REFERENCES compositions(id) ON DELETE CASCADE,
        FOREIGN KEY (source_block_id) REFERENCES composition_blocks(id) ON DELETE CASCADE,
        FOREIGN KEY (target_block_id) REFERENCES composition_blocks(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_composition_edges_cid
        ON composition_edges (composition_id)''')

    # ── Seed taxonomy defaults (only if empty) ───────────────────────────────
    domain_count = c.execute('SELECT COUNT(*) FROM taxonomy_domains').fetchone()[0]
    if domain_count == 0:
        domains_and_cases = {
            'Marketing':   ['Email', 'Social Media', 'Copywriting', 'Campaign', 'SEO', 'Ads'],
            'Engineering': ['Code Review', 'Documentation', 'Debugging', 'Architecture', 'Testing'],
            'Operations':  ['Process', 'Planning', 'Analysis', 'Reporting', 'Training'],
            'Creative':    ['Writing', 'Brainstorming', 'Ideation', 'Storytelling', 'Design Briefs'],
            'Research':    ['Summarisation', 'Analysis', 'Comparison', 'Literature Review', 'Q&A'],
            'Sales':       ['Outreach', 'Follow-Up', 'Objection Handling', 'Proposal', 'Discovery'],
            'Personal':    ['Productivity', 'Learning', 'Reflection', 'Planning', 'Communication'],
        }
        for domain_name, use_cases in domains_and_cases.items():
            c.execute('INSERT OR IGNORE INTO taxonomy_domains (name) VALUES (?)', (domain_name,))
            row = c.execute('SELECT id FROM taxonomy_domains WHERE name=?', (domain_name,)).fetchone()
            domain_id = row[0]
            for uc in use_cases:
                c.execute('INSERT OR IGNORE INTO taxonomy_use_cases (domain_id, name) VALUES (?,?)',
                          (domain_id, uc))

    conn.commit()
    conn.close()

def _json_body():
    return request.get_json(silent=True) or {}

def _normalise_list(value):
    """Return a clean string list from DB strings, API arrays, or JSON strings."""
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith('['):
            try:
                parsed = json.loads(raw)
                items = parsed if isinstance(parsed, list) else raw.split(',')
            except (TypeError, ValueError):
                items = raw.split(',')
        else:
            items = raw.split(',')
    else:
        items = [value]

    cleaned = []
    seen = set()
    for item in items:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned

def _list_for_db(value):
    return ','.join(_normalise_list(value))

def _json_value(value, default):
    if value is None or value == '':
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return default
        if isinstance(default, list) and isinstance(parsed, list):
            return parsed
        if isinstance(default, dict) and isinstance(parsed, dict):
            return parsed
    return default

def _json_for_db(value, default):
    return json.dumps(_json_value(value, default))

def _int_between(value, low, high, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))

def _folder_id(value):
    if value in ('', None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _prompt_payload(data):
    rid = data.get('role_id')
    try:
        rid = int(rid) if rid not in (None, '', 'null') else None
    except (TypeError, ValueError):
        rid = None
    pid = data.get('parent_id')
    try:
        pid = int(pid) if pid not in (None, '', 'null') else None
    except (TypeError, ValueError):
        pid = None
    return {
        'title': (data.get('title') or 'Untitled').strip() or 'Untitled',
        'description': data.get('description') or '',
        'content': data.get('content') or '',
        'categories': _list_for_db(data.get('categories', '')),
        'tags': _list_for_db(data.get('tags', '')),
        'folder_id': _folder_id(data.get('folder_id')),
        'colour_label': data.get('colour_label') or '',
        'rating': _int_between(data.get('rating', 0), 0, 5),
        'notes': data.get('notes') or '',
        'chain_ids': _json_for_db(data.get('chain_ids', []), []),
        'variable_meta': _json_for_db(data.get('variable_meta', {}), {}),
        'chat_turns': _json_for_db(data.get('chat_turns', []), []),
        'role_id': rid,
        'status':               data.get('status') or 'active',
        'parent_id':            pid,
        'prompt_domain':        data.get('prompt_domain') or '',
        'prompt_use_case':      data.get('prompt_use_case') or '',
        'prompt_output_format': data.get('prompt_output_format') or '',
        'prompt_tone':          data.get('prompt_tone') or '',
    }

def detect_variables(content):
    """Detect [[var]], {{var}}, ((var)) patterns — preserves first-occurrence order."""
    if not content:
        return []
    seen = {}  # ordered dict behaviour in Python 3.7+
    for pattern in [r'\[\[(.+?)\]\]', r'\{\{(.+?)\}\}', r'\(\((.+?)\)\)']:
        for m in re.finditer(pattern, content):
            v = m.group(1).strip()
            if v and len(v) < 100 and v not in seen:
                seen[v] = True
    return list(seen.keys())


def serialize_prompt(row):
    p = dict(row)
    # 'variables' is deliberately NOT computed here. It's a pure function of
    # 'content', and detect_variables() was running 3 regex passes per row on
    # every call to this serializer, including the full-list /api/prompts load
    # that fires on every app launch. The frontend already has an identical
    # detectVariables() (static/app.js) used as a fallback wherever this field
    # is read, so the same content always re-derives the same result.
    p['description']   = p.get('description') or ''
    # Fall back to legacy 'category' column if 'categories' is empty
    p['categories']    = _normalise_list(p.get('categories') or p.get('category') or '')
    p['tags']          = _normalise_list(p.get('tags') or '')
    p['colour_label']  = p.get('colour_label') or ''
    p['rating']        = p.get('rating') or 0
    p['notes']         = p.get('notes') or ''
    p['chain_ids']     = _json_value(p.get('chain_ids'), [])
    p['variable_meta'] = _json_value(p.get('variable_meta'), {})
    p['chat_turns']    = _json_value(p.get('chat_turns'), [])
    p.setdefault('folder_id',           None)
    p.setdefault('is_favorite',         0)
    p.setdefault('use_count',           0)
    p.setdefault('role_id',             None)
    p.setdefault('status',              'active')
    p.setdefault('parent_id',           None)
    p.setdefault('prompt_domain',       '')
    p.setdefault('prompt_use_case',     '')
    p.setdefault('prompt_output_format','')
    p.setdefault('prompt_tone',         '')
    p.setdefault('fork_root_id',        None)
    p.setdefault('fork_snapshot',       None)
    return p


@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/static/<path:path>')
def send_static(path):
    response = send_from_directory(STATIC_DIR, path)
    # Prevent pywebview/WebView2 caching stale JS between restarts
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma']        = 'no-cache'
    response.headers['Expires']       = '0'
    return response


@app.route('/api/licence/validate', methods=['POST'])
def validate_licence():
    data = request.json or {}
    key  = _hash_key(data.get('key') or '')
    if key in PREMIUM_KEYS:
        return jsonify({'valid': True, 'message': 'Premium unlocked!'})
    return jsonify({'valid': False, 'message': 'Invalid licence key. Please try again.'}), 400

@app.route('/api/licence/check', methods=['POST'])
def check_licence():
    """Called on app load to re-verify a stored key is still valid."""
    data = request.json or {}
    key  = _hash_key(data.get('key') or '')
    return jsonify({'valid': key in PREMIUM_KEYS})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Return persisted settings, including the saved licence key."""
    licence = get_setting('licence')
    out = {'licence': licence} if licence else {}
    out['tour_done'] = bool(get_setting('tour_done'))
    return jsonify(out)

@app.route('/api/settings/licence', methods=['POST'])
def set_licence_setting():
    """Persist the validated licence key into prompts.db so it survives restarts."""
    data = request.json or {}
    key  = (data.get('key') or '').strip()
    if key:
        set_setting('licence', key)
    else:
        delete_setting('licence')
    return jsonify({'ok': True})

@app.route('/api/settings/tour', methods=['POST'])
def set_tour_setting():
    """Persist whether the onboarding tour has been seen. DB-backed because
    WebView localStorage can reset between launches (see ai-keys sync note)."""
    data = request.json or {}
    if data.get('done'):
        set_setting('tour_done', '1')
    else:
        delete_setting('tour_done')
    return jsonify({'ok': True})


@app.route('/api/folders', methods=['GET'])
def get_folders():
    conn = get_db()
    rows = conn.execute('SELECT * FROM folders ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/folders', methods=['POST'])
def create_folder():
    data = request.json
    conn = get_db()
    cur  = conn.execute('INSERT INTO folders (name) VALUES (?)', (data['name'],))
    fid  = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'id': fid, 'name': data['name']})

@app.route('/api/folders/<int:fid>', methods=['PUT'])
def update_folder(fid):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE folders SET name=? WHERE id=?', (data['name'], fid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/folders/<int:fid>', methods=['DELETE'])
def delete_folder(fid):
    conn = get_db()
    conn.execute('UPDATE prompts SET folder_id=NULL WHERE folder_id=?', (fid,))
    conn.execute('DELETE FROM folders WHERE id=?', (fid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Vaults -- Obsidian-style file-backed prompt folders, alongside PromptLibrary.db
# See docs/superpowers/specs/2026-09-14-vault-system-design.md
# ---------------------------------------------------------------------------

def get_vault_index_conn(vault_path):
    """Open (creating if needed) the .promptvault/index.db cache for a vault folder."""
    index_dir = os.path.join(vault_path, '.promptvault')
    os.makedirs(index_dir, exist_ok=True)
    index_db_path = os.path.join(index_dir, 'index.db')
    conn = sqlite3.connect(index_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL lets concurrent reads/writes from waitress's thread pool coexist --
    # the default rollback-journal mode serialises every writer and was
    # producing "database is locked" under normal multi-request use.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS prompts (
        relative_path   TEXT PRIMARY KEY,
        title           TEXT,
        category        TEXT,
        subcategory     TEXT,
        tags            TEXT,
        difficulty      TEXT,
        target_audience TEXT,
        inputs          TEXT,
        expected_output TEXT,
        related_prompts TEXT,
        version         TEXT,
        last_updated    TEXT,
        body            TEXT,
        parse_error     TEXT,
        scanned_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        description     TEXT
    )''')
    try:
        # Cache is disposable and pre-dates the description column on any
        # vault connected before this field existed -- add it in place
        # rather than forcing a full rebuild.
        conn.execute('ALTER TABLE prompts ADD COLUMN description TEXT')
    except sqlite3.OperationalError:
        pass  # already has it
    conn.commit()
    return conn


def _scalar(value):
    """Front matter values can come back as a list (e.g. 'category: [a, b]'
    flow-style YAML) for any key, not just tags/related_prompts -- SQLite
    can't bind a list, so collapse one to a comma-joined string here."""
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return value


def _as_list(value):
    """Normalise a tags/related_prompts front matter value to a list: pass
    a list through, wrap a non-empty scalar as a single-item list, drop
    anything else -- a bare 'tags: foo' (no brackets) used to be silently
    discarded here instead of kept as one tag."""
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def rescan_vault_index(vault_path):
    """Walk vault_path, upsert every .md file into .promptvault/index.db,
    drop rows for files no longer on disk. Returns count of files indexed
    (including unparseable ones, which are kept with parse_error set)."""
    results = vault_scanner.scan_vault(vault_path)
    # vault_scanner returns OS-native relative paths (backslashes on Windows) --
    # normalise to forward slashes so folder-path comparisons (browsing,
    # create/delete folder) are consistent regardless of platform.
    for r in results:
        r['relative_path'] = r['relative_path'].replace(os.sep, '/')
    conn = get_vault_index_conn(vault_path)
    try:
        on_disk = {r['relative_path'] for r in results}
        existing = {row['relative_path'] for row in conn.execute('SELECT relative_path FROM prompts')}
        for stale in existing - on_disk:
            conn.execute('DELETE FROM prompts WHERE relative_path = ?', (stale,))
        for r in results:
            m = r['metadata']
            conn.execute('''INSERT INTO prompts
                (relative_path, title, category, subcategory, tags, difficulty,
                 target_audience, inputs, expected_output, related_prompts,
                 version, last_updated, body, parse_error, scanned_at, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(relative_path) DO UPDATE SET
                    title=excluded.title, category=excluded.category,
                    subcategory=excluded.subcategory, tags=excluded.tags,
                    difficulty=excluded.difficulty,
                    target_audience=excluded.target_audience,
                    inputs=excluded.inputs, expected_output=excluded.expected_output,
                    related_prompts=excluded.related_prompts, version=excluded.version,
                    last_updated=excluded.last_updated, body=excluded.body,
                    parse_error=excluded.parse_error, scanned_at=excluded.scanned_at,
                    description=excluded.description''',
                (r['relative_path'], _scalar(m.get('title')), _scalar(m.get('category')),
                 _scalar(m.get('subcategory')),
                 json.dumps(_as_list(m.get('tags'))),
                 _scalar(m.get('difficulty')), _scalar(m.get('target_audience')), _scalar(m.get('inputs')),
                 _scalar(m.get('expected_output')),
                 json.dumps(_as_list(m.get('related_prompts'))),
                 _scalar(m.get('version')), _scalar(m.get('last_updated')), r['body'], r['error'], _scalar(m.get('description'))))
        conn.commit()
    finally:
        conn.close()
    return len(results)


def _get_vault_or_404(vault_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM vaults WHERE id = ?', (vault_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _resolve_vault_subpath(vault_path, rel_path):
    """Resolve a user-supplied relative path under vault_path, guarding
    against path traversal (e.g. '../../whatever'). Returns the absolute
    path, or None if it would escape the vault folder."""
    rel_path = (rel_path or '').strip().strip('/\\')
    full = os.path.normpath(os.path.join(vault_path, rel_path))
    vault_abs = os.path.normpath(vault_path)
    if full != vault_abs and not full.startswith(vault_abs + os.sep):
        return None
    return full


@app.route('/api/vaults', methods=['GET'])
def get_vaults():
    conn = get_db()
    rows = conn.execute('SELECT * FROM vaults ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitize_folder_name(name):
    cleaned = _INVALID_FOLDER_CHARS.sub('-', name).strip().rstrip('. ')
    return cleaned or 'Vault'


@app.route('/api/vaults', methods=['POST'])
def create_vault():
    data = request.json
    name = (data.get('name') or '').strip()
    create_new = bool(data.get('create_new'))
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if create_new:
        parent_path = (data.get('parent_path') or '').strip()
        if not parent_path:
            return jsonify({'error': 'parent_path is required'}), 400
        if not os.path.isdir(parent_path):
            return jsonify({'error': f'Folder not found: {parent_path}'}), 400
        folder_name = _sanitize_folder_name(name)
        path = os.path.join(parent_path, folder_name)
        if os.path.exists(path):
            return jsonify({'error': f'"{folder_name}" already exists there'}), 400
        try:
            os.makedirs(path)
        except OSError as e:
            return jsonify({'error': f'Could not create folder: {e}'}), 400
    else:
        path = (data.get('path') or '').strip()
        if not path:
            return jsonify({'error': 'path is required'}), 400
        if not os.path.isdir(path):
            return jsonify({'error': f'Folder not found: {path}'}), 400
    conn = get_db()
    try:
        cur = conn.execute('INSERT INTO vaults (name, path) VALUES (?, ?)', (name, path))
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'That folder is already a connected local library'}), 400
    vault_id = cur.lastrowid
    conn.commit()
    conn.close()
    rescan_vault_index(path)
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'id': vault_id, 'name': name, 'path': path})


@app.route('/api/vaults/<int:vault_id>', methods=['DELETE'])
def delete_vault(vault_id):
    # Forgets the vault connection only -- never touches the folder on disk.
    conn = get_db()
    conn.execute('DELETE FROM vaults WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/vaults/<int:vault_id>/rescan', methods=['POST'])
def rescan_vault(vault_id):
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    count = rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'count': count})


@app.route('/api/vaults/<int:vault_id>/folders', methods=['GET'])
def get_vault_folders(vault_id):
    """Immediate subdirectories at a given relative path -- a real directory
    listing, not derived from the index, so empty folders show too."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    rel_path = request.args.get('path', '')
    full = _resolve_vault_subpath(vault['path'], rel_path)
    if full is None or not os.path.isdir(full):
        return jsonify({'error': 'Folder not found'}), 404
    rel_path = rel_path.strip('/\\')
    subfolders = []
    for entry in sorted(os.listdir(full), key=str.lower):
        if entry.startswith('.'):
            continue
        entry_full = os.path.join(full, entry)
        if os.path.isdir(entry_full):
            subfolders.append({
                'name': entry,
                'path': (rel_path + '/' + entry) if rel_path else entry,
            })
    return jsonify(subfolders)


@app.route('/api/vaults/<int:vault_id>/folders', methods=['POST'])
def create_vault_folder(vault_id):
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    data = request.json or {}
    parent = (data.get('path') or '').strip()
    name = _sanitize_folder_name((data.get('name') or '').strip())
    rel = f"{parent}/{name}" if parent else name
    full = _resolve_vault_subpath(vault['path'], rel)
    if full is None:
        return jsonify({'error': 'Invalid folder path'}), 400
    if os.path.exists(full):
        return jsonify({'error': f'"{name}" already exists there'}), 400
    try:
        os.makedirs(full)
    except OSError as e:
        return jsonify({'error': f'Could not create folder: {e}'}), 400
    return jsonify({'success': True, 'path': rel.replace(os.sep, '/')})


@app.route('/api/vaults/<int:vault_id>/folders', methods=['DELETE'])
def delete_vault_folder(vault_id):
    """Deletes a real folder on disk inside the vault. Destructive --
    resolved path is checked to stay inside the vault folder before
    shutil.rmtree ever runs, and the vault root itself can't be targeted."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    data = request.json or {}
    rel = (data.get('path') or '').strip()
    if not rel:
        return jsonify({'error': 'path is required'}), 400
    full = _resolve_vault_subpath(vault['path'], rel)
    vault_abs = os.path.normpath(vault['path'])
    if full is None or full == vault_abs:
        return jsonify({'error': 'Cannot delete the local library root'}), 400
    if not os.path.isdir(full):
        return jsonify({'error': 'Folder not found'}), 404
    try:
        shutil.rmtree(full)
    except OSError as e:
        return jsonify({'error': f'Could not delete folder: {e}'}), 400
    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/vaults/<int:vault_id>/prompts', methods=['GET'])
def get_vault_prompts(vault_id):
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    folder_path = request.args.get('path', '').strip('/\\')
    conn = get_vault_index_conn(vault['path'])
    rows = conn.execute('SELECT rowid, * FROM prompts ORDER BY title').fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        rel = d['relative_path'] or ''
        dirname = rel.rsplit('/', 1)[0] if '/' in rel else ''
        if dirname != folder_path:
            continue
        d['tags'] = json.loads(d['tags']) if d['tags'] else []
        d['related_prompts'] = json.loads(d['related_prompts']) if d['related_prompts'] else []
        # Normalise onto the same shape /api/prompts returns, so the
        # existing renderPromptCard() / getFilteredPrompts() work unchanged
        # for vault-sourced prompts. `id` must be a real int, not the
        # relative_path string -- renderPromptCard() embeds it unquoted
        # into onclick="...(${p.id})", so a string with dots/dashes in it
        # (any real filename) would produce invalid JS. SQLite's implicit
        # rowid is stable across UPDATEs (our upsert never deletes+reinserts
        # an unchanged row), so it works here even though `relative_path`
        # is the real primary key. Vault prompts have no DB-only actions
        # (favourite, rating, edit, delete) wired up in v1, so this id only
        # needs to be a safe, stable-enough number to embed, not a key
        # anything else looks up by.
        d['id'] = d['rowid']
        d['content'] = d.get('body') or ''
        d['description'] = d.get('description') or ''
        d['categories'] = [d['category']] if d.get('category') else []
        d['folder_id'] = None
        d['is_favorite'] = 0
        d['rating'] = 0
        d['colour_label'] = ''
        d['use_count'] = 0
        d['updated_at'] = d.get('scanned_at')
        d['created_at'] = d.get('scanned_at')
        out.append(d)
    return jsonify(out)


def _slugify_filename(title):
    """Turn a prompt title into a safe filename stem: 'My Prompt!' -> 'My-Prompt'."""
    stem = re.sub(r'[^\w\s-]', '', title or '').strip()
    stem = re.sub(r'\s+', '-', stem)
    return stem or 'Untitled'


def _prompt_to_markdown(prompt_row):
    """Serialise a PromptLibrary.db prompt row (dict) into vault front
    matter + body, matching the existing export convention. categories/tags
    are stored comma-joined (see _list_for_db), not JSON -- reuse
    _normalise_list rather than json.loads."""
    categories = _normalise_list(prompt_row.get('categories') or prompt_row.get('category') or '')
    tags = _normalise_list(prompt_row.get('tags') or '')
    lines = [
        '---',
        f"title: {prompt_row['title']}",
        f"category: {categories[0] if categories else ''}",
        f"tags: [{', '.join(tags)}]",
        "version: 1",
        f"last_updated: {datetime.now().strftime('%Y-%m-%d')}",
        '---',
        '',
        prompt_row.get('content') or '',
    ]
    return '\n'.join(lines)


@app.route('/api/library/export-to-vault', methods=['POST'])
def export_to_vault():
    data = request.json
    prompt_ids = data.get('prompt_ids') or []
    vault_id = data.get('vault_id')
    remove_originals = bool(data.get('remove_originals'))
    if not prompt_ids or not vault_id:
        return jsonify({'error': 'prompt_ids and vault_id are required'}), 400
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404

    conn = get_db()
    placeholders = ','.join('?' for _ in prompt_ids)
    rows = conn.execute(f'SELECT * FROM prompts WHERE id IN ({placeholders})', prompt_ids).fetchall()
    exported = []
    for row in rows:
        prompt = dict(row)
        filename = f"EXP-{_slugify_filename(prompt['title'])}-v1.md"
        full_path = os.path.join(vault['path'], filename)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(_prompt_to_markdown(prompt))
        exported.append(filename)
        if remove_originals:
            conn.execute('DELETE FROM prompts WHERE id = ?', (prompt['id'],))
    conn.commit()
    conn.close()
    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'exported': exported})


@app.route('/api/vaults/<int:vault_id>/prompts', methods=['POST'])
def create_vault_prompt(vault_id):
    """Write a brand-new prompt as a real .md file into the vault, at the
    currently-browsed folder, instead of into PromptLibrary.db. Vaults have
    no DB row for a prompt -- the file itself is the source of truth."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    data = request.json or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'title is required'}), 400
    folder_rel = (data.get('path') or '').strip()
    folder_full = _resolve_vault_subpath(vault['path'], folder_rel)
    if folder_full is None or not os.path.isdir(folder_full):
        return jsonify({'error': 'Folder not found'}), 400

    stem = _slugify_filename(title)
    filename = f"NEW-{stem}-v1.md"
    full_path = os.path.join(folder_full, filename)
    counter = 2
    while os.path.exists(full_path):
        filename = f"NEW-{stem}-v{counter}.md"
        full_path = os.path.join(folder_full, filename)
        counter += 1

    markdown = _prompt_to_markdown({
        'title': title,
        'categories': data.get('categories', ''),
        'tags': data.get('tags', ''),
        'content': data.get('content', ''),
    })
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(markdown)

    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    rel_path = os.path.relpath(full_path, vault['path']).replace(os.sep, '/')
    return jsonify({'success': True, 'relative_path': rel_path, 'filename': filename})


@app.route('/api/vaults/<int:vault_id>/template', methods=['POST'])
def create_vault_template(vault_id):
    """Writes a blank [[Title]]/[[Description]]/[[Prompt]]/[[Categories]]/
    [[Tags]] file into the current folder, for anyone who'd rather write a
    prompt by hand in a text editor than through the app's modal -- no YAML,
    just plain section markers. Picked up like any other file on the next
    rescan."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    data = request.json or {}
    folder_rel = (data.get('path') or '').strip()
    folder_full = _resolve_vault_subpath(vault['path'], folder_rel)
    if folder_full is None or not os.path.isdir(folder_full):
        return jsonify({'error': 'Folder not found'}), 400

    filename = 'Template-v1.md'
    full_path = os.path.join(folder_full, filename)
    counter = 2
    while os.path.exists(full_path):
        filename = f'Template-v{counter}.md'
        full_path = os.path.join(folder_full, filename)
        counter += 1

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(vault_scanner._simple_tag_template())

    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    rel_path = os.path.relpath(full_path, vault['path']).replace(os.sep, '/')
    return jsonify({'success': True, 'relative_path': rel_path, 'filename': filename})


def _retitle_vault_filename(old_filename, new_title):
    """New filename for a retitled vault prompt: slug of the new title,
    keeping the old file's -vN version suffix (defaulting to v1) so a
    rename in the app doesn't churn the version number."""
    stem = _slugify_filename(new_title)
    m = re.search(r'-v(\d+)\.md$', old_filename, re.IGNORECASE)
    version = m.group(1) if m else '1'
    return f"{stem}-v{version}.md"


@app.route('/api/vaults/<int:vault_id>/prompts/<path:relative_path>', methods=['PUT'])
def update_vault_prompt(vault_id, relative_path):
    """Rewrite a vault prompt's file in place. Obsidian-style: the title is
    the filename, so retitling renames the file on disk (version suffix and
    folder are kept)."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    full_path = _resolve_vault_subpath(vault['path'], relative_path)
    if full_path is None or not os.path.isfile(full_path):
        return jsonify({'error': 'Prompt file not found'}), 404
    data = request.json or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'title is required'}), 400

    markdown = _prompt_to_markdown({
        'title': title,
        'categories': data.get('categories', ''),
        'tags': data.get('tags', ''),
        'content': data.get('content', ''),
    })

    dirpath = os.path.dirname(full_path)
    old_filename = os.path.basename(full_path)
    new_filename = _retitle_vault_filename(old_filename, title)
    new_full_path = os.path.join(dirpath, new_filename)
    if new_filename != old_filename:
        counter = 2
        stem = new_filename[:-len('.md')]
        while os.path.exists(new_full_path) and os.path.normcase(new_full_path) != os.path.normcase(full_path):
            new_full_path = os.path.join(dirpath, f"{stem}-{counter}.md")
            counter += 1

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(markdown)
    if os.path.normcase(new_full_path) != os.path.normcase(full_path):
        os.replace(full_path, new_full_path)
        full_path = new_full_path

    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    rel_path = os.path.relpath(full_path, vault['path']).replace(os.sep, '/')
    return jsonify({'success': True, 'relative_path': rel_path})


@app.route('/api/vaults/<int:vault_id>/prompts/<path:relative_path>', methods=['DELETE'])
def delete_vault_prompt(vault_id, relative_path):
    """Deletes the prompt's .md file on disk -- vaults have no DB row, the
    file itself is the source of truth, so this is the only way to remove one."""
    vault = _get_vault_or_404(vault_id)
    if not vault:
        return jsonify({'error': 'Local library not found'}), 404
    if not os.path.isdir(vault['path']):
        return jsonify({'error': f"Local library folder not found: {vault['path']}", 'not_found': True}), 404
    full_path = _resolve_vault_subpath(vault['path'], relative_path)
    if full_path is None or not os.path.isfile(full_path):
        return jsonify({'error': 'Prompt file not found'}), 404
    try:
        os.remove(full_path)
    except OSError as e:
        return jsonify({'error': f'Could not delete file: {e}'}), 400
    rescan_vault_index(vault['path'])
    conn = get_db()
    conn.execute('UPDATE vaults SET last_scan = CURRENT_TIMESTAMP WHERE id = ?', (vault_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


def _cats(data):
    return _list_for_db(data.get('categories', ''))

def _tags(data):
    return _list_for_db(data.get('tags', ''))

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    conn   = get_db()
    search = request.args.get('search', '')
    fid    = request.args.get('folder_id', '')
    favs   = request.args.get('favorites', '0')
    colour = request.args.get('colour_label', '')
    rating = request.args.get('min_rating', '')

    q, params = 'SELECT * FROM prompts WHERE 1=1', []

    if search:
        q += ' AND (title LIKE ? OR content LIKE ? OR description LIKE ? OR tags LIKE ?)'
        params.extend([f'%{search}%'] * 4)
    if fid:
        q += ' AND folder_id=?'; params.append(int(fid))
    if favs == '1':
        q += ' AND is_favorite=1'
    if colour:
        q += ' AND colour_label=?'; params.append(colour)
    if rating:
        q += ' AND rating>=?'; params.append(int(rating))

    q += ' ORDER BY updated_at DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([serialize_prompt(r) for r in rows])

@app.route('/api/prompts/filters', methods=['GET'])
def get_filter_options():
    conn = get_db()
    rows = conn.execute('SELECT categories, tags FROM prompts').fetchall()
    # Also try legacy category column
    try:
        cat_rows = conn.execute('SELECT category FROM prompts').fetchall()
    except Exception:
        cat_rows = []
    conn.close()
    # Frontend expects [{value, count}] shape so the sidebar can show counts.
    cat_counts, tag_counts = {}, {}
    for r in rows:
        for c in _normalise_list(r['categories']):
            cat_counts[c] = cat_counts.get(c, 0) + 1
        for t in _normalise_list(r['tags']):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    for r in cat_rows:
        for c in _normalise_list(r[0]):
            cat_counts[c] = cat_counts.get(c, 0) + 1
    return jsonify({
        'categories': [{'value': c, 'count': n}
                       for c, n in sorted(cat_counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        'tags':       [{'value': t, 'count': n}
                       for t, n in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))],
    })

@app.route('/api/prompts/<int:pid>', methods=['GET'])
def get_prompt(pid):
    conn = get_db()
    row  = conn.execute('SELECT * FROM prompts WHERE id=?', (pid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(serialize_prompt(row))

def _insert_prompt(conn, data):
    cur = conn.execute('''
            INSERT INTO prompts
                (title, description, content, categories, tags, folder_id,
                 colour_label, rating, notes, chain_ids, variable_meta, chat_turns, role_id,
                 status, parent_id, prompt_domain, prompt_use_case, prompt_output_format, prompt_tone)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            data['title'], data['description'], data['content'],
            data['categories'], data['tags'], data['folder_id'],
            data['colour_label'], data['rating'], data['notes'],
            data['chain_ids'], data['variable_meta'], data['chat_turns'],
            data['role_id'],
            data['status'], data['parent_id'],
            data['prompt_domain'], data['prompt_use_case'],
            data['prompt_output_format'], data['prompt_tone'],
        ))
    return cur.lastrowid

@app.route('/api/prompts', methods=['POST'])
def create_prompt():
    data = _prompt_payload(_json_body())
    if not data['content'].strip():
        return jsonify({'error': 'Prompt content is required'}), 400
    conn = get_db()
    try:
        pid = _insert_prompt(conn, data)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': pid})


# NEARBY SHARE -- local-only inbox for offers taken by share_server.py on port 47800
import uuid
import share_server


def share_boot():
    did = get_setting('device_id')
    if not did:
        did = uuid.uuid4().hex
        set_setting('device_id', did)
    name = get_setting('device_name') or socket.gethostname() or 'Desktop'
    receiving = (get_setting('share_receiving') or '1') == '1'
    share_server.configure(did, name, receiving)


def _share_local_only():
    if not _is_loopback(request.remote_addr):
        return jsonify({'error': 'Only available on this computer'}), 403
    return None


@app.route('/api/share/inbox', methods=['GET'])
def share_inbox():
    return _share_local_only() or jsonify({
        'offers': share_server.pending(),
        'receiving': share_server._state['enabled'],
        'name': share_server._state['name'],
        'port': share_server.SHARE_PORT,
    })


@app.route('/api/share/inbox/<oid>', methods=['POST'])
def share_resolve(oid):
    denied = _share_local_only()
    if denied:
        return denied
    accept = bool(_json_body().get('accept'))
    offer = share_server.resolve(oid, accept)
    if not offer:
        return jsonify({'error': 'That offer has expired'}), 410
    if not accept:
        return jsonify({'ok': True})
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM folders WHERE name = 'Received'").fetchone()
        fid = row['id'] if row else conn.execute("INSERT INTO folders (name) VALUES ('Received')").lastrowid
        p = offer['prompt']
        data = _prompt_payload({**p, 'folder_id': fid, 'notes': f"Received from {offer['fromName']}"})
        pid = _insert_prompt(conn, data)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'id': pid, 'folder_id': fid})


@app.route('/api/share/devices', methods=['GET'])
def share_devices():
    denied = _share_local_only()
    if denied:
        return denied
    ip = (request.args.get('ip') or '').strip()
    if ip:
        if not share_server._private(ip):
            return jsonify({'devices': [], 'error': 'Use the address shown on the phone, like 192.168.1.23'})
        d = share_server.probe(ip, timeout=2.5)
        return jsonify({'devices': [d] if d else [], 'error': None if d else 'Nothing answered at ' + ip + '. Keep Prompt Library open on that device.'})
    return jsonify(share_server.scan())


@app.route('/api/share/send', methods=['POST'])
def share_send():
    denied = _share_local_only()
    if denied:
        return denied
    body = _json_body()
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM prompts WHERE id = ?', (body.get('prompt_id'),)).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({'error': 'Prompt not found'}), 404
    p = serialize_prompt(row)
    try:
        code, d = share_server.send(str(body.get('ip') or ''), {
            'title': p['title'], 'description': p['description'], 'content': p['content'],
            'categories': p['categories'], 'tags': p['tags'],
        })
    except Exception:
        return jsonify({'error': 'Could not reach that device'}), 502
    return jsonify(d), code


@app.route('/api/share/send/<ip>/<oid>', methods=['GET'])
def share_send_status(ip, oid):
    denied = _share_local_only()
    if denied:
        return denied
    try:
        code, d = share_server.sent_status(ip, oid)
    except Exception:
        return jsonify({'status': 'unreachable'})
    return jsonify(d), code


@app.route('/api/share/settings', methods=['POST'])
def share_settings():
    denied = _share_local_only()
    if denied:
        return denied
    body = _json_body()
    if 'receiving' in body:
        set_setting('share_receiving', '1' if body.get('receiving') else '0')
    if (body.get('name') or '').strip():
        set_setting('device_name', body['name'].strip()[:60])
    share_boot()
    return jsonify({'receiving': share_server._state['enabled'], 'name': share_server._state['name']})

@app.route('/api/prompts/<int:pid>', methods=['PUT'])
def update_prompt(pid):
    if pid in _locked_prompt_ids():
        return jsonify({'error': 'This prompt is locked. Unlock it in Version Lock before editing.'}), 423
    data = _prompt_payload(_json_body())
    if not data['content'].strip():
        return jsonify({'error': 'Prompt content is required'}), 400
    conn = get_db()
    try:

        # Save version snapshot before overwriting
        old = conn.execute('SELECT title, content, description FROM prompts WHERE id=?', (pid,)).fetchone()
        if not old:
            return jsonify({'error': 'Not found'}), 404
        conn.execute('''
                INSERT INTO prompt_versions (prompt_id, title, content, description)
                VALUES (?,?,?,?)
            ''', (pid, old['title'], old['content'], old['description'] or ''))
            # Keep only last 20 versions
        conn.execute('''
                DELETE FROM prompt_versions WHERE prompt_id=? AND id NOT IN (
                    SELECT id FROM prompt_versions WHERE prompt_id=?
                    ORDER BY saved_at DESC LIMIT 20
                )
            ''', (pid, pid))

        conn.execute('''
            UPDATE prompts SET
                title=?, description=?, content=?, categories=?, tags=?,
                folder_id=?, colour_label=?, rating=?, notes=?,
                chain_ids=?, variable_meta=?, chat_turns=?, role_id=?,
                status=?, parent_id=?,
                prompt_domain=?, prompt_use_case=?, prompt_output_format=?, prompt_tone=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (
            data['title'], data['description'], data['content'],
            data['categories'], data['tags'], data['folder_id'],
            data['colour_label'], data['rating'], data['notes'],
            data['chain_ids'], data['variable_meta'], data['chat_turns'],
            data['role_id'],
            data['status'], data['parent_id'],
            data['prompt_domain'], data['prompt_use_case'],
            data['prompt_output_format'], data['prompt_tone'],
            pid,
        ))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/prompts/<int:pid>', methods=['DELETE'])
def delete_prompt(pid):
    if pid in _locked_prompt_ids():
        return jsonify({'error': 'This prompt is locked. Unlock it in Version Lock before deleting.'}), 423
    conn = get_db()
    row = conn.execute('SELECT title, content FROM prompts WHERE id=?', (pid,)).fetchone()
    if row is not None:
        snapshot = json.dumps({'title': row['title'], 'content': row['content']})
        conn.execute(
            'UPDATE prompts SET fork_snapshot=? WHERE parent_id=? AND fork_snapshot IS NULL',
            (snapshot, pid)
        )
    conn.execute('DELETE FROM prompts WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/prompts/bulk', methods=['PATCH'])
def bulk_update_prompts():
    data = _json_body()
    ids = data.get('ids') or []
    action = data.get('action')
    if not ids or action not in ('add_tag', 'move_folder'):
        return jsonify({'error': 'ids and a valid action are required'}), 400

    conn = get_db()
    success, failed = 0, 0
    try:
        if action == 'add_tag':
            tag = (data.get('tag') or '').strip()
            if not tag:
                conn.close()
                return jsonify({'error': 'tag is required for add_tag'}), 400
            for pid in ids:
                row = conn.execute('SELECT tags FROM prompts WHERE id=?', (pid,)).fetchone()
                if not row:
                    failed += 1
                    continue
                tags = _normalise_list(row['tags'])
                if tag not in tags:
                    tags.append(tag)
                conn.execute(
                    'UPDATE prompts SET tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                    (_list_for_db(tags), pid)
                )
                success += 1
        elif action == 'move_folder':
            folder_id = _folder_id(data.get('folder_id'))
            for pid in ids:
                cur = conn.execute(
                    'UPDATE prompts SET folder_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                    (folder_id, pid)
                )
                if cur.rowcount:
                    success += 1
                else:
                    failed += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': success, 'failed': failed})

@app.route('/api/prompts/bulk', methods=['DELETE'])
def bulk_delete_prompts():
    data = _json_body()
    ids = data.get('ids') or []
    if not ids:
        return jsonify({'error': 'ids is required'}), 400
    locked = _locked_prompt_ids()
    skipped_locked = [pid for pid in ids if pid in locked]
    ids = [pid for pid in ids if pid not in locked]
    conn = get_db()
    success, failed = 0, 0
    try:
        for pid in ids:
            cur = conn.execute('DELETE FROM prompts WHERE id=?', (pid,))
            if cur.rowcount:
                success += 1
            else:
                failed += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': success, 'failed': failed, 'skipped_locked': skipped_locked})

@app.route('/api/prompts/<int:pid>/fork', methods=['POST'])
def fork_prompt(pid):
    """Fork a prompt — creates a copy with parent_id set to the original."""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM prompts WHERE id=?', (pid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Not found'}), 404
        p = serialize_prompt(row)
        source_root = p.get('fork_root_id') or pid
        data = _json_body()
        title = (data.get('title') or p['title'] + ' (Fork)').strip() or p['title'] + ' (Fork)'
        cur = conn.execute('''
            INSERT INTO prompts
                (title, description, content, categories, tags, folder_id,
                 colour_label, notes, chain_ids, variable_meta, chat_turns, role_id,
                 status, parent_id, prompt_domain, prompt_use_case, prompt_output_format, prompt_tone,
                 fork_root_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            title, p['description'], p['content'],
            _list_for_db(p['categories']), _list_for_db(p['tags']), p['folder_id'],
            p['colour_label'], '',
            json.dumps(p['chain_ids']),
            json.dumps(p['variable_meta']),
            json.dumps(p['chat_turns']),
            p.get('role_id'),
            'draft', pid,
            p.get('prompt_domain') or '',
            p.get('prompt_use_case') or '',
            p.get('prompt_output_format') or '',
            p.get('prompt_tone') or '',
            source_root,
        ))
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})


@app.route('/api/prompts/<int:pid>/forks', methods=['GET'])
def list_forks(pid):
    """List direct children (forks) of a prompt."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM prompts WHERE parent_id=? ORDER BY created_at', (pid,)).fetchall()
    conn.close()
    return jsonify({'forks': [serialize_prompt(r) for r in rows]})


@app.route('/api/prompts/<int:pid>/lineage', methods=['GET'])
def get_lineage(pid):
    """Ancestor chain for a prompt, root first, ending at its immediate parent."""
    conn = get_db()
    chain = []
    current = conn.execute('SELECT * FROM prompts WHERE id=?', (pid,)).fetchone()
    seen = {pid}
    while current is not None:
        parent_id = current['parent_id']
        if parent_id is None or parent_id in seen:
            break
        parent = conn.execute('SELECT * FROM prompts WHERE id=?', (parent_id,)).fetchone()
        if parent is None:
            break
        chain.insert(0, serialize_prompt(parent))
        seen.add(parent_id)
        current = parent
    conn.close()
    return jsonify({'chain': chain})


@app.route('/api/prompts/<int:pid>/status', methods=['PATCH'])
def update_prompt_status(pid):
    """Update just the status field of a prompt."""
    data = _json_body()
    status = data.get('status', 'active')
    if status not in ('draft', 'active', 'deprecated'):
        return jsonify({'error': 'Invalid status. Must be draft, active, or deprecated.'}), 400
    conn = get_db()
    try:
        row = conn.execute('SELECT id FROM prompts WHERE id=?', (pid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        conn.execute('UPDATE prompts SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, pid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'status': status})


@app.route('/api/taxonomy', methods=['GET'])
def get_taxonomy():
    """Return all taxonomy domains and their use cases."""
    conn = get_db()
    try:
        domains = conn.execute('SELECT id, name FROM taxonomy_domains ORDER BY name').fetchall()
        result = []
        for d in domains:
            use_cases = conn.execute(
                'SELECT id, name FROM taxonomy_use_cases WHERE domain_id=? ORDER BY name',
                (d['id'],)
            ).fetchall()
            result.append({
                'id': d['id'],
                'name': d['name'],
                'use_cases': [{'id': u['id'], 'name': u['name']} for u in use_cases]
            })
    finally:
        conn.close()
    return jsonify(result)


@app.route('/api/taxonomy/domains', methods=['POST'])
def create_taxonomy_domain():
    data = _json_body()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO taxonomy_domains (name) VALUES (?)', (name,))
        conn.commit()
        row = conn.execute('SELECT id, name FROM taxonomy_domains WHERE name=?', (name,)).fetchone()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'A domain with that name already exists'}), 400
    finally:
        conn.close()
    return jsonify({'id': row['id'], 'name': row['name']})


@app.route('/api/taxonomy/domains/<int:did>', methods=['PUT'])
def rename_taxonomy_domain(did):
    data = _json_body()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    try:
        conn.execute('UPDATE taxonomy_domains SET name=? WHERE id=?', (name, did))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'A domain with that name already exists'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/taxonomy/domains/<int:did>', methods=['DELETE'])
def delete_taxonomy_domain(did):
    conn = get_db()
    try:
        uc_ids = [r['id'] for r in conn.execute(
            'SELECT id FROM taxonomy_use_cases WHERE domain_id=?', (did,)).fetchall()]
        if uc_ids:
            placeholders = ','.join('?' * len(uc_ids))
            conn.execute(f'DELETE FROM prompt_taxonomy WHERE use_case_id IN ({placeholders})', uc_ids)
            conn.execute('DELETE FROM taxonomy_use_cases WHERE domain_id=?', (did,))
        conn.execute('DELETE FROM taxonomy_domains WHERE id=?', (did,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/taxonomy/use-cases', methods=['POST'])
def create_taxonomy_use_case():
    data = _json_body()
    domain_id = data.get('domain_id')
    name = (data.get('name') or '').strip()
    if not domain_id or not name:
        return jsonify({'error': 'domain_id and name are required'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO taxonomy_use_cases (domain_id, name) VALUES (?,?)',
                     (domain_id, name))
        conn.commit()
        row = conn.execute('SELECT id, name FROM taxonomy_use_cases WHERE domain_id=? AND name=?',
                            (domain_id, name)).fetchone()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'A use case with that name already exists'}), 400
    finally:
        conn.close()
    return jsonify({'id': row['id'], 'name': row['name']})


@app.route('/api/taxonomy/use-cases/<int:uid>', methods=['PUT'])
def rename_taxonomy_use_case(uid):
    data = _json_body()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    try:
        conn.execute('UPDATE taxonomy_use_cases SET name=? WHERE id=?', (name, uid))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'A use case with that name already exists'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/taxonomy/use-cases/<int:uid>', methods=['DELETE'])
def delete_taxonomy_use_case(uid):
    conn = get_db()
    try:
        conn.execute('DELETE FROM prompt_taxonomy WHERE use_case_id=?', (uid,))
        conn.execute('DELETE FROM taxonomy_use_cases WHERE id=?', (uid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/taxonomy/use-cases/<int:uid>/prompts', methods=['GET'])
def get_taxonomy_use_case_prompts(uid):
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT p.id, p.title, p.description, p.folder_id, p.updated_at
            FROM prompt_taxonomy pt
            JOIN prompts p ON p.id = pt.prompt_id
            WHERE pt.use_case_id=?
            ORDER BY p.title
        ''', (uid,)).fetchall()
        result = [dict(r) for r in rows]
    finally:
        conn.close()
    return jsonify(result)


@app.route('/api/taxonomy/bulk-tag', methods=['POST'])
def bulk_tag_taxonomy():
    data = _json_body()
    prompt_ids = data.get('prompt_ids') or []
    use_case_id = data.get('use_case_id')
    action = data.get('action', 'add')
    if not prompt_ids or not use_case_id or action not in ('add', 'remove'):
        return jsonify({'error': 'prompt_ids, use_case_id and a valid action are required'}), 400
    conn = get_db()
    try:
        if action == 'add':
            conn.executemany(
                'INSERT OR IGNORE INTO prompt_taxonomy (prompt_id, use_case_id) VALUES (?,?)',
                [(pid, use_case_id) for pid in prompt_ids]
            )
        else:
            placeholders = ','.join('?' * len(prompt_ids))
            conn.execute(
                f'DELETE FROM prompt_taxonomy WHERE use_case_id=? AND prompt_id IN ({placeholders})',
                [use_case_id] + prompt_ids
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'count': len(prompt_ids)})


@app.route('/api/prompts/<int:pid>/relationships', methods=['GET'])
def get_prompt_relationships(pid):
    """Get all prompts related to this one (both directions)."""
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT p.id, p.title, p.description, pr.rel_type
            FROM prompt_relationships pr
            JOIN prompts p ON (p.id = CASE WHEN pr.prompt_a=? THEN pr.prompt_b ELSE pr.prompt_a END)
            WHERE pr.prompt_a=? OR pr.prompt_b=?
            ORDER BY p.title
        ''', (pid, pid, pid)).fetchall()
        result = [{'id': r['id'], 'title': r['title'], 'description': r['description'],
                   'rel_type': r['rel_type']} for r in rows]
    finally:
        conn.close()
    return jsonify(result)


@app.route('/api/prompts/<int:pid>/relationships', methods=['POST'])
def add_prompt_relationship(pid):
    """Link two prompts as related."""
    data = _json_body()
    other_id = data.get('related_id')
    rel_type  = data.get('rel_type', 'related')
    if not other_id or other_id == pid:
        return jsonify({'error': 'Invalid related_id'}), 400
    a, b = (pid, other_id) if pid < other_id else (other_id, pid)
    conn = get_db()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO prompt_relationships (prompt_a, prompt_b, rel_type) VALUES (?,?,?)',
            (a, b, rel_type)
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/prompts/<int:pid>/relationships/<int:other_id>', methods=['DELETE'])
def delete_prompt_relationship(pid, other_id):
    a, b = (pid, other_id) if pid < other_id else (other_id, pid)
    conn = get_db()
    try:
        conn.execute('DELETE FROM prompt_relationships WHERE prompt_a=? AND prompt_b=?', (a, b))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/relationships/orphans', methods=['GET'])
def get_relationship_orphans():
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT id, title, description FROM prompts
            WHERE id NOT IN (SELECT prompt_a FROM prompt_relationships)
              AND id NOT IN (SELECT prompt_b FROM prompt_relationships)
            ORDER BY title
        ''').fetchall()
        result = [dict(r) for r in rows]
    finally:
        conn.close()
    return jsonify(result)


@app.route('/api/prompts/<int:pid>/favorite', methods=['POST'])
def toggle_favorite(pid):
    conn = get_db()
    row  = conn.execute('SELECT is_favorite FROM prompts WHERE id=?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    nv = 0 if row['is_favorite'] else 1
    conn.execute('UPDATE prompts SET is_favorite=? WHERE id=?', (nv, pid))
    conn.commit()
    conn.close()
    return jsonify({'is_favorite': nv})

@app.route('/api/prompts/<int:pid>/template', methods=['POST'])
def toggle_template_tag(pid):
    """Toggle the 'template' tag on a prompt -- powers the Gallery's
    'My Templates' section. No new column: reuses the existing tags field
    so this needs no schema migration."""
    conn = get_db()
    row  = conn.execute('SELECT tags FROM prompts WHERE id=?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    tags = _normalise_list(row['tags'])
    is_template = any(t.lower() == 'template' for t in tags)
    if is_template:
        tags = [t for t in tags if t.lower() != 'template']
    else:
        tags = tags + ['template']
    conn.execute('UPDATE prompts SET tags=? WHERE id=?', (_list_for_db(tags), pid))
    conn.commit()
    conn.close()
    return jsonify({'is_template': not is_template})

@app.route('/api/tags/rename', methods=['POST'])
def rename_tag():
    """Rename, merge, or delete a tag across every prompt.
    Body: {"from": "old", "to": "new"} -- empty "to" deletes the tag.
    Renaming onto an existing tag merges them (lists are deduped)."""
    data = _json_body()
    src = (data.get('from') or '').strip()
    dst = (data.get('to') or '').strip()
    if not src:
        return jsonify({'error': 'Missing tag name'}), 400
    conn = get_db()
    try:
        rows = conn.execute('SELECT id, tags FROM prompts').fetchall()
        changed = 0
        for r in rows:
            tags = _normalise_list(r['tags'])
            if not any(t.lower() == src.lower() for t in tags):
                continue
            out = []
            for t in tags:
                v = dst if t.lower() == src.lower() else t
                if v and v.lower() not in [x.lower() for x in out]:
                    out.append(v)
            conn.execute('UPDATE prompts SET tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (_list_for_db(out), r['id']))
            changed += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'changed': changed})


@app.route('/api/prompts/<int:pid>/use', methods=['POST'])
def use_prompt(pid):
    conn = get_db()
    conn.execute('UPDATE prompts SET use_count=use_count+1, last_used=CURRENT_TIMESTAMP WHERE id=?', (pid,))
    conn.execute('INSERT INTO usage_log (prompt_id) VALUES (?)', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/prompts/<int:pid>/duplicate', methods=['POST'])
def duplicate_prompt(pid):
    conn = get_db()
    try:
        row  = conn.execute('SELECT * FROM prompts WHERE id=?', (pid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        p = serialize_prompt(row)
        cur = conn.execute('''
            INSERT INTO prompts
                (title, description, content, categories, tags, folder_id,
                 colour_label, rating, notes, chain_ids, variable_meta, chat_turns, role_id,
                 status, prompt_domain, prompt_use_case, prompt_output_format, prompt_tone)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            p['title'] + ' (Copy)',
            p['description'], p['content'],
            _list_for_db(p['categories']), _list_for_db(p['tags']), p['folder_id'],
            p['colour_label'], 0, '',
            json.dumps(p['chain_ids']),
            json.dumps(p['variable_meta']),
            json.dumps(p['chat_turns']),
            p.get('role_id'),
            p.get('status') or 'active',
            p.get('prompt_domain') or '',
            p.get('prompt_use_case') or '',
            p.get('prompt_output_format') or '',
            p.get('prompt_tone') or '',
        ))
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})


@app.route('/api/prompts/<int:pid>/rating', methods=['POST'])
def set_rating(pid):
    data   = request.json
    rating = max(0, min(5, int(data.get('rating', 0))))
    notes  = data.get('notes', None)
    conn   = get_db()
    if notes is not None:
        conn.execute('UPDATE prompts SET rating=?, notes=? WHERE id=?', (rating, notes, pid))
    else:
        conn.execute('UPDATE prompts SET rating=? WHERE id=?', (rating, pid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/prompts/<int:pid>/colour', methods=['POST'])
def set_colour(pid):
    data   = request.json
    colour = data.get('colour', '')
    conn   = get_db()
    conn.execute('UPDATE prompts SET colour_label=? WHERE id=?', (colour, pid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/prompts/<int:pid>/versions', methods=['GET'])
def get_versions(pid):
    conn  = get_db()
    rows  = conn.execute('''
        SELECT * FROM prompt_versions WHERE prompt_id=?
        ORDER BY saved_at DESC
    ''', (pid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/prompts/<int:pid>/versions/<int:vid>/restore', methods=['POST'])
def restore_version(pid, vid):
    conn = get_db()
    ver  = conn.execute('SELECT * FROM prompt_versions WHERE id=? AND prompt_id=?', (vid, pid)).fetchone()
    if not ver:
        conn.close()
        return jsonify({'error': 'Version not found'}), 404

    # Snapshot current before restoring
    old = conn.execute('SELECT title, content, description FROM prompts WHERE id=?', (pid,)).fetchone()
    if old:
        conn.execute('INSERT INTO prompt_versions (prompt_id, title, content, description) VALUES (?,?,?,?)',
                     (pid, old['title'], old['content'], old['description'] or ''))

    conn.execute('''
        UPDATE prompts SET title=?, content=?, description=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    ''', (ver['title'], ver['content'], ver['description'] or '', pid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/prompts/<int:pid>/versions/<int:vid>', methods=['PUT'])
def update_version_meta(pid, vid):
    data = _json_body()
    conn = get_db()
    try:
        ver = conn.execute('SELECT id FROM prompt_versions WHERE id=? AND prompt_id=?', (vid, pid)).fetchone()
        if not ver:
            return jsonify({'error': 'Version not found'}), 404
        if 'version_label' in data:
            conn.execute('UPDATE prompt_versions SET version_label=? WHERE id=?',
                         (data['version_label'], vid))
        if 'version_notes' in data:
            conn.execute('UPDATE prompt_versions SET version_notes=? WHERE id=?',
                         (data['version_notes'], vid))
        if 'is_baseline' in data:
            if data['is_baseline']:
                conn.execute('UPDATE prompt_versions SET is_baseline=0 WHERE prompt_id=?', (pid,))
            conn.execute('UPDATE prompt_versions SET is_baseline=? WHERE id=?',
                         (1 if data['is_baseline'] else 0, vid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})


@app.route('/api/variable-templates', methods=['GET'])
def get_var_templates():
    conn  = get_db()
    try:
        rows  = conn.execute('SELECT * FROM variable_templates ORDER BY name').fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['variables'] = _json_value(d.get('variables'), [])
        result.append(d)
    return jsonify(result)

@app.route('/api/variable-templates', methods=['POST'])
def create_var_template():
    data = _json_body()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Template name is required'}), 400
    conn = get_db()
    try:
        cur  = conn.execute(
            'INSERT INTO variable_templates (name, description, variables) VALUES (?,?,?)',
            (name, data.get('description', ''), _json_for_db(data.get('variables', []), []))
        )
        tid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': tid})

@app.route('/api/variable-templates/<int:tid>', methods=['DELETE'])
def delete_var_template(tid):
    conn = get_db()
    conn.execute('DELETE FROM variable_templates WHERE id=?', (tid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# CHAINS — standalone chain workflows
# ============================================================

def serialize_chain(row):
    c = dict(row)
    c['nodes']  = _json_value(c.get('nodes'), [])
    c['layout'] = _json_value(c.get('layout'), {})
    c['tags']   = _normalise_list(c.get('tags') or '')
    c['colour_label'] = c.get('colour_label') or ''
    c.setdefault('is_favorite', 0)
    return c

def _chain_payload(data):
    return {
        'name':         (data.get('name') or 'Untitled chain').strip() or 'Untitled chain',
        'description':  data.get('description') or '',
        'nodes':        _json_for_db(data.get('nodes', []), []),
        'layout':       _json_for_db(data.get('layout', {}), {}),
        'tags':         _list_for_db(data.get('tags', '')),
        'colour_label': data.get('colour_label') or '',
    }

@app.route('/api/chains', methods=['GET'])
def list_chains():
    conn = get_db()
    favs = request.args.get('favorites', '0')
    q, params = 'SELECT * FROM chains WHERE 1=1', []
    if favs == '1':
        q += ' AND is_favorite=1'
    q += ' ORDER BY updated_at DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([serialize_chain(r) for r in rows])

@app.route('/api/chains/<int:cid>', methods=['GET'])
def get_chain(cid):
    conn = get_db()
    row  = conn.execute('SELECT * FROM chains WHERE id=?', (cid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(serialize_chain(row))

@app.route('/api/chains', methods=['POST'])
def create_chain():
    p = _chain_payload(_json_body())
    conn = get_db()
    try:
        cur = conn.execute('''
            INSERT INTO chains (name, description, nodes, layout, tags, colour_label)
            VALUES (?,?,?,?,?,?)
        ''', (p['name'], p['description'], p['nodes'], p['layout'], p['tags'], p['colour_label']))
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': cid})

@app.route('/api/chains/<int:cid>', methods=['PUT'])
def update_chain(cid):
    p = _chain_payload(_json_body())
    conn = get_db()
    try:
        conn.execute('''
            UPDATE chains
               SET name=?, description=?, nodes=?, layout=?, tags=?, colour_label=?,
                   updated_at=CURRENT_TIMESTAMP
             WHERE id=?
        ''', (p['name'], p['description'], p['nodes'], p['layout'], p['tags'], p['colour_label'], cid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/chains/<int:cid>', methods=['DELETE'])
def delete_chain(cid):
    conn = get_db()
    conn.execute('DELETE FROM chains WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chains/<int:cid>/duplicate', methods=['POST'])
def duplicate_chain(cid):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM chains WHERE id=?', (cid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        c = serialize_chain(row)
        cur = conn.execute('''
            INSERT INTO chains (name, description, nodes, layout, tags, colour_label)
            VALUES (?,?,?,?,?,?)
        ''', (
            c['name'] + ' (Copy)',
            c.get('description', ''),
            json.dumps(c['nodes']),
            json.dumps(c['layout']),
            _list_for_db(c['tags']),
            c['colour_label'],
        ))
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})

@app.route('/api/chains/<int:cid>/favorite', methods=['POST'])
def toggle_chain_favorite(cid):
    conn = get_db()
    row  = conn.execute('SELECT is_favorite FROM chains WHERE id=?', (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    nv = 0 if row['is_favorite'] else 1
    conn.execute('UPDATE chains SET is_favorite=? WHERE id=?', (nv, cid))
    conn.commit()
    conn.close()
    return jsonify({'is_favorite': nv})


# ============================================================
# BOARDS — curated prompt collections (pin prompts into named boards)
# ============================================================

def serialize_board(row, pin_count=0):
    b = dict(row)
    b['pin_count'] = pin_count
    b.setdefault('colour_label', '')
    b['colour_label'] = b.get('colour_label') or ''
    return b

def _board_payload(data):
    return {
        'name':         (data.get('name') or 'Untitled board').strip() or 'Untitled board',
        'description':  data.get('description') or '',
        'colour_label': data.get('colour_label') or '',
    }

@app.route('/api/boards', methods=['GET'])
def list_boards():
    conn = get_db()
    rows = conn.execute('''
        SELECT b.*, COUNT(bp.id) AS pin_count
          FROM boards b
          LEFT JOIN board_pins bp ON bp.board_id = b.id
         GROUP BY b.id
         ORDER BY b.updated_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([serialize_board(r, r['pin_count']) for r in rows])

@app.route('/api/boards', methods=['POST'])
def create_board():
    p = _board_payload(_json_body())
    conn = get_db()
    try:
        cur = conn.execute('INSERT INTO boards (name, description, colour_label) VALUES (?,?,?)',
                            (p['name'], p['description'], p['colour_label']))
        bid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': bid})

@app.route('/api/boards/<int:bid>', methods=['PUT'])
def update_board(bid):
    p = _board_payload(_json_body())
    conn = get_db()
    try:
        conn.execute('''
            UPDATE boards SET name=?, description=?, colour_label=?, updated_at=CURRENT_TIMESTAMP
             WHERE id=?
        ''', (p['name'], p['description'], p['colour_label'], bid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/boards/<int:bid>', methods=['DELETE'])
def delete_board(bid):
    conn = get_db()
    conn.execute('DELETE FROM boards WHERE id=?', (bid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/boards/<int:bid>/pins', methods=['GET'])
def list_board_pins(bid):
    conn = get_db()
    rows = conn.execute('''
        SELECT p.* FROM prompts p
          JOIN board_pins bp ON bp.prompt_id = p.id
         WHERE bp.board_id = ?
         ORDER BY bp.added_at DESC
    ''', (bid,)).fetchall()
    conn.close()
    return jsonify([serialize_prompt(r) for r in rows])

@app.route('/api/boards/<int:bid>/pins', methods=['POST'])
def add_board_pin(bid):
    data = _json_body()
    try:
        prompt_id = int(data.get('prompt_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'prompt_id required'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT OR IGNORE INTO board_pins (board_id, prompt_id) VALUES (?,?)',
                      (bid, prompt_id))
        conn.execute('UPDATE boards SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (bid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/boards/<int:bid>/pins/<int:prompt_id>', methods=['DELETE'])
def remove_board_pin(bid, prompt_id):
    conn = get_db()
    conn.execute('DELETE FROM board_pins WHERE board_id=? AND prompt_id=?', (bid, prompt_id))
    conn.execute('UPDATE boards SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (bid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/boards/<int:bid>/duplicate', methods=['POST'])
def duplicate_board(bid):
    """Copy a board and its pins (pointers to the same prompts, not prompt copies)."""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM boards WHERE id=?', (bid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        b = dict(row)
        cur = conn.execute(
            'INSERT INTO boards (name, description, colour_label) VALUES (?,?,?)',
            (b['name'] + ' (Copy)', b.get('description', ''), b.get('colour_label'))
        )
        new_id = cur.lastrowid
        pin_ids = [r['prompt_id'] for r in conn.execute(
            'SELECT prompt_id FROM board_pins WHERE board_id=?', (bid,)
        ).fetchall()]
        conn.executemany(
            'INSERT OR IGNORE INTO board_pins (board_id, prompt_id) VALUES (?,?)',
            [(new_id, pid) for pid in pin_ids]
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})

@app.route('/api/boards/<int:bid>/export', methods=['GET'])
def export_board(bid):
    """Bundle a single board's pinned prompts as a shareable JSON file, distinct from
    the whole-library export — for handing one curated board to someone else."""
    conn = get_db()
    try:
        board = conn.execute('SELECT * FROM boards WHERE id=?', (bid,)).fetchone()
        if not board:
            return jsonify({'error': 'Not found'}), 404
        rows = conn.execute('''
            SELECT p.* FROM prompts p
              JOIN board_pins bp ON bp.prompt_id = p.id
             WHERE bp.board_id = ?
             ORDER BY bp.added_at DESC
        ''', (bid,)).fetchall()
    finally:
        conn.close()
    payload = {
        'board': {'name': board['name'], 'description': board['description']},
        'exported_at': datetime.now().isoformat(),
        'prompts': [serialize_prompt(r) for r in rows],
    }
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '-', board['name']).strip('-') or 'board'
    return Response(json.dumps(payload, indent=2), mimetype='application/json',
                     headers={'Content-Disposition': f'attachment; filename={safe_name}-board.json'})


# ============================================================
# META BLUEPRINTS — prompts that generate prompts
# ============================================================

def serialize_blueprint(row):
    b = dict(row)
    b['variables']     = _json_value(b.get('variables'), [])
    b['tags']          = _normalise_list(b.get('tags') or '')
    b['system']        = b.get('system') or ''
    b['output_format'] = b.get('output_format') or 'text'
    b.setdefault('is_favorite', 0)
    return b

def _blueprint_payload(data):
    return {
        'name':          (data.get('name') or 'Untitled blueprint').strip() or 'Untitled blueprint',
        'description':   data.get('description') or '',
        'template':      data.get('template') or '',
        'system':        data.get('system') or '',
        'variables':     _json_for_db(data.get('variables', []), []),
        'output_format': data.get('output_format') or 'text',
        'tags':          _list_for_db(data.get('tags', '')),
    }

@app.route('/api/meta', methods=['GET'])
def list_blueprints():
    conn = get_db()
    favs = request.args.get('favorites', '0')
    q, params = 'SELECT * FROM meta_blueprints WHERE 1=1', []
    if favs == '1':
        q += ' AND is_favorite=1'
    q += ' ORDER BY updated_at DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([serialize_blueprint(r) for r in rows])

@app.route('/api/meta/<int:bid>', methods=['GET'])
def get_blueprint(bid):
    conn = get_db()
    row  = conn.execute('SELECT * FROM meta_blueprints WHERE id=?', (bid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(serialize_blueprint(row))

@app.route('/api/meta', methods=['POST'])
def create_blueprint():
    p = _blueprint_payload(_json_body())
    conn = get_db()
    try:
        cur = conn.execute('''
            INSERT INTO meta_blueprints
                (name, description, template, system, variables, output_format, tags)
            VALUES (?,?,?,?,?,?,?)
        ''', (p['name'], p['description'], p['template'], p['system'],
              p['variables'], p['output_format'], p['tags']))
        bid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': bid})

@app.route('/api/meta/<int:bid>', methods=['PUT'])
def update_blueprint(bid):
    p = _blueprint_payload(_json_body())
    conn = get_db()
    try:
        conn.execute('''
            UPDATE meta_blueprints
               SET name=?, description=?, template=?, system=?, variables=?,
                   output_format=?, tags=?, updated_at=CURRENT_TIMESTAMP
             WHERE id=?
        ''', (p['name'], p['description'], p['template'], p['system'],
              p['variables'], p['output_format'], p['tags'], bid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/meta/<int:bid>', methods=['DELETE'])
def delete_blueprint(bid):
    conn = get_db()
    conn.execute('DELETE FROM meta_blueprints WHERE id=?', (bid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/meta/<int:bid>/duplicate', methods=['POST'])
def duplicate_blueprint(bid):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM meta_blueprints WHERE id=?', (bid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        b = serialize_blueprint(row)
        cur = conn.execute('''
            INSERT INTO meta_blueprints
                (name, description, template, system, variables, output_format, tags)
            VALUES (?,?,?,?,?,?,?)
        ''', (
            b['name'] + ' (Copy)',
            b.get('description', ''),
            b.get('template', ''),
            b.get('system', ''),
            json.dumps(b['variables']),
            b['output_format'],
            _list_for_db(b['tags']),
        ))
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})

@app.route('/api/meta/<int:bid>/favorite', methods=['POST'])
def toggle_blueprint_favorite(bid):
    conn = get_db()
    row  = conn.execute('SELECT is_favorite FROM meta_blueprints WHERE id=?', (bid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    nv = 0 if row['is_favorite'] else 1
    conn.execute('UPDATE meta_blueprints SET is_favorite=? WHERE id=?', (nv, bid))
    conn.commit()
    conn.close()
    return jsonify({'is_favorite': nv})


@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    conn = get_db()

    total   = conn.execute('SELECT COUNT(*) as n FROM prompts').fetchone()['n']
    favs    = conn.execute('SELECT COUNT(*) as n FROM prompts WHERE is_favorite=1').fetchone()['n']
    folders = conn.execute('SELECT COUNT(*) as n FROM folders').fetchone()['n']
    total_uses = conn.execute('SELECT SUM(use_count) as n FROM prompts').fetchone()['n'] or 0

    # Top 5 most used
    top = conn.execute('''
        SELECT id, title, use_count, colour_label FROM prompts
        ORDER BY use_count DESC LIMIT 5
    ''').fetchall()

    # Never used
    never = conn.execute('''
        SELECT COUNT(*) as n FROM prompts WHERE use_count=0
    ''').fetchone()['n']

    # 30-day daily usage from log
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    daily_raw = conn.execute('''
        SELECT DATE(used_at) as day, COUNT(*) as cnt
        FROM usage_log WHERE used_at >= ?
        GROUP BY day ORDER BY day
    ''', (thirty_days_ago,)).fetchall()

    # Recent 10 used
    recent = conn.execute('''
        SELECT p.id, p.title, p.use_count, p.last_used, p.colour_label
        FROM prompts p WHERE p.last_used IS NOT NULL
        ORDER BY p.last_used DESC LIMIT 10
    ''').fetchall()

    # Rating distribution
    ratings = conn.execute('''
        SELECT rating, COUNT(*) as cnt FROM prompts
        GROUP BY rating ORDER BY rating
    ''').fetchall()

    conn.close()

    return jsonify({
        'summary': {
            'total_prompts': total,
            'total_favourites': favs,
            'total_folders': folders,
            'total_uses': total_uses,
            'never_used': never,
        },
        'top_prompts':    [dict(r) for r in top],
        'recent_prompts': [dict(r) for r in recent],
        'daily_usage':    [{'day': r['day'], 'count': r['cnt']} for r in daily_raw],
        'rating_dist':    [{'rating': r['rating'], 'count': r['cnt']} for r in ratings],
    })


@app.route('/api/usage-log', methods=['GET'])
def get_usage_log():
    """Full chronological run history (one row per use), unlike /api/analytics'
    recent-10-distinct-prompts summary. Optional ?search= filters by prompt title/content."""
    search = request.args.get('search', '').strip()
    limit = min(int(request.args.get('limit', 200) or 200), 500)
    conn = get_db()
    try:
        q = '''SELECT l.id, l.prompt_id, l.used_at, p.title AS prompt_title, p.content AS prompt_content
               FROM usage_log l JOIN prompts p ON p.id = l.prompt_id'''
        params = []
        if search:
            q += ' WHERE p.title LIKE ? OR p.content LIKE ?'
            params.extend([f'%{search}%', f'%{search}%'])
        q += ' ORDER BY l.used_at DESC LIMIT ?'
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/export', methods=['GET'])
def export_json():
    conn  = get_db()
    try:
        rows  = conn.execute('SELECT * FROM prompts ORDER BY title').fetchall()
    finally:
        conn.close()
    out = [serialize_prompt(r) for r in rows]
    return jsonify(out)

@app.route('/api/export/markdown', methods=['GET'])
def export_markdown():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM prompts ORDER BY title').fetchall()
    finally:
        conn.close()
    lines = ['# Prompt Library Export\n', f'*Exported: {datetime.now().strftime("%Y-%m-%d %H:%M")}*\n\n---\n']
    for r in rows:
        p = serialize_prompt(r)
        lines.append(f"## {p['title']}\n")
        if p.get('description'):
            lines.append(f"*{p['description']}*\n")
        if p.get('categories'):
            lines.append(f"**Categories:** {', '.join(p['categories'])}\n")
        if p.get('tags'):
            lines.append(f"**Tags:** {', '.join(p['tags'])}\n")
        lines.append(f"\n```\n{p['content']}\n```\n\n---\n")
    md = '\n'.join(lines)
    return Response(md, mimetype='text/markdown',
                    headers={'Content-Disposition': 'attachment; filename=prompts-export.md'})

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM prompts ORDER BY title').fetchall()
    finally:
        conn.close()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        'id','title','description','content','categories','tags',
        'colour_label','rating','use_count','is_favorite',
        'created_at','updated_at','last_used'
    ])
    writer.writeheader()
    for r in rows:
        p = serialize_prompt(r)
        writer.writerow({
            'id':           p.get('id'),
            'title':        p.get('title', ''),
            'description':  p.get('description', ''),
            'content':      p.get('content', ''),
            'categories':   ','.join(p.get('categories', [])),
            'tags':         ','.join(p.get('tags', [])),
            'colour_label': p.get('colour_label', ''),
            'rating':       p.get('rating', 0),
            'use_count':    p.get('use_count', 0),
            'is_favorite':  p.get('is_favorite', 0),
            'created_at':   p.get('created_at', ''),
            'updated_at':   p.get('updated_at', ''),
            'last_used':    p.get('last_used', ''),
        })
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=prompts-export.csv'})


@app.route('/api/export/bulk', methods=['GET'])
def export_bulk():
    """Bundle a JSON export and a Markdown export into a single ZIP archive."""
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM prompts ORDER BY title').fetchall()
    finally:
        conn.close()
    prompts = [serialize_prompt(r) for r in rows]

    # JSON payload
    json_bytes = json.dumps(prompts, indent=2).encode('utf-8')

    # Markdown payload (same layout as /api/export/markdown)
    md_lines = ['# Prompt Library Export\n',
                f'*Exported: {datetime.now().strftime("%Y-%m-%d %H:%M")}*\n\n---\n']
    for p in prompts:
        md_lines.append(f"## {p['title']}\n")
        if p.get('description'):
            md_lines.append(f"*{p['description']}*\n")
        if p.get('categories'):
            md_lines.append(f"**Categories:** {', '.join(p['categories'])}\n")
        if p.get('tags'):
            md_lines.append(f"**Tags:** {', '.join(p['tags'])}\n")
        md_lines.append(f"\n```\n{p['content']}\n```\n\n---\n")
    md_bytes = '\n'.join(md_lines).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('prompts.json', json_bytes)
        zf.writestr('prompts.md',   md_bytes)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype='application/zip',
                    headers={'Content-Disposition': 'attachment; filename=prompts-export.zip'})


LOCKED_PROMPTS_KEY = 'locked_prompts'

def _locked_prompt_ids():
    raw = get_setting(LOCKED_PROMPTS_KEY)
    try:
        ids = json.loads(raw) if raw else []
        return set(int(i) for i in ids) if isinstance(ids, list) else set()
    except (ValueError, TypeError):
        return set()

def _save_locked_prompt_ids(ids):
    set_setting(LOCKED_PROMPTS_KEY, json.dumps(sorted(ids)))

@app.route('/api/locked-prompts', methods=['GET'])
def get_locked_prompts():
    return jsonify(sorted(_locked_prompt_ids()))

@app.route('/api/locked-prompts/<int:pid>', methods=['POST'])
def lock_prompt(pid):
    conn = get_db()
    try:
        exists = conn.execute('SELECT id FROM prompts WHERE id=?', (pid,)).fetchone()
    finally:
        conn.close()
    if not exists:
        return jsonify({'error': 'Prompt not found'}), 404
    ids = _locked_prompt_ids()
    ids.add(pid)
    _save_locked_prompt_ids(ids)
    return jsonify({'ok': True, 'locked': sorted(ids)})

@app.route('/api/locked-prompts/<int:pid>', methods=['DELETE'])
def unlock_prompt(pid):
    ids = _locked_prompt_ids()
    ids.discard(pid)
    _save_locked_prompt_ids(ids)
    return jsonify({'ok': True, 'locked': sorted(ids)})


@app.route('/api/integrity-check', methods=['GET'])
def integrity_check():
    """Read-only diagnostics for the data layer itself, distinct from Library
    Organizer's organisational health scan (tags, staleness, duplicates)."""
    conn = get_db()
    try:
        results = []

        ic_rows = conn.execute('PRAGMA integrity_check').fetchall()
        ic_ok = len(ic_rows) == 1 and ic_rows[0][0] == 'ok'
        results.append({
            'check': 'SQLite database integrity',
            'ok': ic_ok,
            'detail': 'ok' if ic_ok else '; '.join(r[0] for r in ic_rows),
            'fixable': False,
        })

        orphan_rels = conn.execute('''
            SELECT COUNT(*) as n FROM prompt_relationships
            WHERE prompt_a NOT IN (SELECT id FROM prompts) OR prompt_b NOT IN (SELECT id FROM prompts)
        ''').fetchone()['n']
        results.append({
            'check': 'Orphaned prompt relationships',
            'ok': orphan_rels == 0,
            'detail': 'none found' if not orphan_rels else f'{orphan_rels} relationship(s) reference a deleted prompt',
            'fixable': orphan_rels > 0,
        })

        orphan_folders = conn.execute('''
            SELECT COUNT(*) as n FROM prompts
            WHERE folder_id IS NOT NULL AND folder_id NOT IN (SELECT id FROM folders)
        ''').fetchone()['n']
        results.append({
            'check': 'Prompts pointing to a deleted folder',
            'ok': orphan_folders == 0,
            'detail': 'none found' if not orphan_folders else f'{orphan_folders} prompt(s) reference a deleted folder',
            'fixable': orphan_folders > 0,
        })

        vault_rows = conn.execute('SELECT id, name, path FROM vaults').fetchall()
        missing_vaults = [dict(v) for v in vault_rows if not os.path.isdir(v['path'])]
        results.append({
            'check': 'Vault folders present on disk',
            'ok': len(missing_vaults) == 0,
            'detail': 'none found' if not missing_vaults else ', '.join(v['name'] for v in missing_vaults) + ' — folder no longer exists',
            'fixable': False,
        })
    finally:
        conn.close()
    return jsonify(results)

@app.route('/api/integrity-check/fix-orphaned-relationships', methods=['POST'])
def fix_orphaned_relationships():
    conn = get_db()
    try:
        cur = conn.execute('''
            DELETE FROM prompt_relationships
            WHERE prompt_a NOT IN (SELECT id FROM prompts) OR prompt_b NOT IN (SELECT id FROM prompts)
        ''')
        removed = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'removed': removed})

@app.route('/api/integrity-check/fix-orphaned-folders', methods=['POST'])
def fix_orphaned_folders():
    conn = get_db()
    try:
        cur = conn.execute('''
            UPDATE prompts SET folder_id = NULL
            WHERE folder_id IS NOT NULL AND folder_id NOT IN (SELECT id FROM folders)
        ''')
        fixed = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'fixed': fixed})


def _backup_dir():
    """Folder holding whole-DB snapshots. Deliberately a sibling of Documents/PromptLibrary,
    not a subfolder of it — if that whole folder is lost (deleted, drive failure), the
    backups need to survive it, or Backup & Restore protects nothing in the scenario that
    actually matters."""
    path = os.path.join(os.path.expanduser('~'), 'Documents', 'PromptLibraryBackups')
    os.makedirs(path, exist_ok=True)
    return path

def _backup_info(dir_path, filename):
    st = os.stat(os.path.join(dir_path, filename))
    return {
        'filename':   filename,
        'size':       st.st_size,
        'created_at': datetime.fromtimestamp(st.st_mtime).isoformat(),
    }

@app.route('/api/backup', methods=['GET'])
def list_backups():
    """List whole-DB snapshots, newest first."""
    d = _backup_dir()
    rows = [_backup_info(d, f) for f in os.listdir(d) if f.endswith('.db')]
    rows.sort(key=lambda r: r['created_at'], reverse=True)
    return jsonify(rows)

@app.route('/api/backup', methods=['POST'])
def create_backup():
    """Snapshot the live DB via sqlite3's backup API, safe under WAL and concurrent access."""
    d = _backup_dir()
    filename = f"PromptLibrary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    dest_path = os.path.join(d, filename)
    src = sqlite3.connect(DATABASE)
    dest = sqlite3.connect(dest_path)
    try:
        with dest:
            src.backup(dest)
    finally:
        src.close()
        dest.close()
    return jsonify(_backup_info(d, filename))

@app.route('/api/backup/<path:filename>', methods=['DELETE'])
def delete_backup(filename):
    filename = os.path.basename(filename)
    fp = os.path.join(_backup_dir(), filename)
    if not filename.endswith('.db') or not os.path.isfile(fp):
        return jsonify({'error': 'Backup not found'}), 404
    os.remove(fp)
    return jsonify({'ok': True})

@app.route('/api/backup/<path:filename>/restore', methods=['POST'])
def restore_backup(filename):
    """Restore a snapshot over the live DB. Takes a pre-restore safety snapshot first,
    then uses sqlite3's backup API both ways so WAL state is handled correctly."""
    filename = os.path.basename(filename)
    d = _backup_dir()
    src_path = os.path.join(d, filename)
    if not filename.endswith('.db') or not os.path.isfile(src_path):
        return jsonify({'error': 'Backup not found'}), 404

    safety_name = f"PromptLibrary_pre-restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    live = sqlite3.connect(DATABASE)
    safety = sqlite3.connect(os.path.join(d, safety_name))
    try:
        with safety:
            live.backup(safety)
        live.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        live.close()
        safety.close()

    restore_src = sqlite3.connect(src_path)
    live_dest = sqlite3.connect(DATABASE)
    try:
        with live_dest:
            restore_src.backup(live_dest)
    finally:
        restore_src.close()
        live_dest.close()

    return jsonify({'ok': True, 'safety_backup': safety_name})


def _eval_cases_key(pid):
    return f'eval_cases_{pid}'

def _eval_runs_key(pid):
    return f'eval_runs_{pid}'

@app.route('/api/eval-cases/<int:pid>', methods=['GET'])
def get_eval_cases(pid):
    """Test cases for a prompt's regression suite, stored as JSON in settings (no schema change)."""
    raw = get_setting(_eval_cases_key(pid))
    return jsonify(json.loads(raw) if raw else [])

@app.route('/api/eval-cases/<int:pid>', methods=['POST'])
def save_eval_cases(pid):
    """Replace the full test-case list for a prompt. Body: {cases: [{id, input, expected}, ...]}."""
    data = _json_body()
    cases = data.get('cases')
    if not isinstance(cases, list):
        return jsonify({'error': 'cases must be a list'}), 400
    set_setting(_eval_cases_key(pid), json.dumps(cases))
    return jsonify({'ok': True, 'cases': cases})

@app.route('/api/eval-runs/<int:pid>', methods=['GET'])
def get_eval_runs(pid):
    """Run history for a prompt's regression suite, newest first."""
    raw = get_setting(_eval_runs_key(pid))
    return jsonify(json.loads(raw) if raw else [])

@app.route('/api/eval-runs/<int:pid>', methods=['POST'])
def add_eval_run(pid):
    """Append a run result. Body: {results: [{case_id, output, pass, note}, ...], version_id?}."""
    data = _json_body()
    results = data.get('results')
    if not isinstance(results, list):
        return jsonify({'error': 'results must be a list'}), 400
    raw = get_setting(_eval_runs_key(pid))
    runs = json.loads(raw) if raw else []
    run = {
        'id': int(datetime.now().timestamp() * 1000),
        'timestamp': datetime.now().isoformat(),
        'version_id': data.get('version_id'),
        'results': results,
    }
    runs.insert(0, run)
    runs = runs[:20]
    set_setting(_eval_runs_key(pid), json.dumps(runs))
    return jsonify(run)

@app.route('/api/eval-runs/<int:pid>', methods=['DELETE'])
def clear_eval_runs(pid):
    delete_setting(_eval_runs_key(pid))
    return jsonify({'ok': True})


@app.route('/api/import', methods=['POST'])
def import_json():
    """Import a previously exported list of prompts. Body: {prompts: [...]}."""
    data = _json_body()
    items = data.get('prompts') if isinstance(data, dict) else data
    if not isinstance(items, list):
        return jsonify({'error': 'Expected a list of prompts'}), 400
    conn = get_db()
    imported = 0
    try:
        for raw_p in items:
            if not isinstance(raw_p, dict): continue
            p = _prompt_payload(raw_p)
            if not p['content'].strip(): continue
            conn.execute('''
                INSERT INTO prompts
                    (title, description, content, categories, tags, folder_id,
                     colour_label, rating, notes, chain_ids, variable_meta, chat_turns, role_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                p['title'], p['description'], p['content'],
                p['categories'], p['tags'], p['folder_id'],
                p['colour_label'], p['rating'], p['notes'],
                p['chain_ids'], p['variable_meta'], p['chat_turns'],
                p['role_id'],
            ))
            imported += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({'imported': imported})

@app.route('/api/import/parse-raw', methods=['POST'])
def parse_raw_import():
    """Heuristically split an unformatted text blob into candidate prompts.
    Body: {text: '...'}. Returns {candidates: [{title, content}, ...]}.
    Read-only — never writes to the database."""
    data = _json_body()
    text = (data.get('text') or '').strip() if isinstance(data, dict) else ''
    if not text:
        return jsonify({'candidates': []})

    def _split(pattern, s):
        parts = re.split(pattern, s)
        return [p.strip() for p in parts if p.strip()]

    blocks = _split(r'\n[-=]{3,}\n', text)
    if len(blocks) < 2:
        blocks = _split(r'\n(?=\s*(?:\d+[.)]\s|Prompt\s+\d+|#{1,2}\s))', text)
    if len(blocks) < 2:
        blocks = _split(r'\n{3,}', text)
    if not blocks:
        blocks = [text]

    candidates = []
    for block in blocks:
        lines = block.split('\n')
        title_line = ''
        rest_start = 0
        for i, line in enumerate(lines):
            if line.strip():
                title_line = line.strip()
                rest_start = i + 1
                break
        if not title_line:
            continue
        title = re.sub(
            r'^#{1,2}\s*|^\d+[.)]\s*|^Prompt\s+\d+:?\s*', '',
            title_line, flags=re.IGNORECASE
        ).strip()
        if len(title) > 80:
            title = title[:77].rstrip() + '...'
        content = '\n'.join(lines[rest_start:]).strip()
        if not content:
            continue
        candidates.append({'title': title, 'content': content})

    return jsonify({'candidates': candidates})

# ============================================================
#  ROLES  –  AI persona / system prompt manager
# ============================================================

def serialize_role(row):
    r = dict(row)
    r.setdefault('icon',           '🎯')
    r.setdefault('colour',         '#6366f1')
    r.setdefault('persona',        '')
    r.setdefault('tone',           '')
    r.setdefault('expertise',      '')
    r.setdefault('example_phrase', '')
    raw_ep = r.get('example_phrases') or '[]'
    try:
        r['example_phrases'] = json.loads(raw_ep) if isinstance(raw_ep, str) else raw_ep
    except Exception:
        r['example_phrases'] = []
    r.setdefault('is_favorite',    0)
    r.setdefault('audience',          '')
    r.setdefault('output_format',     '')
    r.setdefault('constraints',       '')
    r.setdefault('domain',            '')
    r.setdefault('tasks',             '')
    r.setdefault('response_style',    '')
    r.setdefault('goal',              '')
    r.setdefault('outcome',           '')
    r.setdefault('opening_message',   '')
    r.setdefault('persistent_context', '')
    # knowledge_base is a JSON array of {name, when_to_use, content, include} objects
    raw_kb = r.get('knowledge_base') or '[]'
    try:
        r['knowledge_base'] = json.loads(raw_kb) if isinstance(raw_kb, str) else raw_kb
    except Exception:
        r['knowledge_base'] = []
    # skills is a JSON array of {name, description, example} objects
    raw_sk = r.get('skills') or '[]'
    try:
        r['skills'] = json.loads(raw_sk) if isinstance(raw_sk, str) else raw_sk
    except Exception:
        r['skills'] = []
    return r

def _role_payload(data):
    raw_kb = data.get('knowledge_base') or []
    if isinstance(raw_kb, str):
        try:
            raw_kb = json.loads(raw_kb)
        except Exception:
            raw_kb = []
    # Sanitise each KB entry
    kb = [
        {
            'name':         str(e.get('name', '')).strip(),
            'when_to_use':  str(e.get('when_to_use', '')).strip(),
            'content':      str(e.get('content', '')).strip(),
            'include':      bool(e.get('include', True)),
        }
        for e in raw_kb if isinstance(e, dict)
    ]

    raw_sk = data.get('skills') or []
    if isinstance(raw_sk, str):
        try:
            raw_sk = json.loads(raw_sk)
        except Exception:
            raw_sk = []
    # Sanitise each skill entry
    skills = [
        {
            'name':        str(e.get('name', '')).strip(),
            'description': str(e.get('description', '')).strip(),
            'example':     str(e.get('example', '')).strip(),
        }
        for e in raw_sk if isinstance(e, dict)
    ]

    return {
        'name':               (data.get('name') or 'Untitled role').strip() or 'Untitled role',
        'icon':               data.get('icon') or '🎯',
        'colour':             data.get('colour') or '#6366f1',
        'persona':            data.get('persona') or '',
        'tone':               data.get('tone') or '',
        'expertise':          data.get('expertise') or '',
        'example_phrase':     data.get('example_phrase') or '',
        'example_phrases': json.dumps([
            {'text': str(e.get('text',''))} for e in (data.get('example_phrases') or [])
            if e.get('text','').strip()
        ]),
        'audience':           data.get('audience') or '',
        'output_format':      data.get('output_format') or '',
        'constraints':        data.get('constraints') or '',
        'domain':             data.get('domain') or '',
        'tasks':              data.get('tasks') or '',
        'response_style':     data.get('response_style') or '',
        'goal':               data.get('goal') or '',
        'outcome':            data.get('outcome') or '',
        'opening_message':    data.get('opening_message') or '',
        'persistent_context': data.get('persistent_context') or '',
        'knowledge_base':     json.dumps(kb),
        'skills':             json.dumps(skills),
    }

# ── AI Config settings (stored in local DB settings table) ───────────────────
@app.route('/api/settings/ai-config', methods=['GET'])
def get_ai_config():
    """Return stored provider (key is never returned for security)."""
    try:
        with get_db() as con:
            row = con.execute("SELECT value FROM settings WHERE key='ai_provider'").fetchone()
            provider = row['value'] if row else 'openai'
            has_key_row = con.execute("SELECT value FROM settings WHERE key='ai_key_set'").fetchone()
            has_key = has_key_row and has_key_row['value'] == '1'
        return jsonify({'provider': provider, 'has_key': has_key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-config', methods=['POST'])
def save_ai_config():
    """Save provider selection. Key stays client-side in localStorage."""
    data = _json_body()
    provider = data.get('provider', 'openai')
    try:
        with get_db() as con:
            con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ai_provider', ?)", (provider,))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-keys', methods=['GET'])
def get_ai_keys():
    """Return stored provider API keys. Local-only app: keys live in the
    user's own DB file so they survive WebView storage resets."""
    try:
        with get_db() as con:
            rows = con.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'ai_apikey_%'"
            ).fetchall()
        return jsonify({r['key'][len('ai_apikey_'):]: r['value'] for r in rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-keys', methods=['POST'])
def save_ai_key():
    """Store or clear one provider's API key in the DB file."""
    data = _json_body()
    provider = data.get('provider') or ''
    key = (data.get('key') or '').strip()
    if not re.match(r'^[a-z0-9_]{1,40}$', provider):
        return jsonify({'error': 'unknown provider'}), 400
    try:
        with get_db() as con:
            if key:
                con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                            ('ai_apikey_' + provider, key))
            else:
                con.execute("DELETE FROM settings WHERE key = ?", ('ai_apikey_' + provider,))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-baseurls', methods=['GET'])
def get_ai_baseurls():
    """Return stored custom base URLs, keyed by provider slug."""
    try:
        with get_db() as con:
            rows = con.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'ai_baseurl_%'"
            ).fetchall()
        return jsonify({r['key'][len('ai_baseurl_'):]: r['value'] for r in rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-baseurls', methods=['POST'])
def save_ai_baseurl():
    """Store or clear one provider's custom base URL in the DB file."""
    data = _json_body()
    provider = data.get('provider') or ''
    url = (data.get('url') or '').strip()
    if not re.match(r'^[a-z0-9_]{1,40}$', provider):
        return jsonify({'error': 'unknown provider'}), 400
    try:
        with get_db() as con:
            if url:
                con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                            ('ai_baseurl_' + provider, url))
            else:
                con.execute("DELETE FROM settings WHERE key = ?", ('ai_baseurl_' + provider,))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-providers', methods=['GET'])
def get_ai_providers():
    """Return custom provider tabs the user has added (slug + label)."""
    try:
        with get_db() as con:
            rows = con.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'ai_customprovider_%'"
            ).fetchall()
        return jsonify([
            {'slug': r['key'][len('ai_customprovider_'):], 'label': r['value']}
            for r in rows
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/ai-providers', methods=['POST'])
def save_ai_provider():
    """Add a custom provider tab (slug + display label) to the DB file."""
    data = _json_body()
    slug = data.get('slug') or ''
    label = (data.get('label') or '').strip()
    if not re.match(r'^[a-z0-9_]{1,40}$', slug) or not label:
        return jsonify({'error': 'invalid provider'}), 400
    try:
        with get_db() as con:
            con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                        ('ai_customprovider_' + slug, label))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/roles', methods=['GET'])
def list_roles():
    conn  = get_db()
    favs  = request.args.get('favorites', '0')
    q     = 'SELECT * FROM roles WHERE 1=1'
    params = []
    if favs == '1':
        q += ' AND is_favorite=1'
    q += ' ORDER BY updated_at DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([serialize_role(r) for r in rows])

@app.route('/api/roles/<int:rid>', methods=['GET'])
def get_role(rid):
    conn = get_db()
    row  = conn.execute('SELECT * FROM roles WHERE id=?', (rid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(serialize_role(row))

@app.route('/api/roles', methods=['POST'])
def create_role():
    p = _role_payload(_json_body())
    conn = get_db()
    try:
        cur = conn.execute('''
            INSERT INTO roles (name, icon, colour, persona, tone, expertise, example_phrase, example_phrases,
                               knowledge_base, skills, audience, output_format, constraints, domain, tasks,
                               response_style, goal, outcome, opening_message, persistent_context)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (p['name'], p['icon'], p['colour'], p['persona'],
              p['tone'], p['expertise'], p['example_phrase'], p['example_phrases'], p['knowledge_base'], p['skills'],
              p['audience'], p['output_format'], p['constraints'], p['domain'], p['tasks'],
              p['response_style'], p['goal'], p['outcome'], p['opening_message'], p['persistent_context']))
        rid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': rid})

@app.route('/api/roles/<int:rid>', methods=['PUT'])
def update_role(rid):
    p = _role_payload(_json_body())
    conn = get_db()
    try:
        conn.execute('''
            UPDATE roles
               SET name=?, icon=?, colour=?, persona=?, tone=?, expertise=?,
                   example_phrase=?, example_phrases=?, knowledge_base=?, skills=?,
                   audience=?, output_format=?, constraints=?, domain=?, tasks=?,
                   response_style=?, goal=?, outcome=?, opening_message=?, persistent_context=?,
                   updated_at=CURRENT_TIMESTAMP
             WHERE id=?
        ''', (p['name'], p['icon'], p['colour'], p['persona'],
              p['tone'], p['expertise'], p['example_phrase'], p['example_phrases'], p['knowledge_base'], p['skills'],
              p['audience'], p['output_format'], p['constraints'], p['domain'], p['tasks'],
              p['response_style'], p['goal'], p['outcome'], p['opening_message'], p['persistent_context'], rid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/roles/<int:rid>', methods=['DELETE'])
def delete_role(rid):
    conn = get_db()
    conn.execute('DELETE FROM roles WHERE id=?', (rid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/roles/<int:rid>/duplicate', methods=['POST'])
def duplicate_role(rid):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM roles WHERE id=?', (rid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        r = serialize_role(row)
        kb_json = json.dumps(r.get('knowledge_base', []))
        sk_json = json.dumps(r.get('skills', []))
        cur = conn.execute(
            'INSERT INTO roles (name, icon, colour, persona, tone, expertise, example_phrase, example_phrases, knowledge_base, skills) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (r['name'] + ' (Copy)', r['icon'], r['colour'], r['persona'],
             r['tone'], r['expertise'], r['example_phrase'],
             json.dumps(r.get('example_phrases', [])),
             kb_json, sk_json)
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': new_id})

@app.route('/api/roles/<int:rid>/favorite', methods=['POST'])
def toggle_role_favorite(rid):
    conn = get_db()
    row  = conn.execute('SELECT is_favorite FROM roles WHERE id=?', (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    nv = 0 if row['is_favorite'] else 1
    conn.execute('UPDATE roles SET is_favorite=? WHERE id=?', (nv, rid))
    conn.commit()
    conn.close()
    return jsonify({'is_favorite': nv})

# ============================================================
#  ROLE ATTACHMENT  —  attach/detach a role to/from a prompt
# ============================================================

@app.route('/api/prompts/<int:pid>/role', methods=['PATCH'])
def set_prompt_role(pid):
    """Set or clear the role_id on a prompt."""
    data = _json_body()
    rid = data.get('role_id')
    try:
        rid = int(rid) if rid not in (None, '', 'null') else None
    except (TypeError, ValueError):
        rid = None
    conn = get_db()
    try:
        conn.execute('UPDATE prompts SET role_id=? WHERE id=?', (rid, pid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'role_id': rid})


@app.route('/api/roles/<int:rid>/prompt-count', methods=['GET'])
def role_prompt_count(rid):
    """Return count of prompts using this role."""
    conn = get_db()
    try:
        row = conn.execute('SELECT COUNT(*) as n FROM prompts WHERE role_id=?', (rid,)).fetchone()
    finally:
        conn.close()
    return jsonify({'count': row['n'] if row else 0})


# ============================================================
#  SETTINGS — author name + role chip display
# ============================================================

@app.route('/api/settings/author', methods=['GET'])
def get_author_name():
    stored = get_setting('author_name')
    if stored:
        return jsonify({'author_name': stored})
    try:
        default = os.getlogin()
    except Exception:
        default = ''
    return jsonify({'author_name': default})

@app.route('/api/settings/author', methods=['POST'])
def set_author_name():
    data = _json_body()
    name = (data.get('author_name') or '').strip()
    if name:
        set_setting('author_name', name)
    else:
        delete_setting('author_name')
    return jsonify({'ok': True})


@app.route('/api/settings/role-chips-always', methods=['GET'])
def get_role_chips_setting():
    val = get_setting('role_chips_always_visible')
    return jsonify({'enabled': val == '1'})

@app.route('/api/settings/role-chips-always', methods=['POST'])
def set_role_chips_setting():
    data = _json_body()
    set_setting('role_chips_always_visible', '1' if data.get('enabled') else '0')
    return jsonify({'ok': True})



# ============================================================
#  PACK IMPORT — parse and preview a .plp ZIP
# ============================================================

def _parse_plp_bytes(raw_bytes):
    """
    Parse raw .plp ZIP bytes and return a Flask JSON response with
    { manifest, prompts, roles } — conflict flags included.
    Shared by import_pack (file upload) and import_pack_from_path (local path).
    """
    try:
        buf = io.BytesIO(raw_bytes)
        with zipfile.ZipFile(buf, 'r') as zf:
            names = zf.namelist()
            if 'manifest.json' not in names:
                return jsonify({'error': 'Invalid .plp file: missing manifest'}), 400
            manifest = json.loads(zf.read('manifest.json'))
            prompts  = json.loads(zf.read('prompts.json')) if 'prompts.json' in names else []
            roles    = json.loads(zf.read('roles.json'))   if 'roles.json'   in names else []
    except zipfile.BadZipFile:
        return jsonify({'error': 'File appears corrupt or is not a valid .plp pack'}), 400
    except (json.JSONDecodeError, KeyError) as e:
        return jsonify({'error': f'Malformed pack data: {str(e)}'}), 400

    if not isinstance(prompts, list) or not isinstance(roles, list):
        return jsonify({'error': 'Invalid pack structure'}), 400
    if not prompts and not roles:
        return jsonify({'error': 'This pack contains no prompts or roles'}), 400

    conn = get_db()
    try:
        existing_titles = {r[0].lower() for r in conn.execute('SELECT title FROM prompts').fetchall()}
        existing_names  = {r[0].lower() for r in conn.execute('SELECT name  FROM roles').fetchall()}
    finally:
        conn.close()

    for p in prompts:
        p['_conflict'] = (p.get('title') or '').lower() in existing_titles
    for r in roles:
        r['_conflict'] = (r.get('name') or '').lower() in existing_names

    return jsonify({'manifest': manifest, 'prompts': prompts, 'roles': roles})


@app.route('/api/packs/import', methods=['POST'])
def import_pack():
    """Parse uploaded .plp — returns manifest + prompts + roles for preview. No DB writes."""
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No file uploaded'}), 400
    return _parse_plp_bytes(f.read())


@app.route('/api/packs/commit', methods=['POST'])
def commit_pack():
    """Import selected prompts and roles from a parsed pack preview."""
    data    = _json_body()
    prompts = data.get('prompts') or []
    roles   = data.get('roles')   or []
    attach  = data.get('roleAttachments') or {}

    conn = get_db()
    try:
        role_id_map = {}
        roles_added = 0
        for i, r in enumerate(roles):
            if not isinstance(r, dict): continue
            cur = conn.execute(
                'INSERT INTO roles (name, icon, colour, persona, tone, expertise, example_phrase) VALUES (?,?,?,?,?,?,?)',
                (
                    (r.get('name') or 'Imported Role').strip(),
                    r.get('icon') or '0x1F3AF',
                    r.get('colour') or '#6366f1',
                    r.get('persona') or '',
                    r.get('tone') or '',
                    r.get('expertise') or '',
                    r.get('example_phrase') or '',
                )
            )
            role_id_map[str(r.get('id', i))] = cur.lastrowid
            role_id_map[str(i)] = cur.lastrowid
            roles_added += 1

        prompts_added = 0
        for i, raw_p in enumerate(prompts):
            if not isinstance(raw_p, dict): continue
            p = _prompt_payload(raw_p)
            if not (raw_p.get('content') or '').strip(): continue

            new_role_id = None
            attach_key = str(i)
            if attach_key in attach:
                new_role_id = role_id_map.get(str(attach[attach_key]))
            elif raw_p.get('role_id') is not None:
                new_role_id = role_id_map.get(str(raw_p['role_id']))

            conn.execute('''
                INSERT INTO prompts
                    (title, description, content, categories, tags, folder_id,
                     colour_label, rating, notes, chain_ids, variable_meta, chat_turns, role_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                p['title'], p['description'], p['content'],
                p['categories'], p['tags'], p['folder_id'],
                p['colour_label'], p['rating'], p['notes'],
                p['chain_ids'], p['variable_meta'], p['chat_turns'],
                new_role_id,
            ))
            prompts_added += 1

        conn.commit()
    finally:
        conn.close()

    return jsonify({'promptsAdded': prompts_added, 'rolesAdded': roles_added})


# ============================================================
#  PENDING IMPORT — temp flag file for single-instance .plp launch
# ============================================================

@app.route('/api/pending-import', methods=['GET'])
def get_pending_import():
    flag_path = os.path.join(get_data_dir(), 'pending_import.plp_path')
    if os.path.exists(flag_path):
        try:
            with open(flag_path, 'r', encoding='utf-8') as fh:
                plp_path = fh.read().strip()
            os.remove(flag_path)
            return jsonify({'pending': True, 'path': plp_path})
        except Exception:
            pass
    return jsonify({'pending': False})

@app.route('/api/pending-import', methods=['POST'])
def set_pending_import():
    data = _json_body()
    plp_path = data.get('path') or ''
    if plp_path:
        flag_path = os.path.join(get_data_dir(), 'pending_import.plp_path')
        try:
            with open(flag_path, 'w', encoding='utf-8') as fh:
                fh.write(plp_path)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})


# ============================================================
#  IMPORT FROM PATH — parse a .plp file on local disk (used by
#  the single-instance pending-import flow)
# ============================================================

@app.route('/api/packs/import-from-path', methods=['POST'])
def import_pack_from_path():
    """
    Accepts { "path": "/absolute/path/to/file.plp" } and returns the same
    preview payload as POST /api/packs/import (multipart upload).
    The .plp file is read directly from disk — no upload needed.
    """
    data = _json_body()
    plp_path = (data.get('path') or '').strip()

    if not plp_path:
        return jsonify({'error': 'No path provided'}), 400
    if not os.path.isfile(plp_path):
        return jsonify({'error': f'File not found: {plp_path}'}), 404
    if not plp_path.lower().endswith('.plp'):
        return jsonify({'error': 'File is not a .plp pack'}), 400

    try:
        with open(plp_path, 'rb') as fh:
            raw = fh.read()
    except OSError as e:
        return jsonify({'error': str(e)}), 500

    # Delegate to the shared parser used by the multipart import endpoint
    return _parse_plp_bytes(raw)


# ============================================================
# STARTER TEMPLATES
# ============================================================
@app.route('/api/starter-templates', methods=['POST'])
def load_starter_templates():
    """Seed the library with starter prompts if empty. Returns {loaded: N}."""
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM prompts').fetchone()[0]
    if count > 0:
        conn.close()
        return jsonify({'loaded': 0, 'skipped': 'Library already has prompts'})

    starters = [
        ('Cold Email Outreach',
         'Personalised cold email for a prospect.',
         'Write a short cold email to [[prospect_name]] at [[company_name]]. They work in [[industry]]. The email should be friendly, under 100 words, and end with a clear call to action. Do not use corporate buzzwords.',
         'Copywriting', 'email,outreach,sales'),
        ('Summarise an Article',
         'Condense any article to its core points.',
         'Summarise the following article in 5 bullet points. Each bullet should be one sentence. Focus on the most actionable insights for [[audience]].\n\n[[article_text]]',
         'Research', 'summary,reading,research'),
        ('Rewrite for Clarity',
         'Simplify dense or jargon-heavy text.',
         'Rewrite the following text so it is clear, direct, and easy to understand. Target reading level: [[reading_level]]. Keep the meaning identical. Cut anything that does not add value.\n\n[[original_text]]',
         'Editing', 'rewrite,clarity,editing'),
        ('LinkedIn Post',
         'Write a LinkedIn post from a topic or idea.',
         'Write a LinkedIn post about [[topic]]. Tone: [[tone]]. Length: 150-200 words. Open with a hook. No hashtags in the body - add 3 relevant hashtags at the end only. Do not start with "I".',
         'Copywriting', 'linkedin,social,content'),
        ('Meeting Agenda',
         'Generate a structured meeting agenda.',
         'Create a meeting agenda for a [[duration]]-minute meeting on [[topic]] with [[attendees]]. Include: goal of the meeting, 4-5 agenda items with time allocations, and a clear next-steps slot at the end.',
         'Productivity', 'meeting,agenda,planning'),
        ('Explain Like I\'m 10',
         'Break down a complex concept simply.',
         'Explain [[concept]] as if talking to a 10-year-old. Use a simple analogy if helpful. Keep it under 150 words. Avoid technical terms - if you must use one, explain it immediately.',
         'Research', 'explainer,learning,simplify'),
        ('Weekly Reflection',
         'Structured end-of-week review prompt.',
         'Help me reflect on my week. Ask me these questions one at a time:\n1. What did I accomplish this week that I am proud of?\n2. What did I leave unfinished and why?\n3. What one thing, if done next week, would make the most difference?\n4. What should I stop doing?',
         'Productivity', 'reflection,planning,weekly'),
        ('Product Description',
         'Write a compelling product description.',
         'Write a product description for [[product_name]]. Key features: [[features]]. Target customer: [[target_customer]]. Tone: [[tone]]. Length: 80-120 words. Focus on benefits over features. End with a single clear CTA.',
         'Copywriting', 'ecommerce,product,marketing'),
        ('Bug Report',
         'Structured prompt for reporting a technical bug.',
         'Write a clear bug report:\n\nIssue: [[issue_description]]\nSteps to reproduce: [[steps]]\nExpected: [[expected]]\nActual: [[actual]]\nEnvironment: [[environment]]\n\nFormat it for a GitHub issue. Keep it factual and concise.',
         'Development', 'dev,bug,github'),
        ('Cover Letter',
         'Write a focused cover letter for a job application.',
         'Write a cover letter for a [[job_title]] role at [[company_name]]. My background: [[background]]. Key skills: [[skills]]. Keep it to 3 short paragraphs. Confident tone. No generic phrases.',
         'Career', 'career,job,cover-letter'),
    ]

    loaded = 0
    for title, desc, body, cats, tags in starters:
        try:
            conn.execute(
                'INSERT INTO prompts (title, description, content, categories, tags) VALUES (?,?,?,?,?)',
                (title, desc, body, cats, tags)
            )
            loaded += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({'loaded': loaded})


# ============================================================
#  SAVE FILE — opens a native Save As dialog via tkinter
#  and writes the export content to the chosen path.
# ============================================================

@app.route('/api/save-file', methods=['POST'])
def save_file_dialog():
    """
    Accepts { "filename": "prompts-2026-05-23.json", "content": "...", "mime": "application/json" }
    Opens a native Save As dialog using tkinter.filedialog (available on Windows with Python).
    Returns { "saved": true, "path": "C:\\Users\\...\\Downloads\\prompts.json" } or
            { "saved": false } if the user cancelled.
    """
    data     = _json_body()
    filename = data.get('filename') or 'export.json'
    content  = data.get('content') or ''
    mime     = data.get('mime') or 'application/json'

    ext_map = {
        'application/json': [('JSON files', '*.json'), ('All files', '*.*')],
        'text/markdown':    [('Markdown files', '*.md'), ('All files', '*.*')],
        'text/csv':         [('CSV files', '*.csv'), ('All files', '*.*')],
        'application/zip':  [('ZIP archives', '*.zip'), ('All files', '*.*')],
    }
    filetypes = ext_map.get(mime, [('All files', '*.*')])

    downloads = os.path.join(os.path.expanduser('~'), 'Downloads')
    result = {}
    done   = threading.Event()

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.asksaveasfilename(
                parent=root,
                initialdir=downloads,
                initialfile=filename,
                filetypes=filetypes,
                defaultextension=os.path.splitext(filename)[1] or '.json',
                title='Save export as…',
            )
            root.destroy()
            result['path'] = path
        except Exception as e:
            result['error'] = str(e)
        finally:
            done.set()

    t = threading.Thread(target=_run_dialog, daemon=True)
    t.start()
    done.wait(timeout=120)

    chosen = result.get('path', '')
    if not chosen:
        return jsonify({'saved': False})

    try:
        if mime == 'application/zip':
            import base64
            raw_bytes = base64.b64decode(content)
            with open(chosen, 'wb') as fh:
                fh.write(raw_bytes)
        else:
            with open(chosen, 'w', encoding='utf-8') as fh:
                fh.write(content)
        return jsonify({'saved': True, 'path': chosen})
    except Exception as e:
        return jsonify({'saved': False, 'error': str(e)})


# ============================================================
#  PROMPT PLAYGROUND
#  A scratch-pad workspace for drafting, comparing, and
#  iterating on prompts before committing them to the library.
#  Fully local — sessions stored in the same SQLite DB.
# ============================================================

def _ensure_playground_tables():
    """Create playground tables if they don't exist yet."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS playground_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL DEFAULT 'Untitled session',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            is_pinned   INTEGER NOT NULL DEFAULT 0,
            note        TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS playground_panels (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   INTEGER NOT NULL REFERENCES playground_sessions(id) ON DELETE CASCADE,
            slot         INTEGER NOT NULL DEFAULT 0,
            label        TEXT    NOT NULL DEFAULT '',
            content      TEXT    NOT NULL DEFAULT '',
            model_tag    TEXT    NOT NULL DEFAULT '',
            output       TEXT    NOT NULL DEFAULT '',
            score        INTEGER,
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    db.commit()


def _serialize_session(row):
    return {
        'id':         row['id'],
        'title':      row['title'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'is_pinned':  bool(row['is_pinned']),
        'note':       row['note'] or '',
    }


def _serialize_panel(row):
    return {
        'id':         row['id'],
        'session_id': row['session_id'],
        'slot':       row['slot'],
        'label':      row['label'] or '',
        'content':    row['content'] or '',
        'model_tag':  row['model_tag'] or '',
        'output':     row['output'] or '',
        'score':      row['score'],
        'updated_at': row['updated_at'],
    }


@app.route('/api/playground/sessions', methods=['GET'])
def pg_list_sessions():
    _ensure_playground_tables()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM playground_sessions ORDER BY is_pinned DESC, updated_at DESC"
    ).fetchall()
    return jsonify([_serialize_session(r) for r in rows])


@app.route('/api/playground/sessions', methods=['POST'])
def pg_create_session():
    _ensure_playground_tables()
    data  = _json_body()
    title = (data.get('title') or 'Untitled session').strip()[:120]
    note  = (data.get('note') or '').strip()
    db    = get_db()
    cur   = db.execute(
        "INSERT INTO playground_sessions (title, note) VALUES (?, ?)",
        (title, note)
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM playground_sessions WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return jsonify(_serialize_session(row)), 201


@app.route('/api/playground/sessions/<int:sid>', methods=['GET'])
def pg_get_session(sid):
    _ensure_playground_tables()
    db  = get_db()
    row = db.execute(
        "SELECT * FROM playground_sessions WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    panels = db.execute(
        "SELECT * FROM playground_panels WHERE session_id=? ORDER BY slot", (sid,)
    ).fetchall()
    data = _serialize_session(row)
    data['panels'] = [_serialize_panel(p) for p in panels]
    return jsonify(data)


@app.route('/api/playground/sessions/<int:sid>', methods=['PUT'])
def pg_update_session(sid):
    _ensure_playground_tables()
    data  = _json_body()
    db    = get_db()
    row   = db.execute(
        "SELECT id FROM playground_sessions WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    fields, vals = [], []
    if 'title' in data:
        fields.append('title=?'); vals.append((data['title'] or '').strip()[:120])
    if 'note' in data:
        fields.append('note=?'); vals.append((data['note'] or '').strip())
    if 'is_pinned' in data:
        fields.append('is_pinned=?'); vals.append(1 if data['is_pinned'] else 0)
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    fields.append("updated_at=datetime('now')")
    vals.append(sid)
    db.execute(f"UPDATE playground_sessions SET {', '.join(fields)} WHERE id=?", vals)
    db.commit()
    row = db.execute(
        "SELECT * FROM playground_sessions WHERE id=?", (sid,)
    ).fetchone()
    return jsonify(_serialize_session(row))


@app.route('/api/playground/sessions/<int:sid>', methods=['DELETE'])
def pg_delete_session(sid):
    _ensure_playground_tables()
    db = get_db()
    db.execute("DELETE FROM playground_sessions WHERE id=?", (sid,))
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/playground/sessions/<int:sid>/panels', methods=['PUT'])
def pg_save_panels(sid):
    """
    Replaces all panels for a session atomically.
    Body: { panels: [ { slot, label, content, model_tag, output, score }, ... ] }
    """
    _ensure_playground_tables()
    db = get_db()
    row = db.execute(
        "SELECT id FROM playground_sessions WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return jsonify({'error': 'Session not found'}), 404
    data   = _json_body()
    panels = data.get('panels') or []
    db.execute("DELETE FROM playground_panels WHERE session_id=?", (sid,))
    for p in panels:
        db.execute(
            """INSERT INTO playground_panels
               (session_id, slot, label, content, model_tag, output, score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                int(p.get('slot', 0)),
                (p.get('label') or '')[:80],
                p.get('content') or '',
                (p.get('model_tag') or '')[:60],
                p.get('output') or '',
                p.get('score') if isinstance(p.get('score'), int) else None,
            )
        )
    db.execute(
        "UPDATE playground_sessions SET updated_at=datetime('now') WHERE id=?", (sid,)
    )
    db.commit()
    saved = db.execute(
        "SELECT * FROM playground_panels WHERE session_id=? ORDER BY slot", (sid,)
    ).fetchall()
    return jsonify([_serialize_panel(p) for p in saved])


@app.route('/api/playground/sessions/<int:sid>/from-prompt/<int:pid>', methods=['POST'])
def pg_seed_from_prompt(sid, pid):
    """
    Pre-fills panel 0 with the content of prompt pid.
    Handy 'Send to Playground' action from a prompt card.
    """
    _ensure_playground_tables()
    db  = get_db()
    row = db.execute("SELECT * FROM playground_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return jsonify({'error': 'Session not found'}), 404
    prompt = db.execute("SELECT * FROM prompts WHERE id=?", (pid,)).fetchone()
    if not prompt:
        return jsonify({'error': 'Prompt not found'}), 404
    # Remove existing slot-0 panel for this session
    db.execute(
        "DELETE FROM playground_panels WHERE session_id=? AND slot=0", (sid,)
    )
    db.execute(
        """INSERT INTO playground_panels (session_id, slot, label, content, model_tag)
           VALUES (?, 0, ?, ?, '')""",
        (sid, prompt['title'], prompt['content'])
    )
    db.execute(
        "UPDATE playground_sessions SET updated_at=datetime('now') WHERE id=?", (sid,)
    )
    db.commit()
    return jsonify({'ok': True})




import hashlib
from datetime import datetime

@app.route('/api/licence/status', methods=['GET'])
def licence_status():
    """
    Check if this machine has a valid licence.
    Returns: {
        "licensed": bool,
        "key": str (masked, last 4 chars only),
        "activated": str (ISO timestamp)
    }
    """
    key = get_setting('licence_key')
    activated = get_setting('licence_activated')

    if key and activated:
        masked_key = key[:10] + '*' * (len(key) - 14) + key[-4:]
        return jsonify({
            'licensed': True,
            'key': masked_key,
            'activated': activated
        })
    else:
        return jsonify({
            'licensed': False,
            'key': None,
            'activated': None
        })


# ══ Component workspace ═════════════════════════════════════════════

def serialize_component(row):
    b = dict(row)
    b['description'] = b.get('description') or ''
    b['source']      = b.get('source') or 'user'
    return b

def serialize_composition(row, blocks=None):
    comp = dict(row)
    comp['tags']       = _normalise_list(comp.get('tags') or '')
    comp['view_state'] = _json_value(comp.get('view_state'), {})
    comp['is_draft']   = int(comp.get('is_draft') or 0)
    comp['blocks']     = [dict(b) for b in (blocks or [])]
    return comp

def _composition_payload(data):
    """Shared field mapping for composition create and update."""
    return (
        (data.get('title') or '').strip(),
        _folder_id(data.get('folder_id')),
        _list_for_db(data.get('tags', '')),
        _json_for_db(data.get('view_state'), {}),
        1 if data.get('is_draft', 1) else 0,
    )

def _replace_composition_blocks(conn, cid, blocks):
    """Blocks are replaced wholesale — the canvas is the source of truth."""
    conn.execute('DELETE FROM composition_blocks WHERE composition_id=?', (cid,))
    for i, blk in enumerate(blocks or []):
        if not isinstance(blk, dict):
            continue
        ref = str(blk.get('block_ref') or '').strip()
        if not ref:
            continue
        conn.execute(
            '''INSERT INTO composition_blocks
               (composition_id, block_ref, position, x, y, z_index, collapsed, body_override)
               VALUES (?,?,?,?,?,?,?,?)''',
            (cid, ref, _int_between(blk.get('position', i), 0, 100000, i),
             float(blk.get('x') or 0), float(blk.get('y') or 0),
             _int_between(blk.get('z_index', 0), 0, 100000, 0),
             1 if blk.get('collapsed') else 0,
             blk.get('body_override'))
        )


@app.route('/api/components', methods=['GET'])
def get_components():
    conn = get_db()
    rows = conn.execute('SELECT * FROM component_blocks ORDER BY category, name').fetchall()
    conn.close()
    return jsonify([serialize_component(r) for r in rows])

@app.route('/api/components', methods=['POST'])
def create_component():
    data = _json_body()
    name = (data.get('name') or '').strip()
    body = data.get('body') or ''
    if not name or not body.strip():
        return jsonify({'error': 'name and body are required'}), 400
    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO component_blocks (name, category, body, description, source, forked_from)
           VALUES (?,?,?,?,?,?)''',
        (name, (data.get('category') or 'misc').strip(), body,
         data.get('description') or '',
         'fork' if data.get('forked_from') else 'user',
         data.get('forked_from'))
    )
    bid = cur.lastrowid
    conn.commit()
    row = conn.execute('SELECT * FROM component_blocks WHERE id=?', (bid,)).fetchone()
    conn.close()
    return jsonify(serialize_component(row)), 201

@app.route('/api/components/<int:bid>', methods=['PUT'])
def update_component(bid):
    data = _json_body()
    conn = get_db()
    row = conn.execute('SELECT * FROM component_blocks WHERE id=?', (bid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    conn.execute(
        '''UPDATE component_blocks
           SET name=?, category=?, body=?, description=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=?''',
        ((data.get('name') or row['name']).strip(),
         (data.get('category') or row['category']).strip(),
         data.get('body') if data.get('body') is not None else row['body'],
         data.get('description') if data.get('description') is not None else row['description'],
         bid)
    )
    conn.commit()
    updated = conn.execute('SELECT * FROM component_blocks WHERE id=?', (bid,)).fetchone()
    conn.close()
    return jsonify(serialize_component(updated))

@app.route('/api/components/<int:bid>/usage', methods=['GET'])
def component_usage(bid):
    """How many saved compositions reference this block — shown before delete."""
    conn = get_db()
    n = conn.execute(
        'SELECT COUNT(DISTINCT composition_id) FROM composition_blocks WHERE block_ref=?',
        ('user:%d' % bid,)
    ).fetchone()[0]
    conn.close()
    return jsonify({'composition_count': n})

@app.route('/api/components/<int:bid>', methods=['DELETE'])
def delete_component(bid):
    # Placements are deliberately left in place. serialize keeps body_override,
    # so a composition still renders its text with the source block gone.
    conn = get_db()
    conn.execute('DELETE FROM component_blocks WHERE id=?', (bid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/compositions', methods=['GET'])
def get_compositions():
    conn = get_db()
    rows = conn.execute('SELECT * FROM compositions ORDER BY updated_at DESC').fetchall()
    counts = {}
    for r in conn.execute(
        'SELECT composition_id, COUNT(*) n FROM composition_blocks GROUP BY composition_id'
    ).fetchall():
        counts[r['composition_id']] = r['n']
    conn.close()
    out = []
    for r in rows:
        comp = serialize_composition(r)
        comp['block_count'] = counts.get(r['id'], 0)
        out.append(comp)
    return jsonify(out)

@app.route('/api/compositions/<int:cid>', methods=['GET'])
def get_composition(cid):
    conn = get_db()
    row = conn.execute('SELECT * FROM compositions WHERE id=?', (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    blocks = conn.execute(
        'SELECT * FROM composition_blocks WHERE composition_id=? ORDER BY position', (cid,)
    ).fetchall()
    conn.close()
    return jsonify(serialize_composition(row, blocks))

@app.route('/api/compositions', methods=['POST'])
def create_composition():
    data = _json_body()
    title, folder_id, tags, view_state, is_draft = _composition_payload(data)
    if not title:
        return jsonify({'error': 'title is required'}), 400
    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO compositions (title, prompt_id, folder_id, tags, view_state, is_draft)
           VALUES (?,?,?,?,?,?)''',
        (title, data.get('prompt_id'), folder_id, tags, view_state, is_draft)
    )
    cid = cur.lastrowid
    _replace_composition_blocks(conn, cid, data.get('blocks'))
    conn.commit()
    row = conn.execute('SELECT * FROM compositions WHERE id=?', (cid,)).fetchone()
    blocks = conn.execute(
        'SELECT * FROM composition_blocks WHERE composition_id=? ORDER BY position', (cid,)
    ).fetchall()
    conn.close()
    return jsonify(serialize_composition(row, blocks)), 201

@app.route('/api/compositions/<int:cid>', methods=['PUT'])
def update_composition(cid):
    data = _json_body()
    conn = get_db()
    row = conn.execute('SELECT * FROM compositions WHERE id=?', (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    # Merge, don't replace: a partial payload must not silently clear the
    # fields it omits. Only keys actually present in the request are applied.
    title      = (data.get('title') or '').strip() or row['title']
    prompt_id  = data['prompt_id'] if 'prompt_id' in data else row['prompt_id']
    folder_id  = _folder_id(data['folder_id']) if 'folder_id' in data else row['folder_id']
    tags       = _list_for_db(data['tags']) if 'tags' in data else row['tags']
    view_state = _json_for_db(data['view_state'], {}) if 'view_state' in data else row['view_state']
    is_draft   = (1 if data['is_draft'] else 0) if 'is_draft' in data else row['is_draft']

    conn.execute(
        '''UPDATE compositions
           SET title=?, prompt_id=?, folder_id=?, tags=?, view_state=?, is_draft=?,
               updated_at=CURRENT_TIMESTAMP
           WHERE id=?''',
        (title, prompt_id, folder_id, tags, view_state, is_draft, cid)
    )
    if 'blocks' in data:
        _replace_composition_blocks(conn, cid, data.get('blocks'))
    conn.commit()
    updated = conn.execute('SELECT * FROM compositions WHERE id=?', (cid,)).fetchone()
    blocks = conn.execute(
        'SELECT * FROM composition_blocks WHERE composition_id=? ORDER BY position', (cid,)
    ).fetchall()
    conn.close()
    return jsonify(serialize_composition(updated, blocks))

@app.route('/api/compositions/<int:cid>', methods=['DELETE'])
def delete_composition(cid):
    conn = get_db()
    conn.execute('DELETE FROM compositions WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============================================================
# PROMPT COMPONENT GRAPH
# ============================================================

def _composition_owned(cid):
    conn = get_db()
    try:
        return conn.execute('SELECT * FROM compositions WHERE id=?', (cid,)).fetchone()
    finally:
        conn.close()

@app.route('/api/compositions/<int:cid>/graph', methods=['GET', 'PUT'])
def composition_graph(cid):
    composition = _composition_owned(cid)
    if not composition:
        return jsonify({'error': 'Composition not found'}), 404
    conn = get_db()
    try:
        if request.method == 'GET':
            nodes = [dict(r) for r in conn.execute(
                'SELECT * FROM composition_blocks WHERE composition_id=? ORDER BY z_index, position',
                (cid,)
            ).fetchall()]
            edges = [dict(r) for r in conn.execute(
                'SELECT * FROM composition_edges WHERE composition_id=? ORDER BY id',
                (cid,)
            ).fetchall()]
            return jsonify({
                'composition': dict(composition),
                'nodes': nodes,
                'edges': edges
            })
        data = request.get_json(silent=True) or {}
        nodes = data.get('nodes') or []
        edges = data.get('edges') or []
        view_state = data.get('view_state') or {}
        conn.execute('DELETE FROM composition_edges WHERE composition_id=?', (cid,))
        conn.execute('DELETE FROM composition_blocks WHERE composition_id=?', (cid,))
        node_map = {}
        for pos, node in enumerate(nodes):
            cur = conn.execute(
                '''INSERT INTO composition_blocks
                   (composition_id,block_ref,position,x,y,z_index,collapsed,body_override)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (
                    cid,
                    str(node.get('block_ref') or ''),
                    pos,
                    float(node.get('x') or 0),
                    float(node.get('y') or 0),
                    int(node.get('z_index') or pos),
                    1 if node.get('collapsed') else 0,
                    node.get('body_override')
                )
            )
            node_map[str(node.get('id') or pos)] = cur.lastrowid
        for edge in edges:
            source = node_map.get(str(edge.get('source')))
            target = node_map.get(str(edge.get('target')))
            if not source or not target or source == target:
                continue
            conn.execute(
                '''INSERT INTO composition_edges
                   (composition_id,source_block_id,target_block_id,source_port,target_port,relation)
                   VALUES(?,?,?,?,?,?)''',
                (
                    cid,
                    source,
                    target,
                    edge.get('source_port') or 'right',
                    edge.get('target_port') or 'left',
                    edge.get('relation') or 'sequence'
                )
            )
        conn.execute(
            'UPDATE compositions SET view_state=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (json.dumps(view_state), cid)
        )
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()

@app.route('/api/compositions/graph', methods=['POST'])
def create_graph_composition():
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or 'Untitled composition').strip()[:160]
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO compositions(title,view_state,is_draft) VALUES(?,?,1)',
            (title, json.dumps(data.get('view_state') or {}))
        )
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({'id': cid, 'title': title})

# Prompt Components graph routes.
