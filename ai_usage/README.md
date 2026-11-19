# AI and research usage

This file lists every tool and source I used for this project and what I used each one for.
I am not including the raw chat logs: the work was spread over many separate threads in both
ChatGPT and Claude, with no single thread covering the project, so a summary is the honest
way to show what was used and for what.

## AI tools

**Claude (Anthropic)** was used for building the system.
- I wrote the design first: a 3 km conveyor with a 6 km belt loop, 10 sensor points, four
  signals, three failure types, the kinds of messy data, FastAPI with SQLite, gradient
  boosting, a Streamlit dashboard, the temperature limits, and what to leave out.
- Claude wrote the code for all five parts from that design and explained it step by step,
  in most detail for the backend.
- I ran every step myself in Kaggle notebooks and compared each output with the expected
  one. Claude could not run FastAPI, Streamlit or the trained damage model itself, so the
  first real run of those parts was mine.
- Changes Claude proposed and I accepted: belt slip as a belt-wide fault, five damage
  classes in place of four, the pretend belt for testing the loop logic, and a fourth
  sensor status, "no data".

**ChatGPT (OpenAI)** was used for the literature research: finding the papers and sources
listed below and working through the research areas.

## Other sources

**Google** was used to find and read the research papers listed below.

**YouTube** videos of mining conveyor belts in operation, to see what happens on a real belt
in a mine. Mining was new to me, and the videos gave me a picture of the belt, the rollers
and the material on it before I designed the simulator.

## Research papers studied

| Research paper | Year | Research focus |
|---|---|---|
| [Experimental Research on Condition Monitoring of Belt Conveyor Idlers](https://research.tudelft.nl/en/publications/experimental-research-on-condition-monitoring-of-belt-conveyor-id/) | 2018 | Sensor selection, vibration and temperature signatures |
| [Integrated Decision Making for Predictive Maintenance of Belt Conveyor Systems](https://repository.tudelft.nl/record/uuid%3A5a9f698e-b3fe-4927-8eaa-fcbe0f7b7fec) | 2019 | Condition monitoring and maintenance decisions |
| [BeltCrack: Sequential-image Industrial Conveyor Belt Crack Detection Dataset](https://arxiv.org/abs/2506.17892) | 2025 | Computer vision and sequential defect detection |
| [Non-Destructive Diagnostics in the Assessment of Splice Geometry in Steel Cord Conveyor Belts](https://www.mdpi.com/2076-3417/15/9/5034) | 2025 | Belt-relative localization and encoder-based tracking |

## Additional research areas

- **Conveyor engineering:** Belt mechanics, idlers, pulleys, motors, gearboxes, tension and operating conditions.
- **Failure mechanisms:** Bearing degradation, misalignment, slippage, motor overload and surface damage.
- **Sensor instrumentation:** Sensor placement, vibration, temperature, speed, displacement and motor current.
- **Synthetic data generation:** Physics-informed degradation, operating variability, correlated readings and run-to-failure trajectories.
- **Predictive maintenance:** Anomaly detection, fault diagnosis, failure forecasting and remaining useful life.
- **Continuous-loop vision:** Persistent defect identification, deduplication, spatial localization and damage progression.
- **Data reliability:** Missing readings, sensor drift, duplicate events, out-of-order timestamps and stale data.
- **Model evaluation:** Event-level recall, false alarm rates, warning lead time and leakage prevention.

## Research objective

Develop a research-backed, physically informed conveyor monitoring system that integrates
simulated sensor data, predictive maintenance, computer vision and continuous-loop defect
tracking into an actionable belt-health dashboard.
