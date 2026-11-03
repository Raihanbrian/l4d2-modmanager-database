"""Explicit, bounded public Steam metadata retrieval; no browser or VPK URLs."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import http.client
import json
import re
import ssl
import time
import html
from urllib.parse import urlencode

from .storage import CatalogError

HOST = 'api.steampowered.com'
ENDPOINT = '/ISteamRemoteStorage/GetPublishedFileDetails/v1/'
SOURCE = 'Steam GetPublishedFileDetails v1'
MAX_RESPONSE = 2 * 1024 * 1024
BATCH_SIZE = 20
MAX_ITEMS = 200


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[1-9][0-9]{0,19}', value)) and int(value) <= 18446744073709551615


def workshop_url(value):
    return 'https://steamcommunity.com/sharedfiles/filedetails/?id=' + value if valid_id(value) else None


class MetadataError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def request_details(ids):
    """One HTTPS POST, fixed host/path, no credentials/proxy/redirects/retries."""
    if not ids or len(ids) > BATCH_SIZE or len(set(ids)) != len(ids) or not all(map(valid_id, ids)):
        raise ValueError('Only bounded batches of distinct numeric Workshop IDs are allowed.')
    body = urlencode({'itemcount': len(ids), **{f'publishedfileids[{i}]': value for i, value in enumerate(ids)}})
    connection = http.client.HTTPSConnection(HOST, timeout=8, context=ssl.create_default_context())
    try:
        connection.request('POST', ENDPOINT, body, {'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'L4D2ModDatabase/0.1'})
        response = connection.getresponse()
        if response.status == 429:
            raise MetadataError('rate_limited', 'Steam requested a pause. Cached information is retained; retry later.')
        if response.status != 200:
            raise MetadataError('network_error', f'Steam HTTP {response.status}; cached information retained.')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise MetadataError('malformed', 'Unsupported compressed Steam response.')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE):
            raise MetadataError('malformed', 'Steam response exceeds the size limit.')
        content_type = response.getheader('Content-Type', '').lower()
        if not any(value in content_type for value in ('application/json', 'text/json')):
            raise MetadataError('malformed', 'Steam did not return JSON.')
        chunks = []; size = 0; started = time.monotonic()
        while True:
            if time.monotonic() - started > 20:
                raise MetadataError('network_error', 'Steam response timed out.')
            chunk = response.read(min(8192, MAX_RESPONSE + 1 - size))
            if not chunk: break
            size += len(chunk)
            if size > MAX_RESPONSE: raise MetadataError('malformed', 'Steam response exceeds the size limit.')
            chunks.append(chunk)
        return b''.join(chunks)
    except MetadataError:
        raise
    except (OSError, http.client.HTTPException):
        raise MetadataError('network_error', 'Steam could not be reached. Your cached information is unchanged.') from None
    finally:
        connection.close()


@dataclass(frozen=True)
class ItemMetadata:
    workshop_id: str
    status: str
    title: str | None = None
    tags: tuple[str, ...] = ()
    result_code: int | None = None
    diagnostic: str = ''
    description_raw: str | None = None


def _steam_text(value, limit):
    if not isinstance(value, str) or not value or len(value) > limit or '\x00' in value:
        raise ValueError('Invalid text')
    value.encode('utf8', 'strict')
    return value  # Never strip, case-fold, normalize Unicode, or rewrite source text.


def parse_response(body, requested):
    """Reject ambiguous envelopes; malformed individual items cannot clobber cache."""
    try:
        if not isinstance(body, bytes) or len(body) > MAX_RESPONSE: raise ValueError()
        data = json.loads(body.decode('utf8'))['response']
        items = data['publishedfiledetails']
        if not isinstance(items, list) or len(items) != len(requested) or type(data.get('resultcount')) is not int or data['resultcount'] != len(requested): raise ValueError()
        by_id = {}
        for item in items:
            key = item['publishedfileid']
            if key not in requested or key in by_id: raise ValueError()
            by_id[key] = item
        if set(by_id) != set(requested): raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        raise MetadataError('malformed', 'Steam returned an unexpected response; cached information is retained.') from None
    result = []
    for key in requested:
        item = by_id[key]
        code = item.get('result')
        if type(code) is not int or not 0 <= code <= 4294967295:
            result.append(ItemMetadata(key, 'malformed', diagnostic='Missing item result code.')); continue
        if code != 1:
            result.append(ItemMetadata(key, 'unavailable', result_code=code,
                diagnostic=f'Steam result {code}: item unavailable to this public request. This does not establish deletion or unsubscription.')); continue
        if type(item.get('consumer_app_id')) is not int or item['consumer_app_id'] != 550:
            result.append(ItemMetadata(key, 'wrong_app', result_code=code, diagnostic='Steam item is not verified for L4D2 App 550.')); continue
        if type(item.get('visibility')) is not int or item['visibility'] != 0:
            result.append(ItemMetadata(key, 'unavailable', result_code=code, diagnostic='Item is not verified public.')); continue
        try:
            title = _steam_text(item['title'], 4096)
            tags = item['tags']
            if not isinstance(tags, list) or len(tags) > 128: raise ValueError()
            values = tuple(dict.fromkeys(_steam_text(tag['tag'], 256) for tag in tags))
            description = item.get('description')
            if description is not None:
                if description != '': _steam_text(description, 65536)
            result.append(ItemMetadata(key, 'ok', title, values, code, description_raw=description))
        except (ValueError, KeyError, TypeError, UnicodeError):
            result.append(ItemMetadata(key, 'malformed', result_code=code, diagnostic='Invalid title or tag values; cached information retained.'))
    return tuple(result)


def cached_metadata(connection, ids):
    # One consistent snapshot for title/tags while another connection refreshes.
    owned = not connection.in_transaction
    if owned: connection.execute('BEGIN')
    try: return _cached_metadata(connection, ids)
    finally:
        if owned: connection.execute('ROLLBACK')


def _cached_metadata(connection, ids):
    result = {}
    for key in set(ids):
        row = connection.execute('SELECT * FROM workshop_metadata WHERE workshop_id=?', (key,)).fetchone()
        if row:
            item = dict(row)
            item['tags'] = tuple(row[0] for row in connection.execute('SELECT t.value FROM workshop_item_tags j JOIN steam_tags t USING(tag_id) WHERE j.workshop_id=? ORDER BY t.value COLLATE BINARY', (key,)))
            result[key] = item
    return result


def fetch_collection(database, installation_id, observed_ids, *, transport=request_details, now=None, pause=time.sleep, cancelled=lambda:False):
    """Only fresh inferred IDs intersecting the active selected installation."""
    current = now or datetime.now(timezone.utc)
    eligible = {row[0] for row in database.connection.execute('SELECT DISTINCT workshop_id FROM packages WHERE installation_id=? AND removed_at IS NULL AND workshop_id IS NOT NULL', (installation_id,))}
    ids = sorted(eligible.intersection(observed_ids))
    ids = [key for key in ids if valid_id(key)]
    cache = cached_metadata(database.connection, ids)
    pending = [key for key in ids if key not in cache or cache[key]['next_attempt_at'] <= current.isoformat()]
    if len(pending) > MAX_ITEMS:
        raise CatalogError(f'Fetch at most {MAX_ITEMS} Workshop items per action; narrow the collection first.')
    counts = {'requested': len(pending), 'cached': len(ids) - len(pending), 'ok': 0, 'failed': 0}
    for start in range(0, len(pending), BATCH_SIZE):
        if cancelled(): break
        batch = pending[start:start+BATCH_SIZE]
        if start: pause(1)
        if cancelled(): break
        try:
            items = parse_response(transport(batch), batch)
        except MetadataError as error:
            items = tuple(ItemMetadata(key, error.status, diagnostic=str(error)) for key in batch)
        completed = now or datetime.now(timezone.utc)
        stamp = completed.isoformat()
        with database.transaction() as connection:
            for item in items:
                delay = timedelta(hours=24) if item.status == 'ok' else timedelta(hours=1) if item.status == 'rate_limited' else timedelta(minutes=15)
                connection.execute('''INSERT INTO workshop_metadata
                    (workshop_id,title,app_id,source,last_success_at,last_attempt_at,next_attempt_at,retrieval_status,result_code,diagnostic)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(workshop_id) DO UPDATE SET
                    title=CASE WHEN excluded.retrieval_status='ok' THEN excluded.title ELSE workshop_metadata.title END,
                    app_id=CASE WHEN excluded.retrieval_status='ok' THEN excluded.app_id ELSE workshop_metadata.app_id END,
                    last_success_at=CASE WHEN excluded.retrieval_status='ok' THEN excluded.last_success_at ELSE workshop_metadata.last_success_at END,
                    last_attempt_at=excluded.last_attempt_at,next_attempt_at=excluded.next_attempt_at,
                    retrieval_status=excluded.retrieval_status,result_code=excluded.result_code,diagnostic=excluded.diagnostic''',
                    (item.workshop_id,item.title,550 if item.status=='ok' else None,SOURCE,stamp if item.status=='ok' else None,
                     stamp,(completed+delay).isoformat(),item.status,item.result_code,item.diagnostic))
                if item.status == 'ok':
                    if item.description_raw is not None and connection.execute('PRAGMA user_version').fetchone()[0] >= 5:
                        connection.execute('UPDATE workshop_metadata SET description_raw=? WHERE workshop_id=?', (item.description_raw,item.workshop_id))
                    connection.execute('DELETE FROM workshop_item_tags WHERE workshop_id=?', (item.workshop_id,))
                    for tag in item.tags:
                        connection.execute('INSERT INTO steam_tags(value) VALUES (?) ON CONFLICT(value) DO NOTHING', (tag,))
                        connection.execute('INSERT INTO workshop_item_tags SELECT ?,tag_id FROM steam_tags WHERE value=?', (item.workshop_id,tag))
                counts['ok' if item.status=='ok' else 'failed'] += 1
        # Stop further network calls after a batch transport/rate failure. The next
        # explicit action may retry remaining IDs; no tight automatic retry loop.
        if any(item.status in ('network_error','rate_limited') for item in items): break
    return counts


def readable_description(raw):
    """Plain text only. No browser, embedded images, links or code execution."""
    if not isinstance(raw,str): return ''
    text=re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>','',raw[:65536],flags=re.I|re.S)
    text=re.sub(r'<[^>]*>','',text)
    text=re.sub(r'\[(?:/?[a-z][a-z0-9]*)(?:=[^\]\r\n]*)?\]','',text,flags=re.I)
    return html.unescape(text).replace('\x00','')
