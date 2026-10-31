"""Inspect/recover crash guards; never clears guards held by a live DB writer."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/control'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-id', required=True)
    parser.add_argument('--apply', action='store_true')
    arguments = parser.parse_args()
    from studio.widget_frame_cache import recover
    print(json.dumps(recover(arguments.workspace_id, arguments.apply)))


if __name__ == '__main__':
    main()
