import storage

# Let code.py write to the drive, so the menu's SAVE can store grooves in
# /grooves (see groove.py). The drive is read-only to the computer while
# this is in effect -- to copy code over, boot into safe mode (BOOTSEL
# during startup), where boot.py doesn't run.
storage.remount("/", readonly=False)
