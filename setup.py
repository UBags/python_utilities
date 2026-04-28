"""Setup script for python-utilities package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="python-utilities",
    version="1.0.0",
    author="Python Utilities Contributors",
    author_email="contributors@python-utilities.org",
    description="Production-ready utilities for modern Python applications",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/python-utilities",
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Typing :: Typed",
    ],
    python_requires=">=3.8",
    install_requires=[
        "pydantic>=2.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "performance": [
            "prometheus-client>=0.16.0",
        ],
        "async": [
            "aiohttp>=3.8.0",
            "aiofiles>=23.0.0",
        ],
    ],
    keywords="utilities decorators async performance validation dependency-injection patterns",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/python-utilities/issues",
        "Source": "https://github.com/yourusername/python-utilities",
        "Documentation": "https://python-utilities.readthedocs.io",
    },
)
