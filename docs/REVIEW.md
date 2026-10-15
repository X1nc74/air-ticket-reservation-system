# Review and validation

## Changes from the supplied project

| Finding | Implemented change |
| --- | --- |
| A public registration request could create an airline operator | Reject staff registration before accessing the database; remove the public staff form option |
| Missing permission records defaulted to operator authority | Default to no permission; prefer an explicitly assigned administrator permission when multiple rows exist |
| Both purchase routes checked inventory without serializing writers | Share a transaction that acquires InnoDB locks before checking sold inventory and writing both records |
| Purchase checks could rely on an earlier consistent-read snapshot | End the display transaction and start a fresh booking transaction before acquiring locks |
| A flight could be purchased after cancellation or departure | Check current departure time and status within the locked transaction |
| New flights had no seat inventory | Create economy inventory with the airplane capacity in the flight-creation transaction |
| Source code embedded development configuration | Read session secret and database settings from environment variables; disable debug by default |
| POST forms and logout lacked request protection | Add session CSRF tokens to POST forms and change logout to POST |
| The SQL dump lived under the public static path | Move schema into `database/`; replace original account rows with generated fictional fixtures |
| A second schema file was incomplete | Derive the complete 13-table schema and indexes from the full supplied dump |
| Database exception details were shown in forms | Use generic database failure messages; log unexpected purchase failures on the server |

## Verification

The local review uses the pure-Python Flask, Werkzeug, and PyMySQL packages supplied in the uploaded virtual environment, materialized outside this repository. The original macOS interpreter, binary extension, pip files, and virtual environment are not committed. The direct dependency versions are Flask 3.1.2, PyMySQL 1.1.2, and Werkzeug 3.1.4.

Local checks cover Python parsing, all 24 template compilations, 14 offline tests, public form rendering, role guards, CSRF enforcement, no public SQL dump, successful transaction sequencing, rejection paths, and failed-write rollback calls.

The repository also defines seven integration tests against a disposable MySQL 8.4 service. Those tests use actual SQL queries and independent connections for concurrent seat purchases. The live status and logs are available from [GitHub Actions](https://github.com/X1nc74/air-ticket-reservation-system/actions/workflows/checks.yml). A mocked transaction test alone does not establish real database concurrency correctness.

No MySQL server is available in the local review workspace. Real database checks are therefore delegated to the repository's isolated CI service after the local checks pass. Browser appearance, load/performance, production deployment, and behavior under broader external database writers are not established by this suite.

## Retained limitations

The application keeps the original Flask route structure and simple HTML pages. Demo initialization is intended for an empty disposable database, not as a migration of an existing deployment. Seat locking serializes purchases for each flight; a more scalable design could use narrower locks after reviewing interactions with flight-status changes. Stored staff permissions in sessions are refreshed at login rather than on every request.
