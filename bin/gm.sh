#!/system/bin/sh
# Runs the Python backend with the Termux toolchain (as root).
# Usage: gm.sh <base64-json-request>
MODDIR="${0%/*}"
PREFIX=/data/data/com.termux/files/usr
DATA=/data/adb/gitmigrator

if [ ! -x "$PREFIX/bin/python3" ]; then
  echo '{"ok":false,"error":"python3 در Termux پیدا نشد. توی Termux بزن: pkg install python git"}'
  exit 0
fi

mkdir -p "$DATA/home" "$DATA/tmp"
export HOME="$DATA/home" TMPDIR="$DATA/tmp" GM_DATA="$DATA"
export PREFIX
export PATH="$PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$PREFIX/lib"
export GIT_EXEC_PATH="$PREFIX/libexec/git-core"
export SSL_CERT_FILE="$PREFIX/etc/tls/cert.pem"
export GIT_SSL_CAINFO="$PREFIX/etc/tls/cert.pem"
export LANG=C.UTF-8

exec "$PREFIX/bin/python3" "$MODDIR/gm.py" call "$1"
