"""Minimal setup.py for editable install."""
from setuptools import setup, find_packages

setup(
    name="quadruped-robot-competition",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
)
