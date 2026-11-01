"""Map-bound places and waypoint snapshots with optimistic atomic updates."""
import hashlib
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ID = Annotated[str, StringConstraints(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
Name = Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=80)]


class Pose(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x: float
    y: float
    yaw: float


class Waypoint(Pose):
    label: str = Field(default='',max_length=80)
    wait_s: float = Field(default=0,ge=0,le=60)


class Place(Pose):
    id: ID
    name: Name


class Route(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: ID
    name: Name
    points: list[Waypoint] = Field(min_length=1,max_length=100)


class Document(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0,strict=True)
    fingerprint: str
    places: list[Place] = Field(max_length=200)
    routes: list[Route] = Field(max_length=100)


class Conflict(ValueError): pass


class Annotations:
    def __init__(self,catalog):
        self.catalog = catalog
        self.lock = threading.RLock()
        self._fingerprints = {}
        self._documents = {}

    def fingerprint(self,map_id):
        info=self.catalog.inspect(map_id)
        path=self.catalog.path(map_id)
        image=self.catalog.directory/info['image']
        signature=tuple((p.stat().st_ino,p.stat().st_mtime_ns,p.stat().st_size) for p in (path,image))
        cached=self._fingerprints.get(map_id)
        if cached and cached[0]==signature:return cached[1]
        digest=hashlib.sha256(path.read_bytes());digest.update(image.read_bytes())
        result=digest.hexdigest();self._fingerprints[map_id]=(signature,result)
        return result

    def path(self,map_id):
        path=self.catalog.path(map_id).with_suffix('.ijk.json')
        if path.is_symlink(): raise ValueError('Метаданные не могут быть символической ссылкой')
        return path

    def _read(self,map_id):
        fp=self.fingerprint(map_id)
        path=self.path(map_id)
        stamp=(path.stat().st_ino,path.stat().st_mtime_ns,path.stat().st_size) if path.exists() else None
        cached=self._documents.get(map_id)
        if cached and cached[0]==stamp:doc=cached[1]
        else:
            doc=Document.model_validate_json(path.read_text()).model_dump() if stamp else {'revision':0,'fingerprint':fp,'places':[],'routes':[]}
            self._documents[map_id]=(stamp,doc)
        return {**doc,'map_id':map_id,'current_fingerprint':fp,'valid':doc['fingerprint']==fp}

    def load(self,map_id):
        with self.lock:return copy.deepcopy(self._read(map_id))

    def identity(self,map_id):
        with self.lock:
            document=self._read(map_id)
            return {key:document[key] for key in ('revision','fingerprint','current_fingerprint','valid','map_id')}

    def update(self,map_id,payload,revalidate=False):
        with self.lock:
            new=Document.model_validate(payload).model_dump()
            current=self.load(map_id)
            if new['revision']!=current['revision']: raise Conflict('Места изменены в другой вкладке. Обновите данные.')
            if new['fingerprint']!=current['current_fingerprint']:
                raise Conflict('Карта изменилась. Проверьте места и маршруты на новой карте.')
            if not current['valid'] and not revalidate:
                raise Conflict('Подтвердите проверку мест после изменения карты')
            ids=[v['id'] for v in new['places']+new['routes']]
            if len(ids)!=len(set(ids)): raise ValueError('Идентификаторы мест и маршрутов должны различаться')
            info=self.catalog.inspect(map_id)
            ox,oy,angle=info['origin']
            for pose in new['places']+[p for r in new['routes'] for p in r['points']]:
                dx,dy=pose['x']-ox,pose['y']-oy
                x=math.cos(angle)*dx+math.sin(angle)*dy
                y=-math.sin(angle)*dx+math.cos(angle)*dy
                if not (0<=x<=info['width']*info['resolution'] and 0<=y<=info['height']*info['resolution']):
                    raise ValueError('Точка находится вне карты')
                pose['yaw']=math.atan2(math.sin(pose['yaw']),math.cos(pose['yaw']))
            new['revision']+=1
            path=self.path(map_id)
            temp=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.annotations-',delete=False) as output:
                    temp=Path(output.name)
                    json.dump(new,output,ensure_ascii=False,allow_nan=False,indent=2)
                    output.flush();os.fsync(output.fileno())
                os.replace(temp,path)
            finally:
                if temp and temp.exists(): temp.unlink()
            return self.load(map_id)
