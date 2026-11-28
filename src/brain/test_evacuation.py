"""Evacuation regressions using stamped D435 observations and controlled clocks."""
import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from brain.llm_client import CommandInterpretation, load_arena
from brain.mission_sm import MissionState, MissionStateMachine, MissionROSNode
from brain.semantic_map import SemanticTraining, STATIC_IDS, validate_snapshot

JPEG = base64.b64encode(b'\xff\xd8test\xff\xd9').decode()


class LLM:
    def __init__(self):
        self.arena = load_arena()

    def interpret(self, text, **kwargs):
        goals = [{'x': x, 'y': y, 'yaw': yaw, 'frame_id': 'map'}
                 for x, y, yaw in self.arena['objects']['blue_building']['goals']]
        return CommandInterpretation('blue_building', 'inspect_perimeter', 'Голубое здание',
                                     nav2_goal=goals[0], nav2_goals=goals, source='llm')


@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv('IJKBOT_LOG_DIR', str(tmp_path))
    model = MissionStateMachine(LLM(), mock_mode=True)
    model.parse_task_with_llm()
    model.start_mission()
    return model


def observation(sm, label='victim', position=(2.1, .5, .1), stamp=100.):
    return dict(attempt_id=sm.evacuation.attempt_id, label=label, stamp=stamp,
                frame_id='map', position=position, confidence=.95, image_jpeg_b64=JPEG)


def found(sm):
    sm.state = MissionState.SEARCHING_VICTIM
    sm.evacuation.observe(observation(sm), 100.)


def at_victim(sm):
    found(sm)
    sm.evacuation.select_cell()
    sm.robot_x, sm.robot_y = sm.current_waypoint.x, sm.current_waypoint.y
    sm.step(0)
    assert sm.state == MissionState.WAIT_5_SECONDS


def test_begin_accepts_ros_time_exposed_as_a_message(sm):
    stamp = SimpleNamespace(sec=100, nanosec=125_000_000)
    clock = SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: stamp))
    sm.ros_node = SimpleNamespace(node=SimpleNamespace(get_clock=lambda: clock))

    sm.evacuation.begin()

    assert sm.evacuation.attempt_source_started == 100.125


def test_qr_before_figure_does_not_complete_search(sm):
    sm.state = MissionState.SEARCHING_VICTIM
    MissionROSNode._qr_callback(SimpleNamespace(sm=sm), SimpleNamespace(data='Стабилен'))
    MissionROSNode._qr_detected_callback(SimpleNamespace(sm=sm), SimpleNamespace(data=True))
    assert not sm.victim_found and not sm.qr_scanned
    found(sm)
    assert sm.victim_found and sm.state == MissionState.SEARCHING_VICTIM


def test_first_observation_confirms_victim_without_landmark_or_local_object(sm):
    sm.state = MissionState.SEARCHING_VICTIM
    sm.command_interpretation.local_object_id = 'tanker_truck'
    sm.evacuation.observe(observation(sm), 100)
    assert sm.victim_found
    assert sm.evacuation.landmark_confirmed
    with pytest.raises(ValueError):
        sm.evacuation.observe(observation(sm, stamp=95), 100)
    with pytest.raises(ValueError):
        sm.evacuation.observe(dict(observation(sm), image_jpeg_b64='invalid'), 100)


def test_repeated_yolo_observations_keep_completed_cell_plans(sm):
    found(sm)
    original = sm.evacuation.victim
    sm.evacuation.paths = {(2, 1): 1.0}
    sm.evacuation.request_paths = Mock()
    clock = SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=101_000_000_000))
    wrapper = SimpleNamespace(sm=sm, node=SimpleNamespace(get_clock=lambda: clock))
    msg = SimpleNamespace(data=json.dumps(observation(sm, position=(2.2, .5, .1), stamp=101)))

    MissionROSNode._observation_callback(wrapper, msg)

    assert sm.evacuation.victim is original
    assert sm.evacuation.paths == {(2, 1): 1.0}
    sm.evacuation.request_paths.assert_not_called()


def test_confidence_threshold_06_accepts_and_059_rejects(sm):
    sm.state = MissionState.SEARCHING_VICTIM
    low = dict(observation(sm), confidence=0.59)
    with pytest.raises(ValueError):
        sm.evacuation.observe(low, 100)
    assert not sm.victim_found

    edge = dict(observation(sm), confidence=0.6)
    sm.evacuation.observe(edge, 100)
    assert sm.victim_found
    assert sm.evacuation.victim.confidence == pytest.approx(0.6)


def test_blocked_closest_cell_is_excluded(sm):
    found(sm)
    sm.evacuation.paths = {(0, 0): 3., (2, 0): 1., (2, 1): 2.}
    sm.evacuation.select_cell()
    # Victim is within the chassis clearance of cell 2,0.
    assert sm.evacuation.selected_cell == (2, 1)
    assert sm.current_waypoint.cell == (2, 1)


def test_equal_distance_prefers_shorter_path(sm):
    found(sm)
    sm.evacuation.victim = sm.evacuation.observations['victim'].__class__(**observation(sm, position=(1.6, .4, .1)))
    sm.evacuation.paths = {(1, 0): 4., (2, 0): 1.}
    sm.evacuation.select_cell()
    assert sm.evacuation.selected_cell == (2, 0)


def test_five_continuous_seconds_before_qr(sm):
    at_victim(sm)
    start = sm.evacuation.started
    with patch('time.monotonic', return_value=start+1):
        sm.step(0)
    with patch('time.monotonic', return_value=start+5.9):
        sm.step(0)
        assert sm.state == MissionState.WAIT_5_SECONDS
    with patch('time.monotonic', return_value=start+6):
        sm.step(0)
    assert sm.state == MissionState.READING_QR
    assert sm.evacuation.standing_done
    assert not sm.qr_scanned


def test_move_on_fourth_second_restarts_hold(sm):
    at_victim(sm)
    start = sm.evacuation.started
    with patch('time.monotonic', return_value=start+1):
        sm.step(0)
    sm.robot_x += .3
    with patch('time.monotonic', return_value=start+5):
        sm.step(0)
    assert sm.evacuation.stationary_since is None
    sm.robot_x -= .3
    with patch('time.monotonic', return_value=start+6):
        sm.step(0)
    with patch('time.monotonic', return_value=start+10):
        sm.step(0)
    assert not sm.evacuation.standing_done


def test_stale_odometry_restarts_hold(sm):
    rt = sm.evacuation
    with patch('time.monotonic', return_value=10):
        rt.odometry(0., 0., 0.)
    rt.stationary_since = 10
    with patch('time.monotonic', return_value=11):
        rt.odometry(0., 0., 0.)
    assert rt.stationary_since is None


def test_no_qr_preserves_return_and_partial_result(sm):
    found(sm)
    sm.robot_x, sm.robot_y = 2., 2.
    sm.evacuation.home_length = 3
    with patch('time.monotonic', return_value=sm.evacuation.started+270):
        sm.step(0)
    assert sm.state == MissionState.RETURNING_HOME
    sm.robot_x, sm.robot_y = sm.evacuation.home.x, sm.evacuation.home.y
    sm.step(0)
    assert sm.evacuated_home and sm.evacuation.outcome == 'PARTIAL'
    assert not sm.qr_scanned


def test_full_attempt_and_evidence_export(sm):
    at_victim(sm)
    sm.evacuation.stationary_since = sm.evacuation.started-6
    sm.step(0)
    assert sm.state == MissionState.READING_QR
    sm.evacuation.qr('Стабилен', sm.evacuation.qr_started+.1)
    assert not sm.qr_scanned
    sm.latest_qr_image_b64 = JPEG
    sm.latest_qr_image_bytes = base64.b64decode(JPEG)
    sm.evacuation.qr_image_stamp = sm.evacuation.qr_started+.1
    sm.step(0)
    assert sm.state == MissionState.RETURNING_HOME
    sm.robot_x, sm.robot_y = sm.evacuation.home.x, sm.evacuation.home.y
    sm.step(0)
    assert sm.evacuation.outcome == 'COMPLETE'
    protocol = sm.export_protocol_dict()
    assert protocol['attempt']['victim']['image_jpeg_b64'] == JPEG
    assert protocol['attempt']['qr_image_jpeg_b64'] == JPEG
    assert protocol['qr_code_data'] == 'Стабилен'


def test_new_attempt_clears_movable_evidence(sm):
    found(sm)
    previous = observation(sm)
    sm.state = MissionState.READY_TO_START
    sm.start_mission()
    assert not sm.victim_found and not sm.evacuation.observations
    assert sm.latest_qr_image_b64 is None
    with pytest.raises(ValueError):
        sm.evacuation.observe(previous, 100)


def test_optional_qualifier_is_still_recorded_in_protocol(sm):
    sm.command_interpretation.local_object_id = 'tanker_truck'
    found(sm)
    assert sm.victim_found
    sm.evacuation.observe(observation(sm, 'tanker_truck'), 100)
    assert 'tanker_truck' in sm.evacuation.observations


def test_pre_read_qr_2s_old_is_accepted_after_full_5s_hold(sm):
    at_victim(sm)
    start = sm.evacuation.started
    jpeg_raw = b'\xff\xd8preread\xff\xd9'
    # Robot stands still starting at start+1
    with patch('time.monotonic', return_value=start + 1.0):
        sm.step(0)
    # Valid QR + snapshot arrive 2.0s before 5s hold finishes (at start+4.0)
    with patch('time.monotonic', return_value=start + 4.0):
        sm.evacuation.qr('Пульс 75', start + 4.0)
        sm.evacuation.cache_qr_image(jpeg_raw, start + 4.0)
    # At 4.9s of hold (start+5.9), 5s hold must NOT be skipped
    with patch('time.monotonic', return_value=start + 5.9):
        sm.step(0)
        assert sm.state == MissionState.WAIT_5_SECONDS
        assert not sm.evacuation.standing_done
        assert not sm.qr_scanned
    # At 5.0s of hold (start+6.0), enters READING_QR cleanly
    with patch('time.monotonic', return_value=start + 6.0):
        sm.step(0)
        assert sm.state == MissionState.READING_QR
        assert sm.evacuation.standing_done
    # Next step in READING_QR immediately validates the 2.0s-old pre-read QR
    with patch('time.monotonic', return_value=start + 6.1):
        sm.step(0)
    assert sm.qr_scanned
    assert sm.qr_code_data == 'Пульс 75'
    assert sm.latest_qr_image_bytes == jpeg_raw
    assert sm.state == MissionState.RETURNING_HOME


def test_pre_read_qr_4s_old_and_previous_attempt_are_rejected(sm):
    # Case 1: 4.0s-old pre-read QR (> 3.0s window) is rejected
    at_victim(sm)
    start = sm.evacuation.started
    with patch('time.monotonic', return_value=start + 1.0):
        sm.step(0)
    with patch('time.monotonic', return_value=start + 2.0):
        sm.evacuation.qr('Старый QR', start + 2.0)
        sm.evacuation.cache_qr_image(b'\xff\xd8stale\xff\xd9', start + 2.0)
    with patch('time.monotonic', return_value=start + 6.0):
        sm.step(0)
    assert sm.state == MissionState.READING_QR
    with patch('time.monotonic', return_value=start + 6.1):
        sm.step(0)
    assert sm.state == MissionState.READING_QR
    assert not sm.qr_scanned
    assert sm.qr_code_data is None

    # Case 2: previous attempt pre-read QR is cleared on new attempt start
    sm.state = MissionState.WAIT_5_SECONDS
    sm.evacuation.qr('От прошлой попытки', 500.0)
    sm.evacuation.cache_qr_image(b'\xff\xd8prev\xff\xd9', 500.0)
    assert sm.evacuation.pre_read_qr_text == 'От прошлой попытки'
    sm.state = MissionState.READY_TO_START
    sm.start_mission()
    assert sm.evacuation.pre_read_qr_text is None
    assert sm.evacuation.pre_read_qr_image_bytes is None


def test_qr_photo_retries_leave_time_for_decoder_confirmation(sm):
    at_victim(sm)
    sm._trigger_photo_snapshot = Mock()
    start = sm.evacuation.started
    sm.evacuation.stationary_since = start
    with patch('time.monotonic', return_value=start + 5.0):
        sm.step(0)
    assert sm.state == MissionState.READING_QR
    assert sm._trigger_photo_snapshot.call_count == 1

    for elapsed in (8.25, 8.5, 9.0, 9.5):
        with patch('time.monotonic', return_value=start + elapsed):
            sm.step(0)
    assert sm._trigger_photo_snapshot.call_count == 2
    with patch('time.monotonic', return_value=start + 9.75):
        sm.step(0)
    assert sm._trigger_photo_snapshot.call_count == 3


def test_separate_start_signal(sm):
    sm.reset_mission()
    sm._publish_goal_pose = Mock()
    sm.start_mission()
    sm._publish_goal_pose.assert_not_called()
    sm.parse_task_with_llm()
    assert not sm.publish_nav2_goal()
    sm._publish_goal_pose.assert_not_called()


def test_localization_loss_cancels_and_pauses(sm):
    sm.mock_mode = False
    sm.ros_node = SimpleNamespace(has_fresh_odometry=lambda: True, update_pose_from_tf=lambda: False)
    sm._cancel_nav_goal = Mock()
    sm.step(0)
    assert sm.state == MissionState.PAUSED
    sm._cancel_nav_goal.assert_called_once()


def test_pause_does_not_count_as_hold(sm):
    at_victim(sm)
    sm.evacuation.stationary_since = sm.evacuation.started
    sm.toggle_pause()
    sm.step(0)
    assert sm.evacuation.stationary_since is None
    sm.toggle_pause()
    assert sm.state == MissionState.WAIT_5_SECONDS


def test_training_snapshot_and_version(tmp_path):
    arena = load_arena()
    training = SemanticTraining(arena)
    assert training.state == 'TRAINING'
    for label in STATIC_IDS:
        training.observe(dict(label=label, frame_id='map', position=[1, 1, 0], stamp=100,
                              image_jpeg_b64=JPEG))
    training.review()
    for label in STATIC_IDS:
        info = arena['objects'][label]
        training.approve(label, info['cells'], info['goals'], info['description'])
    image = tmp_path/'occupancy.pgm'
    image.write_bytes(b'P5\n1 1\n255\n\xff')
    meta = tmp_path/'occupancy.yaml'
    meta.write_text('image: occupancy.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n')
    output = training.save(tmp_path/'arena.json', meta)
    validate_snapshot(output)
    assert training.state == 'MAP_READY'
    assert 'bus_stop' not in output['objects']
    assert 'остановка' not in output['objects']['parking']['description']
    changed = copy.deepcopy(output)
    changed['legend']['parking'] = 'changed'
    with pytest.raises(ValueError):
        validate_snapshot(changed)
    image.write_bytes(b'changed')
    with pytest.raises(ValueError):
        validate_snapshot(output)


def test_training_requires_sensor_evidence():
    training = SemanticTraining(load_arena())
    training.review()
    with pytest.raises(ValueError):
        training.approve('parking', [[1, 1]], [[.4, 1.2, 0]], 'Парковка')


def test_navigation_failures_are_bounded(sm):
    sm.ros_node = SimpleNamespace(goal_status=6)
    sm._publish_goal_pose = Mock()
    for _ in range(3):
        sm.ros_node.goal_status = 6
        sm.step(0)
    assert sm.state == MissionState.NAVIGATING_TO_LANDMARK
    sm.ros_node.goal_status = 6
    sm.step(0)
    assert sm.state == MissionState.PAUSED
    assert sm._publish_goal_pose.call_count == 3


def test_estop_cannot_be_overwritten_by_late_llm(sm):
    def stopped(text, **kwargs):
        sm.trigger_emergency_stop()
        return LLM().interpret(text)
    sm.reset_mission()
    sm.llm_client.interpret = stopped
    with pytest.raises(ValueError, match='отменена'):
        sm.parse_task_with_llm()
    assert sm.state == MissionState.EMERGENCY_STOP


def test_early_qr_evidence_image_is_rejected(sm):
    sm.state = MissionState.READING_QR
    sm.evacuation.qr_source_started = 100
    clock = SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=101_000_000_000))
    wrapper = SimpleNamespace(sm=sm, node=SimpleNamespace(get_clock=lambda: clock))
    frame = SimpleNamespace(data=b'\xff\xd8old', header=SimpleNamespace(stamp=SimpleNamespace(sec=99, nanosec=0)))
    MissionROSNode._qr_image_callback(wrapper, frame)
    assert sm.latest_qr_image_bytes is None


def test_pre_read_qr_keeps_latest_image_from_current_attempt(sm):
    clock = SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=101_000_000_000))
    wrapper = SimpleNamespace(sm=sm, node=SimpleNamespace(get_clock=lambda: clock))
    sm.evacuation.attempt_source_started = 99
    sm.state = MissionState.APPROACHING_VICTIM

    def receive(captured, data):
        header = SimpleNamespace(stamp=SimpleNamespace(sec=captured, nanosec=0))
        MissionROSNode._qr_image_callback(wrapper, SimpleNamespace(data=data, header=header))

    receive(98, b'\xff\xd8previous')
    assert sm.evacuation.pre_read_qr_image_bytes is None
    receive(101, b'\xff\xd8current')
    receive(100, b'\xff\xd8out-of-order')
    assert sm.evacuation.pre_read_qr_image_bytes == b'\xff\xd8current'


def test_nav_success_survives_stationary_settling(sm):
    sm.mock_mode = False
    sm.state = MissionState.RETURNING_HOME
    sm.current_waypoint = sm.evacuation.home
    sm.robot_x, sm.robot_y = sm.evacuation.home.x, sm.evacuation.home.y
    sm.ros_node = SimpleNamespace(goal_status=4)
    assert sm._check_reached_waypoint(sm.evacuation.home)
    assert sm._check_reached_waypoint(sm.evacuation.home)
    assert sm.ros_node.goal_status == 4


def test_already_in_selected_cell_stops_without_new_goal(sm):
    found(sm)
    sm.evacuation.paths = {(0, 0): 0.}
    sm._publish_goal_pose = Mock()
    sm.evacuation.select_cell()
    assert sm.state == MissionState.WAIT_5_SECONDS
    assert sm.evacuation.selected_cell == (0, 0)
    sm._publish_goal_pose.assert_not_called()


def test_fragment_blocks_nearest_approach(sm):
    found(sm)
    sm.evacuation.paths = {(2, 1): 1., (3, 0): 2.}
    sm.evacuation.select_cell()
    assert sm.evacuation.selected_cell == (2, 1)
    sm.state = MissionState.SEARCHING_VICTIM
    sm.evacuation.map['blocked_cells'].append([2, 1])
    sm.evacuation.request_paths()
    sm.evacuation.select_cell()
    assert sm.evacuation.selected_cell != (2, 1)
