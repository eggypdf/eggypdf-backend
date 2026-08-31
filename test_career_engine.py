from career_engine import analyze_resume, extract_skills


SAMPLE_RESUME = """
AHMAD KHAN
Email: ahmad@example.com | Phone: +971500000000 | LinkedIn: linkedin.com/in/ahmad

PROFESSIONAL SUMMARY
Digital marketing specialist with experience in SEO, Google Ads and content marketing.

EXPERIENCE
Marketing Specialist | Example LLC | 2024 - Present
- Increased organic traffic by 45% through SEO improvements.
- Managed Google Ads campaigns for 12 clients.
- Created content strategy and improved lead generation by 20%.

EDUCATION
Bachelor of Business Administration

SKILLS
SEO, Google Ads, Canva, Excel, Communication
"""

SAMPLE_JOB = """
We are hiring a Digital Marketing Specialist with SEO, Google Ads, social media,
content marketing, analytics, communication and lead generation experience.
"""


def test_analysis_is_explainable_and_bounded():
    result = analyze_resume(SAMPLE_RESUME, SAMPLE_JOB)
    assert 0 <= result["score"] <= 100
    assert result["checks"]
    assert "keyword_analysis" in result
    assert "recommendations" in result


def test_relevant_skills_are_detected():
    skills = extract_skills(SAMPLE_RESUME)
    assert "seo" in skills
    assert "google ads" in skills
    assert "canva" in skills
    assert "excel" in skills


def test_job_match_finds_missing_terms():
    result = analyze_resume(SAMPLE_RESUME, SAMPLE_JOB)
    analysis = result["keyword_analysis"]
    assert analysis["match_percentage"] > 0
    assert "social" in analysis["missing"] or "media" in analysis["missing"]
