# Design document

## The belt

A 3 km mining conveyor. The belt is a closed loop, so it is 6 km long. It runs at 4 m/s, which
makes one lap 25 minutes. A failure stops production, and a seized roller under a moving belt is
a fire risk. The goal is to see a failure coming early enough to plan a repair.

## What I monitor, and why

Ten sensor points, S1 to S10, one every 300 m. S10 is at the drive pulley. Each point reports
four values once a minute.

| Value | What it shows | Failure it reveals |
|---|---|---|
| Roller bearing temperature | Friction in the bearing | Seized roller, late stage. Also the fire risk. |
| Vibration | Wear in the bearing | Seized roller, early stage. It moves hours before temperature does. |
| Belt speed | Whether the belt follows the drive | Belt slip at the drive pulley. |
| Sideways drift | Whether the belt runs centred | Belt drift (mistracking), which damages the belt edge and spills material. |

A camera watches the belt surface for wear and tear: tears, punctures, holes, impact damage and
old repairs.

## Two kinds of data, two chains

Sensor readings are data over time. Belt images are image data. Each has its own chain and both
end at the dashboard.

```
Sensors: simulator -> backend -> anomaly rules -> prediction model -> dashboard
Vision : camera frames -> damage model -> loop logic -> damage records -> backend -> dashboard
```

## How each part works

**Simulator.** There is no hardware, so a Python simulator produces every reading. It models
healthy signals (a daily temperature wave, noise, a fixed offset per sensor), three failures that
develop over hours, and messy data: dropped messages, outages, nulls, stuck sensors, spikes and
late messages. It writes a log of everything it injected. That log is the ground truth for every
check.

**Backend.** FastAPI and SQLite. For each message: validate, store, analyse. A bad value is stored
as missing and flagged, never guessed. Anomaly rules compare the newest readings with fixed limits
and need three readings in a row, so one spike cannot raise an alarm.

**Prediction model.** Gradient boosting on features built from each sensor's recent history: how
far each signal is from the sensor's own normal level, and how fast it is changing. The output is
the failure type, the sensor, and the hours left. It is trained on simulator history, cut by time
so that no failure episode is in both training and test.

**Sensor status.** Normal: no anomaly and no prediction. Abnormal: a current reading is past its
limit. Predicted failure: readings are inside the limits but the model expects a failure. No data:
the sensor is silent.

**Vision.** A segmentation model outlines each damaged area and names its type. The outline's size
gives the severity. The "patch work" class keeps old repairs from raising alarms.

**The loop.** A fixed camera sees the same damage again on every lap. The loop logic gives every
detection a position on the belt and merges detections at the same position into one record with
a size history. The README lists the loop problems I found and which ones are solved.

**Dashboard.** Streamlit, reading only from the backend's API. It shows every sensor point with
its status, the active anomalies with location, type and severity, the model's predictions, and
the vision records.

## What I left out, and why

Cloud deployment, login, message queues and more than one belt do not change whether the idea
works. The 18-hour duty cycle and load changes would make the simulator more realistic but would
touch every later part. Correcting belt position for slip and stretch needs a physical reference
mark; the loop logic allows for the error but does not measure it.
