"""Sensor-derived semantic map review and immutable competition snapshots."""

import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

STATIC_IDS = {'yellow_building', 'blue_building', 'bridges', 'river', 'parking'}
MOVABLE_IDS = {'bus_stop', 'tanker_truck', 'fallen_tree', 'car_jam', 'debris_pvc',
               'yellow_building_debris', 'victim', 'qr_stand', 'trash_bin'}


class SemanticTraining:
    """Operator reviews labels backed by stamped camera observations in map."""

    def __init__(self, arena: dict[str, Any]):
        self.arena = copy.deepcopy(arena)
        self.state = 'TRAINING'
        self.observations: dict[str, dict] = {}
        self.approved: set[str] = set()

    def observe(self, observation: dict) -> None:
        if self.state != 'TRAINING':
            raise ValueError('Collect observations during TRAINING')
        label = observation['label']
        if label not in STATIC_IDS | MOVABLE_IDS:
            raise ValueError('Unknown semantic label')
        xyz = observation['position']
        if (observation['frame_id'] != 'map' or len(xyz) != 3 or
                not all(math.isfinite(float(v)) for v in xyz) or
                not math.isfinite(float(observation['stamp'])) or
                float(observation['stamp']) <= 0 or not observation.get('image_jpeg_b64')):
            raise ValueError('A stamped map pose and camera evidence are required')
        image = base64.b64decode(observation['image_jpeg_b64'], validate=True)
        if not image.startswith(b'\xff\xd8') or len(image) > 2_000_000:
            raise ValueError('JPEG camera evidence required')
        self.observations[label] = copy.deepcopy(observation)
        self.approved.discard(label)

    def review(self) -> None:
        if self.state != 'TRAINING':
            raise ValueError('Training is not active')
        self.state = 'MAP_REVIEW'

    def approve(self, label: str, cells: list, goals: list, description: str) -> None:
        if self.state != 'MAP_REVIEW' or label not in self.observations:
            raise ValueError('Review requires a sensor observation')
        if not description.strip() or not cells or not goals:
            raise ValueError('Legend, cells and inspection poses are required')
        if any(len(cell) != 2 or any(type(v) is not int or not 0 <= v < 5 for v in cell) for cell in cells):
            raise ValueError('Cells must belong to the 5 by 5 arena')
        if any(len(pose) != 3 or not all(math.isfinite(float(v)) for v in pose)
               or not 0 <= pose[0] < 4 or not 0 <= pose[1] < 4 for pose in goals):
            raise ValueError('Inspection poses must belong to map')
        self.arena['objects'][label] = {
            'description': description, 'cells': cells, 'goals': goals,
            'static': label in STATIC_IDS, 'observation': self.observations[label],
        }
        self.approved.add(label)

    def save(self, destination: Path, occupancy_yaml: Path) -> dict:
        if self.state != 'MAP_REVIEW' or not STATIC_IDS <= self.approved:
            raise ValueError('Approve every static landmark before freezing the map')
        import yaml
        occupancy_yaml = occupancy_yaml.resolve()
        metadata = yaml.safe_load(occupancy_yaml.read_text())
        image = occupancy_yaml.parent / metadata['image']
        digest = hashlib.sha256(occupancy_yaml.read_bytes() + image.read_bytes()).hexdigest()
        arena = copy.deepcopy(self.arena)
        arena['objects'] = {key: value for key, value in arena['objects'].items()
                            if key in STATIC_IDS | {'start'}}
        arena.update(training_state='MAP_READY', occupancy_map=str(occupancy_yaml),
                     occupancy_sha256=digest, grid_size=[5, 5], cell_size_m=0.8,
                     frame_id='map', legend={key: arena['objects'][key]['description'] for key in STATIC_IDS})
        arena['blocked_cells'] = sorted({tuple(cell) for key in ('yellow_building', 'blue_building', 'river', 'parking') for cell in arena['objects'][key]['cells']})
        arena['blocked_cells'] = [list(cell) for cell in arena['blocked_cells']]
        arena.pop('version', None)
        arena['version'] = hashlib.sha256(json.dumps(arena, sort_keys=True).encode()).hexdigest()
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=destination.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(arena, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, destination)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.state = 'MAP_READY'
        return arena


def validate_snapshot(arena: dict) -> None:
    """Reject changed occupancy assets or semantic labels after judge review."""
    import yaml
    if arena.get('training_state') != 'MAP_READY' or not STATIC_IDS <= set(arena.get('objects', {})):
        raise ValueError('A reviewed semantic map is required')
    payload = copy.deepcopy(arena)
    version = payload.pop('version', None)
    if hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() != version:
        raise ValueError('Semantic map version mismatch')
    occupancy = Path(arena['occupancy_map'])
    metadata = yaml.safe_load(occupancy.read_text())
    image = occupancy.parent / metadata['image']
    digest = hashlib.sha256(occupancy.read_bytes() + image.read_bytes()).hexdigest()
    if digest != arena['occupancy_sha256']:
        raise ValueError('Occupancy map changed after review')
