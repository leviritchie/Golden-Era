#!/usr/bin/env bash
# Deprecated name — forwards to package_release.sh
exec "$(dirname "$0")/package_release.sh" "$@"
