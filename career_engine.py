"""EggyPDF Career Engine.

Deterministic ATS-style analysis utilities used by the Career Pro API.
The score measures common resume structure, parse-readiness, content quality,
and job-description alignment. It does not claim compatibility with a specific
ATS vendor and it cannot judge visual design from extracted PDF text alone.
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
    "negotiated", "executed", "coordinated", "produced", "decreased", "supported", "maintained",
}

SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "profile", "professional profile", "objective", "career objective"},
    "experience": {"experience", "work experience", "work history", "employment", "professional experience"},
    "education": {"education", "academic", "academic background", "qualifications"},
    "skills": {"skills", "technical skills", "core competencies", "competencies", "key skills"},
}

DEGREE_TERMS = {
    "bachelor", "master", "mba", "bsc", "msc", "ba", "ma", "phd", "diploma", "degree",
    "university", "college", "school", "certification", "certificate",
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


def _clean_heading(line: str) -> str:
    line = re.sub(r"[^A-Za-z ]+", " ", line or "")
    return normalize(line)


def _heading_map(lines: List[str]) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for i, line in enumerate(lines):
        heading = _clean_heading(line)
        if not heading or len(heading.split()) > 4:
            continue
        for section, aliases in SECTION_ALIASES.items():
            if heading in aliases and section not in found:
                found[section] = i
    return found


def section_signals(text: str) -> Dict[str, bool]:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    headings = _heading_map(lines)
    return {section: section in headings for section in SECTION_ALIASES}


def _section_body(lines: List[str], headings: Dict[str, int], section: str) -> List[str]:
    if section not in headings:
        return []
    start = headings[section] + 1
    later = [idx for idx in headings.values() if idx > headings[section]]
    end = min(later) if later else len(lines)
    return lines[start:end]


def _points_for_ratio(count: int, total: int, weight: int, min_full_count: int = 2) -> int:
    if total <= 0 or count <= 0:
        return 0
    ratio = count / total
    count_factor = min(1.0, count / max(1, min_full_count))
    quality = min(1.0, ratio / 0.6)
    return round(weight * min(count_factor, quality))


def _genuine_metric_bullet(line: str) -> bool:
    # Require a real measurable signal. Bare years such as 2024 do not count.
    metric_patterns = [
        r"\b\d+(?:\.\d+)?\s*%\b?",
        r"(?:[$€£]|aed\s*|usd\s*|sar\s*|qar\s*)\d[\d,.]*",
        r"\b\d+(?:\.\d+)?\s*(?:k|m|million|billion|hours?|days?|weeks?|months?|people|employees|clients?|customers?|projects?|tickets?|leads?|sales|orders|users)\b",
        r"\b(?:increased|reduced|grew|improved|saved|generated|managed|served|supported)\b[^\n]{0,45}\b\d+(?!\s*(?:-|–|to)\s*\d{2,4}\b)",
    ]
    lower = line.lower()
    return any(re.search(p, lower, re.I) for p in metric_patterns)


def _content_depth_score(word_count: int) -> int:
    if word_count >= 180:
        return 12
    if word_count >= 120:
        return 10
    if word_count >= 80:
        return 8
    if word_count >= 50:
        return 6
    if word_count >= 30:
        return 3
    return 0


def _parse_quality(lines: List[str], word_count: int) -> Tuple[int, Dict]:
    if not lines or word_count < 20:
        return 0, {"short_line_ratio": 1.0, "very_long_lines": 0, "quality": "poor"}
    short = sum(1 for x in lines if len(tokenize(x)) <= 1)
    very_long = sum(1 for x in lines if len(x) > 220)
    short_ratio = short / len(lines)
    score = 5
    if short_ratio > 0.45:
        score -= 2
    elif short_ratio > 0.30:
        score -= 1
    if very_long >= 3:
        score -= 2
    elif very_long:
        score -= 1
    score = max(0, score)
    quality = "good" if score >= 4 else "mixed" if score >= 2 else "poor"
    return score, {"short_line_ratio": round(short_ratio, 2), "very_long_lines": very_long, "quality": quality}


def analyze_resume(resume_text: str, job_text: str = "") -> Dict:
    resume_text = resume_text or ""
    job_text = job_text or ""
    lines = [x.strip() for x in resume_text.splitlines() if x.strip()]
    headings = _heading_map(lines)
    sections = {section: section in headings for section in SECTION_ALIASES}
    contacts = contact_signals(resume_text)
    skills = extract_skills(resume_text)
    matched, missing, keyword_score = keyword_overlap(resume_text, job_text) if job_text.strip() else ([], [], 0)

    bullets = [x for x in lines if re.match(r"^[•●▪◦*\-]\s+", x)]
    action_bullets = [x for x in bullets if any(re.search(r"\b" + re.escape(v) + r"\b", x.lower()) for v in ACTION_VERBS)]
    quantified = [x for x in bullets if _genuine_metric_bullet(x)]
    word_count = len(tokenize(resume_text))

    summary_body = _section_body(lines, headings, "summary")
    experience_body = _section_body(lines, headings, "experience")
    education_body = _section_body(lines, headings, "education")
    summary_words = len(tokenize(" ".join(summary_body)))
    experience_words = len(tokenize(" ".join(experience_body)))
    education_text = normalize(" ".join(education_body))
    date_ranges = re.findall(r"\b(?:19|20)\d{2}\b\s*(?:-|–|to)\s*(?:present|current|(?:19|20)\d{2})", resume_text, re.I)

    checks = []
    def add_check(name: str, points: int, weight: int, detail: str):
        points = max(0, min(weight, int(points)))
        checks.append({"name": name, "passed": points >= max(1, round(weight * 0.7)), "detail": detail, "weight": weight, "points": points})

    contact_points = (4 if contacts["email"] else 0) + (4 if contacts["phone"] else 0) + (2 if contacts["linkedin"] else 0)
    add_check("Contact information", contact_points, 10, "Include a valid email and phone number; LinkedIn is recommended.")

    summary_points = 0
    if sections["summary"]:
        summary_points += 3
        if summary_words >= 20:
            summary_points += 5
        elif summary_words >= 10:
            summary_points += 3
        elif summary_words >= 5:
            summary_points += 1
    add_check("Professional summary", summary_points, 8, "Use a real summary section with 2–4 concise, role-relevant lines.")

    experience_points = 0
    if sections["experience"]:
        experience_points += 5
        if experience_words >= 35:
            experience_points += 4
        elif experience_words >= 15:
            experience_points += 2
        if len(date_ranges) >= 1:
            experience_points += 2
        if len(bullets) >= 3:
            experience_points += 4
        elif len(bullets) >= 1:
            experience_points += 2
    add_check("Work experience", experience_points, 15, "Use a clear experience section with roles, dates, and several outcome-focused bullets.")

    education_points = 0
    if sections["education"]:
        education_points += 3
        if any(term in education_text for term in DEGREE_TERMS):
            education_points += 4
        elif len(tokenize(education_text)) >= 4:
            education_points += 2
    add_check("Education", education_points, 7, "Include a clear education/training section with the qualification or institution.")

    skills_points = 0
    if sections["skills"]:
        skills_points += 3
    skills_points += min(5, len(skills))
    add_check("Skills", skills_points, 8, "Use a dedicated skills section and include several genuine, role-relevant skills.")

    action_points = _points_for_ratio(len(action_bullets), len(bullets), 10, min_full_count=3)
    add_check("Action-oriented bullets", action_points, 10, "Use at least 3 bullets and start most of them with strong action verbs.")

    quantified_points = _points_for_ratio(len(quantified), len(bullets), 10, min_full_count=2)
    add_check("Quantified achievements", quantified_points, 10, "Add genuine measurable outcomes; dates alone do not count as achievements.")

    keyword_points = round(15 * (keyword_score / 100)) if job_text.strip() else 0
    add_check("Job keyword alignment", keyword_points, 15, "Match relevant terminology from the target job description naturally and truthfully.")

    depth_points = _content_depth_score(word_count)
    add_check("Resume completeness", depth_points, 12, "Add enough evidence and detail for an employer to understand your background; very sparse resumes score lower.")

    parse_points, parse_detail = _parse_quality(lines, word_count)
    add_check("ATS parse/readability", parse_points, 5, "Keep text clean and readable after extraction; fragmented or extremely long lines can indicate ATS parsing problems.")

    score = round(sum(c["points"] for c in checks))
    recommendations = [c["detail"] for c in checks if not c["passed"]]
    if job_text.strip() and missing:
        recommendations.insert(0, "Consider adding genuinely relevant missing keywords: " + ", ".join(missing[:10]) + ".")

    if score >= 85:
        label = "Strong"
    elif score >= 70:
        label = "Good foundation"
    elif score >= 55:
        label = "Needs improvement"
    else:
        label = "Needs significant work"

    return {
        "score": score,
        "score_label": label,
        "checks": checks,
        "contact_analysis": contacts,
        "keyword_analysis": {"matched": matched[:30], "missing": missing[:20], "match_percentage": keyword_score},
        "skills_detected": skills,
        "bullet_analysis": {"total_bullets": len(bullets), "action_bullets": len(action_bullets), "quantified_bullets": len(quantified)},
        "format_analysis": {"word_count": word_count, "section_headings_detected": sorted(headings.keys()), "parse_quality": parse_detail, "note": "This score evaluates extracted text structure and ATS readability, not visual design or typography."},
        "recommendations": recommendations[:12],
    }
