"""Wall-angle geometry for MediaPipe world landmarks.

Coordinate frame (MediaPipe pose_world_landmarks):
    origin = midpoint between the hips, units = meters
    x = to the climber's right in the image, y = down, z = away from the camera

Assumptions (shown to the user in the app as a filming tip):
    - the phone is roughly level and behind the climber, facing the wall,
    - the wall angle is measured from vertical:
      0 = vertical, positive = overhang (e.g. a 40 deg board), negative = slab.

With wall angle t:
    up-the-wall direction  u = (0, -cos t, -sin t)
    out-of-wall normal     n = (0,  sin t, -cos t)   (points from the wall toward the camera)

On an overhang the top of the wall leans toward the camera, so moving up the
wall means moving toward the camera as well as up.
"""

import math
import statistics


def wall_vectors(wall_angle_deg: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    t = math.radians(wall_angle_deg)
    up = (0.0, -math.cos(t), -math.sin(t))
    out = (0.0, math.sin(t), -math.cos(t))
    return up, out


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def hip_to_wall_distance(contact_points: list[tuple[float, float, float]], wall_angle_deg: float) -> float | None:
    """Estimate how far the hips are from the wall, in meters (experimental).

    Hands and feet are usually on holds, so they approximate where the wall
    surface is. The wall plane passes through them with normal `out`; the
    hips are the origin, so their distance from that plane is -(c . out)
    for each contact c. The median ignores the one limb that is moving.

    Requires at least 3 visible contacts. MediaPipe's depth (z) is its
    least accurate axis, so treat the result as a rough trend, not a
    precise measurement.
    """
    if len(contact_points) < 3:
        return None
    _, out = wall_vectors(wall_angle_deg)
    distances = [-_dot(point, out) for point in contact_points]
    return statistics.median(distances)


def up_wall_velocity(screen_up_velocity_mps: float | None, wall_angle_deg: float) -> float | None:
    """Convert screen-up hip speed into speed along the wall surface.

    If the climber moves along the wall, a level camera only sees the
    vertical component (speed x cos t). Beyond 60 deg the conversion
    amplifies noise too much, so it is not reported.
    """
    if screen_up_velocity_mps is None or abs(wall_angle_deg) > 60:
        return None
    return screen_up_velocity_mps / math.cos(math.radians(wall_angle_deg))


def wall_category(wall_angle_deg: float) -> str:
    if wall_angle_deg < -2:
        return "slab"
    if wall_angle_deg <= 5:
        return "vertical"
    if wall_angle_deg < 30:
        return "slight overhang"
    if wall_angle_deg < 50:
        return "steep overhang"
    return "very steep / roof"


def describe_wall(wall_angle_deg: float) -> str:
    category = wall_category(wall_angle_deg)
    if category == "vertical":
        return "a vertical wall (about 0 degrees)"
    if category == "slab":
        return f"a slab, {abs(wall_angle_deg):.0f} degrees less than vertical"
    return f"a {category} wall, {wall_angle_deg:.0f} degrees past vertical"
