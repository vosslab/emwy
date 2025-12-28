#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [ ! -f "Psy-Gangnam_Style.mp4" ]; then
	yt-dlp -f 18 http://youtu.be/9bZkp7q19f0 -o Psy-Gangnam_Style.mp4
fi

../emwy_cli.py -y gangnam.emwy.yaml
