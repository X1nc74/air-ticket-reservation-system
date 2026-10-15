# Air Ticket Reservation System

[![Application and MySQL checks](https://github.com/X1nc74/air-ticket-reservation-system/actions/workflows/checks.yml/badge.svg)](https://github.com/X1nc74/air-ticket-reservation-system/actions/workflows/checks.yml)

A Flask and MySQL application for flight search, seat-class booking, and airline sales reporting. The project models public visitors, customers, booking agents, and airline staff with separate workflows and permissions.

The original database coursework contains **25 routes, 24 Jinja templates, and 13 relational tables**. This portfolio version adds shared transactional booking, form protection, environment-based configuration, fictional demo data, and automated regression and MySQL integration checks.

## Main workflows

| Role | Functionality |
| --- | --- |
| Public visitor | Search flights and look up flight status; register a customer or booking-agent account |
| Customer | Purchase an available seat class, view flights, and explore spending totals and monthly reports |
| Booking agent | Sell tickets for assigned airlines, view commissions, and identify top customers |
| Airline operator | View airline data and update flight status |
| Airline administrator | Create airports, airplanes and flights, assign agents, and inspect passengers and sales analytics |

Ticket purchases create database records under the configured seat inventory and price. There is no payment-provider integration.

## Booking correctness

Both customer and agent purchases use [`booking.py`](booking.py). The transaction ends the earlier display-query snapshot, locks the current flight and seat-inventory row, checks eligibility and sold seats again, inserts the ticket and purchase together, and commits. Failed writes roll back the complete purchase.

The concurrent last-seat integration test uses two independent MySQL connections and expects exactly one successful purchase. All application purchase writers must follow this locking protocol; direct external database writes can bypass it.

Creating a new flight now creates an economy inventory row in the same transaction, using the selected airplane's capacity. The original code created the flight without purchasable inventory.

## Local setup

Use Python 3.12 and MySQL 8.4, the versions targeted by CI. Create an **empty** database and an application account using your local MySQL administrator:

```sql
CREATE DATABASE airline_system CHARACTER SET utf8mb4;
CREATE USER 'airline_app'@'localhost' IDENTIFIED BY 'choose_your_local_password';
GRANT ALL PRIVILEGES ON airline_system.* TO 'airline_app'@'localhost';
```

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your database password and a random `SECRET_KEY`. Generate the latter with `python -c "import secrets; print(secrets.token_hex(32))"`. Then load the settings into your shell and initialize the database:

```bash
set -a
source .env
set +a
python scripts/init_demo.py
python app.py
```

Open `http://127.0.0.1:5000/`. The initializer refuses to overwrite a nonempty database. Schema DDL is not transactional in MySQL; if initialization is interrupted, start with another empty demo database. No SQL dump is served from the app's static directory.

### Fictional demo accounts

All accounts below use the local demonstration password `DemoFlights2026!`. Set `DEMO_PASSWORD` before initialization to use another value. Password hashes are generated when the demo database is created.

| Role | Login identifier |
| --- | --- |
| Customer | `customer@example.invalid` |
| Second customer | `second@example.invalid` |
| Booking agent | `agent@example.invalid` |
| Administrator | `demo_admin` |
| Operator | `demo_operator` |

Demo flights are dated relative to initialization: two future flights and one completed historical flight. The dataset uses fictional accounts and does not redistribute the uploaded account rows or password hashes. Public staff registration is disabled; staff identities and permissions are provisioned through database administration or the demo initializer.

## Tests

```bash
# No database required: authorization boundaries, CSRF, templates, transactions.
python -m unittest discover -s tests -p test_application.py -v

# Uses and mutates an initialized disposable demo database.
RUN_DB_TESTS=1 python -m unittest discover -s tests -p test_database.py -v
```

There are **14 offline tests and 7 MySQL integration tests**. The latter cover role-specific SQL pages, both purchase routes, concurrent last-seat requests, a real failed-write rollback, purchase eligibility, and newly created flight inventory. The GitHub Actions workflow provisions a separate MySQL service, installs dependencies, initializes the demo, and runs both suites.

## Project structure

| Path | Purpose |
| --- | --- |
| [`app.py`](app.py) | Existing Flask routes, sessions, reports, and administrative workflows |
| [`booking.py`](booking.py) | Shared booking transaction and inventory validation |
| [`templates/`](templates) | Role-specific Jinja pages and token-protected forms |
| [`database/schema.sql`](database/schema.sql) | Complete schema, indexes, foreign keys, and basic value constraints |
| [`scripts/init_demo.py`](scripts/init_demo.py) | Empty-database setup with generated demo account hashes |
| [`tests/`](tests) | Offline regression and real MySQL integration tests |
| [`docs/REVIEW.md`](docs/REVIEW.md) | Changes and verification boundaries |
| [`docs/provenance.json`](docs/provenance.json) | Original ZIP and core-file checksums |

## Scope and provenance

This is a database course project curated for a software portfolio. It retains the original server-rendered interface and route organization. Sessions use HTTP-only, SameSite cookies; POST forms require CSRF tokens; logout uses POST; debug mode is off by default. Set a stable environment secret for a multi-process deployment and enable secure cookies when serving over HTTPS.

The development server, payment handling, deployment infrastructure, account recovery, rate limiting, and database migrations have not been developed into a production service. The existing query-heavy `app.py` remains a candidate for later separation into blueprints and service modules.

Portfolio curation used AI assistance for code review, targeted fixes, tests, and documentation. The uploaded virtual environment, raw database account data, and obsolete setup notes are omitted. Original input checksums are retained for provenance.
