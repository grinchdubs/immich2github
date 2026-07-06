"""Setup script for Immich to GitHub sync tool."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="immich-to-github",
    version="0.1.0",
    author="GRNCH",
    description="Sync photos from Immich to GitHub based on tags",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/grinchdubs/immich-to-github",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.27.0",
        "click>=8.1.7",
        "rich>=13.7.0",
        "pydantic>=2.5.3",
        "pydantic-settings>=2.1.0",
        "python-dotenv>=1.0.0",
        "PyYAML>=6.0.1",
        "schedule>=1.2.0",
        "python-dateutil>=2.8.2",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.3",
            "pytest-asyncio>=0.21.1",
            "pytest-cov>=4.1.0",
            "black>=23.12.1",
            "ruff>=0.1.9",
            "mypy>=1.8.0",
            "types-PyYAML>=6.0.12.12",
            "types-python-dateutil>=2.8.19.14",
        ],
    },
    entry_points={
        "console_scripts": [
            "immich-sync=src.cli:cli",
        ],
    },
)
