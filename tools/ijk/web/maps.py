"""Validated local map catalog shared by the web UI and save jobs."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import math
import re
import copy
import threading

from PIL import Image
import yaml


class MapCatalog:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self._cache = {}
        self._lock = threading.RLock()

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
            raise ValueError('Имя карты: до 80 латинских букв, цифр, дефисов или подчёркиваний')
        return name

    def path(self, map_id: str) -> Path:
        if not isinstance(map_id, str) or not map_id.endswith('.yaml') or Path(map_id).name != map_id:
            raise ValueError('Недопустимый идентификатор карты')
        self.validate_name(map_id[:-5])
        path = (self.directory / map_id).resolve()
        if path.parent != self.directory or not path.is_file():
            raise ValueError('Карта не найдена')
        return path

    def inspect(self, map_id: str) -> dict:
        with self._lock:
            path=self.path(map_id)
            stamp=lambda p:(p.stat().st_ino,p.stat().st_mtime_ns,p.stat().st_size)
            cached=self._cache.get(map_id)
            if cached:
                try:
                    if cached[0]==stamp(path) and cached[1]==stamp(self.directory/cached[2]['image']):
                        return copy.deepcopy(cached[2])
                except OSError:pass
            info=self._inspect(map_id)
            self._cache[map_id]=(stamp(path),stamp(self.directory/info['image']),info)
            return copy.deepcopy(info)

    def _inspect(self, map_id: str) -> dict:
        path = self.path(map_id)
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('image'), str):
            raise ValueError('В YAML отсутствует изображение карты')
        image = (path.parent / data['image']).resolve()
        if image.parent != self.directory or not image.is_file():
            raise ValueError('Изображение карты отсутствует или находится вне каталога')
        resolution = float(data['resolution'])
        origin = data['origin']
        if not math.isfinite(resolution) or resolution <= 0 or len(origin) != 3 or not all(math.isfinite(float(v)) for v in origin):
            raise ValueError('Неверное разрешение или начало координат карты')
        with Image.open(image) as bitmap:
            bitmap.load()
            width, height = bitmap.size
        return {'id': map_id, 'name': path.stem, 'valid': True,
                'modified': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                'resolution': resolution, 'origin': [float(v) for v in origin], 'width': width, 'height': height,
                'image': image.name, 'preview_url': f'/api/maps/{map_id}/preview'}

    def list(self) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob('*.yaml'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                result.append(self.inspect(path.name))
            except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as exc:
                result.append({'id': path.name, 'name': path.stem, 'valid': False, 'error': str(exc)})
        return result

    def preview(self, map_id: str) -> bytes:
        info = self.inspect(map_id)
        with Image.open(self.directory / info['image']) as bitmap:
            output = BytesIO()
            bitmap.convert('RGB').save(output, format='PNG')
        return output.getvalue()
