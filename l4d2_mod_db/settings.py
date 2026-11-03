"""Small atomic app-owned preferences; no drive discovery or game writes."""

import json
import os
from pathlib import Path
from uuid import uuid4

from .storage import StoragePolicy, CatalogError, _check_component


class AppSettings:
    def __init__(self, directory=None):
        if directory is None:
            base = os.environ.get('LOCALAPPDATA', '')
            if not base or not Path(base).is_absolute() or base.startswith(('\\\\','//')):
                raise CatalogError('An absolute local LOCALAPPDATA folder is required.')
            directory = Path(base) / 'L4D2ModDatabase'
        else:
            directory = Path(directory)
            allowed = Path(__file__).resolve().parents[1] / '.test-tmp'
            if directory == allowed or not directory.is_relative_to(allowed):
                raise CatalogError('Test preferences must be isolated under .test-tmp.')
        self.policy = StoragePolicy(directory, None)
        self.path = directory / 'preferences.json'

    def load(self):
        return self.options()['game_root']

    def options(self):
        self.policy.check()
        if not self.path.exists() and not self.path.is_symlink(): return dict(game_root='',auto_online=True,online_notice_seen=False)
        _check_component(self.path,directory=False)
        if self.path.stat().st_size > 4096: raise CatalogError('Saved preferences are invalid; choose the game folder again.')
        try:
            with self.path.open('rb') as stream:content=stream.read(4097)
            if len(content)>4096:raise ValueError()
            data = json.loads(content.decode('utf8'))
            if data['version'] not in (1,2) or not isinstance(data['game_root'],str) or len(data['game_root']) > 1024: raise ValueError()
            if any(type(data.get(key,default)) is not bool for key,default in (('auto_online',True),('online_notice_seen',False))): raise ValueError()
            return dict(game_root=data['game_root'],auto_online=data.get('auto_online',True),online_notice_seen=data.get('online_notice_seen',False))
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise CatalogError('Saved preferences are invalid; choose the game folder again.') from None

    def save(self, access, **options):
        if set(options)-{'auto_online','online_notice_seen'} or any(type(value) is not bool for value in options.values()): raise ValueError('Invalid preference option')
        data=self.options();data.update(options);data.update(version=2,game_root=str(access.validated_root))
        policy = StoragePolicy(self.policy.directory, access.validated_root)
        policy.prepare()
        if self.path.exists() or self.path.is_symlink(): _check_component(self.path,directory=False)
        temporary = self.path.with_name('preferences-' + uuid4().hex + '.tmp')
        with temporary.open('x',encoding='utf8') as stream:
            json.dump(data,stream,ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        policy.check()
        if self.path.exists() or self.path.is_symlink(): _check_component(self.path,directory=False)
        temporary.replace(self.path)
