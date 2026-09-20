"""The dashboard must not run a competing real mission or drive in mock mode."""

from types import SimpleNamespace
from unittest.mock import Mock

from std_msgs.msg import String

from ijkbot_brain.mission_sm import MissionROSNode, MissionState, MissionStateMachine


def test_real_trial_step_delegates_without_search_or_velocity():
    sm = MissionStateMachine(mock_mode=False)
    sm.ros_node = Mock(trial_mode=True)
    sm.state = MissionState.WAIT_5_SECONDS
    sm.wait_timer_start = 0.0
    sm.step()
    assert sm.state == MissionState.WAIT_5_SECONDS
    sm.ros_node.send_cmd_vel.assert_not_called()
    sm.ros_node.send_nav_goal.assert_not_called()


def test_mock_never_publishes_goal_or_velocity():
    sm = MissionStateMachine(mock_mode=True)
    sm.ros_node = Mock(trial_mode=True)
    sm._publish_zero_velocity()
    sm._publish_goal_pose(None)
    sm.ros_node.send_cmd_vel.assert_not_called()
    sm.ros_node.send_nav_goal.assert_not_called()


def test_repeated_stopped_status_does_not_override_operator_reset():
    sm = MissionStateMachine(mock_mode=False)
    node = SimpleNamespace(sm=sm)
    MissionROSNode._trial_callback(node, String(data='STOPPED'))
    assert sm.state == MissionState.EMERGENCY_STOP
    sm.state = MissionState.READY_TO_START
    MissionROSNode._trial_callback(node, String(data='STOPPED'))
    assert sm.state == MissionState.READY_TO_START


def test_estop_from_gui_reaches_planner():
    sm = MissionStateMachine(mock_mode=False)
    sm.ros_node = Mock(trial_mode=True)
    sm.trigger_emergency_stop()
    sm.ros_node.set_trial_stop.assert_called_once_with(True)
    sm.reset_emergency_stop()
    sm.ros_node.set_trial_stop.assert_called_with(False)
    assert sm.state == MissionState.READY_TO_START
