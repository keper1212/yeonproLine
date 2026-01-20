#!/usr/bin/env python3
import argparse
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from app.db.session import SessionLocal

LIST_URLS = [
    "https://gall.dcinside.com/mgallery/board/lists/?id=transferlove4",
    "https://gall.dcinside.com/mini/board/lists/?id=hslove",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-1.5-flash:generateContent"
)


def _http_get(url: str) -> Optional[str]:
    try:
        res = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        res.raise_for_status()
        return res.text
    except requests.RequestException:
        return None


def _parse_list_page(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.gall_list tbody tr")
    links: List[str] = []
    for row in rows:
        if "ub-content" not in row.get("class", []):
            continue
        title_anchor = row.select_one("td.gall_tit a")
        if not title_anchor:
            continue
        href = title_anchor.get("href", "")
        if not href or href.startswith("javascript"):
            continue
        links.append(urljoin(base_url, href))
    return links


def _parse_post(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".title_subject") or soup.select_one("h3.title")
    body = soup.select_one(".write_div")
    if not title or not body:
        return None
    title_text = title.get_text(" ", strip=True)
    body_text = body.get_text(" ", strip=True)
    if not title_text and not body_text:
        return None
    return f"{title_text}\n{body_text}"


def crawl_posts(pages: int) -> List[str]:
    posts: List[str] = []
    for base in LIST_URLS:
        for page in range(1, pages + 1):
            page_url = f"{base}&page={page}"
            html = _http_get(page_url)
            if not html:
                continue
            links = _parse_list_page(html, base)
            for link in links:
                detail = _http_get(link)
                if not detail:
                    continue
                content = _parse_post(detail)
                if content:
                    posts.append(content)
                time.sleep(2.0)
    return posts


def gemini_classify(api_key: str, target_label: str, text: str) -> Optional[int]:
    prompt = (
        "You are a Korean sentiment classifier.\n"
        f"Target: {target_label}\n"
        "Classify the sentiment toward the target as one of:\n"
        "-1 (negative), 0 (neutral), 1 (positive)\n"
        "Return ONLY JSON like: {\"sentiment\": -1}\n"
        "Text:\n"
        f"{text}\n"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    try:
        res = requests.post(
            f"{GEMINI_ENDPOINT}?key={api_key}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text_out.strip())
        return int(parsed["sentiment"])
    except Exception:
        return None


def gemini_summary(api_key: str, target_label: str, texts: List[str]) -> Optional[str]:
    joined = "\n\n".join(texts[:20])
    prompt = (
        "You are a Korean social sentiment summarizer.\n"
        f"Target: {target_label}\n"
        "Summarize the community sentiment in 2-3 sentences.\n"
        "Return plain Korean text only.\n"
        "Texts:\n"
        f"{joined}\n"
    )
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ]
    }
    try:
        res = requests.post(
            f"{GEMINI_ENDPOINT}?key={api_key}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


def load_participants() -> List[Dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT id, name, gender FROM participants")
        ).fetchall()
        return [{"id": r.id, "name": r.name, "gender": r.gender} for r in rows]
    finally:
        db.close()


def detect_mentions(text: str, participants: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    females = []
    males = []
    for p in participants:
        if p["name"] and p["name"] in text:
            if p["gender"] == "female":
                females.append(p)
            elif p["gender"] == "male":
                males.append(p)
    return females, males


def current_episode_id(db) -> Optional[int]:
    now = datetime.now()
    row = db.execute(
        text(
            "SELECT id FROM episodes "
            "WHERE start_time <= :now "
            "ORDER BY start_time DESC LIMIT 1"
        ),
        {"now": now},
    ).fetchone()
    return row.id if row else None


def fetch_last_snapshot(db, female_id, male_id, target_id) -> Optional[int]:
    row = db.execute(
        text(
            "SELECT support_rate FROM sentiment_snapshots "
            "WHERE female_id IS NOT DISTINCT FROM :female_id "
            "AND male_id IS NOT DISTINCT FROM :male_id "
            "AND target_participant_id IS NOT DISTINCT FROM :target_id "
            "ORDER BY captured_at DESC LIMIT 1"
        ),
        {
            "female_id": female_id,
            "male_id": male_id,
            "target_id": target_id,
        },
    ).fetchone()
    return row.support_rate if row else None


def insert_snapshot(db, episode_id, female_id, male_id, target_id, support_rate, delta_5m):
    db.execute(
        text(
            "INSERT INTO sentiment_snapshots "
            "(episode_id, female_id, male_id, target_participant_id, support_rate, delta_5m, captured_at) "
            "VALUES (:episode_id, :female_id, :male_id, :target_id, :support_rate, :delta_5m, :captured_at)"
        ),
        {
            "episode_id": episode_id,
            "female_id": female_id,
            "male_id": male_id,
            "target_id": target_id,
            "support_rate": support_rate,
            "delta_5m": delta_5m,
            "captured_at": datetime.now(),
        },
    )


def insert_event(db, episode_id, female_id, male_id, target_id, delta):
    event_type = "up" if delta > 0 else "down" if delta < 0 else "stable"
    end_at = datetime.now()
    start_at = end_at - timedelta(minutes=5)
    db.execute(
        text(
            "INSERT INTO sentiment_events "
            "(episode_id, female_id, male_id, target_participant_id, event_type, delta, start_at, end_at) "
            "VALUES (:episode_id, :female_id, :male_id, :target_id, :event_type, :delta, :start_at, :end_at)"
        ),
        {
            "episode_id": episode_id,
            "female_id": female_id,
            "male_id": male_id,
            "target_id": target_id,
            "event_type": event_type,
            "delta": delta,
            "start_at": start_at,
            "end_at": end_at,
        },
    )


def insert_summary(db, episode_id, female_id, male_id, target_id, summary_text):
    db.execute(
        text(
            "INSERT INTO sentiment_summaries "
            "(episode_id, female_id, male_id, target_participant_id, summary_text, generated_at) "
            "VALUES (:episode_id, :female_id, :male_id, :target_id, :summary_text, :generated_at)"
        ),
        {
            "episode_id": episode_id,
            "female_id": female_id,
            "male_id": male_id,
            "target_id": target_id,
            "summary_text": summary_text,
            "generated_at": datetime.now(),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--event-threshold", type=int, default=5)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY 환경변수를 설정하세요.")

    participants = load_participants()
    posts = crawl_posts(args.pages)

    pair_scores: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    single_scores: Dict[int, List[int]] = defaultdict(list)
    pair_texts: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    single_texts: Dict[int, List[str]] = defaultdict(list)

    for text_content in posts:
        females, males = detect_mentions(text_content, participants)
        if females and males:
            for f in females:
                for m in males:
                    label = f"{f['name']}♥{m['name']}"
                    sentiment = gemini_classify(api_key, label, text_content)
                    if sentiment is None:
                        continue
                    pair_scores[(f["id"], m["id"])].append(sentiment)
                    pair_texts[(f["id"], m["id"])].append(text_content)
        else:
            targets = females or males
            for t in targets:
                sentiment = gemini_classify(api_key, t["name"], text_content)
                if sentiment is None:
                    continue
                single_scores[t["id"]].append(sentiment)
                single_texts[t["id"]].append(text_content)

    db = SessionLocal()
    try:
        episode_id = current_episode_id(db)

        for (female_id, male_id), scores in pair_scores.items():
            positives = sum(1 for s in scores if s > 0)
            negatives = sum(1 for s in scores if s < 0)
            total = positives + negatives
            support_rate = int(round((positives / total) * 100)) if total else 0
            last_rate = fetch_last_snapshot(db, female_id, male_id, None)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(db, episode_id, female_id, male_id, None, support_rate, delta_5m)
            if abs(delta_5m) >= args.event_threshold:
                insert_event(db, episode_id, female_id, male_id, None, delta_5m)

            summary = gemini_summary(api_key, f"{female_id}-{male_id}", pair_texts[(female_id, male_id)])
            if summary:
                insert_summary(db, episode_id, female_id, male_id, None, summary)

        for target_id, scores in single_scores.items():
            positives = sum(1 for s in scores if s > 0)
            negatives = sum(1 for s in scores if s < 0)
            total = positives + negatives
            support_rate = int(round((positives / total) * 100)) if total else 0
            last_rate = fetch_last_snapshot(db, None, None, target_id)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(db, episode_id, None, None, target_id, support_rate, delta_5m)
            if abs(delta_5m) >= args.event_threshold:
                insert_event(db, episode_id, None, None, target_id, delta_5m)

            summary = gemini_summary(api_key, f"participant-{target_id}", single_texts[target_id])
            if summary:
                insert_summary(db, episode_id, None, None, target_id, summary)

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
