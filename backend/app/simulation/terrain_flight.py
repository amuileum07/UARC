"""Version-bound RocketPy event adapter; never changes the launch elevation.

RocketPy 1.13 has no public ground-event hook. Keep this small subclass isolated
and fail closed on other versions; re-audit the event/phase contract on upgrades.
No methods on RocketPy classes are monkey-patched.
"""

from importlib.metadata import version
from typing import override

import numpy as np
from rocketpy import Flight
from scipy.optimize import brentq

from app.terrain import GroundSurface


class TerrainFlight(Flight):
    def __init__(self, *, ground: GroundSurface, **kwargs):
        if version("rocketpy") != "1.13.0":
            raise RuntimeError("Terrain events are verified only with RocketPy 1.13.0.")
        self.ground = ground
        if ground.at(0, 0) > kwargs["environment"].elevation + 1e-6:
            raise ValueError("Launch point is below the terrain surface.")
        super().__init__(**kwargs)

    @override
    def _Flight__check_simulation_events(self, phase, phase_index, node_index):
        """Detect first ground crossing before processing later flight events."""
        interpolator = phase.solver.dense_output()
        start, end = phase.solver.t_old, self.t
        # A bounded 0.05 s solver step plus subdivisions guards narrow crossings.
        # Sub-grid ridges cannot be resolved; use a finer DEM for those features.
        previous_time, previous_gap = start, self._gap(interpolator(start))
        for time in np.linspace(start, end, 9)[1:]:
            gap = self._gap(interpolator(time))
            if previous_gap >= 0 and gap < 0:
                root = brentq(
                    lambda t: self._gap(interpolator(t)), previous_time, time, xtol=1e-9
                )
                self.t = self.t_final = root
                self.y_sol = self.impact_state = interpolator(root)
                while self.solution and self.solution[-1][0] >= root:
                    self.solution.pop()
                self.solution.append([root, *self.y_sol])
                self.x_impact, self.y_impact, self.z_impact = self.y_sol[:3]
                self.impact_velocity = self.y_sol[5]
                self.flight_phases.flush_after(phase_index)
                self.flight_phases.add_phase(root)
                phase.time_nodes.flush_after(node_index)
                phase.time_nodes.add_node(root, [], [], [])
                phase.solver.status = "finished"
                return True
            previous_time, previous_gap = time, gap

        # Preserve 1.13.0 rail and apogee handling, omitting its flat impact test.
        if len(self.out_of_rail_state) == 1 and (
            self.y_sol[0] ** 2
            + self.y_sol[1] ** 2
            + (self.y_sol[2] - self.env.elevation) ** 2
            >= self.effective_1rl**2
        ):
            return self._Flight__handle_out_of_rail_event(
                phase, phase_index, node_index
            )
        if len(self.apogee_state) == 1 and self.y_sol[5] < 0:
            return self._Flight__handle_apogee_event(phase, phase_index, node_index)
        return False

    def _gap(self, state):
        return state[2] - self.ground.at(float(state[0]), float(state[1]))
