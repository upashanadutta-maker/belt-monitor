"""Every number the simulator uses, in one place.

The backend imports the belt geometry and VALID_RANGE from here too, so the
simulator and the backend can never disagree about them.
"""

# ---------------------------------------------------------------- belt
CONVEYOR_LENGTH_M = 3000          # distance from tail pulley to head pulley
BELT_LOOP_M = 6000                # the belt goes out and comes back
BELT_SPEED_MPS = 4.0              # design speed; one lap = 6000 / 4 = 1500 s = 25 min
BELT_WIDTH_MM = 1600

SENSOR_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10"]
# S1 is 300 m from the tail pulley, S10 is at 3000 m, which is the head (drive) pulley.
SENSOR_POSITION_M = {"S1": 300, "S2": 600, "S3": 900, "S4": 1200, "S5": 1500,
                     "S6": 1800, "S7": 2100, "S8": 2400, "S9": 2700, "S10": 3000}

READING_INTERVAL_S = 60           # each sensor sends one message per minute

CHANNELS = ["temperature_c", "vibration_mm_s", "belt_speed_mps", "drift_mm"]

# ---------------------------------------------------------------- healthy signals
# Air temperature follows a daily wave: 36 C at 15:00, 20 C at 03:00.
AMBIENT_MEAN_C = 28.0
AMBIENT_SWING_C = 8.0
AMBIENT_HOTTEST_HOUR = 15

BEARING_RISE_C = 22.0             # a healthy roller bearing runs this much above the air
VIBRATION_BASE_MM_S = 2.0         # healthy vibration velocity (RMS)

# Random noise added to every reading (standard deviation).
NOISE_SD = {"temperature_c": 0.8, "vibration_mm_s": 0.25,
            "belt_speed_mps": 0.02, "drift_mm": 6.0}

# Each sensor point gets one fixed offset per channel, drawn once from
# -OFFSET_MAX..+OFFSET_MAX. No two sensor points read exactly the same.
OFFSET_MAX = {"temperature_c": 3.0, "vibration_mm_s": 0.3,
              "belt_speed_mps": 0.0, "drift_mm": 5.0}

# ---------------------------------------------------------------- failures
# A failure episode has three moments:
#   onset    -> the fault starts to develop
#   failure  -> the fault is fully developed (the values below are reached)
#   repaired -> maintenance has fixed it; readings go back to healthy
# Real faults take days. The durations are compressed to hours so that a
# 60-day run holds enough episodes to train on. The README must say so.
FAILURE_DURATION_H = {"seized_roller": (8, 24),   # (shortest, longest) onset -> failure
                      "belt_drift": (6, 18),
                      "belt_slip": (4, 12)}
FAILURE_MEAN_GAP_H = 36           # average quiet time between two episodes of one type
REPAIR_MINUTES = (30, 90)         # failure -> repaired

ROLLER_VIBRATION_ADD = 7.0        # mm/s added at failure. Grows as progress ** 1.5 (early)
ROLLER_TEMPERATURE_ADD = 50.0     # deg C added at failure. Grows as progress ** 3 (late)
DRIFT_ADD_MM = 150.0              # sideways shift at failure. Grows as progress ** 2
SLIP_SPEED_LOSS = 0.20            # share of speed lost at failure (4.0 -> 3.2 m/s)

# ---------------------------------------------------------------- messy data
P_DROPPED = 0.005                 # chance a message is never sent
P_NULL_FIELD = 0.003              # chance one value inside a message is null
P_SPIKE = 0.002                   # chance one value is replaced by a wild number
P_LATE = 0.01                     # chance a message arrives late
LATE_MINUTES = (2, 15)

OUTAGE_MEAN_GAP_H = 240           # per sensor: one silent period about every 10 days
OUTAGE_MINUTES = (10, 120)
STUCK_MEAN_GAP_H = 240            # per sensor: one frozen channel about every 10 days
STUCK_MINUTES = (30, 180)

# A value outside these limits cannot be a real measurement. Half of all
# spikes are pushed outside them, the other half stay inside.
VALID_RANGE = {"temperature_c": (-20.0, 200.0),
               "vibration_mm_s": (0.0, 50.0),
               "belt_speed_mps": (0.0, 8.0),
               "drift_mm": (-800.0, 800.0)}      # 800 mm = half the belt width

IMPOSSIBLE_SPIKES = {"temperature_c": [-273.0, 999.0],
                     "vibration_mm_s": [-5.0, 500.0],
                     "belt_speed_mps": [-3.0, 40.0],
                     "drift_mm": [-5000.0, 5000.0]}
# A spike that stays inside the valid range: the true value plus one of these.
PLAUSIBLE_SPIKE_ADD = {"temperature_c": (25.0, 60.0),
                       "vibration_mm_s": (5.0, 20.0),
                       "belt_speed_mps": (-2.5, -1.0),
                       "drift_mm": (100.0, 300.0)}

DECIMALS = {"temperature_c": 2, "vibration_mm_s": 3, "belt_speed_mps": 3, "drift_mm": 1}
