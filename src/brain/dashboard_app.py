#!/usr/bin/env python3
"""
dashboard_app.py — Отдельный модуль запуска судейского Web Dashboard на базе NiceGUI
для мобильного робота IJKbot (Хакатон «Эвакуация», Кубок РТК Высшая Лига).

Предоставляет:
- Окно ввода задания судей и демонстрации работы LLM с подсветкой JSON
- Видеопоток камеры RealSense с наложенными детекциями человека и QR-кода
- Интерактивную векторную карту полигона 5х5 ячеек (4.0х4.0 м) с позицией робота
- Кнопки управления: «Распознать задание», «СТАРТ МИССИИ», «E-STOP», штрафы
- Судейскую лог-панель с миллисекундными временными метками и экспортом протокола
"""

try:
    from brain.mission_sm import main as sm_main
except ImportError:
    from mission_sm import main as sm_main


def main(args=None):
    """Точка запуска Web Dashboard."""
    sm_main(args)


if __name__ in {"__main__", "__mp_main__"}:
    main()
