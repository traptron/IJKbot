"""Check the ROS parameters emitted by the ZXing launch description."""

from pathlib import Path
import runpy

import pytest

pytest.importorskip('launch_ros')

from launch import LaunchContext  # noqa: E402
from launch.actions import LogInfo  # noqa: E402
from launch_ros.utilities import evaluate_parameters, normalize_parameters  # noqa: E402


@pytest.mark.parametrize(('require_trigger', 'requested', 'expected'), [
    ('false', '/vision/take_photo', '/vision/take_photo'),
    ('true', '/vision/take_photo', ''),
    ('true', '/vision/reset_qr', '/vision/reset_qr'),
])
def test_zxing_launch_reset_topic(monkeypatch, require_trigger, requested, expected):
    package = Path(__file__).resolve().parents[1]
    generate = runpy.run_path(str(package / 'launch' / 'zxing_qr.launch.py'))['generate_launch_description']
    node_parameters = []

    def capture_node(*, parameters, **_):
        node_parameters.extend(parameters)
        return LogInfo(msg='')

    monkeypatch.setitem(generate.__globals__, 'Node', capture_node)
    monkeypatch.setitem(generate.__globals__, 'get_package_share_directory', lambda _: str(package))
    context = LaunchContext()
    context.launch_configurations.update(
        params_file=str(package / 'config' / 'zxing_qr.yaml'),
        require_trigger=require_trigger,
        reset_topic=requested,
        use_sim_time='false',
        image_reliability='best_effort',
    )

    generate()

    _, overrides = evaluate_parameters(context, normalize_parameters(node_parameters))
    assert overrides['require_trigger'] is (require_trigger == 'true')
    assert overrides['reset_topic'] == expected
