"""Real InnoDB integration tests; opt in against a disposable demo database."""

import os
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import app as module
from booking import BookingError, purchase_ticket


@unittest.skipUnless(os.environ.get("RUN_DB_TESTS") == "1", "Requires an initialized disposable MySQL database")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        module.app.config.update(TESTING=True)
        conn=module.get_db_connection();cur=conn.cursor()
        cur.execute("SELECT flight_id,airplane_id FROM flight WHERE flight_num='D101'")
        row=cur.fetchone();self.flight_id=row['flight_id'];self.plane_id=row['airplane_id']
        cur.execute("DELETE FROM ticket WHERE flight_id=%s AND class_code='BUS'",(self.flight_id,))
        cur.execute("UPDATE flight_seat_inventory SET capacity=1 WHERE flight_id=%s AND class_code='BUS'",(self.flight_id,))
        cur.execute("INSERT IGNORE INTO agent_works_for VALUES ('agent@example.invalid','Demo Air')")
        conn.commit();cur.close();conn.close()

    def login(self,identifier):
        client=module.app.test_client()
        html=client.get('/login').data.decode()
        token=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
        response=client.post('/login',data={'identifier':identifier,'password':os.environ.get('DEMO_PASSWORD','DemoFlights2026!'),'csrf_token':token})
        self.assertEqual(response.status_code,302)
        return client

    def token(self,client):
        # Authenticated home pages expose the logout form and a fresh token.
        with client.session_transaction() as s:
            role=s['role']
        client.get('/'+role+'/home')
        with client.session_transaction() as s:return s['_csrf_token']

    def counts(self):
        conn=module.get_db_connection();cur=conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM ticket WHERE flight_id=%s AND class_code='BUS'",(self.flight_id,))
        count=cur.fetchone()['n'];cur.close();conn.close();return count

    def test_role_pages_render_with_real_queries(self):
        groups={
            'customer@example.invalid':['/customer/home','/customer/search_flights','/customer/my_flights','/customer/spending',f'/customer/purchase/{self.flight_id}'],
            'agent@example.invalid':['/agent/home','/agent/search_flights','/agent/commissions','/agent/top_customers',f'/agent/purchase/{self.flight_id}'],
            'demo_admin':['/staff/home','/staff/create_airport','/staff/create_airplane','/staff/create_flight','/staff/flights','/staff/analytics','/staff/assign_agent','/staff/passengers','/staff/customer_flights'],
        }
        for user,urls in groups.items():
            client=self.login(user)
            for url in urls:self.assertEqual(client.get(url).status_code,200,url)

    def test_customer_purchase_route_and_sold_out_rejection(self):
        client=self.login('customer@example.invalid')
        result=client.post(f'/customer/purchase/{self.flight_id}',data={'csrf_token':self.token(client),'class_code':'BUS'})
        self.assertIn(b'purchased successfully',result.data)
        result=client.post(f'/customer/purchase/{self.flight_id}',data={'csrf_token':self.token(client),'class_code':'BUS'})
        self.assertIn(b'No seats remaining',result.data)
        self.assertEqual(self.counts(),1)

    def test_agent_purchase_records_agent_and_customer(self):
        client=self.login('agent@example.invalid')
        result=client.post(f'/agent/purchase/{self.flight_id}',data={'csrf_token':self.token(client),'class_code':'BUS','customer_email':'second@example.invalid'})
        self.assertIn(b'purchased successfully',result.data)
        conn=module.get_db_connection();cur=conn.cursor()
        cur.execute("SELECT p.agent_email,p.customer_email FROM purchases p JOIN ticket t USING(ticket_id) WHERE t.flight_id=%s AND t.class_code='BUS'",(self.flight_id,))
        self.assertEqual(cur.fetchone(),{'agent_email':'agent@example.invalid','customer_email':'second@example.invalid'})
        cur.close();conn.close()

    def test_two_buyers_for_last_seat_only_one_commits(self):
        barrier=threading.Barrier(2)
        def buy(customer):
            conn=module.get_db_connection()
            try:
                barrier.wait(timeout=10)
                try:
                    purchase_ticket(conn,self.flight_id,'BUS',customer)
                    return 'purchased'
                except BookingError:return 'sold out'
            finally:conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(buy,'customer@example.invalid');two=pool.submit(buy,'second@example.invalid')
            outcomes=[one.result(timeout=30),two.result(timeout=30)]
        self.assertCountEqual(outcomes,['purchased','sold out'])
        self.assertEqual(self.counts(),1)

    def test_insert_failure_rolls_back_real_ticket(self):
        class FailingCursor:
            def __init__(self,cur):self.cur=cur
            def execute(self,sql,*args):
                if 'INSERT INTO purchases' in sql:
                    return self.cur.execute('INSERT INTO deliberately_missing_rollback_test_table VALUES (1)')
                return self.cur.execute(sql,*args)
            def __getattr__(self,name):return getattr(self.cur,name)
        class FailingConnection:
            def __init__(self,conn):self.conn=conn
            def cursor(self):return FailingCursor(self.conn.cursor())
            def __getattr__(self,name):return getattr(self.conn,name)
        conn=module.get_db_connection()
        try:
            with self.assertRaises(Exception):purchase_ticket(FailingConnection(conn),self.flight_id,'BUS','customer@example.invalid')
        finally:conn.close()
        self.assertEqual(self.counts(),0)

    def test_cancelled_flight_and_unassigned_agent_rejected(self):
        conn=module.get_db_connection();cur=conn.cursor()
        cur.execute("UPDATE flight SET status='cancelled' WHERE flight_id=%s",(self.flight_id,));conn.commit()
        try:
            with self.assertRaises(BookingError):purchase_ticket(conn,self.flight_id,'BUS','customer@example.invalid')
        finally:
            cur.execute("UPDATE flight SET status='upcoming' WHERE flight_id=%s",(self.flight_id,));conn.commit()
        with self.assertRaises(BookingError):purchase_ticket(conn,self.flight_id,'BUS','customer@example.invalid',agent_email='unassigned@example.invalid')
        cur.close();conn.close()

    def test_admin_new_flight_has_purchasable_inventory(self):
        client=self.login('demo_admin')
        start=datetime.now()+timedelta(days=70)
        data={'csrf_token':self.token(client),'flight_num':'TESTCREATE','airplane_id':str(self.plane_id),'departure_airport':'JFK','arrival_airport':'PVG','departure_time':start.strftime('%Y-%m-%dT%H:%M'),'arrival_time':(start+timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M'),'base_price':'400'}
        result=client.post('/staff/create_flight',data=data)
        self.assertIn(b'success',result.data.lower())
        conn=module.get_db_connection();cur=conn.cursor()
        cur.execute("SELECT flight_id FROM flight WHERE flight_num='TESTCREATE'")
        flight_id=cur.fetchone()['flight_id']
        try:
            self.assertIsInstance(purchase_ticket(conn,flight_id,'ECON','customer@example.invalid'),int)
        finally:
            cur.execute('DELETE FROM ticket WHERE flight_id=%s',(flight_id,))
            cur.execute('DELETE FROM flight WHERE flight_id=%s',(flight_id,));conn.commit();cur.close();conn.close()


if __name__=='__main__':unittest.main()
