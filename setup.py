try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name="syndicate-py",
    version="0.9.0",
    author="Tony Garnock-Jones",
    author_email="tonyg@leastfixedpoint.com",
    license="GNU General Public License v3 or later (GPLv3+)",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3",
    ],
    packages=["syndicate"],
    url="https://git.syndicate-lang.org/syndicate-lang/syndicate-py",
    description="Syndicated Actor model and Syndicate network protocol for Python 3",
    install_requires=['websockets', 'preserves'],
    python_requires=">=3.6, <4",
    setup_requires=['setuptools_scm'],
    include_package_data=True,
)
