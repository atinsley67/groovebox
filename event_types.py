# Input events — payload is pad index (0-7)
PAD_DOWN = "pd"
PAD_UP   = "pu"

# Function button events — payload is one of the BTN_* strings from config
BTN_DOWN = "bd"
BTN_UP   = "bu"

# Clock events emitted by the main loop when playing
TICK = "tk"   # one 16th-note step; payload = step index 0..15
BEAT = "bt"   # quarter note; payload = beat count (ever-increasing)
