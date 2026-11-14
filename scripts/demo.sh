#!/bin/sh
# Run from any directory after building the controller and worker images.
# Example: sh scripts/demo.sh --controller-image mini-object-store-controller:integration \
#   --worker-image mini-object-store-worker:integration --large
# --help lists options. Only uniquely named, labelled QA resources are created;
# the existing Compose stack, worker1..worker4 containers and data are not used.
set -eu
root=$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)
exec "${PYTHON:-python}" "$root/tests/test_end_to_end.py" "$@"
