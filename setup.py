# Copyright (c) The RTMPy Project.
# See LICENSE.txt for details.

from distribute_setup import use_setuptools
use_setuptools(download_delay=3)

import sys, os.path

from setuptools import setup, find_packages
from setuptools.command import test


# add the path of the folder this file lives in
base_path = os.path.dirname(os.path.normpath(os.path.abspath(__file__)))

# since the basedir is set as the first option in sys.path, this works
sys.path.insert(0, base_path)

readme = os.path.join(base_path, 'README.txt')


class TestCommand(test.test):
    """
    Ensures that unittest2 is imported if required and replaces the old
    unittest module.
    """

    def run_tests(self):
        try:
            import unittest2
            import sys

            sys.modules['unittest'] = unittest2
        except ImportError:
            pass

        return test.test.run_tests(self)



def get_test_requirements():
    tests_require = []

    if sys.version_info < (2, 7):
        tests_require.append('unittest2')

    return tests_require


def get_version():
    from rtmpy import __version__

    return '.'.join([str(x) for x in __version__])


def get_install_requirements():
    """
    Returns a list of dependencies for RTMPy to function correctly on the
    target platform.
    """
    install_requires = ['Twisted>=2.5.0', 'PyAMF>=0.6,<=0.6b2']

    if sys.platform.startswith('win'):
        install_requires.append('PyWin32')

    return install_requires

keyw = """\
rtmp flv rtmps rtmpe rtmpt rtmpte amf amf0 amf3 flex flash http https
streaming video audio sharedobject webcam record playback pyamf client
flashplayer air actionscript decoder encoder gateway server"""

setup(name = "RTMPy",
    version = get_version(),
    description = "Twisted protocol for RTMP",
    long_description = open(readme, 'rt').read(),
    cmdclass = {
       'test': TestCommand
    },
    url = "http://rtmpy.org",
    author = "The RTMPy Project",
    author_email = "rtmpy-dev@rtmpy.org",
    keywords = keyw,
    packages = find_packages(exclude=["*.tests"]),
    install_requires = get_install_requirements(),
    tests_require = get_test_requirements(),
    test_suite = "rtmpy.tests.get_suite",
    zip_safe = True,
    license = "MIT License",
    platforms = ["any"],
    classifiers = [
        "Development Status :: 2 - Pre-Alpha",
        "Framework :: Twisted",
        "Natural Language :: English",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.4",
        "Programming Language :: Python :: 2.5",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ])
