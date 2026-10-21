"""Deterministic process simulation, separate from protocols for testing."""
import math

SCENARIOS = {"normal", "jam", "overheat", "vibration", "quality-drop", "stopped"}


def sample(tick: int, scenario: str, count: int) -> dict:
    values = dict(ConveyorSpeed=1.2 + 0.015 * math.sin(tick / 5),
                  MotorTemperature=45.0 + 0.8 * math.sin(tick / 11),
                  Vibration=0.12 + 0.006 * math.sin(tick / 3),
                  QualityScore=0.985 + 0.002 * math.sin(tick / 7),
                  BottleCount=count, BlockedSensor=False, LineStatus="RUNNING")
    if scenario == "jam":
        values.update(ConveyorSpeed=0.02, Vibration=0.8, QualityScore=0.65,
                      BlockedSensor=True, LineStatus="BLOCKED")
    elif scenario == "overheat":
        values["MotorTemperature"] = 95.0
    elif scenario == "vibration":
        values["Vibration"] = 1.2
    elif scenario == "quality-drop":
        values["QualityScore"] = 0.65
    elif scenario == "stopped":
        values.update(ConveyorSpeed=0.0, LineStatus="STOPPED")
    return values
