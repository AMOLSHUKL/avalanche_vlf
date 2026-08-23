"""
Digital Elevation Model (DEM) and Monotonically Sound Rescuer Hazard Calculation.
"""

import math
import numpy as np
from typing import Tuple


class TerrainEngine:
    def __init__(self, width_m: float = 500.0, height_m: float = 500.0, cell_size_m: float = 5.0):
        self.width_m = width_m
        self.height_m = height_m
        self.cell_size_m = cell_size_m
        self.cols = int(round(width_m / cell_size_m))
        self.rows = int(round(height_m / cell_size_m))
        self.elevation_grid, self.slope_grid, self.grad_dx, self.grad_dy = self._generate_dem()

    def _generate_dem(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        # Sample at cell centers: spacing equals cell_size_m exactly, so the
        # finite-difference gradient below carries no spacing bias.
        x = (np.arange(self.cols) + 0.5) * self.cell_size_m
        y = (np.arange(self.rows) + 0.5) * self.cell_size_m
        xx, yy = np.meshgrid(x, y)

        # Himalayan Avalanche Gully Profile
        elevation = 3800.0 + (yy * 0.42) + 25.0 * np.sin(xx / 70.0)
        dy, dx = np.gradient(elevation, self.cell_size_m, self.cell_size_m)
        slope_rad = np.arctan(np.hypot(dx, dy))
        slope_deg = np.degrees(slope_rad)
        return elevation, slope_deg, dx, dy

    def compute_prior_prob(
        self,
        cell_x: int,
        cell_y: int,
        lkp_cell: Tuple[int, int],
        sigma_lkp_m: float = 85.0
    ) -> float:
        """Contextual spatial prior: LKP Gaussian x slope-band likelihood."""
        dist = math.sqrt((cell_x - lkp_cell[0])**2 + (cell_y - lkp_cell[1])**2) * self.cell_size_m
        p_lkp = math.exp(-(dist**2) / (2.0 * (sigma_lkp_m**2)))

        slope = self.slope_grid[cell_y, cell_x]
        if slope < 15.0:
            p_slope = 0.65
        elif 15.0 <= slope <= 32.0:
            p_slope = 0.95
        elif 32.0 < slope <= 45.0:
            p_slope = 0.35
        else:
            p_slope = 0.05

        return max(0.01, min(0.95, p_lkp * p_slope))

    def calculate_rescuer_hazard(self, slope_deg: float) -> float:
        """
        Monotonically Increasing Rescuer Hazard Function:
        - theta < 25 deg: 1.0 (Stable Terrain)
        - 25 <= theta <= 45 deg: Sinusoidal increase to 4.5
        - theta > 45 deg: Continuous linear penalty >= 4.5 (Extreme Cliff/Launch Face)
        """
        if slope_deg < 25.0:
            return 1.0
        elif 25.0 <= slope_deg <= 45.0:
            fraction = (slope_deg - 25.0) / 20.0
            return 1.0 + 3.5 * (math.sin(fraction * (math.pi / 2.0)) ** 2)
        else:
            return 4.5 + 0.15 * (slope_deg - 45.0)