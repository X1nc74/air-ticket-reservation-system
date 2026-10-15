from flask import Flask, render_template, request, redirect, url_for, session, abort
import pymysql
import os
import secrets
import hmac
import math
from booking import BookingError, purchase_ticket
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


# ---------- 数据库连接 ----------
def get_db_connection():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "airline_app"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "airline_system"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


@app.context_processor
def csrf_context():
    def csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return session["_csrf_token"]
    return {"csrf_token": csrf_token}


@app.before_request
def protect_form_posts():
    if request.method == "POST":
        expected = session.get("_csrf_token")
        supplied = request.form.get("csrf_token", "")
        if not expected or not supplied.isascii() or not hmac.compare_digest(expected, supplied):
            abort(400, description="Invalid form token. Refresh the form and try again.")


app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1")


# ---------- 首页 ----------
@app.route("/")
def index():
    return render_template("index.html")


# ---------- 登录 ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    identifier = request.form["identifier"].strip()   # email 或 username
    password = request.form["password"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 尝试当作 customer email 登录
    cursor.execute(
    """
    SELECT email, name, password_hash
    FROM customer
    WHERE email = %s OR name = %s
    """,
    (identifier, identifier)
    )
    customer = cursor.fetchone()
    if customer and check_password_hash(customer["password_hash"], password):
        session.clear()
        session["role"] = "customer"
        session["email"] = customer["email"]
        session["name"] = customer["name"]
        cursor.close()
        conn.close()
        return redirect(url_for("customer_home"))

    # 2. 尝试当作 booking_agent email 登录
    cursor.execute(
        "SELECT email, password_hash, agent_id FROM booking_agent WHERE email = %s",
        (identifier,)
    )
    agent = cursor.fetchone()
    if agent and check_password_hash(agent["password_hash"], password):
        session.clear()
        session["role"] = "agent"
        session["email"] = agent["email"]
        session["agent_id"] = agent["agent_id"]
        cursor.close()
        conn.close()
        return redirect(url_for("agent_home"))

    # 3. 尝试当作 airline_staff username 登录
    cursor.execute(
        "SELECT username, password_hash, airline_name FROM airline_staff WHERE username = %s",
        (identifier,)
    )
    staff = cursor.fetchone()
    if staff and check_password_hash(staff["password_hash"], password):
        # 查权限 admin / operator
        cursor.execute(
            "SELECT permission_type FROM staff_permission WHERE username = %s ORDER BY permission_type = 'admin' DESC LIMIT 1",
            (staff["username"],)
        )
        perm_row = cursor.fetchone()
        permission_type = perm_row["permission_type"] if perm_row else None

        session.clear()
        session["role"] = "staff"
        session["username"] = staff["username"]
        session["airline_name"] = staff["airline_name"]
        session["permission_type"] = permission_type

        cursor.close()
        conn.close()
        return redirect(url_for("staff_home"))

    # 三种都没匹配上 → 登录失败
    cursor.close()
    conn.close()
    error = "Invalid email/username or password"
    return render_template("login.html", error=error)

@app.route("/search", methods=["GET", "POST"])
def public_search():
    if request.method == "GET":
        return render_template("public_search.html", error=None)

    from_place = request.form["from_place"].strip()
    to_place = request.form["to_place"].strip()
    departure_date = request.form["departure_date"].strip()

    if not from_place or not to_place or not departure_date:
        return render_template(
            "public_search.html",
            error="All fields are required."
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # allow search by city OR airport_code
        cursor.execute(
            """
            SELECT
                f.airline_name,
                f.flight_num,
                f.departure_airport,
                da.city AS dep_city,
                f.departure_time,
                f.arrival_airport,
                aa.city AS arr_city,
                f.arrival_time,
                f.base_price,
                f.status
            FROM flight f
            JOIN airport da ON f.departure_airport = da.airport_code
            JOIN airport aa ON f.arrival_airport = aa.airport_code
            WHERE DATE(f.departure_time) = %s
              AND (
                    da.city = %s
                 OR da.airport_code = %s
                  )
              AND (
                    aa.city = %s
                 OR aa.airport_code = %s
                  )
              AND f.status IN ('upcoming','in-progress','delayed')
            ORDER BY f.departure_time
            """,
            (
                departure_date,
                from_place, from_place.upper(),
                to_place, to_place.upper()
            )
        )
        flights = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "public_search.html",
        error=None,
        flights=flights
    )

@app.route("/status", methods=["GET", "POST"])
def public_status():
    if request.method == "GET":
        return render_template("public_status.html", error=None)

    airline_name = request.form["airline_name"].strip()
    flight_num = request.form["flight_num"].strip()

    if not airline_name or not flight_num:
        return render_template(
            "public_status.html",
            error="Both airline name and flight number are required."
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                flight_id,
                airline_name,
                flight_num,
                departure_airport,
                departure_time,
                arrival_airport,
                arrival_time,
                status
            FROM flight
            WHERE airline_name = %s
              AND flight_num = %s
              AND status = 'in-progress'
            ORDER BY departure_time DESC
            """,
            (airline_name, flight_num)
        )
        flights = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "public_status.html",
        error=None,
        flights=flights
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", error=None)

    user_type = request.form.get("user_type", "")  # 'customer' / 'agent' / 'staff'
    if user_type == "staff":
        return render_template("register.html", error="Staff accounts are provisioned by an administrator."), 403
    email = request.form.get("email", "").strip()
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    airline_name = request.form.get("airline_name", "").strip()
    password = request.form.get("password", "")

    # ---------- 后端必填校验 ----------
    if not password:
        return render_template("register.html", error="Password is required.")

    if user_type == "customer":
        if not email or not name:
            return render_template(
                "register.html",
                error="Customer must provide both email and name."
            )
    elif user_type == "agent":
        if not email:
            return render_template(
                "register.html",
                error="Booking agent must provide an email address."
            )
    elif user_type == "staff":
        if not username or not airline_name:
            return render_template(
                "register.html",
                error="Airline staff must provide username and airline name."
            )
    else:
        return render_template("register.html", error="Unknown user type.")

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ---------- Customer 注册 ----------
        if user_type == "customer":
            cursor.execute(
                """
                INSERT INTO customer (email, name, password_hash)
                VALUES (%s, %s, %s)
                """,
                (email, name, password_hash)
            )

        # ---------- Booking Agent 注册 ----------
        elif user_type == "agent":
            cursor.execute(
                """
                INSERT INTO booking_agent (email, password_hash)
                VALUES (%s, %s)
                """,
                (email, password_hash)
            )


        conn.commit()

    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        # 这里可以统一返回一个比较友好的错误提示
        return render_template(
            "register.html",
            error="Registration failed. Please check your input or try a different email/username."
        )

    cursor.close()
    conn.close()
    return redirect(url_for("login"))


# ---------- Customer 首页 ----------
@app.route("/customer/home")
def customer_home():
    if session.get("role") != "customer":
        return redirect(url_for("login"))
    return render_template("customer_home.html", name=session.get("name"))

@app.route("/customer/search_flights", methods=["GET", "POST"])
def customer_search_flights():
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("customer_search_flights.html", error=None)

    # POST: handle search
    dep = request.form["departure_airport"].strip().upper()
    arr = request.form["arrival_airport"].strip().upper()
    date_raw = request.form["departure_date"].strip()

    if len(dep) != 3 or len(arr) != 3:
        return render_template(
            "customer_search_flights.html",
            error="Airport codes must be 3 letters.",
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Match flights by exact departure date
        cursor.execute(
            """
            SELECT flight_id, airline_name, flight_num,
                   departure_airport, departure_time,
                   arrival_airport, arrival_time,
                   base_price, status
            FROM flight
            WHERE departure_airport = %s
              AND arrival_airport = %s
              AND DATE(departure_time) = %s
              AND status IN ('upcoming', 'in-progress')
            ORDER BY departure_time
            """,
            (dep, arr, date_raw)
        )
        flights = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "customer_search_flights.html",
        error=None,
        flights=flights
    )
@app.route("/customer/purchase/<int:flight_id>", methods=["GET", "POST"])
def customer_purchase(flight_id):
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) 先查 flight 信息
    cursor.execute(
        """
        SELECT flight_id, airline_name, flight_num,
               departure_airport, departure_time,
               arrival_airport, arrival_time,
               base_price, status
        FROM flight
        WHERE flight_id = %s
        """,
        (flight_id,)
    )
    flight = cursor.fetchone()

    if not flight:
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html",
            flight=None,
            seat_options=None,
            error="Flight not found.",
            message=None
        )

    # 2) 查这个航班各舱位的容量 + 已售
    cursor.execute(
        """
        SELECT
            fsi.class_code,
            fsi.capacity,
            fsi.base_price,
            COALESCE(SUM(CASE WHEN p.ticket_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS sold
        FROM flight_seat_inventory fsi
        LEFT JOIN ticket t
            ON t.flight_id = fsi.flight_id
           AND t.class_code = fsi.class_code
        LEFT JOIN purchases p
            ON p.ticket_id = t.ticket_id
        WHERE fsi.flight_id = %s
        GROUP BY fsi.class_code, fsi.capacity, fsi.base_price
        ORDER BY fsi.class_code
        """,
        (flight_id,)
    )
    rows = cursor.fetchall()

    seat_options = []
    for r in rows:
        remaining = r["capacity"] - r["sold"]
        seat_options.append({
            "class_code": r["class_code"],
            "capacity": r["capacity"],
            "sold": r["sold"],
            "remaining": remaining,
            "base_price": r["base_price"],
        })

    # ---------- GET: 展示页面 ----------
    if request.method == "GET":
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error=None,
            message=None
        )

    # ---------- POST: 确认购票 ----------
    class_code = request.form.get("class_code")

    # 找出选中的舱位
    selected = None
    for s in seat_options:
        if s["class_code"] == class_code:
            selected = s
            break

    if selected is None:
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error="Invalid seat class selection.",
            message=None
        )

    # ------- Ticket-limit check -------
    if selected["remaining"] <= 0:
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error=f"No seats remaining in class {class_code}. Ticket cannot be purchased.",
            message=None
        )
    # ----------------------------------

    customer_email = session.get("email")
    sold_price = selected["base_price"]

    try:
        purchase_ticket(conn, flight_id, class_code, customer_email)
    except BookingError as e:
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html", flight=flight, seat_options=seat_options,
            error=str(e), message=None
        ), 409
    except Exception:
        app.logger.exception("Ticket purchase failed")
        conn.rollback()
        cursor.close()
        conn.close()
        return render_template(
            "customer_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error="Purchase failed. Please try again.",
            message=None
        )

    cursor.close()
    conn.close()

    return render_template(
        "customer_purchase.html",
        flight=flight,
        seat_options=seat_options,
        error=None,
        message=f"Ticket purchased successfully in class {class_code}."
    )

@app.route("/customer/my_flights")
def customer_my_flights():
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    customer_email = session.get("email")

    # 读取筛选参数（来自 ?start_date=... 这种）
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    dep_airport = request.args.get("departure_airport", "").strip().upper()
    arr_airport = request.args.get("arrival_airport", "").strip().upper()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ---------- Upcoming flights 查询 ----------
        base_sql_upcoming = """
            SELECT
                f.airline_name,
                f.flight_num,
                t.class_code,
                f.departure_airport,
                f.departure_time,
                f.arrival_airport,
                f.arrival_time,
                f.status,
                p.sold_price,
                p.purchase_date
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE p.customer_email = %s
              AND f.departure_time >= NOW()
              AND f.status IN ('upcoming', 'in-progress', 'delayed')
        """
        params_upcoming = [customer_email]

        # 按筛选条件动态加 WHERE
        if start_date:
            base_sql_upcoming += " AND DATE(f.departure_time) >= %s"
            params_upcoming.append(start_date)
        if end_date:
            base_sql_upcoming += " AND DATE(f.departure_time) <= %s"
            params_upcoming.append(end_date)
        if dep_airport:
            base_sql_upcoming += " AND f.departure_airport = %s"
            params_upcoming.append(dep_airport)
        if arr_airport:
            base_sql_upcoming += " AND f.arrival_airport = %s"
            params_upcoming.append(arr_airport)

        base_sql_upcoming += " ORDER BY f.departure_time ASC"

        cursor.execute(base_sql_upcoming, params_upcoming)
        upcoming_flights = cursor.fetchall()

        # ---------- Past flights 查询 ----------
        base_sql_past = """
            SELECT
                f.airline_name,
                f.flight_num,
                t.class_code,
                f.departure_airport,
                f.departure_time,
                f.arrival_airport,
                f.arrival_time,
                f.status,
                p.sold_price,
                p.purchase_date
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE p.customer_email = %s
              AND (
                    f.departure_time < NOW()
                    OR f.status IN ('completed', 'cancelled')
                  )
        """
        params_past = [customer_email]

        if start_date:
            base_sql_past += " AND DATE(f.departure_time) >= %s"
            params_past.append(start_date)
        if end_date:
            base_sql_past += " AND DATE(f.departure_time) <= %s"
            params_past.append(end_date)
        if dep_airport:
            base_sql_past += " AND f.departure_airport = %s"
            params_past.append(dep_airport)
        if arr_airport:
            base_sql_past += " AND f.arrival_airport = %s"
            params_past.append(arr_airport)

        base_sql_past += " ORDER BY f.departure_time DESC"

        cursor.execute(base_sql_past, params_past)
        past_flights = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    # 把当前筛选条件一并传给模板，用来回显
    return render_template(
        "customer_my_flights.html",
        email=customer_email,
        upcoming_flights=upcoming_flights,
        past_flights=past_flights,
        start_date=start_date,
        end_date=end_date,
        departure_airport=dep_airport,
        arrival_airport=arr_airport,
    )


@app.route("/customer/spending")
def customer_spending():
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    customer_email = session.get("email")

    # 从 URL 里拿自定义时间范围参数（GET）
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1) Summary：总消费 / 最近12个月 / 最近30天
        cursor.execute(
            """
            SELECT COALESCE(SUM(sold_price), 0) AS total_all
            FROM purchases
            WHERE customer_email = %s
            """,
            (customer_email,)
        )
        row = cursor.fetchone()
        total_all = row["total_all"] if row else 0

        cursor.execute(
            """
            SELECT COALESCE(SUM(sold_price), 0) AS total_1year
            FROM purchases
            WHERE customer_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            """,
            (customer_email,)
        )
        row = cursor.fetchone()
        total_1year = row["total_1year"] if row else 0

        cursor.execute(
            """
            SELECT COALESCE(SUM(sold_price), 0) AS total_30days
            FROM purchases
            WHERE customer_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            """,
            (customer_email,)
        )
        row = cursor.fetchone()
        total_30days = row["total_30days"] if row else 0

        # 2) 默认视图：最近 6 个月的月度消费柱状图
        cursor.execute(
            """
            SELECT
                DATE_FORMAT(purchase_date, '%%Y-%%m') AS ym,
                SUM(sold_price) AS total_month
            FROM purchases
            WHERE customer_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY ym
            ORDER BY ym
            """,
            (customer_email,)
        )
        month_rows = cursor.fetchall()

        months_default = []
        max_total = 0
        for r in month_rows:
            if r["total_month"] > max_total:
                max_total = r["total_month"]

        for r in month_rows:
            if max_total > 0:
                width = int(r["total_month"] / max_total * 300)
            else:
                width = 0
            months_default.append({
                "month": r["ym"],
                "total": r["total_month"],
                "bar_width": width,
            })

        # 3) 自定义视图：start_date ~ end_date 的总消费 + 月度柱状图
        custom_total = None          # 没有选日期时就保持 None
        custom_months = []
        custom_error = None

        if start_date or end_date:
            # 只填了一个日期 → 提示错误
            if not (start_date and end_date):
                custom_error = "Please provide both start and end dates for the custom view."
            else:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    custom_error = "Invalid date format."
                else:
                    if end_dt < start_dt:
                        custom_error = "End date must be on or after start date."
                    else:
                        # 自定义范围总消费
                        cursor.execute(
                            """
                            SELECT COALESCE(SUM(sold_price), 0) AS total_custom
                            FROM purchases
                            WHERE customer_email = %s
                              AND DATE(purchase_date) BETWEEN %s AND %s
                            """,
                            (customer_email, start_date, end_date)
                        )
                        row = cursor.fetchone()
                        custom_total = row["total_custom"] if row else 0

                        # 自定义范围月度柱状图
                        cursor.execute(
                            """
                            SELECT
                                DATE_FORMAT(purchase_date, '%%Y-%%m') AS ym,
                                SUM(sold_price) AS total_month
                            FROM purchases
                            WHERE customer_email = %s
                              AND DATE(purchase_date) BETWEEN %s AND %s
                            GROUP BY ym
                            ORDER BY ym
                            """,
                            (customer_email, start_date, end_date)
                        )
                        rows = cursor.fetchall()

                        max_total_custom = 0
                        for r in rows:
                            if r["total_month"] > max_total_custom:
                                max_total_custom = r["total_month"]

                        for r in rows:
                            width = int(r["total_month"] / max_total_custom * 300) if max_total_custom > 0 else 0
                            custom_months.append({
                                "month": r["ym"],
                                "total": r["total_month"],
                                "bar_width": width
                            })

        # 4) 所有购买明细（用于下面的表）
        cursor.execute(
            """
            SELECT
                p.purchase_date,
                p.sold_price,
                p.agent_email,
                f.airline_name,
                f.flight_num,
                t.class_code
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE p.customer_email = %s
            ORDER BY p.purchase_date DESC
            """,
            (customer_email,)
        )
        purchases = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "customer_spending.html",
        email=customer_email,
        total_all=total_all,
        total_1year=total_1year,
        total_30days=total_30days,
        months=months_default,
        purchases=purchases,
        start_date=start_date,
        end_date=end_date,
        custom_total=custom_total,
        custom_months=custom_months,
        custom_error=custom_error,
    )


# ---------- Agent 首页 ----------
@app.route("/agent/home")
def agent_home():
    if session.get("role") != "agent":
        return redirect(url_for("login"))
    return render_template("agent_home.html", email=session.get("email"),
                           agent_id=session.get("agent_id"))

@app.route("/agent/search_flights", methods=["GET", "POST"])
def agent_search_flights():
    if session.get("role") != "agent":
        return redirect(url_for("login"))

    agent_email = session.get("email")

    if request.method == "GET":
        return render_template("agent_search_flights.html", error=None)

    dep = request.form["departure_airport"].strip().upper()
    arr = request.form["arrival_airport"].strip().upper()
    date_raw = request.form["departure_date"].strip()

    if len(dep) != 3 or len(arr) != 3:
        return render_template(
            "agent_search_flights.html",
            error="Airport codes must be 3 letters.",
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 只允许搜索 agent_works_for 里该 agent 所属航空公司的航班
        cursor.execute(
            """
            SELECT
                f.flight_id,
                f.airline_name,
                f.flight_num,
                f.departure_airport,
                f.departure_time,
                f.arrival_airport,
                f.arrival_time,
                f.base_price,
                f.status
            FROM flight f
            JOIN agent_works_for aw
              ON aw.airline_name = f.airline_name
            WHERE aw.email = %s
              AND f.departure_airport = %s
              AND f.arrival_airport = %s
              AND DATE(f.departure_time) = %s
              AND f.status IN ('upcoming', 'in-progress')
            ORDER BY f.departure_time
            """,
            (agent_email, dep, arr, date_raw)
        )
        flights = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "agent_search_flights.html",
        error=None,
        flights=flights
    )

@app.route("/agent/purchase/<int:flight_id>", methods=["GET", "POST"])
def agent_purchase(flight_id):
    if session.get("role") != "agent":
        return redirect(url_for("login"))

    agent_email = session.get("email")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) 先确认这个航班属于 agent_works_for 里的航空公司
    cursor.execute(
        """
        SELECT
            f.flight_id,
            f.airline_name,
            f.flight_num,
            f.departure_airport,
            f.departure_time,
            f.arrival_airport,
            f.arrival_time,
            f.base_price,
            f.status
        FROM flight f
        JOIN agent_works_for aw
          ON aw.airline_name = f.airline_name
        WHERE f.flight_id = %s
          AND aw.email = %s
        """,
        (flight_id, agent_email)
    )
    flight = cursor.fetchone()

    if not flight:
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=None,
            seat_options=None,
            error="You are not authorized to purchase tickets for this flight (different airline).",
            message=None
        )

    # 2) Seat inventory + sold count
    cursor.execute(
        """
        SELECT
            fsi.class_code,
            fsi.capacity,
            fsi.base_price,
            COALESCE(SUM(CASE WHEN p.ticket_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS sold
        FROM flight_seat_inventory fsi
        LEFT JOIN ticket t
               ON t.flight_id = fsi.flight_id
              AND t.class_code = fsi.class_code
        LEFT JOIN purchases p
               ON p.ticket_id = t.ticket_id
        WHERE fsi.flight_id = %s
        GROUP BY fsi.class_code, fsi.capacity, fsi.base_price
        ORDER BY fsi.class_code
        """,
        (flight_id,)
    )
    rows = cursor.fetchall()

    seat_options = []
    for r in rows:
        remaining = r["capacity"] - r["sold"]
        seat_options.append({
            "class_code": r["class_code"],
            "capacity": r["capacity"],
            "sold": r["sold"],
            "remaining": remaining,
            "base_price": r["base_price"],
        })

    if request.method == "GET":
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error=None,
            message=None
        )

    # ---------- POST: confirm purchase ----------
    customer_email = request.form["customer_email"].strip()
    class_code = request.form.get("class_code")

    # Make sure customer exists
    cursor.execute(
        "SELECT email FROM customer WHERE email = %s",
        (customer_email,)
    )
    cust = cursor.fetchone()
    if not cust:
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error="Customer email not found. Please make sure the customer has registered.",
            message=None
        )

    # Find selected seat class
    selected = None
    for s in seat_options:
        if s["class_code"] == class_code:
            selected = s
            break

    if selected is None:
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error="Invalid seat class selection.",
            message=None
        )

    # ------- Ticket-limit check -------
    if selected["remaining"] <= 0:
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error=f"No seats remaining in class {class_code}. Ticket cannot be purchased.",
            message=None
        )
    # ----------------------------------

    sold_price = selected["base_price"]

    try:
        purchase_ticket(conn, flight_id, class_code, customer_email, agent_email=agent_email)
    except BookingError as e:
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html", flight=flight, seat_options=seat_options,
            error=str(e), message=None
        ), 409
    except Exception:
        app.logger.exception("Ticket purchase failed")
        conn.rollback()
        cursor.close()
        conn.close()
        return render_template(
            "agent_purchase.html",
            flight=flight,
            seat_options=seat_options,
            error="Purchase failed. Please try again.",
            message=None
        )

    cursor.close()
    conn.close()

    return render_template(
        "agent_purchase.html",
        flight=flight,
        seat_options=seat_options,
        error=None,
        message=f"Ticket purchased successfully for {customer_email} in class {class_code}."
    )

@app.route("/agent/commissions")
def agent_commissions():
    if session.get("role") != "agent":
        return redirect(url_for("login"))

    agent_email = session.get("email")
    agent_id = session.get("agent_id")
    commission_rate = 0.10  # 10% commission

    # 读取筛选条件（用于“我帮客户买过的航班”那一块）
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    filter_dep = request.args.get("departure_airport", "").strip().upper()
    filter_arr = request.args.get("arrival_airport", "").strip().upper()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1) Total revenue (all time)
        cursor.execute(
            """
            SELECT COALESCE(SUM(sold_price), 0) AS total_revenue
            FROM purchases
            WHERE agent_email = %s
            """,
            (agent_email,)
        )
        row = cursor.fetchone()
        total_all_revenue = float(row["total_revenue"] or 0)
        total_all_commission = round(total_all_revenue * commission_rate, 2)

        # 2) Last 12 months (可选增强)
        cursor.execute(
            """
            SELECT COALESCE(SUM(sold_price), 0) AS total_revenue
            FROM purchases
            WHERE agent_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            """,
            (agent_email,)
        )
        row = cursor.fetchone()
        total_1year_revenue = float(row["total_revenue"] or 0)
        total_1year_commission = round(total_1year_revenue * commission_rate, 2)

        # 3) Last 30 days: 总佣金 + 票数 + 平均每张佣金
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(sold_price), 0) AS total_revenue,
                COUNT(*) AS ticket_count
            FROM purchases
            WHERE agent_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            """,
            (agent_email,)
        )
        row = cursor.fetchone()
        total_30days_revenue = float(row["total_revenue"] or 0)
        total_30days_commission = round(total_30days_revenue * commission_rate, 2)
        tickets_30days = int(row["ticket_count"] or 0)
        if tickets_30days > 0:
            avg_30days_commission = round(total_30days_commission / tickets_30days, 2)
        else:
            avg_30days_commission = 0.0

        # 4) Revenue by month (last 6 months) -> 用来画条形图
        cursor.execute(
            """
            SELECT
                YEAR(purchase_date) AS y,
                MONTH(purchase_date) AS m,
                SUM(sold_price) AS total_revenue
            FROM purchases
            WHERE agent_email = %s
              AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY y, m
            ORDER BY y, m
            """,
            (agent_email,)
        )
        month_rows = cursor.fetchall()

        months = []
        max_commission = 0.0
        tmp = []

        for r in month_rows:
            revenue = float(r["total_revenue"] or 0)
            commission = revenue * commission_rate
            tmp.append((r["y"], r["m"], commission))
            if commission > max_commission:
                max_commission = commission

        for y, m, commission in tmp:
            if max_commission > 0:
                width = int(commission / max_commission * 300)
            else:
                width = 0
            month_label = f"{y}-{m:02d}"
            months.append({
                "month": month_label,
                "commission": round(commission, 2),
                "bar_width": width,
            })

        # 5) 详细销售记录（可按时间 + 起降机场筛选）
        base_query = """
            SELECT
                p.purchase_date,
                p.sold_price,
                p.customer_email,
                f.airline_name,
                f.flight_num,
                t.class_code,
                f.departure_airport,
                f.arrival_airport
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE p.agent_email = %s
        """
        params = [agent_email]

        if start_date:
            base_query += " AND p.purchase_date >= %s"
            params.append(start_date)
        if end_date:
            # 用 DATE() 包一下，让 date input 更好用
            base_query += " AND DATE(p.purchase_date) <= %s"
            params.append(end_date)
        if filter_dep:
            base_query += " AND f.departure_airport = %s"
            params.append(filter_dep)
        if filter_arr:
            base_query += " AND f.arrival_airport = %s"
            params.append(filter_arr)

        base_query += " ORDER BY p.purchase_date DESC"

        cursor.execute(base_query, tuple(params))
        rows = cursor.fetchall()

        sales = []
        for r in rows:
            price = float(r["sold_price"] or 0)
            commission = round(price * commission_rate, 2)
            sales.append({
                "purchase_date": r["purchase_date"],
                "customer_email": r["customer_email"],
                "airline_name": r["airline_name"],
                "flight_num": r["flight_num"],
                "class_code": r["class_code"],
                "departure_airport": r["departure_airport"],
                "arrival_airport": r["arrival_airport"],
                "sold_price": price,
                "commission": commission,
            })

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "agent_commissions.html",
        email=agent_email,
        agent_id=agent_id,
        rate=commission_rate,
        total_all_commission=total_all_commission,
        total_1year_commission=total_1year_commission,
        total_30days_commission=total_30days_commission,
        tickets_30days=tickets_30days,
        avg_30days_commission=avg_30days_commission,
        months=months,
        sales=sales,
        # 为了表单回显
        start_date=start_date,
        end_date=end_date,
        filter_dep=filter_dep,
        filter_arr=filter_arr,
    )



@app.route("/agent/top_customers")
def agent_top_customers():
    if session.get("role") != "agent":
        return redirect(url_for("login"))

    agent_email = session.get("email")
    agent_id = session.get("agent_id")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Top customers in the last 6 months by revenue
        cursor.execute(
            """
            SELECT
                p.customer_email,
                COALESCE(c.name, p.customer_email) AS customer_name,
                COUNT(*) AS ticket_count,
                SUM(p.sold_price) AS total_revenue
            FROM purchases p
            LEFT JOIN customer c ON p.customer_email = c.email
            WHERE p.agent_email = %s
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY p.customer_email, c.name
            ORDER BY total_revenue DESC
            LIMIT 5
            """,
            (agent_email,)
        )
        rows = cursor.fetchall()

        customers = []
        max_revenue = 0
        for r in rows:
            if r["total_revenue"] > max_revenue:
                max_revenue = r["total_revenue"]

        for r in rows:
            label = r["customer_name"] or r["customer_email"]
            revenue = r["total_revenue"]
            tickets = r["ticket_count"]
            if max_revenue > 0:
                width = int(revenue / max_revenue * 300)
            else:
                width = 0
            customers.append({
                "label": label,
                "ticket_count": tickets,
                "total_revenue": revenue,
                "bar_width": width,
            })

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "agent_top_customers.html",
        email=agent_email,
        agent_id=agent_id,
        customers=customers
    )


# ---------- Staff 首页 ----------
@app.route("/staff/home")
def staff_home():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    return render_template(
        "staff_home.html",
        username=session.get("username"),
        airline_name=session.get("airline_name"),
        permission_type=session.get("permission_type")
    )
@app.route("/staff/create_airport", methods=["GET", "POST"])
def staff_create_airport():
    # 必须是 staff
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    # 必须是 admin
    if session.get("permission_type") != "admin":
        return render_template(
            "staff_create_airport.html",
            error="You do not have permission to create airports (admin only).",
            message=None
        )

    # GET: 显示表单
    if request.method == "GET":
        return render_template(
            "staff_create_airport.html",
            error=None,
            message=None
        )

    # POST: 处理表单提交
    airport_code = request.form["airport_code"].strip().upper()
    name = request.form["name"].strip()
    city = request.form["city"].strip()
    country = request.form["country"].strip()

    # 基本后端校验
    if len(airport_code) != 3 or not airport_code.isalpha():
        return render_template(
            "staff_create_airport.html",
            error="Airport code must be exactly 3 letters.",
            message=None
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 检查是否已存在
        cursor.execute(
            "SELECT * FROM airport WHERE airport_code = %s",
            (airport_code,)
        )
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return render_template(
                "staff_create_airport.html",
                error=f"Airport with code {airport_code} already exists.",
                message=None
            )

        # 插入新机场
        cursor.execute(
            """
            INSERT INTO airport (airport_code, name, city, country)
            VALUES (%s, %s, %s, %s)
            """,
            (airport_code, name, city, country)
        )
        conn.commit()

    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_airport.html",
            error="The database operation failed. Please check the submitted values.",
            message=None
        )

    cursor.close()
    conn.close()

    return render_template(
        "staff_create_airport.html",
        error=None,
        message=f"Airport {airport_code} created successfully."
    )
@app.route("/staff/create_airplane", methods=["GET", "POST"])
def staff_create_airplane():
    # Must be staff
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    # Must be admin (authorization)
    if session.get("permission_type") != "admin":
        return render_template(
            "staff_create_airplane.html",
            airline_name=session.get("airline_name"),
            error="You do not have permission to create airplanes (admin only).",
            message=None
        )

    airline_name = session.get("airline_name")

    if request.method == "GET":
        return render_template(
            "staff_create_airplane.html",
            airline_name=airline_name,
            error=None,
            message=None
        )

    # POST: handle form submission
    model = request.form["model"].strip()
    total_seats_raw = request.form["total_seats"].strip()

    # Basic server-side validation
    if not total_seats_raw.isdigit():
        return render_template(
            "staff_create_airplane.html",
            airline_name=airline_name,
            error="Total seats must be a positive integer.",
            message=None
        )

    total_seats = int(total_seats_raw)
    if total_seats <= 0:
        return render_template(
            "staff_create_airplane.html",
            airline_name=airline_name,
            error="Total seats must be greater than zero.",
            message=None
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Insert a new airplane for this staff's airline
        cursor.execute(
            """
            INSERT INTO airplane (airline_name, model, total_seats)
            VALUES (%s, %s, %s)
            """,
            (airline_name, model, total_seats)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_airplane.html",
            airline_name=airline_name,
            error="The database operation failed. Please check the submitted values.",
            message=None
        )

    cursor.close()
    conn.close()

    return render_template(
        "staff_create_airplane.html",
        airline_name=airline_name,
        error=None,
        message=f"Airplane created successfully for {airline_name}."
    )
@app.route("/staff/create_flight", methods=["GET", "POST"])
def staff_create_flight():
    # Must be logged in as staff
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    # Must be admin
    if session.get("permission_type") != "admin":
        # Still render the page, but with error message
        # For simplicity we pass empty lists for airplanes/airports
        return render_template(
            "staff_create_flight.html",
            airline_name=session.get("airline_name"),
            airplanes=[],
            airports=[],
            error="You do not have permission to create flights (admin only).",
            message=None
        )

    airline_name = session.get("airline_name")

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "GET":
        # Load airplanes owned by this airline
        cursor.execute(
            """
            SELECT airplane_id, model, total_seats
            FROM airplane
            WHERE airline_name = %s
            """,
            (airline_name,)
        )
        airplanes = cursor.fetchall()

        # Load all airports
        cursor.execute(
            """
            SELECT airport_code, city, country
            FROM airport
            ORDER BY airport_code
            """
        )
        airports = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error=None,
            message=None
        )

    # POST: handle form submission
    flight_num = request.form["flight_num"].strip()
    airplane_id_raw = request.form["airplane_id"].strip()
    departure_airport = request.form["departure_airport"].strip()
    arrival_airport = request.form["arrival_airport"].strip()
    departure_time_raw = request.form["departure_time"].strip()
    arrival_time_raw = request.form["arrival_time"].strip()
    base_price_raw = request.form["base_price"].strip()

    # Reload airplanes and airports for error rendering
    cursor.execute(
        """
        SELECT airplane_id, model, total_seats
        FROM airplane
        WHERE airline_name = %s
        """,
        (airline_name,)
    )
    airplanes = cursor.fetchall()

    cursor.execute(
        """
        SELECT airport_code, city, country
        FROM airport
        ORDER BY airport_code
        """
    )
    airports = cursor.fetchall()

    # Basic validation
    if not airplane_id_raw.isdigit():
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Invalid airplane selected.",
            message=None
        )
    airplane_id = int(airplane_id_raw)

    if departure_airport == arrival_airport:
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Departure and arrival airports must be different.",
            message=None
        )

    # Parse datetimes from HTML datetime-local format
    try:
        dt_format = "%Y-%m-%dT%H:%M"
        departure_dt = datetime.strptime(departure_time_raw, dt_format)
        arrival_dt = datetime.strptime(arrival_time_raw, dt_format)
    except ValueError:
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Invalid date/time format.",
            message=None
        )

    if arrival_dt <= departure_dt:
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Arrival time must be later than departure time.",
            message=None
        )

    try:
        base_price = float(base_price_raw)
        if not math.isfinite(base_price) or base_price < 0:
            raise ValueError()
    except ValueError:
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Base price must be a non-negative number.",
            message=None
        )

    # Format datetimes for MySQL
    departure_time = departure_dt.strftime("%Y-%m-%d %H:%M:%S")
    arrival_time = arrival_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Check that airplane belongs to this airline (extra safety)
    cursor.execute(
        """
        SELECT airplane_id, total_seats
        FROM airplane
        WHERE airplane_id = %s AND airline_name = %s
        """,
        (airplane_id, airline_name)
    )
    plane_row = cursor.fetchone()
    if not plane_row:
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="Selected airplane does not belong to your airline.",
            message=None
        )

    # Insert the new flight
    try:
        cursor.execute(
            """
            INSERT INTO flight (
                airline_name, flight_num,
                departure_airport, departure_time,
                arrival_airport, arrival_time,
                base_price, status, airplane_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'upcoming', %s)
            """,
            (
                airline_name, flight_num,
                departure_airport, departure_time,
                arrival_airport, arrival_time,
                base_price, airplane_id
            )
        )
        new_id = cursor.lastrowid
        cursor.execute(
            "INSERT IGNORE INTO seat_class (class_code, description) VALUES ('ECON', 'Economy')"
        )
        cursor.execute(
            """INSERT INTO flight_seat_inventory (flight_id, class_code, capacity, base_price)
               VALUES (%s, 'ECON', %s, %s)""",
            (new_id, plane_row["total_seats"], base_price),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return render_template(
            "staff_create_flight.html",
            airline_name=airline_name,
            airplanes=airplanes,
            airports=airports,
            error="The database operation failed. Please check the submitted values.",
            message=None
        )

    cursor.close()
    conn.close()

    return render_template(
        "staff_create_flight.html",
        airline_name=airline_name,
        airplanes=airplanes,
        airports=airports,
        error=None,
        message=f"Flight created successfully with id {new_id}."
    )

@app.route("/staff/flights", methods=["GET", "POST"])
def staff_flights():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    username = session.get("username")
    airline_name = session.get("airline_name")
    permission_type = session.get("permission_type")
    can_update = permission_type in ("admin", "operator")

    message = None
    error = None

    conn = get_db_connection()
    cursor = conn.cursor()

    # ---------- 先处理航班状态更新（POST） ----------
    if request.method == "POST":
        if not can_update:
            error = "You do not have permission to update flight status."
        else:
            flight_id = request.form.get("flight_id")
            new_status = request.form.get("new_status")

            valid_status = [
                "upcoming",
                "delayed",
                "in-progress",
                "completed",
                "cancelled",
            ]

            if new_status not in valid_status:
                error = "Invalid status value."
            else:
                try:
                    cursor.execute(
                        """
                        UPDATE flight
                        SET status = %s
                        WHERE flight_id = %s
                          AND airline_name = %s
                        """,
                        (new_status, flight_id, airline_name)
                    )
                    if cursor.rowcount == 0:
                        error = "Flight not found or does not belong to your airline."
                    else:
                        conn.commit()
                        message = f"Flight {flight_id} status updated to {new_status}."
                except Exception as e:
                    conn.rollback()
                    error = f"Database error during update: {e}"

    # ---------- 构造过滤条件（GET 参数） ----------
    # 如果没有任何 filter，默认：未来 30 天内本航司所有航班
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    dep_airport = (request.args.get("departure_airport") or "").strip().upper()
    arr_airport = (request.args.get("arrival_airport") or "").strip().upper()

    # 是否用户手动指定了日期范围
    has_custom_date = bool(start_date or end_date)

    where_clauses = ["airline_name = %s"]
    params = [airline_name]

    if has_custom_date:
        if start_date:
            where_clauses.append("DATE(departure_time) >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("DATE(departure_time) <= %s")
            params.append(end_date)
    else:
        # 默认：未来 30 天
        where_clauses.append(
            "departure_time BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 30 DAY)"
        )

    if dep_airport:
        where_clauses.append("departure_airport = %s")
        params.append(dep_airport)

    if arr_airport:
        where_clauses.append("arrival_airport = %s")
        params.append(arr_airport)

    query = f"""
        SELECT
            flight_id,
            flight_num,
            departure_airport,
            departure_time,
            arrival_airport,
            arrival_time,
            status
        FROM flight
        WHERE {' AND '.join(where_clauses)}
        ORDER BY departure_time ASC
    """

    cursor.execute(query, tuple(params))
    flights = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "staff_flights.html",
        username=username,
        airline_name=airline_name,
        permission_type=permission_type,
        can_update=can_update,
        flights=flights,
        message=message,
        error=error,
        filter_start_date=start_date,
        filter_end_date=end_date,
        filter_dep_airport=dep_airport,
        filter_arr_airport=arr_airport,
    )


@app.route("/staff/analytics")
def staff_analytics():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    username = session.get("username")
    airline_name = session.get("airline_name")
    permission_type = session.get("permission_type")

    conn = get_db_connection()
    cursor = conn.cursor()

    error = None

    # 所有要传给模板的列表，先初始化
    top_agents_30d = []         # 最近30天，按出票数排行的agent
    top_agents_1y = []          # 最近1年，按佣金排行的agent
    frequent_customers = []     # 最近1年，按票数排行的customers
    most_frequent_customers = []  # 其中票数最多的customer（可能有并列）
    tickets_per_month = []      # 最近12个月，按月卖出的票数
    delay_stats = []            # delay vs on-time 统计
    top_dest_3m = []            # 最近3个月最热门目的地
    top_dest_1y = []            # 最近1年最热门目的地

    commission_rate = 0.10   # 假设 agent 佣金率 10%

    try:
        # ---------- 1) Top booking agents - 最近30天按票数 ----------
        cursor.execute(
            """
            SELECT
                p.agent_email,
                COUNT(*) AS ticket_count,
                SUM(p.sold_price) AS total_revenue
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE f.airline_name = %s
              AND p.agent_email IS NOT NULL
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY p.agent_email
            ORDER BY ticket_count DESC
            LIMIT 5
            """,
            (airline_name,)
        )
        rows = cursor.fetchall()

        max_tickets_30d = max((r["ticket_count"] or 0) for r in rows) if rows else 0
        for r in rows:
            ticket_count = int(r["ticket_count"] or 0)
            revenue = float(r["total_revenue"] or 0.0)
            commission = round(revenue * commission_rate, 2)
            width = int(ticket_count / max_tickets_30d * 300) if max_tickets_30d > 0 else 0
            top_agents_30d.append({
                "agent_email": r["agent_email"],
                "ticket_count": ticket_count,
                "commission": commission,
                "bar_width": width,
            })

        # ---------- 2) Top booking agents - 最近1年按佣金 ----------
        cursor.execute(
            """
            SELECT
                p.agent_email,
                COUNT(*) AS ticket_count,
                SUM(p.sold_price) AS total_revenue
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE f.airline_name = %s
              AND p.agent_email IS NOT NULL
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP BY p.agent_email
            ORDER BY total_revenue DESC
            LIMIT 5
            """,
            (airline_name,)
        )
        rows = cursor.fetchall()

        max_commission_1y = 0.0
        tmp = []
        for r in rows:
            revenue = float(r["total_revenue"] or 0.0)
            commission = revenue * commission_rate
            tmp.append((r["agent_email"], int(r["ticket_count"] or 0), commission))
            if commission > max_commission_1y:
                max_commission_1y = commission

        for email, ticket_count, commission in tmp:
            width = int(commission / max_commission_1y * 300) if max_commission_1y > 0 else 0
            top_agents_1y.append({
                "agent_email": email,
                "ticket_count": ticket_count,
                "commission": round(commission, 2),
                "bar_width": width,
            })

        # ---------- 3) Frequent customers - 最近1年 ----------
        cursor.execute(
            """
            SELECT
                p.customer_email,
                COALESCE(c.name, p.customer_email) AS customer_name,
                COUNT(*) AS ticket_count,
                SUM(p.sold_price) AS total_spent
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            LEFT JOIN customer c ON p.customer_email = c.email
            WHERE f.airline_name = %s
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP BY p.customer_email, c.name
            ORDER BY ticket_count DESC
            LIMIT 10
            """,
            (airline_name,)
        )
        cust_rows = cursor.fetchall()

        max_ticket_count = max((r["ticket_count"] or 0) for r in cust_rows) if cust_rows else 0
        for r in cust_rows:
            label = r["customer_name"] or r["customer_email"]
            tickets = int(r["ticket_count"] or 0)
            spent = float(r["total_spent"] or 0.0)
            width = int(tickets / max_ticket_count * 300) if max_ticket_count > 0 else 0
            frequent_customers.append({
                "label": label,
                "email": r["customer_email"],
                "ticket_count": tickets,
                "total_spent": spent,
                "bar_width": width,
            })
            if tickets == max_ticket_count and max_ticket_count > 0:
                most_frequent_customers.append({
                    "label": label,
                    "email": r["customer_email"],
                    "ticket_count": tickets,
                    "total_spent": spent,
                })

        # ---------- 4) Tickets sold per month - 最近12个月 ----------
        cursor.execute(
            """
            SELECT
                YEAR(p.purchase_date) AS y,
                MONTH(p.purchase_date) AS m,
                COUNT(*) AS tickets_sold
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            WHERE f.airline_name = %s
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP BY y, m
            ORDER BY y, m
            """,
            (airline_name,)
        )
        month_rows = cursor.fetchall()

        max_tickets = max((r["tickets_sold"] or 0) for r in month_rows) if month_rows else 0
        for r in month_rows:
            tickets = int(r["tickets_sold"] or 0)
            month_label = f"{r['y']}-{int(r['m']):02d}"
            width = int(tickets / max_tickets * 300) if max_tickets > 0 else 0
            tickets_per_month.append({
                "month": month_label,
                "tickets": tickets,
                "bar_width": width,
            })

        # ---------- 5) Delay vs on-time 统计 - 最近1年 ----------
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'delayed' THEN 1 ELSE 0 END) AS delayed_count,
                SUM(CASE WHEN status IN ('upcoming','in-progress','completed') THEN 1 ELSE 0 END) AS on_time_count,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count
            FROM flight
            WHERE airline_name = %s
              AND departure_time >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            """,
            (airline_name,)
        )
        row = cursor.fetchone() or {}
        delayed = int(row.get("delayed_count") or 0)
        on_time = int(row.get("on_time_count") or 0)
        cancelled = int(row.get("cancelled_count") or 0)

        max_count = max(delayed, on_time, cancelled)
        def mk_bar(label, count):
            w = int(count / max_count * 300) if max_count > 0 else 0
            return {"label": label, "count": count, "bar_width": w}

        delay_stats = [
            mk_bar("On-time / completed", on_time),
            mk_bar("Delayed", delayed),
            mk_bar("Cancelled", cancelled),
        ]


        # ---------- 6) Top destinations - 最近3个月 ----------
        cursor.execute(
            """
            SELECT
                f.arrival_airport,
                a.city,
                COUNT(*) AS tickets_sold
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            JOIN airport a ON f.arrival_airport = a.airport_code
            WHERE f.airline_name = %s
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
            GROUP BY f.arrival_airport, a.city
            ORDER BY tickets_sold DESC
            LIMIT 5
            """,
            (airline_name,)
        )
        dest_rows = cursor.fetchall()

        max_tickets_3m = max((r["tickets_sold"] or 0) for r in dest_rows) if dest_rows else 0
        for r in dest_rows:
            tickets = int(r["tickets_sold"] or 0)
            width = int(tickets / max_tickets_3m * 300) if max_tickets_3m > 0 else 0
            top_dest_3m.append({
                "arrival_airport": r["arrival_airport"],
                "city": r["city"],
                "tickets_sold": tickets,
                "bar_width": width,
            })

        # ---------- 7) Top destinations - 最近1年 ----------
        cursor.execute(
            """
            SELECT
                f.arrival_airport,
                a.city,
                COUNT(*) AS tickets_sold
            FROM purchases p
            JOIN ticket t ON p.ticket_id = t.ticket_id
            JOIN flight f ON t.flight_id = f.flight_id
            JOIN airport a ON f.arrival_airport = a.airport_code
            WHERE f.airline_name = %s
              AND p.purchase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP BY f.arrival_airport, a.city
            ORDER BY tickets_sold DESC
            LIMIT 5
            """,
            (airline_name,)
        )
        dest_rows = cursor.fetchall()

        max_tickets_1y = max((r["tickets_sold"] or 0) for r in dest_rows) if dest_rows else 0
        for r in dest_rows:
            tickets = int(r["tickets_sold"] or 0)
            width = int(tickets / max_tickets_1y * 300) if max_tickets_1y > 0 else 0
            top_dest_1y.append({
                "arrival_airport": r["arrival_airport"],
                "city": r["city"],
                "tickets_sold": tickets,
                "bar_width": width,
            })

    except Exception as e:
        # 关键：SQL 有问题时显示在页面，而不是直接 500
        error = f"Database error in analytics: {e}"

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "staff_analytics.html",
        username=username,
        airline_name=airline_name,
        permission_type=permission_type,
        error=error,
        top_agents_30d=top_agents_30d,
        top_agents_1y=top_agents_1y,
        frequent_customers=frequent_customers,
        most_frequent_customers=most_frequent_customers,
        tickets_per_month=tickets_per_month,
        delay_stats=delay_stats,
        top_dest_3m=top_dest_3m,
        top_dest_1y=top_dest_1y,
    )

@app.route("/staff/assign_agent", methods=["GET", "POST"])
def staff_assign_agent():
    # 必须是 staff
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    airline_name = session.get("airline_name")
    permission_type = session.get("permission_type")

    # 不是 admin，直接给一个只读页面
    if permission_type != "admin":
        return render_template(
            "staff_assign_agent.html",
            airline_name=airline_name,
            error="You do not have permission to manage booking agents (admin only).",
            message=None,
            current_agents=[],
            all_agents=[]
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    error = None
    message = None

    # ---------- 处理表单提交（POST） ----------
    if request.method == "POST":
        agent_email = request.form.get("agent_email", "").strip()

        if not agent_email:
            error = "Please select a booking agent email."
        else:
            try:
                # 1) 检查这个 email 是否真的是 booking_agent
                cursor.execute(
                    "SELECT email, agent_id FROM booking_agent WHERE email = %s",
                    (agent_email,)
                )
                agent_row = cursor.fetchone()
                if not agent_row:
                    error = f"No booking agent found with email {agent_email}."
                else:
                    # 2) 检查是否已经和当前 airline 关联
                    cursor.execute(
                        """
                        SELECT 1
                        FROM agent_works_for
                        WHERE email = %s AND airline_name = %s
                        """,
                        (agent_email, airline_name)
                    )
                    exists = cursor.fetchone()
                    if exists:
                        error = f"{agent_email} is already associated with {airline_name}."
                    else:
                        # 3) 插入关联
                        cursor.execute(
                            """
                            INSERT INTO agent_works_for (email, airline_name)
                            VALUES (%s, %s)
                            """,
                            (agent_email, airline_name)
                        )
                        conn.commit()
                        message = f"Booking agent {agent_email} is now associated with {airline_name}."
            except Exception as e:
                conn.rollback()
                error = f"Database error while assigning agent: {e}"

    # ---------- 无论 GET / POST，都要拉取列表用于展示 ----------

    # 当前 airline 已经关联的 agent 列表
    cursor.execute(
        """
        SELECT aw.email, ba.agent_id
        FROM agent_works_for aw
        JOIN booking_agent ba ON aw.email = ba.email
        WHERE aw.airline_name = %s
        ORDER BY aw.email
        """,
        (airline_name,)
    )
    current_agents = cursor.fetchall()

    # 系统中所有 booking agents（用于下拉菜单）
    cursor.execute(
        """
        SELECT email, agent_id
        FROM booking_agent
        ORDER BY email
        """
    )
    all_agents = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "staff_assign_agent.html",
        airline_name=airline_name,
        error=error,
        message=message,
        current_agents=current_agents,
        all_agents=all_agents
    )

@app.route("/staff/passengers", methods=["GET", "POST"])
def staff_passengers():
    # 必须是 staff
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    airline_name = session.get("airline_name")
    username = session.get("username")
    permission_type = session.get("permission_type")

    conn = get_db_connection()
    cursor = conn.cursor()

    error = None
    passengers = []
    selected_flight = None
    selected_flight_id = None

    # 先把本航司的所有航班拉出来，用于下拉框
    cursor.execute(
        """
        SELECT
            flight_id,
            flight_num,
            departure_airport,
            departure_time,
            arrival_airport,
            arrival_time,
            status
        FROM flight
        WHERE airline_name = %s
        ORDER BY departure_time DESC
        """,
        (airline_name,)
    )
    flights = cursor.fetchall()

    # ---------- 如果是 POST，处理选择的 flight ----------
    if request.method == "POST":
        flight_id_raw = request.form.get("flight_id", "").strip()
        if not flight_id_raw.isdigit():
            error = "Please select a valid flight."
        else:
            selected_flight_id = int(flight_id_raw)

            # 确认这个 flight 属于当前 staff 的 airline
            cursor.execute(
                """
                SELECT
                    flight_id,
                    flight_num,
                    departure_airport,
                    departure_time,
                    arrival_airport,
                    arrival_time,
                    status
                FROM flight
                WHERE flight_id = %s AND airline_name = %s
                """,
                (selected_flight_id, airline_name)
            )
            selected_flight = cursor.fetchone()

            if not selected_flight:
                error = "Flight not found or does not belong to your airline."
            else:
                # 查这个航班的乘客名单
                cursor.execute(
                    """
                    SELECT
                        p.ticket_id,
                        COALESCE(c.name, p.customer_email) AS customer_name,
                        p.customer_email,
                        t.class_code,
                        p.agent_email,
                        p.purchase_date,
                        p.sold_price
                    FROM purchases p
                    JOIN ticket t ON p.ticket_id = t.ticket_id
                    JOIN flight f ON t.flight_id = f.flight_id
                    LEFT JOIN customer c ON p.customer_email = c.email
                    WHERE t.flight_id = %s
                      AND f.airline_name = %s
                    ORDER BY p.purchase_date
                    """,
                    (selected_flight_id, airline_name)
                )
                passengers = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "staff_passengers.html",
        username=username,
        airline_name=airline_name,
        permission_type=permission_type,
        flights=flights,
        error=error,
        selected_flight=selected_flight,
        selected_flight_id=selected_flight_id,
        passengers=passengers,
    )

@app.route("/staff/customer_flights", methods=["GET", "POST"])
def staff_customer_flights():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    airline_name = session.get("airline_name")
    username = session.get("username")
    permission_type = session.get("permission_type")

    conn = get_db_connection()
    cursor = conn.cursor()

    error = None
    flights = []
    customer_email = ""
    customer_name = None

    if request.method == "POST":
        customer_email = request.form.get("customer_email", "").strip()

        if not customer_email:
            error = "Please enter a customer email."
        else:
            # 先看看这个 customer 在系统里有没有
            cursor.execute(
                "SELECT email, name FROM customer WHERE email = %s",
                (customer_email,)
            )
            row = cursor.fetchone()
            if not row:
                error = f"No customer found with email {customer_email}."
            else:
                customer_name = row["name"]

                # 查该 customer 在本航司坐过的所有航班
                cursor.execute(
                    """
                    SELECT
                        f.flight_id,
                        f.flight_num,
                        f.departure_airport,
                        f.departure_time,
                        f.arrival_airport,
                        f.arrival_time,
                        f.status,
                        t.class_code,
                        p.sold_price,
                        p.purchase_date,
                        p.agent_email
                    FROM purchases p
                    JOIN ticket t ON p.ticket_id = t.ticket_id
                    JOIN flight f ON t.flight_id = f.flight_id
                    WHERE p.customer_email = %s
                      AND f.airline_name = %s
                    ORDER BY f.departure_time DESC
                    """,
                    (customer_email, airline_name)
                )
                flights = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "staff_customer_flights.html",
        username=username,
        airline_name=airline_name,
        permission_type=permission_type,
        error=error,
        customer_email=customer_email,
        customer_name=customer_name,
        flights=flights
    )


# ---------- Logout ----------
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=os.environ.get("FLASK_DEBUG", "0") == "1")
