# -*- coding: utf-8 -*-

import codecs
import os

from setuptools import setup

long_description = codecs.open("README.rst", "r", "utf-8").read()

CLASSIFIERS = [
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: BSD License',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2.6',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3.3',
    'Operating System :: POSIX',
    'Operating System :: MacOS :: MacOS X',
    'Operating System :: Unix',
    'Topic :: Software Development :: Build Tools',
    'Topic :: Software Development :: Libraries',
    'Topic :: Software Development :: Libraries :: Python Modules',
    'Topic :: System :: Clustering',
    'Topic :: System :: Software Distribution',
    'Topic :: System :: Systems Administration',
]

NAME = 'neckbeard'

# Distribution Meta stuff because we can't just import neckbeard
# Mostly cribbed fro Celery's setup.py

import re

# Standard ``__foo__ = 'bar'`` pairs.
re_meta = re.compile(r'__(\w+?)__\s*=\s*(.*)')
# VERSION tuple
re_vers = re.compile(r'VERSION\s*=\s*\((.*?)\)')
# Module docstring
re_doc = re.compile(r'^"""(.+?)"""')
# We don't need the quotes
rq = lambda s: s.strip("\"'")

def add_default(m):
    """
    Get standard ``__foo__ = 'bar'`` pairs as a (foo, bar) tuple.
    """
    attr_name, attr_value = m.groups()
    return ((attr_name, rq(attr_value)), )

def add_version(m):
    v = list(map(rq, m.groups()[0].split(', ')))
    return (('VERSION', '.'.join(v[0:3]) + ''.join(v[3:])), )


def add_doc(m):
    """
    Grab the module docstring
    """
    return (('doc', m.groups()[0]), )

pats = {
    re_meta: add_default,
    re_vers: add_version,
    re_doc: add_doc,
}

here = os.path.abspath(os.path.dirname(__file__))
meta_fh = open(os.path.join(here, 'neckbeard/__init__.py'))

# Parse out the package meta information from the __init__ using *shudder*
# regexes
meta = {}
try:
    for line in meta_fh:
        if line.strip() == '# -eof meta-':
            break
        for pattern, handler in pats.items():
            m = pattern.match(line.strip())
            if m:
                meta.update(handler(m))
finally:
    meta_fh.close()

# Requirements

def strip_comments(l):
    return l.split('#', 1)[0].strip()


def reqs(*f):
    return list(filter(None, [strip_comments(l) for l in open(
        os.path.join(os.getcwd(), 'requirements', *f)).readlines()]))


install_requires = reqs('default.txt')
tests_require = reqs('development.txt')

# Entry Points

entrypoints = {
    'console_scripts': 'neckbeard = neckbeard.bin.neckbeard:main',
}

setup(
    name=NAME,
    version=meta['VERSION'],
    description=meta['doc'],
    author=meta['author'],
    author_email=meta['contact'],
    url=meta['homepage'],
    long_description=long_description,
    packages=[NAME],
    license='BSD',
    platforms=['any'],
    classifiers=CLASSIFIERS,
    install_requires=install_requires,
    tests_require=tests_require,
    test_suite='nose.collector',
    entry_points=entrypoints,
)
