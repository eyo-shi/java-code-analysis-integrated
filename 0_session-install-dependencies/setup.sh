#!/bin/bash
set -e
pip install -r 0_session-install-dependencies/requirements.txt
pip install --no-deps git+https://github.com/fastforwardlabs/cmlbootstrap#egg=cmlbootstrap
