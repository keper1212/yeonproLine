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
    "https://generativelanguage.googleapis.com/v1/"
    "models/gemini-2.5-flash:generateContent"
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


def crawl_posts(pages: int, max_posts: int) -> List[str]:
    posts: List[str] = []
    for base in LIST_URLS:
        print(f"[crawl] list base: {base}")
        for page in range(1, pages + 1):
            page_url = f"{base}&page={page}"
            print(f"[crawl] list page: {page_url}")
            html = _http_get(page_url)
            if not html:
                print(f"[crawl] list fetch failed: {page_url}")
                continue
            links = _parse_list_page(html, base)
            for link in links:
                if len(posts) >= max_posts:
                    print(f"[crawl] reached max_posts={max_posts}, stop crawling")
                    return posts
                detail = _http_get(link)
                if not detail:
                    print(f"[crawl] post fetch failed: {link}")
                    continue
                content = _parse_post(detail)
                if content:
                    print(f"[crawl] fetched post: {link}")
                    posts.append(content)
                else:
                    print(f"[crawl] post parse failed: {link}")
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
        text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text_out.startswith("```"):
            text_out = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text_out).strip()
        parsed = json.loads(text_out)
        return int(parsed["sentiment"])
    except Exception as exc:
        status = getattr(locals().get("res", None), "status_code", None)
        body = getattr(locals().get("res", None), "text", None)
        print(
            f"[gemini] classify failed target={target_label} "
            f"status={status} error={exc}"
        )
        if body:
            print(f"[gemini] classify response: {body[:500]}")
        return None


def gemini_batch_classify(api_key: str, items: List[Dict]) -> Optional[Dict]:
    prompt = (
        "You are a Korean sentiment classifier.\n"
        "For each post, evaluate sentiment toward each target label provided.\n"
        "Sentiment values must be one of: -1 (negative), 0 (neutral), 1 (positive).\n"
        "Return ONLY JSON in this exact schema:\n"
        "{\"results\": [{\"post_id\": 1, \"targets\": [{\"label\": \"A♥B\", \"sentiment\": -1}]}]}\n"
        "Rules:\n"
        "- Include every target label listed for each post.\n"
        "- Do not add extra fields or text.\n"
        "Posts:\n"
    )
    for item in items:
        targets = [t["label"] for t in item["targets"]]
        prompt += (
            f"post_id: {item['post_id']}\n"
            f"targets: {targets}\n"
            f"text:\n{item['text']}\n---\n"
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
            timeout=60,
        )
        res.raise_for_status()
        data = res.json()
        text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text_out.startswith("```"):
            text_out = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text_out).strip()
        return json.loads(text_out)
    except Exception as exc:
        status = getattr(locals().get("res", None), "status_code", None)
        body = getattr(locals().get("res", None), "text", None)
        print(f"[gemini] batch classify failed status={status} error={exc}")
        if body:
            print(f"[gemini] batch classify response: {body[:500]}")
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
    except Exception as exc:
        status = getattr(locals().get("res", None), "status_code", None)
        body = getattr(locals().get("res", None), "text", None)
        print(
            f"[gemini] summary failed target={target_label} "
            f"status={status} error={exc}"
        )
        if body:
            print(f"[gemini] summary response: {body[:500]}")
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


def _name_variants(name: str) -> List[str]:
    variants = []
    if not name:
        return variants
    name = name.strip()
    if not name:
        return variants
    variants.append(name)
    if " " in name:
        last_token = name.split()[-1].strip()
        if len(last_token) >= 2:
            variants.append(last_token)
    if len(name) >= 3:
        given = name[1:]
        if len(given) >= 2:
            variants.append(given)
    return list(dict.fromkeys(variants))


def detect_mentions(text: str, participants: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    females = []
    males = []
    for p in participants:
        for variant in _name_variants(p["name"]):
            if variant in text:
                if p["gender"] == "female":
                    females.append(p)
                elif p["gender"] == "male":
                    males.append(p)
                break
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
    parser.add_argument("--max-posts", type=int, default=20)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY 환경변수를 설정하세요.")

    participants = load_participants()
    print(f"[run] participants loaded: {len(participants)}")
    posts = crawl_posts(args.pages, args.max_posts)
    print(f"[run] posts collected: {len(posts)}")

    pair_scores: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    single_scores: Dict[int, List[int]] = defaultdict(list)
    pair_texts: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    single_texts: Dict[int, List[str]] = defaultdict(list)

    classify_attempts = 0
    classify_failures = 0
    matched_posts = 0
    items: List[Dict] = []

    for idx, text_content in enumerate(posts, start=1):
        females, males = detect_mentions(text_content, participants)
        targets: List[Dict] = []
        if females and males:
            for f in females:
                for m in males:
                    targets.append(
                        {
                            "type": "pair",
                            "female_id": f["id"],
                            "male_id": m["id"],
                            "label": f"{f['name']}♥{m['name']}",
                        }
                    )
        else:
            targets = [
                {
                    "type": "single",
                    "target_id": t["id"],
                    "label": t["name"],
                }
                for t in (females or males)
            ]

        if targets:
            matched_posts += 1
            classify_attempts += len(targets)
            items.append(
                {
                    "post_id": idx,
                    "text": text_content,
                    "targets": targets,
                }
            )

    print(f"[run] matched posts: {matched_posts}")
    print(f"[run] classify attempts: {classify_attempts}")

    results_map: Dict[int, Dict[str, int]] = {}
    if items:
        batch_size = 10
        for start in range(0, len(items), batch_size):
            batch = items[start:start + batch_size]
            print(
                f"[run] classify batch {start // batch_size + 1} "
                f"size={len(batch)}"
            )
            results = gemini_batch_classify(api_key, batch)
            if not results or not isinstance(results, dict):
                classify_failures += sum(len(i["targets"]) for i in batch)
                continue
            for entry in results.get("results", []):
                post_id = entry.get("post_id")
                targets = entry.get("targets", [])
                if post_id is None:
                    continue
                results_map[int(post_id)] = {
                    t.get("label"): int(t.get("sentiment"))
                    for t in targets
                    if isinstance(t, dict) and "label" in t and "sentiment" in t
                }

    for item in items:
        post_id = item["post_id"]
        sentiments = results_map.get(post_id, {})
        for target in item["targets"]:
            label = target["label"]
            sentiment = sentiments.get(label)
            if sentiment not in (-1, 0, 1):
                classify_failures += 1
                continue
            if target["type"] == "pair":
                key = (target["female_id"], target["male_id"])
                pair_scores[key].append(sentiment)
                pair_texts[key].append(item["text"])
            else:
                key = target["target_id"]
                single_scores[key].append(sentiment)
                single_texts[key].append(item["text"])

    print(f"[run] classify failures: {classify_failures}")

    db = SessionLocal()
    try:
        episode_id = current_episode_id(db)
        print(f"[db] current episode id: {episode_id}")
        snapshot_inserts = 0
        event_inserts = 0
        summary_inserts = 0

        for (female_id, male_id), scores in pair_scores.items():
            positives = sum(1 for s in scores if s > 0)
            negatives = sum(1 for s in scores if s < 0)
            total = positives + negatives
            support_rate = int(round((positives / total) * 100)) if total else 0
            last_rate = fetch_last_snapshot(db, female_id, male_id, None)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(db, episode_id, female_id, male_id, None, support_rate, delta_5m)
            snapshot_inserts += 1
            if abs(delta_5m) >= args.event_threshold:
                insert_event(db, episode_id, female_id, male_id, None, delta_5m)
                event_inserts += 1

            summary = gemini_summary(api_key, f"{female_id}-{male_id}", pair_texts[(female_id, male_id)])
            if summary:
                insert_summary(db, episode_id, female_id, male_id, None, summary)
                summary_inserts += 1

        for target_id, scores in single_scores.items():
            positives = sum(1 for s in scores if s > 0)
            negatives = sum(1 for s in scores if s < 0)
            total = positives + negatives
            support_rate = int(round((positives / total) * 100)) if total else 0
            last_rate = fetch_last_snapshot(db, None, None, target_id)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(db, episode_id, None, None, target_id, support_rate, delta_5m)
            snapshot_inserts += 1
            if abs(delta_5m) >= args.event_threshold:
                insert_event(db, episode_id, None, None, target_id, delta_5m)
                event_inserts += 1

            summary = gemini_summary(api_key, f"participant-{target_id}", single_texts[target_id])
            if summary:
                insert_summary(db, episode_id, None, None, target_id, summary)
                summary_inserts += 1

        db.commit()
        print(
            f"[db] commit ok: snapshots={snapshot_inserts}, "
            f"events={event_inserts}, summaries={summary_inserts}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
