from setuptools import find_packages, setup

package_name = 'ijkbot_brain'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/arena.json']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='IJKbot Team',
    maintainer_email='team@ijkbot.local',
    description='LLM decision-making and mission orchestrator for IJKbot',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'trial_planner = ijkbot_brain.trial_planner:main',
            'llm_client = ijkbot_brain.llm_client:main',
            'mission_sm = ijkbot_brain.mission_sm:main',
            'dashboard_app = ijkbot_brain.dashboard_app:main',
        ],
    },
)
