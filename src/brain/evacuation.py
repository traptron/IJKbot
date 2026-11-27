"""Attempt-scoped evidence, cell selection and evacuation state transitions."""

import base64
import copy
import math
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

MIN_OBSERVATION_CONFIDENCE = 0.6
PRE_READ_QR_MAX_AGE_SEC = 3.0
PRE_READ_QR_STATES = ('APPROACHING_VICTIM', 'WAIT_5_SECONDS')
QR_PHOTO_RETRY_SEC = 1.5


@dataclass(frozen=True)
class Observation:
    attempt_id: str
    label: str
    stamp: float
    frame_id: str
    position: tuple[float, float, float]
    image_jpeg_b64: str
    confidence: float

    @classmethod
    def parse(cls, data: dict, attempt_id: str, now: float) -> 'Observation':
        obs = cls(**dict(data, position=tuple(data['position'])))
        if (obs.attempt_id != attempt_id or obs.frame_id != 'map' or
                not 0 <= now - obs.stamp <= 1.0 or len(obs.position) != 3 or
                not all(math.isfinite(v) for v in obs.position) or
                not MIN_OBSERVATION_CONFIDENCE <= obs.confidence <= 1 or not obs.image_jpeg_b64):
            raise ValueError('Stale or invalid observation')
        image = base64.b64decode(obs.image_jpeg_b64, validate=True)
        if not image.startswith(b'\xff\xd8') or len(image) > 2_000_000:
            raise ValueError('JPEG evidence required')
        return obs


class Evacuation:
    """Pure orchestration owned by MissionStateMachine; ROS operations are asynchronous."""

    def __init__(self, sm: Any):
        self.sm = sm
        self.attempt_id = ''
        self.started = None
        self.home = None
        self.observations: dict[str, Observation] = {}
        self.victim = None
        self.selected_cell = None
        self.stationary_since = None
        self.standing_seconds = 0.0
        self.standing_done = False
        self.last_odom = None
        self.stationary = False
        self.paths: dict[tuple[int, int], float] = {}
        self.home_length = None
        self.paths_at = 0.0
        self.reason = ''
        self.last_stage = 'PREPARATION'
        self.interpretation = None
        self.qr_started = None
        self.qr_last_photo_at = None
        self.qr_stamp = 0.0
        self.qr_image_stamp = 0.0
        self.nav_retries = 0
        self.outcome = None
        self.map = copy.deepcopy(getattr(sm.llm_client, 'arena', None) or {})
        self.map_version = self.map.get('version')
        self.last_plan = 0.0
        self.last_home_plan = 0.0
        self.landmark_confirmed = False
        self.qr_source_started = None
        self.attempt_source_started = None
        self.pre_read_qr_max_age_sec = PRE_READ_QR_MAX_AGE_SEC
        self.pre_read_qr_text: str | None = None
        self.pre_read_qr_stamp: float | None = None
        self.pre_read_qr_attempt_id: str = ''
        self.pre_read_qr_image_bytes: bytes | None = None
        self.pre_read_qr_image_b64: str | None = None
        self.pre_read_qr_image_stamp: float | None = None
        self.pre_read_qr_image_source_stamp: float | None = None
        self.pre_read_qr_image_attempt_id: str = ''

    def begin(self) -> None:
        sm = self.sm
        self.__init__(sm)
        self.attempt_id = uuid.uuid4().hex
        self.started = time.monotonic()
        if sm.ros_node and getattr(sm.ros_node, 'node', None):
            self.attempt_source_started = sm.ros_node.node.get_clock().now().nanoseconds / 1e9
        self.home = type(sm.current_waypoint)(sm.robot_x, sm.robot_y, sm.robot_yaw,
                                              (int(sm.robot_x / .8), int(sm.robot_y / .8)), 'start')
        sm.victim_found = sm.victim_detected = sm.qr_scanned = sm.evacuated_home = False
        sm.qr_code_data = sm.latest_qr_text = None
        sm.latest_qr_received_at = None
        sm.latest_qr_image_bytes = sm.latest_qr_image_b64 = None
        sm.wait_timer_start = None
        self.last_stage = 'LLM_INTERPRETED'
        self.interpretation = copy.deepcopy(sm.command_interpretation.to_dict()) if sm.command_interpretation else None
        sm._log('STATE', f'Попытка {self.attempt_id}, версия карты {self.map_version}')

    def observe(self, data: dict, now: float) -> None:
        obs = Observation.parse(data, self.attempt_id, now)
        sm = self.sm
        if sm.state.value != 'SEARCHING_VICTIM':
            return
        # Restrict observations to the selected landmark's inspection region.
        points = sm.inspection_waypoints
        if not points or min(math.hypot(obs.position[0]-p.x, obs.position[1]-p.y) for p in points) > 1.2:
            return
        if obs.label != 'victim':
            self.observations[obs.label] = obs
            if obs.label == getattr(sm.command_interpretation, 'target_landmark_id', None):
                self.landmark_confirmed = True
            return
        if self.victim is not None:
            return  # Keep the position and paths from the confirmation that started planning.
        self.observations[obs.label] = self.victim = obs
        self.landmark_confirmed = True
        sm.victim_found = sm.victim_detected = True
        self.last_stage = 'VICTIM_FOUND'
        sm._log('VISION', 'Фигурка подтверждена по кадру и глубине; проверка доступных ячеек')
        sm._publish_zero_velocity()
        self.request_paths()

    def request_paths(self) -> None:
        sm = self.sm
        self.paths = {}
        self.last_plan = time.monotonic()
        if sm.mock_mode:
            for x in range(5):
                for y in range(5):
                    if [x, y] not in self.map.get('blocked_cells', []):
                        self.paths[x, y] = math.hypot(.4+.8*x-sm.robot_x, .4+.8*y-sm.robot_y)
            self.paths_at = time.monotonic()
        elif sm.ros_node:
            sm.ros_node.plan_cells(self.attempt_id)

    def select_cell(self) -> None:
        sm = self.sm
        if not self.paths or self.victim is None:
            return
        vx, vy, _ = self.victim.position
        candidates = [cell for cell in self.paths
                      if math.hypot(.4+.8*cell[0]-vx, .4+.8*cell[1]-vy) >= .32
                      and (sm.mock_mode or sm.ros_node.navigation.free(.4+.8*cell[0], .4+.8*cell[1]))]
        if not candidates:
            return
        cell = min(candidates, key=lambda c: (round(math.hypot(.4+.8*c[0]-vx, .4+.8*c[1]-vy), 6), self.paths[c], c))
        self.selected_cell = cell
        x, y = .4+.8*cell[0], .4+.8*cell[1]
        sm.current_waypoint = type(sm.current_waypoint)(x, y, math.atan2(vy-y, vx-x), cell, 'victim_approach')
        sm._cancel_nav_goal()
        if (cell == (int(sm.robot_x/.8), int(sm.robot_y/.8)) and
                math.hypot(sm.robot_x-vx, sm.robot_y-vy) >= .32 and
                (sm.mock_mode or sm.ros_node.navigation.free(sm.robot_x, sm.robot_y))):
            sm.current_waypoint.x, sm.current_waypoint.y = sm.robot_x, sm.robot_y
            sm.state = type(sm.state).WAIT_5_SECONDS
            self.stationary_since = None
            sm._publish_zero_velocity()
            sm._log('NAV', f'Робот уже в ближайшей доступной ячейке {cell}; проверка стоянки')
            return
        sm.state = type(sm.state).APPROACHING_VICTIM
        sm._log('NAV', f'Ближайшая доступная ячейка {cell}, путь {self.paths[cell]:.2f} м')
        sm._publish_goal_pose(sm.current_waypoint)

    def odometry(self, vx: float, vy: float, wz: float) -> None:
        now = time.monotonic()
        self.stationary = all(math.isfinite(v) for v in (vx, vy, wz)) and math.hypot(vx, vy) < .01 and abs(wz) < .02
        if not self.stationary or self.last_odom is None or now-self.last_odom > .5:
            self.stationary_since = None
        self.last_odom = now

    def still(self) -> bool:
        return self.sm.mock_mode or (self.stationary and self.last_odom is not None and time.monotonic()-self.last_odom <= .5)

    def return_home(self, reason: str) -> None:
        sm = self.sm
        self.clear_pre_read_qr()
        self.reason = reason
        sm._cancel_nav_goal()
        sm.current_waypoint = self.home
        sm.state = type(sm.state).RETURNING_HOME
        self.stationary_since = None
        sm._log('STATE', f'Возврат на старт; {reason}')
        sm._publish_goal_pose(self.home)

    def clear_pre_read_qr(self) -> None:
        """Drop any cached pre-read QR text and JPEG snapshot."""
        self.pre_read_qr_text = None
        self.pre_read_qr_stamp = None
        self.pre_read_qr_attempt_id = ''
        self.pre_read_qr_image_bytes = None
        self.pre_read_qr_image_b64 = None
        self.pre_read_qr_image_stamp = None
        self.pre_read_qr_image_source_stamp = None
        self.pre_read_qr_image_attempt_id = ''

    def cache_qr_image(self, data: bytes, stamp: float, source_stamp: float | None = None) -> None:
        """Cache a valid QR JPEG frame captured during victim approach/hold for the active attempt."""
        if not self.attempt_id or self.sm.state.value not in PRE_READ_QR_STATES:
            return
        if not data.startswith(b'\xff\xd8') or len(data) > 2_000_000:
            return
        if source_stamp is not None and any(
            lower_bound is not None and source_stamp < lower_bound
            for lower_bound in (self.attempt_source_started, self.pre_read_qr_image_source_stamp)
        ):
            return
        self.pre_read_qr_image_bytes = data
        self.pre_read_qr_image_b64 = base64.b64encode(data).decode('ascii')
        self.pre_read_qr_image_stamp = stamp
        self.pre_read_qr_image_source_stamp = source_stamp
        self.pre_read_qr_image_attempt_id = self.attempt_id

    def _consume_pre_read_qr(self, now: float) -> bool:
        """Promote fresh pre-read QR text and JPEG from the same attempt when entering READING_QR."""
        if not self.attempt_id or self.qr_started is None:
            self.clear_pre_read_qr()
            return False
        if (
            self.pre_read_qr_attempt_id != self.attempt_id
            or self.pre_read_qr_image_attempt_id != self.attempt_id
            or not self.pre_read_qr_text
            or not self.pre_read_qr_text.strip()
            or self.pre_read_qr_stamp is None
            or self.pre_read_qr_image_bytes is None
            or self.pre_read_qr_image_b64 is None
            or self.pre_read_qr_image_stamp is None
        ):
            self.clear_pre_read_qr()
            return False
        if (
            not 0.0 <= now - self.pre_read_qr_stamp <= self.pre_read_qr_max_age_sec
            or not 0.0 <= now - self.pre_read_qr_image_stamp <= self.pre_read_qr_max_age_sec
        ):
            self.clear_pre_read_qr()
            return False
        if (
            self.qr_source_started is not None
            and self.pre_read_qr_image_source_stamp is not None
            and not 0.0 <= self.qr_source_started - self.pre_read_qr_image_source_stamp <= self.pre_read_qr_max_age_sec
        ):
            self.clear_pre_read_qr()
            return False
        sm = self.sm
        sm.qr_code_data = self.pre_read_qr_text
        sm.latest_qr_text = self.pre_read_qr_text
        sm.latest_qr_received_at = sm._now_str()
        self.qr_stamp = now
        sm.latest_qr_image_bytes = self.pre_read_qr_image_bytes
        sm.latest_qr_image_b64 = self.pre_read_qr_image_b64
        self.qr_image_stamp = now
        self.clear_pre_read_qr()
        return True

    def qr(self, text: str, stamp: float) -> None:
        sm = self.sm
        if not text.strip():
            return
        state = sm.state.value
        if state == 'READING_QR':
            if self.qr_started is None or stamp < self.qr_started or self.has_qr_evidence():
                return
            sm.qr_code_data = text
            self.qr_stamp = stamp
            sm.latest_qr_text = text
            sm.latest_qr_received_at = sm._now_str()
            return
        if self.attempt_id and state in PRE_READ_QR_STATES:
            self.pre_read_qr_text = text
            self.pre_read_qr_stamp = stamp
            self.pre_read_qr_attempt_id = self.attempt_id

    def has_qr_evidence(self) -> bool:
        return (
            self.qr_started is not None
            and bool(self.sm.qr_code_data)
            and self.qr_stamp >= self.qr_started
            and self.qr_image_stamp >= self.qr_started
            and self.sm.latest_qr_image_bytes is not None
        )

    def tick(self, dt: float) -> None:
        sm = self.sm
        state = sm.state.value
        inactive = {'PREPARATION', 'LLM_PARSING', 'READY_TO_START', 'MISSION_COMPLETE'}
        if state in inactive or self.started is None:
            return
        now = time.monotonic()
        elapsed = now-self.started
        if elapsed >= 300:
            sm._cancel_nav_goal()
            sm._publish_zero_velocity()
            self.reason = 'Лимит времени попытки'
            self.finish()
            return
        if state in {'EMERGENCY_STOP', 'PAUSED'}:
            self.stationary_since = None
            return
        if not sm.mock_mode and (not sm.ros_node or not sm.ros_node.has_fresh_odometry() or not sm.ros_node.update_pose_from_tf()):
            sm.previous_state = sm.state
            sm.state = type(sm.state).PAUSED
            self.stationary_since = None
            sm._cancel_nav_goal()
            sm._publish_zero_velocity()
            sm._log('ERROR', 'Потеря локализации или одометрии; остановка')
            return
        if sm.mock_mode:
            self.home_length = math.hypot(sm.robot_x-self.home.x, sm.robot_y-self.home.y)
        elif now-self.paths_at > 2 and now-self.last_home_plan > 2:
            sm.ros_node.plan_home(self.attempt_id)
            self.last_home_plan = now
        reserve = max(30., (self.home_length / .15 + 20) if self.home_length is not None and now-self.paths_at <= 5 else 60.)
        if elapsed >= 300-reserve and state != 'RETURNING_HOME':
            self.return_home('Сохранение времени на обратный путь')
            state = sm.state.value
        if not sm.mock_mode and self.victim is not None and math.dist(
                (sm.robot_x, sm.robot_y), self.victim.position[:2]) < .32:
            sm._cancel_nav_goal()
            sm._publish_zero_velocity()
            sm.previous_state = sm.state
            sm.state = type(sm.state).PAUSED
            sm._log('ERROR', 'Достигнут защитный зазор до фигурки')
            return
        if sm.mock_mode and state in {'NAVIGATING_TO_LANDMARK', 'APPROACHING_VICTIM', 'RETURNING_HOME'}:
            sm._step_mock_kinematics(dt)
        if state == 'NAVIGATING_TO_LANDMARK':
            if sm._check_reached_waypoint(sm.current_waypoint):
                sm.state = type(sm.state).SEARCHING_VICTIM
                sm._cancel_nav_goal()
                sm.spin_step, sm.spin_phase, sm.spin_timer = 0, 'ROTATE', 0.
                sm.scan_center_yaw = sm._landmark_bearing()
                self.last_stage = 'LANDMARK_REACHED'
                sm._publish_zero_velocity()
        elif state == 'SEARCHING_VICTIM':
            if sm.victim_found:
                self.select_cell()
                if now-self.last_plan > 5:
                    self.request_paths()
            else:
                sm._handle_spin_and_scan(dt)
        elif state == 'APPROACHING_VICTIM':
            if sm._check_reached_waypoint(sm.current_waypoint):
                sm._cancel_nav_goal()
                sm.state = type(sm.state).WAIT_5_SECONDS
                self.stationary_since = None
        elif state == 'WAIT_5_SECONDS':
            sm._publish_zero_velocity()
            wp = sm.current_waypoint
            in_cell = self.selected_cell == (int(sm.robot_x/.8), int(sm.robot_y/.8))
            if not in_cell or math.hypot(sm.robot_x-wp.x, sm.robot_y-wp.y) > .15 or not self.still():
                self.stationary_since = None
                self.standing_seconds = 0
                return
            if self.stationary_since is None:
                self.stationary_since = now
            sm.wait_timer_start = time.time() - (now-self.stationary_since)
            self.standing_seconds = now-self.stationary_since
            if self.standing_seconds >= 5:
                self.standing_done = True
                self.last_stage = 'HOLD_COMPLETE'
                sm.state = type(sm.state).READING_QR
                self.qr_started = now
                if sm.ros_node and getattr(sm.ros_node, 'node', None):
                    self.qr_source_started = sm.ros_node.node.get_clock().now().nanoseconds / 1e9
                sm.qr_code_data = None
                sm._log('STATE', 'Пять секунд неподвижности подтверждены; чтение QR')
                if self._consume_pre_read_qr(now):
                    sm._log('STATE', f'Использован предсчитанный QR-код текущей попытки (<= {self.pre_read_qr_max_age_sec:.1f} с)')
                else:
                    self.qr_last_photo_at = now
                    sm._trigger_photo_snapshot()
        elif state == 'READING_QR':
            if self.qr_started is None:
                return
            if self.has_qr_evidence():
                sm.qr_scanned = True
                self.last_stage = 'QR_READ'
                sm._log('QR', sm.qr_code_data)
                self.return_home('Информация о состоянии получена')
            elif now-self.qr_started > 3 and self.victim is not None:
                # Bounded in-place views preserve the verified approach cell.
                sm.spin_step = min(3, int((now-self.qr_started)/5) % 4)
                target = math.atan2(self.victim.position[1]-sm.robot_y, self.victim.position[0]-sm.robot_x) + sm.SCAN_OFFSETS[sm.spin_step]/3
                error = sm._yaw_error(target, sm.robot_yaw)
                if abs(error) > .05 and sm.ros_node:
                    sm.ros_node.send_cmd_vel(0., max(-.2, min(.2, error)))
                else:
                    sm._publish_zero_velocity()
                    if self.still() and (
                        self.qr_last_photo_at is None or now - self.qr_last_photo_at >= QR_PHOTO_RETRY_SEC
                    ):
                        self.qr_last_photo_at = now
                        sm._trigger_photo_snapshot()
            else:
                sm._publish_zero_velocity()
        elif state == 'RETURNING_HOME':
            if sm._check_reached_waypoint(self.home) and self.still():
                sm.evacuated_home = True
                self.finish()
        if sm.ros_node and getattr(sm.ros_node, 'goal_status', None) in (5, 6):
            sm.ros_node.goal_status = None
            self.nav_retries += 1
            if self.nav_retries > 3:
                sm._cancel_nav_goal()
                sm.previous_state = sm.state
                sm.state = type(sm.state).PAUSED
                sm._publish_zero_velocity()
                terrain = getattr(sm.ros_node, 'terrain_status', None)
                if terrain and time.monotonic() - terrain[0] <= 1. and (
                    terrain[1].get('blocked_cells', 0) > 0
                    or terrain[1].get('reason') == 'Проезд перекрыт или поверхность не подтверждена'
                ):
                    self.reason = 'Проезд перекрыт или поверхность не подтверждена. Объезд не найден'
                else:
                    self.reason = 'Три неудачных перепланирования'
                sm._log('ERROR', self.reason)
            elif state == 'APPROACHING_VICTIM':
                self.clear_pre_read_qr()
                sm.state = type(sm.state).SEARCHING_VICTIM
                self.request_paths()
            else:
                sm._publish_goal_pose(sm.current_waypoint)

    def finish(self) -> None:
        sm = self.sm
        self.clear_pre_read_qr()
        self.outcome = 'COMPLETE' if all((sm.llm_parsed, self.landmark_confirmed, sm.victim_found, self.standing_done, sm.qr_scanned, sm.evacuated_home)) else 'PARTIAL'
        sm.state = type(sm.state).MISSION_COMPLETE
        sm.mission_end_time = time.time()
        sm._cancel_nav_goal()
        sm._publish_zero_velocity()
        sm._log('STATE', f'Итог {self.outcome}; последний этап {self.last_stage}; {self.reason}')
        sm.save_protocol_to_disk()

    def protocol(self) -> dict:
        return {'attempt_id': self.attempt_id, 'map_version': self.map_version,
                'interpretation': self.interpretation,
                'home': asdict(self.home) if self.home else None,
                'victim': asdict(self.victim) if self.victim else None,
                'local_objects': {k: asdict(v) for k,v in self.observations.items() if k != 'victim'},
                'selected_cell': self.selected_cell, 'standing_seconds': self.standing_seconds,
                'standing_done': self.standing_done, 'outcome': self.outcome,
                'landmark_confirmed': self.landmark_confirmed,
                'last_stage': self.last_stage, 'reason': self.reason,
                'qr_image_jpeg_b64': self.sm.latest_qr_image_b64 if self.sm.qr_scanned else None}
