"""Domain-specific exceptions for booking, auth, cart, and configuration."""


class GolfBookingError(Exception):
    """Base exception for golf booking errors."""


class AuthenticationError(GolfBookingError):
    """Authentication-related failures."""


class TeeTimeError(GolfBookingError):
    """Tee time API or selection failures."""


class CartError(GolfBookingError):
    """Shopping cart session failures."""


class ReservationError(GolfBookingError):
    """Final reservation UI step failures."""


class ConfigError(Exception):
    """Invalid or missing configuration."""
