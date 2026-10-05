from datetime import datetime
from rocketpy import Environment

def run_simulation(
    rail_length: float,
    inclination: float,
    heading: float
):
    pass

def build_environment(
    latitude: float,
    longitude: float,
    elevation: float,
    date: datetime | tuple[int, int, int, int] | None = None,
    timezone: str = "UTC",
    gravity: float | None = None,
    datum: str = "SIRGAS2000",
    max_expected_height: float = 80000.0,
) -> Environment:
    pass

def build_rocket(motor):
    pass

def summarize_flight(flight):
    pass
