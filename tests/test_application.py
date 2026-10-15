import importlib
import re
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as module
from booking import BookingError, purchase_ticket


class PublicAndPermissionTests(unittest.TestCase):
    def setUp(self):
        module.app.config.update(TESTING=True, SECRET_KEY="offline-test-key")
        self.client = module.app.test_client()

    def token(self):
        self.client.get("/login")
        with self.client.session_transaction() as s:
            return s["_csrf_token"]

    def test_public_forms_render(self):
        for url in ["/", "/login", "/register"]:
            self.assertEqual(self.client.get(url).status_code,200)

    def test_every_template_compiles(self):
        for name in module.app.jinja_env.list_templates():
            module.app.jinja_env.get_template(name)

    def test_forged_staff_registration_is_rejected_before_db_access(self):
        token=self.token()
        with patch.object(module,"get_db_connection",side_effect=AssertionError("Must not access database")):
            response=self.client.post("/register",data={"user_type":"staff","csrf_token":token,"password":"example"})
            self.assertEqual(response.status_code,403)

    def test_mutating_forms_require_csrf(self):
        self.assertEqual(self.client.post("/register",data={"user_type":"customer"}).status_code,400)
        self.token()
        for invalid in ["wrong", "无效令牌"]:
            self.assertEqual(self.client.post("/login",data={"csrf_token":invalid}).status_code,400)

    def test_protected_routes_reject_anonymous_users_without_db_access(self):
        with patch.object(module,"get_db_connection",side_effect=AssertionError("Must not access database")):
            for rule in module.app.url_map.iter_rules():
                if rule.rule.startswith(("/customer/","/agent/","/staff/")):
                    self.assertEqual(self.client.get(rule.rule.replace("<int:flight_id>","1")).status_code,302,rule.rule)

    def test_operator_cannot_open_admin_actions(self):
        with self.client.session_transaction() as s:
            s.update(role="staff",permission_type="operator",airline_name="Demo Air")
        with patch.object(module,"get_db_connection",side_effect=AssertionError("Must not access database")):
            for url in ["/staff/create_airport","/staff/create_airplane","/staff/create_flight","/staff/assign_agent"]:
                response=self.client.get(url)
                self.assertIn(b"do not have permission",response.data)

    def test_logout_requires_post_with_token(self):
        token=self.token()
        with self.client.session_transaction() as s:s["role"]="customer"
        self.assertEqual(self.client.get("/logout").status_code,405)
        self.assertEqual(self.client.post("/logout",data={"csrf_token":token}).status_code,302)
        with self.client.session_transaction() as s:self.assertNotIn("role",s)

    def test_no_sql_dump_is_publicly_served(self):
        self.assertEqual(self.client.get("/static/airline_system.sql").status_code,404)


class BookingTransactionTests(unittest.TestCase):
    def connection(self, *, flight=True, customer=True, capacity=1, sold=0, agent=None):
        conn=Mock();cur=Mock();conn.cursor.return_value=cur;cur.lastrowid=42
        rows=[{"flight_id":1,"airline_name":"Demo Air"} if flight else None]
        if agent is not None:rows.append({"email":agent} if agent else None)
        rows.extend([{"email":"customer@example.invalid"} if customer else None,
                     {"capacity":capacity,"base_price":500}, {"sold":sold}])
        cur.fetchone.side_effect=rows
        return conn,cur

    def test_success_commits_ticket_and_purchase_after_locks(self):
        conn,cur=self.connection()
        self.assertEqual(purchase_ticket(conn,1,"ECON","customer@example.invalid"),42)
        queries=[call.args[0] for call in cur.execute.call_args_list]
        self.assertIn("FOR UPDATE",queries[0]);self.assertIn("FOR UPDATE",queries[2])
        self.assertTrue(queries[-2].startswith("INSERT INTO ticket"))
        self.assertIn("INSERT INTO purchases",queries[-1])
        conn.begin.assert_called_once();conn.commit.assert_called_once()
        cur.close.assert_called_once()

    def test_sold_out_rejects_without_inserting(self):
        conn,cur=self.connection(capacity=1,sold=1)
        with self.assertRaises(BookingError):purchase_ticket(conn,1,"ECON","customer@example.invalid")
        conn.commit.assert_not_called()
        self.assertFalse(any("INSERT" in call.args[0] for call in cur.execute.call_args_list))

    def test_past_or_cancelled_flight_rejected(self):
        conn,cur=self.connection(flight=False)
        with self.assertRaises(BookingError):purchase_ticket(conn,1,"ECON","customer@example.invalid")
        conn.commit.assert_not_called()

    def test_unassigned_agent_rejected(self):
        conn,cur=self.connection(agent="")
        with self.assertRaises(BookingError):purchase_ticket(conn,1,"ECON","customer@example.invalid",agent_email="agent@example.invalid")
        conn.commit.assert_not_called()

    def test_unknown_customer_rejected(self):
        conn,cur=self.connection(customer=False)
        with self.assertRaises(BookingError):purchase_ticket(conn,1,"ECON","missing@example.invalid")
        conn.commit.assert_not_called()

    def test_database_failure_rolls_back_both_writes(self):
        conn,cur=self.connection()
        def execute(query,*args):
            if "INSERT INTO purchases" in query:raise RuntimeError("simulated write failure")
        cur.execute.side_effect=execute
        with self.assertRaises(RuntimeError):purchase_ticket(conn,1,"ECON","customer@example.invalid")
        conn.commit.assert_not_called();self.assertEqual(conn.rollback.call_count,2)


if __name__=="__main__":unittest.main()
