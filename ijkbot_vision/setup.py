from setuptools import find_packages, setup

package_name = 'ijkbot_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/qr_reader.launch.py']),
        ('share/' + package_name + '/config', ['config/qr_reader.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='IJKbot Team',
    maintainer_email='team@ijkbot.local',
    description='Computer-vision nodes for IJKbot.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'qr_reader_node = ijkbot_vision.qr_reader_node:main',
        ],
    },
)
