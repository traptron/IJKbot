"""Training workflow over sensor observations and an operator review console.

Publish /training/command JSON with action review, resume, approve or save.
The save action freezes semantic observations with a saved occupancy map.
"""

from concurrent.futures import ThreadPoolExecutor
import html
import json
from pathlib import Path
import subprocess
import tempfile

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from brain.llm_client import load_arena
from brain.semantic_map import SemanticTraining


class TrainingNode(Node):
    def __init__(self):
        super().__init__('semantic_training')
        self.training = SemanticTraining(load_arena())
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.saving = None
        self.create_subscription(String, '/vision/observations', self.observe, 10)
        self.create_subscription(String, '/training/command', self.command, 10)
        self.status = self.create_publisher(String, '/training/status', 10)
        self.create_timer(.5, self.tick)

    def observe(self, msg):
        if self.training.state != 'TRAINING':
            return
        try:
            self.training.observe(json.loads(msg.data))
        except (ValueError, TypeError, KeyError) as error:
            self.get_logger().warning(str(error))

    def command(self, msg):
        try:
            if self.saving is not None:
                raise ValueError('Saving map; wait for completion')
            data = json.loads(msg.data)
            action = data['action']
            if action == 'review':
                self.training.review()
            elif action == 'resume':
                self.training.state = 'TRAINING'
            elif action == 'approve':
                self.training.approve(data['label'], data['cells'], data['goals'], data['description'])
            elif action == 'save':
                if self.training.state != 'MAP_REVIEW':
                    raise ValueError('Review map before saving')
                self.saving = self.pool.submit(self.save, Path(data['directory']).expanduser())
            else:
                raise ValueError('Unknown training action')
            self.get_logger().info(f'Training {action}: {self.training.state}')
        except (ValueError, KeyError, TypeError) as error:
            self.get_logger().error(str(error))

    def save(self, parent):
        parent.mkdir(parents=True, exist_ok=True)
        # A new directory keeps previous judge snapshots immutable.
        output = Path(tempfile.mkdtemp(prefix='evacuation-map-', dir=parent))
        subprocess.run(['ros2', 'run', 'nav2_map_server', 'map_saver_cli',
                        '-f', str(output/'occupancy'), '--ros-args', '-p', 'map_subscribe_transient_local:=true'],
                       check=True, timeout=30, capture_output=True)
        arena = self.training.save(output/'arena.json', output/'occupancy.yaml')
        legend = '<h1>Карта «Эвакуация»</h1><p>' + html.escape(arena['version']) + '</p><img src="occupancy.pgm"><ul>'
        for label, description in sorted(arena['legend'].items()):
            legend += '<li>' + html.escape(label+' — '+description+'; '+str(arena['objects'][label]['cells'])) + '</li>'
        legend += '</ul><p>Сетка 5 × 5, размер ячейки 0,8 м. Координаты и точки осмотра представлены в arena.json.</p>'
        # Draw the competition grid in the same map coordinates as arena.json.
        from PIL import Image, ImageDraw
        import yaml
        metadata = yaml.safe_load((output/'occupancy.yaml').read_text())
        image = Image.open(output/metadata['image']).convert('RGB')
        scale = max(1, 800 // max(image.size))
        image = image.resize((image.width*scale, image.height*scale), Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(image)
        ox, oy, yaw = metadata['origin']
        if abs(yaw) > 1e-6:
            raise ValueError('Align the competition grid with map X/Y before review')
        pixels = scale/metadata['resolution']
        def point(x, y):
            return ((x-ox)*pixels, image.height-(y-oy)*pixels)
        for index in range(6):
            draw.line([point(index*.8, 0), point(index*.8, 4)], fill='red', width=2)
            draw.line([point(0, index*.8), point(4, index*.8)], fill='red', width=2)
        for x in range(5):
            for y in range(5):
                draw.text(point(x*.8+.05, y*.8+.7), f'{x}:{y}', fill='blue')
        image.save(output/'occupancy.png')
        legend = legend.replace('occupancy.pgm', 'occupancy.png')
        (output/'legend.html').write_text('<!doctype html><meta charset="utf-8">'+legend)
        return str(output/'arena.json')

    def tick(self):
        if self.saving is not None and self.saving.done():
            try:
                self.get_logger().info('Judge snapshot saved: '+self.saving.result())
            except Exception as error:
                self.training.state = 'MAP_REVIEW'
                self.get_logger().error(f'Map save failed: {error}')
            self.saving = None
        self.status.publish(String(data=json.dumps({
            'state': self.training.state, 'saving': self.saving is not None,
            'approved': sorted(self.training.approved),
            'observations': self.training.observations,
        }, ensure_ascii=False)))


def main(args=None):
    rclpy.init(args=args)
    node = TrainingNode()
    try:
        rclpy.spin(node)
    finally:
        node.pool.shutdown(wait=True, cancel_futures=True)
        node.destroy_node()
        rclpy.shutdown()
