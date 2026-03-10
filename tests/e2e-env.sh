#!/bin/bash
exec python3 "$(cd "$(dirname "$0")" && pwd)/e2e_env.py" "$@"
