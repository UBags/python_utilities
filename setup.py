"""Setup script for prod-py-utils package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file safely. Missing or non-UTF-8 READMEs would otherwise
# crash the install with a confusing traceback.
this_directory = Path(__file__).parent
readme = this_directory / "README.md"
long_description = readme.read_text(encoding="utf-8") if readme.exists() else ""

setup(
    name="prod-py-utils",
    version="1.0.0",
    author="Uddipan Bagchi",
    author_email="uddipan.tweets@gmail.com",
    license="MIT",
    description="Production-ready utilities for modern Python applications, including a payments subpackage.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/UBags/python-utilities",
    # Both python_utilities/ and payments/ are top-level packages in this repo.
    # find_packages walks the tree from setup.py's directory; the explicit
    # `include` list makes the intent obvious and prevents accidental
    # inclusion of stray top-level directories.
    packages=find_packages(
        include=[
            "python_utilities", "python_utilities.*",
            "payments", "payments.*",
        ],
        exclude=["tests", "tests.*", "examples", "examples.*"],
    ),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business :: Financial",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Operating System :: OS Independent",
        "Typing :: Typed",
    ],
    python_requires=">=3.9",
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
    },
    keywords=(
        "utilities decorators async performance validation "
        "dependency-injection patterns payments idempotency saga webhooks"
    ),
    project_urls={
        "Bug Reports": "https://github.com/UBags/python-utilities/issues",
        "Source": "https://github.com/UBags/python-utilities",
        "Documentation": "https://github.com/UBags/python-utilities#readme",
    },
)