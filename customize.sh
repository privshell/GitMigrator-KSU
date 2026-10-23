#!/system/bin/sh
SKIPUNZIP=0
ui_print "- Git Migrator"
ui_print "- Needs Termux with:  pkg install python git"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/bin/gm.sh" 0 0 0755
set_perm "$MODPATH/bin/gm.py" 0 0 0755
mkdir -p /data/adb/gitmigrator
ui_print "- Data folder: /data/adb/gitmigrator (tokens are stored there, chmod 600)"
ui_print "- Open the module's WebUI from the KernelSU Manager"
