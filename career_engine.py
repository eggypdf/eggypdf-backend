"""EggyPDF Career Engine

Deterministic ATS-style analysis utilities used by the Career Pro API.
This module deliberately avoids claiming compatibility with a specific ATS vendor.
It measures common resume/job-description signals and returns explainable results.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

STOP_WORDS = {
    "about", "after", "again", "against", "also", "and", "are", "because", "been",
    "before", "being", "between", "both", "but", "can", "could", "did", "does", "doing",
    "for", "from", "had", "has", "have", "having", "her", "here", "hers", "him", "his",
    "how", "into", "its", "just", "more", "most", "not", "now", "of", "on", "once", "only",
    "or", "other", "our", "ours", "out", "over", "same", "she", "should", "so", "some",
    "such", "than", "that", "the", "their", "theirs", "them", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "until", "very", "was", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would",
    "you", "your", "yours", "job", "work", "working", "role", "team", "company", "experience",
}

COMMON_SKILLS = {
    "python", "java", "javascript", "typescript", "react", "node.js", "node", "sql", "mysql",
    "postgresql", "mongodb", "aws", "azure", "gcp", "docker", "kubernetes", "git", "github",
    "excel", "power bi", "tableau", "salesforce", "hubspot", "seo", "sem", "google ads",
    "facebook ads", "figma", "photoshop", "canva", "project management", "agile", "scrum",
    "leadership", "communication", "marketing", "sales", "customer service", "recruiting",
    "recruitment", "accounting", "financial analysis", "data analysis", "machine learning",
    "artificial intelligence", "content writing", "copywriting", "social media", "negotiation",
    "microsoft office", "powerpoint", "word", "arabic", "english", "urdu",
}

ACTION_VERBS = {
    "achieved", "analyzed", "built", "created", "delivered", "developed", "drove", "generated",
    "grew", "implemented", "improved", "increased", "launched", "led", "managed", "optimized",
    "reduced", "resolved", "streamlined", "supervised", "trained", "automated", "designed",
    "negotiated", "executed", "coordinated", "produced", "increased", "decreased",
}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z][a-z0-9+#./-]{1,30}", normalize(text))


def extract_keywords(text: str, limit: int = 40) -> List[str]:
    tokens = [t for t in tokenize(text) if len(t) > 2 and t not in STOP_WORDS]
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]


def extract_skills(text: str) -> List[str]:
    n = normalize(text)
    found = []
    for skill in sorted(COMMON_SKILLS, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", n):
            found.append(skill)
    return found


def keyword_overlap(resume: str, job: str) -> Tuple[List[str], List[str], float]:
    resume_n = normalize(resume)
    job_keywords = extract_keywords(job, 40)
    matched = [k for k in job_keywords if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", resume_n)]
    missing = [k for k in job_keywords if k not in matched]
    score = round((len(matched) / len(job_keywords)) * 100) if job_keywords else 0
    return matched, missing, score


def section_signals(text: str) -> Dict[str, bool]:
    n = normalize(text)
    aliases = {
        "contact": ["email", "phone", "linkedin"],
        "summary": ["summary", "professional summary", "profile", "objective"],
        "experience": ["experience", "work history", "employment"],
        "education": ["education", "academic"],
        "skills": ["skills", "technical skills", "core competencies"],
    }
    return {section: any(a in n for a in terms) for section, terms in aliases.items()}


def analyze_resume(resume_text: str, job_text: str = "") -> Dict:
    resume_text = resume_text or ""
    job_text = job_text or ""
    sections = section_signals(resume_text)
    skills = extract_skills(resume_text)
    matched, missing, keyword_score = keyword_overlap(resume_text, job_text) if job_text.strip() else ([], [], 0)

    lines = [x.strip() for x in resume_text.splitlines() if x.strip()]
    bullets = [x for x in lines if re.match(r"^[•●▪◦*-]\s+", x)]
    action_bullets = [x for x in bullets if any(re.search(r"\b" + re.escape(v) + r"\b", x.lower()) for v in ACTION_VERBS)]
    quantified = [x for x in bullets if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|k|m|million|billion|hours|days|people|clients|customers|projects)?\b", x.lower())]

    checks = []
    def check(name, passed, detail, weight):
        checks.append({"name": name, "passed": bool(passed), "detail": detail, "weight": weight})

    check("Contact information", sections["contact"], "Include an email, phone number, and a professional profile link.", 10)
    check("Professional summary", sections["summary"], "Add a concise summary aligned to the target role.", 10)
    check("Work experience", sections["experience"], "Use a clear employment/experience section with dates and outcomes.", 15)
    check("Education", sections["education"], "Include education or relevant training where appropriate.", 10)
    check("Skills section", sections["skills"], "Add a dedicated skills/competencies section.", 10)
    check("Action-oriented bullets", bool(action_bullets), "Start experience bullets with strong action verbs.", 15)
    check("Quantified achievements", bool(quantified), "Add measurable outcomes such as %, revenue, volume, time, or team size.", 15)
    check("Job keyword alignment", keyword_score >= 60 if job_text.strip() else True, "Match relevant terminology from the target job description without keyword stuffing.", 15)

    score = round(sum(c["weight"] for c in checks if c["passed"]))
    recommendations = [c["detail"] for c in checks if not c["passed"]]
    if job_text.strip() and missing:
        recommendations.insert(0, "Consider adding genuinely relevant missing keywords: " + ", ".join(missing[:10]) + ".")

    return {
        "score": score,
        "score_label": "Strong" if score >= 80 else "Needs improvement" if score >= 60 else "Needs work",
        "checks": checks,
        "keyword_analysis": {
            "matched": matched[:30],
            "missing": missing[:20],
            "match_percentage": keyword_score,
        },
        "skills_detected": skills,
        "bullet_analysis": {
            "total_bullets": len(bullets),
            "action_bullets": len(action_bullets),
            "quantified_bullets": len(quantified),
        },
        "recommendations": recommendations[:12],
    }
