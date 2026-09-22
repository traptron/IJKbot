"""Exercise mission sequencing with a fake Nav2 transport, without motors."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool

from ijkbot_brain.trial_planner import TrialPlanner


def planner():
    node = SimpleNamespace(
        state='OUTBOUND', started=0.0, timeout=300.0,
        pending=False, handle=None, estopped=False,
        stationary_since=None, last_odom=None, stationary=False,
        home=PoseStamped(), state_pub=Mock(), active_goals=set(), legacy_active=False, owned_goal_id=None,
        client=Mock(), get_logger=Mock(return_value=Mock()),
        get_clock=Mock(return_value=Mock()),
    )
    for name in ('transition', 'on_goal', 'accepted', 'finished', 'on_odom',
                 'tick', 'cancel', 'canceled', 'on_stop', 'fail', 'on_external_goal', 'on_mission_state', 'on_nav_status'):
        setattr(node, name, getattr(TrialPlanner, name).__get__(node))
    node.send = Mock()
    return node


def result(status):
    return Mock(result=Mock(return_value=SimpleNamespace(
        status=status, result=SimpleNamespace(error_code=0))))


def test_success_waits_five_seconds_then_returns_and_completes():
    node = planner()
    node.finished(result(GoalStatus.STATUS_SUCCEEDED))
    assert node.state == 'HOLDING'
    with patch('ijkbot_brain.trial_planner.time.monotonic') as clock:
        for moment in (10.0, 14.99, 15.0):
            clock.return_value = moment
            # Keep odom continuously fresh, without a callback gap.
            node.last_odom = moment
            node.on_odom(Odometry())
            node.tick()
            if moment < 15:
                node.send.assert_not_called()
    node.send.assert_called_once_with(node.home, 'RETURNING')
    node.state = 'RETURNING'
    node.finished(result(GoalStatus.STATUS_SUCCEEDED))
    assert node.state == 'COMPLETE'


def test_no_odom_does_not_start_return():
    node = planner()
    node.state = 'HOLDING'
    with patch('ijkbot_brain.trial_planner.time.monotonic', return_value=20.0):
        node.tick()
    node.send.assert_not_called()
    assert node.stationary_since is None


def test_motion_and_stale_odom_reset_hold():
    node = planner()
    node.state = 'HOLDING'
    node.stationary_since = 1.0
    node.last_odom = 4.9
    moving = Odometry()
    moving.twist.twist.linear.x = 0.05
    with patch('ijkbot_brain.trial_planner.time.monotonic', return_value=5.0):
        node.on_odom(moving)
        node.tick()
    assert node.stationary_since is None
    node.stationary = True
    node.stationary_since = 1.0
    with patch('ijkbot_brain.trial_planner.time.monotonic', return_value=6.0):
        node.tick()
    assert node.stationary_since is None
    node.send.assert_not_called()


def test_abort_never_starts_hold_or_return():
    node = planner()
    node.finished(result(GoalStatus.STATUS_ABORTED))
    assert node.state == 'FAILED'
    node.send.assert_not_called()


def test_stop_while_acceptance_pending_cancels_late_goal():
    node = planner()
    node.pending = True
    node.on_stop(Bool(data=True))
    handle = Mock(accepted=True)
    handle.goal_id.uuid = [0] * 16
    node.accepted(Mock(result=Mock(return_value=handle)))
    handle.cancel_goal_async.assert_called_once()
    node.finished(result(GoalStatus.STATUS_SUCCEEDED))
    assert node.state == 'STOPPED'
    node.send.assert_not_called()


def test_timeout_cancels_navigation():
    node = planner()
    node.handle = Mock()
    with patch('ijkbot_brain.trial_planner.time.monotonic', return_value=301.0):
        node.tick()
    assert node.state == 'FAILED'
    node.handle.cancel_goal_async.assert_called_once()


def test_busy_and_invalid_goal_do_not_replace_mission():
    node = planner()
    node.on_goal(PoseStamped())
    node.state = 'IDLE'
    node.on_goal(PoseStamped())
    node.send.assert_not_called()


def test_result_transport_error_keeps_handle_for_cancellation():
    node = planner()
    node.handle = Mock()
    node.finished(Mock(result=Mock(side_effect=RuntimeError('connection lost'))))
    assert node.state == 'FAILED'
    node.handle.cancel_goal_async.assert_called_once()


def test_external_topic_goal_cancels_only_our_mission():
    node = planner()
    node.handle = Mock()
    node.on_external_goal(PoseStamped())
    assert node.state == 'FAILED'
    node.handle.cancel_goal_async.assert_called_once()
    node.send.assert_not_called()


def test_legacy_mission_interrupts_hold():
    from std_msgs.msg import String
    node = planner()
    node.state = 'HOLDING'
    node.on_mission_state(String(data='RETURNING_HOME'))
    assert node.state == 'FAILED'
    assert node.legacy_active
    node.send.assert_not_called()
