"""Pure-numpy Kalman filter for person bounding-box tracking.

State vector (7-dim):
	[cx, cy, log_h, aspect, vx, vy, v_log_h]

Measurement vector (4-dim):
	[cx, cy, log_h, aspect]
"""

# Standard Library
import math

# PIP3 modules
import numpy

STATE_DIM = 7
MEASUREMENT_DIM = 4


#============================================
def create_kalman(bbox: tuple) -> dict:
	"""Initialize a Kalman filter state from a bounding box.

	Args:
		bbox: Tuple of (cx, cy, w, h) in pixel coordinates.

	Returns:
		Dict with keys "x", "P", "F", "H", "Q", "R" as numpy arrays.
	"""
	cx, cy, w, h = bbox

	# Initial state: position, log height, aspect ratio, zero velocities
	x = numpy.array([
		cx, cy, math.log(h), w / h,
		0.0, 0.0, 0.0,
	], dtype=numpy.float64)

	# Initial covariance: high uncertainty on velocities
	p_diag = numpy.array([
		10.0, 10.0,    # cx, cy position variance
		0.01,          # log_h scale variance
		0.01,          # aspect ratio variance
		100.0, 100.0,  # vx, vy velocity variance
		100.0,         # v_log_h velocity variance
	], dtype=numpy.float64)
	P = numpy.diag(p_diag)

	# Transition matrix: constant-velocity model
	F = numpy.eye(STATE_DIM, dtype=numpy.float64)
	# velocity coupling: position += velocity per step
	F[0, 4] = 1.0  # cx += vx
	F[1, 5] = 1.0  # cy += vy
	F[2, 6] = 1.0  # log_h += v_log_h

	# Measurement matrix: observe position and shape, not velocity
	H = numpy.zeros((MEASUREMENT_DIM, STATE_DIM), dtype=numpy.float64)
	H[0, 0] = 1.0  # cx
	H[1, 1] = 1.0  # cy
	H[2, 2] = 1.0  # log_h
	H[3, 3] = 1.0  # aspect

	# Process noise
	q_diag = numpy.array([
		1.0, 1.0,    # position
		0.01,        # log_h
		0.01,        # aspect
		0.1, 0.1,   # velocity
		0.1,         # v_log_h
	], dtype=numpy.float64)
	Q = numpy.diag(q_diag)

	# Measurement noise
	r_diag = numpy.array([
		4.0, 4.0,    # position
		0.04,        # log_h
		0.04,        # aspect
	], dtype=numpy.float64)
	R = numpy.diag(r_diag)

	state = {
		"x": x,
		"P": P,
		"F": F,
		"H": H,
		"Q": Q,
		"R": R,
	}
	return state


#============================================
def predict(state: dict) -> dict:
	"""Run the Kalman predict step.

	Args:
		state: Current Kalman state dict.

	Returns:
		New state dict with predicted x and P (input is not mutated).
	"""
	F = state["F"]
	x = state["x"]
	P = state["P"]
	Q = state["Q"]

	# Predicted state and covariance
	x_pred = F @ x
	P_pred = F @ P @ F.T + Q

	new_state = {
		"x": x_pred,
		"P": P_pred,
		"F": state["F"],
		"H": state["H"],
		"Q": state["Q"],
		"R": state["R"],
	}
	return new_state


#============================================
def update(state: dict, measurement: tuple) -> dict:
	"""Run the Kalman update step with a new measurement.

	Args:
		state: Current Kalman state dict (typically after predict).
		measurement: Tuple of (cx, cy, log_h, aspect).

	Returns:
		New state dict with updated x and P (input is not mutated).
	"""
	x = state["x"]
	P = state["P"]
	H = state["H"]
	R = state["R"]

	# Measurement vector
	z = numpy.array(measurement, dtype=numpy.float64)

	# Innovation (residual)
	y = z - H @ x

	# Innovation covariance
	S = H @ P @ H.T + R

	# Kalman gain
	K = P @ H.T @ numpy.linalg.inv(S)

	# Updated state and covariance
	x_new = x + K @ y
	I = numpy.eye(STATE_DIM, dtype=numpy.float64)
	P_new = (I - K @ H) @ P

	new_state = {
		"x": x_new,
		"P": P_new,
		"F": state["F"],
		"H": state["H"],
		"Q": state["Q"],
		"R": state["R"],
	}
	return new_state


#============================================
def get_bbox(state: dict) -> tuple:
	"""Extract a bounding box from the Kalman state.

	Args:
		state: Current Kalman state dict.

	Returns:
		Tuple of (cx, cy, w, h) in pixel coordinates.
	"""
	x = state["x"]
	cx = float(x[0])
	cy = float(x[1])
	# Undo log transform to recover height
	h = math.exp(float(x[2]))
	aspect = float(x[3])
	w = aspect * h
	result = (cx, cy, w, h)
	return result


#============================================
def get_velocity(state: dict) -> tuple:
	"""Extract velocity components from the Kalman state.

	Args:
		state: Current Kalman state dict.

	Returns:
		Tuple of (vx, vy) in pixels per frame.
	"""
	x = state["x"]
	result = (float(x[4]), float(x[5]))
	return result


#============================================
def get_innovation_distance(state: dict, measurement: tuple) -> float:
	"""Compute Mahalanobis-like distance for gating decisions.

	Args:
		state: Current Kalman state dict.
		measurement: Tuple of (cx, cy, log_h, aspect).

	Returns:
		Float distance value.
	"""
	x = state["x"]
	P = state["P"]
	H = state["H"]
	R = state["R"]

	# Measurement vector
	z = numpy.array(measurement, dtype=numpy.float64)

	# Innovation
	y = z - H @ x

	# Innovation covariance
	S = H @ P @ H.T + R

	# Mahalanobis distance
	S_inv = numpy.linalg.inv(S)
	dist_sq = float(y.T @ S_inv @ y)
	distance = math.sqrt(dist_sq)
	return distance


#============================================
def measurement_from_bbox(bbox: tuple) -> tuple:
	"""Convert a bounding box to Kalman measurement format.

	Args:
		bbox: Tuple of (cx, cy, w, h) in pixel coordinates.

	Returns:
		Tuple of (cx, cy, log_h, aspect) for the update step.
	"""
	cx, cy, w, h = bbox
	result = (cx, cy, math.log(h), w / h)
	return result
