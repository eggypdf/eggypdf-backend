import io
import os
import unittest
from unittest.mock import patch
from flask import Flask
from career_routes import career_bp, DODO_PRODUCT_ID

RESUME="""Jane Doe
Email: jane@example.com
Phone: +971 50 123 4567
Professional Summary
Data analyst experienced in SQL, Excel and Power BI.
Experience
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data and improved reporting time by 35%.
Education
Bachelor of Science
Skills
SQL, Excel, Power BI, Communication
"""
JOB="We are seeking a data analyst with SQL, Excel, Power BI, Tableau and communication skills."

class CareerRouteTests(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__); app.register_blueprint(career_bp); app.config['TESTING']=True; self.client=app.test_client()

    def test_health(self):
        r=self.client.get('/api/career/health'); self.assertEqual(r.status_code,200); self.assertEqual(r.get_json()['status'],'ok')

    def test_json_ats_analysis(self):
        r=self.client.post('/api/career/ats/analyze',json={'resume_text':RESUME,'job_description':JOB}); b=r.get_json(); self.assertEqual(r.status_code,200); self.assertTrue(b['success']); self.assertIn('score',b['analysis']); self.assertIn('tableau',b['analysis']['keyword_analysis']['missing'])

    def test_txt_upload(self):
        r=self.client.post('/api/career/ats/analyze',data={'resume':(io.BytesIO(RESUME.encode()),'resume.txt'),'job_description':JOB},content_type='multipart/form-data'); self.assertEqual(r.status_code,200); self.assertTrue(r.get_json()['success'])

    def test_rejects_unsupported_upload(self):
        r=self.client.post('/api/career/ats/analyze',data={'resume':(io.BytesIO(b'hello'),'resume.docx'),'job_description':JOB},content_type='multipart/form-data'); self.assertEqual(r.status_code,400)

    def test_job_match_requires_job_description(self):
        r=self.client.post('/api/career/job-match',json={'resume_text':RESUME}); self.assertEqual(r.status_code,400)

    @patch('career_routes._dodo_request')
    def test_checkout_uses_career_pro_product(self,dodo):
        dodo.return_value={'checkout_url':'https://checkout.example/session','session_id':'cks_test_123'}
        r=self.client.post('/api/career/checkout'); b=r.get_json(); self.assertEqual(r.status_code,200); self.assertTrue(b['success']); args,kwargs=dodo.call_args; self.assertEqual(args[:2],('POST','/checkouts')); self.assertEqual(kwargs['json']['product_cart'],[{'product_id':DODO_PRODUCT_ID,'quantity':1}]); self.assertNotIn('authorization',str(b).lower())

    @patch('career_routes._dodo_request')
    def test_checkout_fails_safely_when_dodo_fails(self,dodo):
        dodo.side_effect=RuntimeError('Payment service is temporarily unavailable.'); r=self.client.post('/api/career/checkout'); self.assertEqual(r.status_code,503); self.assertNotIn(os.getenv('DODO_PAYMENTS_API_KEY','never-expose-this'),str(r.get_json()))

    @patch('career_routes._dodo_request')
    def test_unpaid_checkout_does_not_unlock_pro(self,dodo):
        dodo.return_value={'payment_status':'pending','metadata':{'product':'career_pro'}}; b=self.client.get('/api/career/checkout/cks_test_123').get_json(); self.assertFalse(b['paid']); self.assertIsNone(b['feature_id'])

    @patch('career_routes._dodo_request')
    def test_successful_verified_checkout_unlocks_career_pro(self,dodo):
        dodo.return_value={'payment_status':'succeeded','metadata':{'product':'career_pro'}}; b=self.client.get('/api/career/checkout/cks_test_123').get_json(); self.assertTrue(b['paid']); self.assertEqual(b['feature_id'],'career_pro')

    @patch('career_routes._dodo_request')
    def test_wrong_product_metadata_does_not_unlock_pro(self,dodo):
        dodo.return_value={'payment_status':'succeeded','metadata':{'product':'something_else'}}; b=self.client.get('/api/career/checkout/cks_test_123').get_json(); self.assertFalse(b['paid'])

    def test_invalid_checkout_session_is_rejected(self):
        self.assertEqual(self.client.get('/api/career/checkout/not%20valid!').status_code,400)

    @patch('career_routes._dodo_request')
    def test_paid_user_can_get_tailoring_plan(self,dodo):
        dodo.return_value={'payment_status':'succeeded','metadata':{'product':'career_pro'}}
        r=self.client.post('/api/career/pro/tailor',json={'session_id':'cks_test_123','resume_text':RESUME,'job_description':JOB}); b=r.get_json(); self.assertEqual(r.status_code,200); self.assertTrue(b['success']); self.assertIn('priority_keywords',b['tailoring']); self.assertIn('tableau',b['tailoring']['priority_keywords'])

    @patch('career_routes._dodo_request')
    def test_unpaid_user_cannot_use_tailoring(self,dodo):
        dodo.return_value={'payment_status':'pending','metadata':{'product':'career_pro'}}
        r=self.client.post('/api/career/pro/tailor',json={'session_id':'cks_test_123','resume_text':RESUME,'job_description':JOB}); self.assertEqual(r.status_code,403)

    @patch('career_routes._dodo_request')
    def test_paid_user_can_generate_cover_letter(self,dodo):
        dodo.return_value={'payment_status':'succeeded','metadata':{'product':'career_pro'}}
        r=self.client.post('/api/career/pro/cover-letter',json={'session_id':'cks_test_123','resume_text':RESUME,'job_description':JOB,'applicant_name':'Jane Doe','company':'Example Labs','role':'Data Analyst'}); b=r.get_json(); self.assertEqual(r.status_code,200); self.assertIn('Dear Example Labs',b['cover_letter']); self.assertIn('Jane Doe',b['cover_letter'])

    @patch('career_routes._dodo_request')
    def test_unpaid_user_cannot_generate_cover_letter(self,dodo):
        dodo.return_value={'payment_status':'failed','metadata':{'product':'career_pro'}}
        r=self.client.post('/api/career/pro/cover-letter',json={'session_id':'cks_test_123','resume_text':RESUME,'job_description':JOB}); self.assertEqual(r.status_code,403)

if __name__=='__main__': unittest.main()
