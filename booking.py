"""Atomic purchases shared by the customer and booking-agent routes."""


class BookingError(ValueError):
    """A purchase rejected by the business rules, without partial writes."""


def purchase_ticket(connection, flight_id, class_code, customer_email, agent_email=None):
    """Lock the flight and seat class before checking sold inventory.

    All application purchase paths use this transaction. End an earlier
    display-only transaction first, so an old consistent-read snapshot cannot
    hide a purchase committed while waiting for the inventory lock.
    """
    if not class_code or not customer_email:
        raise BookingError("A seat class and customer email are required.")

    connection.rollback()
    connection.begin()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT flight_id, airline_name FROM flight
               WHERE flight_id = %s AND departure_time > NOW()
                 AND status IN ('upcoming', 'delayed') FOR UPDATE""",
            (flight_id,),
        )
        flight = cursor.fetchone()
        if not flight:
            raise BookingError("This flight is not available for purchase.")

        if agent_email is not None:
            cursor.execute(
                "SELECT email FROM agent_works_for WHERE email = %s AND airline_name = %s",
                (agent_email, flight["airline_name"]),
            )
            if not cursor.fetchone():
                raise BookingError("This agent is not assigned to the flight's airline.")

        cursor.execute("SELECT email FROM customer WHERE email = %s", (customer_email,))
        if not cursor.fetchone():
            raise BookingError("Customer email not found.")

        cursor.execute(
            """SELECT capacity, base_price FROM flight_seat_inventory
               WHERE flight_id = %s AND class_code = %s FOR UPDATE""",
            (flight_id, class_code),
        )
        inventory = cursor.fetchone()
        if not inventory:
            raise BookingError("Invalid seat class selection.")
        cursor.execute(
            """SELECT COUNT(*) AS sold FROM ticket t
               JOIN purchases p ON p.ticket_id = t.ticket_id
               WHERE t.flight_id = %s AND t.class_code = %s""",
            (flight_id, class_code),
        )
        if cursor.fetchone()["sold"] >= inventory["capacity"]:
            raise BookingError("No seats remaining in the selected class.")

        cursor.execute(
            "INSERT INTO ticket (flight_id, class_code) VALUES (%s, %s)",
            (flight_id, class_code),
        )
        ticket_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO purchases
               (ticket_id, customer_email, agent_email, purchase_date, sold_price)
               VALUES (%s, %s, %s, NOW(), %s)""",
            (ticket_id, customer_email, agent_email, inventory["base_price"]),
        )
        connection.commit()
        return ticket_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
