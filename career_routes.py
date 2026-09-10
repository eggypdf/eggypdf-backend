"""EggyPDF Career Pro API routes."""
from __future__ import annotations
import io,os,requests
from flask import Blueprint,jsonify,request,send_file
from werkzeug.utils import secure_filename
from career_engine import analyze_resume,extract_keywords,extract_skills
from career_v2 import extract_resume_upload,optimize_with_gemini
from career_ai import generate_cover_letter_with_gemini
from career_export import build_resume_export
from career_regen import regenerate_section
from career_pdf_ai import extract_pdf_text,summarize_pdf_text

career_bp=Blueprint('career',__name__,url_prefix='/api/career');MAX_TEXT_LENGTH=100_000
DEFAULT_DODO_PRODUCT_ID='pdt_0Nmk7wwSsTDKzOvbI7z9n';DODO_PRODUCT_ID=os.getenv('DODO_PRODUCT_ID',DEFAULT_DODO_PRODUCT_ID).strip();DODO_API_BASE=os.getenv('DODO_API_BASE','https://live.dodopayments.com').rstrip('/');CAREER_PRO_RETURN_URL=os.getenv('CAREER_PRO_RETURN_URL','https://eggypdf.com/ats-checker.html?career_pro=return')

def _validate_text(t,label):
 if not t:raise ValueError(f'{label} is required.')
 if len(t)>MAX_TEXT_LENGTH:raise ValueError(f'{label} is too long. Please keep it under {MAX_TEXT_LENGTH:,} characters.')

def _headers():
 k=os.getenv('DODO_PAYMENTS_API_KEY','').strip()
 if not k:raise RuntimeError('Dodo Payments is not configured.')
 return {'Authorization':f'Bearer {k}','Content-Type':'application/json','Accept':'application/json'}

def _payerr(s):
 if s in(401,403):return 'Dodo authentication failed. Check that the API key matches the selected live/test environment.'
 if s==404:return 'Dodo could not find the requested checkout resource or product. Check the Career Pro product ID and environment.'
 if s in(400,409,422):return 'Dodo rejected the checkout configuration. Check the product, return URL, and account environment.'
 if s==429:return 'Dodo is temporarily rate-limiting checkout requests. Please try again shortly.'
 return f'Payment service rejected the request (HTTP {s}).'

def _dodo(method,path,**kw):
 try:r=requests.request(method,f'{DODO_API_BASE}{path}',headers=_headers(),timeout=20,**kw)
 except requests.RequestException as e:raise RuntimeError('Payment service is temporarily unavailable.') from e
 if not r.ok:raise RuntimeError(_payerr(r.status_code))
 return r.json()

def _valid(v,p):return bool(v and v.startswith(p) and len(v)<=200 and all(c.isalnum() or c in '_-' for c in v))

def _ispro(p,cks=None):
 if p.get('status')!='succeeded' or (cks and p.get('checkout_session_id')!=cks):return False
 return any(x.get('product_id')==DODO_PRODUCT_ID and int(x.get('quantity') or 0)>=1 for x in(p.get('product_cart') or []))

def _verify(i):
 if _valid(i,'pay_'):
  p=_dodo('GET',f'/payments/{i}');return _ispro(p),p.get('status')
 if not _valid(i,'cks_'):raise ValueError('Invalid checkout or payment identifier.')
 c=_dodo('GET',f'/checkouts/{i}');s=c.get('payment_status') or c.get('status');m=c.get('metadata') or {}
 if s=='succeeded' and m.get('product')=='career_pro':return True,s
 pid=(c.get('payment_id') or '').strip()
 if _valid(pid,'pay_'):
  p=_dodo('GET',f'/payments/{pid}')
  return _ispro(p,i),p.get('status') or s
 return False,s

def _require(d):
 paid,_=_verify((d.get('session_id') or d.get('payment_id') or '').strip())
 if not paid:raise PermissionError('Career Pro purchase could not be verified.')

@career_bp.get('/health')
def health():return jsonify({'status':'ok','service':'EggyPDF Career Pro','features':['ats-analysis','job-matching','career-pro-checkout','resume-upload','resume-optimizer','section-regeneration','resume-export','ai-cover-letter','ai-pdf-summarizer'],'payments_configured':bool(os.getenv('DODO_PAYMENTS_API_KEY','').strip()),'payment_environment':'test' if 'test' in DODO_API_BASE.lower() else 'live','career_pro_product_configured':bool(DODO_PRODUCT_ID),'ai_optimizer_configured':bool((os.getenv('GEMINI_API') or os.getenv('GEMINI_API_KEY') or '').strip()),'ai_cover_letter_configured':bool((os.getenv('GEMINI_API') or os.getenv('GEMINI_API_KEY') or '').strip()),'ai_section_regeneration_configured':bool((os.getenv('GEMINI_API') or os.getenv('GEMINI_API_KEY') or '').strip()),'ai_pdf_summarizer_configured':bool((os.getenv('GEMINI_API') or os.getenv('GEMINI_API_KEY') or '').strip())})

@career_bp.post('/checkout')
def checkout():
 try:
  c=_dodo('POST','/checkouts',json={'product_cart':[{'product_id':DODO_PRODUCT_ID,'quantity':1}],'return_url':CAREER_PRO_RETURN_URL,'metadata':{'product':'career_pro','source':'eggypdf'}});u,i=c.get('checkout_url'),c.get('session_id')
  if not u or not i:raise RuntimeError('Payment service returned an incomplete checkout session.')
  return jsonify({'success':True,'checkout_url':u,'session_id':i})
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.get('/checkout/<identifier>')
def verify(identifier):
 try:p,s=_verify(identifier);return jsonify({'success':True,'paid':p,'payment_status':s,'feature_id':'career_pro' if p else None})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.post('/pro/extract-resume')
def pro_extract():
 try:
  sid=(request.form.get('session_id') or '').strip();_require({'session_id':sid});f=request.files.get('resume') or request.files.get('file')
  if not f:raise ValueError('Choose a resume file first.')
  text=extract_resume_upload(f);_validate_text(text,'Resume text');return jsonify({'success':True,'resume_text':text,'filename':secure_filename(f.filename),'characters':len(text)})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503
 except Exception:return jsonify({'success':False,'error':'We could not read this resume. Try a text-based PDF, DOCX, or TXT file.'}),500

@career_bp.post('/pro/optimize')
def pro_optimize():
 try:
  d=request.get_json(silent=True) or {};_require(d);resume=(d.get('resume_text') or '').strip();job=(d.get('job_description') or '').strip();_validate_text(resume,'Resume text');_validate_text(job,'Job description');return jsonify({'success':True,'optimization':optimize_with_gemini(resume,job)})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.post('/pro/regenerate-section')
def pro_regenerate_section():
 try:
  d=request.get_json(silent=True) or {};_require(d)
  source=(d.get('source_resume') or '').strip();optimized=(d.get('optimized_resume') or '').strip();job=(d.get('job_description') or '').strip();section=(d.get('section_type') or '').strip();current=(d.get('current_text') or '').strip()
  _validate_text(source,'Source resume');_validate_text(optimized,'Optimized resume');_validate_text(job,'Job description')
  result=regenerate_section(source,optimized,job,section,current)
  return jsonify({'success':True,'regeneration':result})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.post('/pro/export-resume')
def pro_export_resume():
 try:
  d=request.get_json(silent=True) or {};_require(d);resume=(d.get('resume_text') or '').strip();fmt=(d.get('format') or '').strip().lower();_validate_text(resume,'Optimized resume text')
  data,mime,name=build_resume_export(resume,fmt)
  return send_file(io.BytesIO(data),mimetype=mime,as_attachment=True,download_name=name,max_age=0)
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.post('/pro/pdf-summary')
def pro_pdf_summary():
 try:
  sid=(request.form.get('session_id') or '').strip();_require({'session_id':sid})
  f=request.files.get('pdf') or request.files.get('file')
  if not f:raise ValueError('Choose a PDF file first.')
  detail=(request.form.get('detail') or 'short').strip().lower()
  extracted=extract_pdf_text(f)
  summary=summarize_pdf_text(extracted['text'],detail)
  return jsonify({'success':True,'document':{'filename':secure_filename(extracted['filename']),'page_count':extracted['page_count'],'characters':extracted['characters']},'summary':summary})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503
 except Exception:return jsonify({'success':False,'error':'We could not summarize this PDF. Please try another text-based PDF.'}),500

@career_bp.post('/pro/tailor')
def tailor():
 try:
  d=request.get_json(silent=True) or {};_require(d);r=(d.get('resume_text') or '').strip();j=(d.get('job_description') or '').strip();_validate_text(r,'Resume text');_validate_text(j,'Job description');return jsonify({'success':True,'tailoring':optimize_with_gemini(r,j)})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

@career_bp.post('/pro/cover-letter')
def letter():
 try:
  d=request.get_json(silent=True) or {};_require(d);r=(d.get('resume_text') or '').strip();j=(d.get('job_description') or '').strip();_validate_text(r,'Resume text');_validate_text(j,'Job description')
  result=generate_cover_letter_with_gemini(r,j,(d.get('applicant_name') or '').strip(),(d.get('company') or '').strip(),(d.get('role') or '').strip(),(d.get('tone') or 'professional').strip())
  return jsonify({'success':True,**result})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except PermissionError as e:return jsonify({'success':False,'error':str(e)}),403
 except RuntimeError as e:return jsonify({'success':False,'error':str(e)}),503

def _gettext():
 if request.is_json:return((request.get_json(silent=True) or {}).get('resume_text') or '').strip()
 f=request.files.get('resume') or request.files.get('file')
 if not f:return''
 return extract_resume_upload(f)

def _job():
 if request.is_json:d=request.get_json(silent=True) or {};return(d.get('job_description') or d.get('job_text') or '').strip()
 return(request.form.get('job_description') or request.form.get('job_text') or '').strip()

@career_bp.post('/ats/analyze')
def ats():
 try:
  r=_gettext();j=_job();_validate_text(r,'Resume text')
  return jsonify({'success':True,'analysis':analyze_resume(r,j),'resume_text':r})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
 except Exception:return jsonify({'success':False,'error':'We could not analyze this resume. Please try another file.'}),500

@career_bp.post('/job-match')
def match():
 try:r=_gettext();j=_job();_validate_text(r,'Resume text');_validate_text(j,'Job description');a=analyze_resume(r,j);return jsonify({'success':True,'match':{'score':a['keyword_analysis']['match_percentage'],'matched_keywords':a['keyword_analysis']['matched'],'missing_keywords':a['keyword_analysis']['missing'],'skills_detected':a['skills_detected'],'recommendations':a['recommendations']}})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400

@career_bp.post('/keywords')
def keywords():
 try:d=request.get_json(silent=True) or {};t=(d.get('text') or '').strip();_validate_text(t,'Text');return jsonify({'success':True,'keywords':extract_keywords(t),'skills':extract_skills(t)})
 except ValueError as e:return jsonify({'success':False,'error':str(e)}),400
