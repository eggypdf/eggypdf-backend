"""EggyPDF Career Engine.

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
    "hiring", "hire", "seeking", "looking", "candidate", "candidates", "required", "requirement",
    "requirements", "preferred", "responsibilities", "responsibility", "position", "opportunity",
    "ideal", "must", "join", "apply", "application",
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
    "negotiated", "executed", "coordinated", "produced", "decreased",
}

DEGREE_TERMS = {
    "bachelor", "master", "mba", "bba", "bsc", "msc", "phd", "diploma", "certificate",
    "certification", "university", "college", "school", "degree",
}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z][a-z0-9+#]*(?:\.[a-z0-9+#]+)?", normalize(text))


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
    resume_tokens = set(tokenize(resume))
    job_keywords = extract_keywords(job, 40)
    matched = [k for k in job_keywords if k in resume_tokens]
    missing = [k for k in job_keywords if k not in resume_tokens]
    score = round((len(matched) / len(job_keywords)) * 100) if job_keywords else 0
    return matched, missing, score


def contact_signals(text: str) -> Dict[str, bool]:
    return {
        "email": bool(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)),
        "phone": bool(re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)),
        "linkedin": bool(re.search(r"(?:linkedin\.com/in/|\blinkedin\b)", text, re.I)),
    }


def section_signals(text: str) -> Dict[str, bool]:
    n = normalize(text)
    aliases = {
        "summary": ["summary", "professional summary", "profile", "objective"],
        "experience": ["experience", "work history", "employment"],
        "education": ["education", "academic"],
        "skills": ["skills", "technical skills", "core competencies"],
    }
    return {section: any(a in n for a in terms) for section, terms in aliases.items()}


def _section_body_word_count(text: str, heading_terms: List[str]) -> int:
    lines = [x.strip() for x in text.splitlines()]
    for i, line in enumerate(lines):
        n = normalize(line)
        if any(n == term or n.startswith(term + ":") for term in heading_terms):
            body = []
            for candidate in lines[i + 1:i + 6]:
                if re.fullmatch(r"[A-Z][A-Z /&-]{2,}", candidate or ""):
                    break
                body.append(candidate)
            return len(tokenize(" ".join(body)))
    return 0


def analyze_resume(resume_text: str, job_text: str = "") -> Dict:
    resume_text = resume_text or ""
    job_text = job_text or ""
    sections = section_signals(resume_text)
    contacts = contact_signals(resume_text)
    skills = extract_skills(resume_text)
    matched, missing, keyword_score = keyword_overlap(resume_text, job_text) if job_text.strip() else ([], [], 0)

    lines = [x.strip() for x in resume_text.splitlines() if x.strip()]
    bullets = [x for x in lines if re.match(r"^[•●▪◦*-]\s+", x)]
    action_bullets = [x for x in bullets if any(re.search(r"\b" + re.escape(v) + r"\b", x.lower()) for v in ACTION_VERBS)]
    quantified = [x for x in bullets if re.search(r"(?:\b\d+(?:\.\d+)?\s*(?:%|k|m|million|billion|hours|days|people|clients|customers|projects|sales|users)\b|[$€£]\s?\d+)", x.lower())]

    words = tokenize(resume_text)
    word_count = len(words)
    heading_count = sum(1 for present in sections.values() if present)
    date_signals = len(re.findall(r"\b(?:19|20)\d{2}\b", resume_text))
    long_lines = [x for x in lines if len(x) > 180]
    summary_words = _section_body_word_count(resume_text, ["summary", "professional summary", "profile", "objective"])
    degree_signal = any(term in normalize(resume_text) for term in DEGREE_TERMS)

    checks = []

    def add_check(name: str, points: float, weight: int, detail: str):
        points = max(0.0, min(float(weight), float(points)))
        passed = points >= weight * 0.7
        checks.append({
            "name": name,
            "passed": passed,
            "detail": detail,
            "weight": weight,
            "points": round(points, 1),
        })

    contact_points = (5 if contacts["email"] else 0) + (5 if contacts["phone"] else 0)
    add_check("Contact information", contact_points, 10, "Include a valid email address and phone number. LinkedIn is recommended.")

    summary_points = (3 if sections["summary"] else 0) + (7 if 20 <= summary_words <= 100 else 3 if 10 <= summary_words < 20 else 0)
    add_check("Professional summary", summary_points, 10, "Use a clear summary of roughly 20–100 words focused on the target role and your strongest evidence.")

    experience_points = 0
    if sections["experience"]:
        experience_points += 4
    if date_signals >= 2:
        experience_points += 4
    if len(bullets) >= 2:
        experience_points += 5
    if len(action_bullets) >= 1:
        experience_points += 5
    add_check("Work experience", experience_points, 18, "Use a clear experience section with dates and at least 2 achievement-focused bullets.")

    education_points = (4 if sections["education"] else 0) + (4 if degree_signal or date_signals >= 1 else 0)
    add_check("Education / training", education_points, 8, "Include education, training, or relevant certifications with enough detail to verify them.")

    skills_points = (3 if sections["skills"] else 0) + min(5, len(skills) * 1.25)
    add_check("Skills section", skills_points, 8, "Use a dedicated skills section with several role-relevant skills rather than a vague list.")

    action_ratio = (len(action_bullets) / len(bullets)) if bullets else 0
    add_check("Action-oriented bullets", 12 * action_ratio, 12, "Most experience bullets should start with strong action language and describe what you actually did.")

    quantified_ratio = (len(quantified) / len(bullets)) if bullets else 0
    add_check("Quantified achievements", min(12, quantified_ratio * 24), 12, "Quantify meaningful outcomes where you have real numbers: %, revenue, time, volume, customers, projects, or team size.")

    keyword_points = (15 * keyword_score / 100) if job_text.strip() else 7.5
    add_check("Job keyword alignment", keyword_points, 15, "Use genuinely relevant terminology from the target job description; do not keyword-stuff or claim skills you do not have.")

    structure_points = 0
    if 200 <= word_count <= 1200:
        structure_points += 3
    elif 120 <= word_count < 200 or 1200 < word_count <= 1500:
        structure_points += 1.5
    if heading_count >= 3:
        structure_points += 2
    elif heading_count == 2:
        structure_points += 1
    if not long_lines:
        structure_points += 2
    elif len(long_lines) <= 2:
        structure_points += 1
    add_check("Structure & readability", structure_points, 7, "Keep the resume concise, clearly sectioned, and readable. Very short, very long, or dense unstructured resumes score lower.")

    score = round(sum(c["points"] for c in checks))
    score = max(0, min(100, score))
    recommendations = [c["detail"] for c in checks if not c["passed"]]
    if job_text.strip() and missing:
        recommendations.insert(0, "Consider adding genuinely relevant missing keywords: " + ", ".join(missing[:10]) + ".")

    return {
        "score": score,
        "score_label": "Strong" if score >= 80 else "Needs improvement" if score >= 60 else "Needs work",
        "checks": checks,
        "contact_analysis": contacts,
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
        "format_analysis": {
            "word_count": word_count,
            "section_count": heading_count,
            "date_signals": date_signals,
            "long_line_count": len(long_lines),
            "visual_layout_checked": False,
            "note": "EggyPDF evaluates text structure and ATS-readiness signals. It cannot fully judge visual design, columns, fonts, spacing, or graphics from extracted PDF text alone.",
        },
        "recommendations": recommendations[:12],
    }
