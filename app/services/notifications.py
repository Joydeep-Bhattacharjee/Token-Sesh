"""Notification stub: confirmation emails are logged, never sent (spec)."""

import logging

logger = logging.getLogger("cowork.notifications")


def send_booking_confirmation(username: str, reference_code: str) -> None:
    logger.info("Confirmation email to %s for booking %s", username, reference_code)
