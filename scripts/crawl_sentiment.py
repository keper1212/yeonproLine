#!/usr/bin/env python3
import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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


def _parse_post_datetime(text_value: str) -> Optional[datetime]:
    if not text_value:
        return None
    match = re.search(r"(\\d{2,4})\\.(\\d{2})\\.(\\d{2})\\s+(\\d{2}):(\\d{2})", text_value)
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    month = int(match.group(2))
    day = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _parse_post(html: str) -> Optional[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".title_subject") or soup.select_one("h3.title")
    body = soup.select_one(".write_div")
    date_node = (
        soup.select_one(".gall_date")
        or soup.select_one("span.gall_date")
        or soup.select_one(".date")
    )
    if not title or not body:
        return None
    title_text = title.get_text(" ", strip=True)
    body_text = body.get_text(" ", strip=True)
    if not title_text and not body_text:
        return None
    created_at = _parse_post_datetime(date_node.get_text(strip=True)) if date_node else None
    return {"text": f"{title_text}\n{body_text}", "created_at": created_at}


def crawl_posts(base_url: str, start_page: int, page_count: int, max_posts: int) -> List[Dict]:
    posts: List[Dict] = []
    print(f"[crawl] list base: {base_url}")
    for page in range(start_page, max(start_page - page_count, 0), -1):
        page_url = f"{base_url}&page={page}"
        print(f"[crawl] list page: {page_url}")
        html = _http_get(page_url)
        if not html:
            print(f"[crawl] list fetch failed: {page_url}")
            continue
        links = _parse_list_page(html, base_url)
        for link in links:
            if len(posts) >= max_posts:
                print(f"[crawl] reached max_posts={max_posts}, stop crawling")
                return posts
            detail = _http_get(link)
            if not detail:
                print(f"[crawl] post fetch failed: {link}")
                continue
            parsed = _parse_post(detail)
            if parsed and parsed.get("text"):
                print(f"[crawl] fetched post: {link}")
                posts.append(parsed)
            else:
                print(f"[crawl] post parse failed: {link}")
            time.sleep(1.5)
    return posts


def page_sequence(start_page: int, page_count: int) -> List[int]:
    pages: List[int] = []
    current = start_page
    for _ in range(page_count):
        if current <= 0:
            break
        pages.append(current)
        current -= 2
    return pages


def gemini_analyze_all_targets_hourly(
    api_key: str,
    target_data_map: Dict[str, Dict],
    prior_summaries: Optional[Dict[str, str]] = None,
) -> Optional[Dict]:
    prompt = (
        "다음은 특정 페이지 범위에서 수집된 커뮤니티 글입니다.\n"
        "대상별 텍스트 묶음을 읽고, 각 대상에 대한 대중의 호감도를 0~100 사이 숫자로 평가하세요.\n"
        "점수는 언급 빈도, 긍/부정 뉘앙스, 비판/옹호 강도를 종합적으로 반영해야 합니다.\n"
        "이전에 생성된 요약이 제공되면, 새 텍스트와 함께 통합된 최종 요약(1~2문장)을 작성하세요.\n"
        "새 텍스트가 없더라도 이전 요약을 기반으로 자연스럽게 유지 요약을 작성하세요.\n"
        "반드시 아래 JSON 형식만 반환하세요.\n"
        "{\n"
        "  \"results\": [\n"
        "    {\"label\": \"지우♥민수\", \"score\": 78, \"summary\": \"...\"}\n"
        "  ]\n"
        "}\n"
        "대상별 텍스트:\n"
    )
    prior_summaries = prior_summaries or {}
    for label, data in target_data_map.items():
        joined = "\n\n".join(data["texts"]) if data.get("texts") else ""
        prior = prior_summaries.get(label)
        prompt += f"[{label}]\n"
        if prior:
            prompt += f"이전 요약: {prior}\n"
        prompt += "새 텍스트:\n"
        prompt += f"{joined if joined else '(없음)'}\n---\n"

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
            timeout=240,
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
        print(f"[gemini] hourly analysis failed status={status} error={exc}")
        if body:
            print(f"[gemini] hourly analysis response: {body[:500]}")
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


def episode_capture_time(db, episode_id: Optional[int]) -> datetime:
    if not episode_id:
        return datetime.now()
    row = db.execute(
        text("SELECT start_time FROM episodes WHERE id = :episode_id"),
        {"episode_id": episode_id},
    ).fetchone()
    if not row:
        return datetime.now()
    start_time = row.start_time
    return datetime(
        start_time.year,
        start_time.month,
        start_time.day,
        16,
        0,
        0,
    )


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


def insert_snapshot(
    db,
    episode_id,
    female_id,
    male_id,
    target_id,
    support_rate,
    delta_5m,
    captured_at,
):
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
            "captured_at": captured_at,
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


def insert_summaries_only(
    db,
    episode_id: Optional[int],
    label_meta: Dict[str, Dict],
    summaries: Dict[str, str],
) -> int:
    summary_inserts = 0
    for label, meta in label_meta.items():
        summary = summaries.get(label)
        if not isinstance(summary, str) or not summary.strip():
            continue
        if meta["type"] == "pair":
            insert_summary(
                db,
                episode_id,
                meta["female_id"],
                meta["male_id"],
                None,
                summary.strip(),
            )
        else:
            insert_summary(
                db,
                episode_id,
                None,
                None,
                meta["target_id"],
                summary.strip(),
            )
        summary_inserts += 1
    db.commit()
    return summary_inserts


def process_analysis(
    db,
    analysis: Optional[Dict],
    combined_label_meta: Dict[str, Dict],
    episode_id: Optional[int],
    capture_time: datetime,
    event_threshold: int,
    save_summary: bool,
    base_url: str,
) -> Tuple[Dict[str, str], Dict[str, Dict]]:
    if not analysis or not isinstance(analysis, dict):
        print(f"[run] gemini analysis failed or empty (base={base_url})")
        return {}, combined_label_meta

    results_list = analysis.get("results", [])
    results_map: Dict[str, Dict] = {}
    for item in results_list:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not label:
            continue
        results_map[label] = item

    snapshot_inserts = 0
    event_inserts = 0
    summary_inserts = 0

    for label, meta in combined_label_meta.items():
        result = results_map.get(label)
        if not result:
            continue
        score = result.get("score")
        if not isinstance(score, (int, float)):
            continue
        support_rate = max(0, min(100, int(round(score))))
        summary = result.get("summary")
        if meta["type"] == "pair":
            female_id = meta["female_id"]
            male_id = meta["male_id"]
            last_rate = fetch_last_snapshot(db, female_id, male_id, None)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(
                db,
                episode_id,
                female_id,
                male_id,
                None,
                support_rate,
                delta_5m,
                capture_time,
            )
            snapshot_inserts += 1
            if abs(delta_5m) >= event_threshold:
                insert_event(db, episode_id, female_id, male_id, None, delta_5m)
                event_inserts += 1
            if isinstance(summary, str) and summary.strip() and save_summary:
                insert_summary(db, episode_id, female_id, male_id, None, summary.strip())
                summary_inserts += 1
        else:
            target_id = meta["target_id"]
            last_rate = fetch_last_snapshot(db, None, None, target_id)
            delta_5m = support_rate - last_rate if last_rate is not None else 0
            insert_snapshot(
                db,
                episode_id,
                None,
                None,
                target_id,
                support_rate,
                delta_5m,
                capture_time,
            )
            snapshot_inserts += 1
            if abs(delta_5m) >= event_threshold:
                insert_event(db, episode_id, None, None, target_id, delta_5m)
                event_inserts += 1
            if isinstance(summary, str) and summary.strip() and save_summary:
                insert_summary(db, episode_id, None, None, target_id, summary.strip())
                summary_inserts += 1

    db.commit()
    print(
        f"[db] commit ok: snapshots={snapshot_inserts}, "
        f"events={event_inserts}, summaries={summary_inserts} "
        f"(base={base_url})"
    )

    next_prior_summaries = {
        label: item.get("summary")
        for label, item in results_map.items()
        if isinstance(item.get("summary"), str) and item.get("summary")
    }
    return next_prior_summaries, combined_label_meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pages",
        type=str,
        default="1",
        help="시작 페이지. 단일 값 또는 CSV 형식(예: 220,120).",
    )
    parser.add_argument(
        "--page-count",
        type=int,
        default=5,
        help="각 URL에서 시작 페이지부터 읽을 페이지 수.",
    )
    parser.add_argument("--event-threshold", type=int, default=5)
    parser.add_argument("--max-posts", type=int, default=200)
    parser.add_argument("--episode-id", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY 환경변수를 설정하세요.")

    participants = load_participants()
    print(f"[run] participants loaded: {len(participants)}")

    def parse_pages(value: str, url_count: int) -> List[int]:
        items = [v.strip() for v in value.split(",") if v.strip()]
        try:
            pages = [int(v) for v in items] if items else [1]
        except ValueError:
            raise SystemExit("--pages는 숫자 또는 CSV 숫자 형식이어야 합니다.")
        if len(pages) == 1:
            return pages * url_count
        if len(pages) != url_count:
            raise SystemExit(
                f"--pages 개수({len(pages)})가 URL 개수({url_count})와 일치해야 합니다."
            )
        return pages

    pages_list = parse_pages(args.pages, len(LIST_URLS))

    db = SessionLocal()
    try:
        episode_id = args.episode_id or current_episode_id(db)
        print(f"[db] current episode id: {episode_id}")
        prior_summaries: Dict[str, str] = {}
        prior_label_meta: Dict[str, Dict] = {}
        total_urls = len(LIST_URLS)

        capture_time = episode_capture_time(db, episode_id)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_future = None
            pending_context: Dict[str, object] = {}

            for url_idx, (base_url, start_page) in enumerate(zip(LIST_URLS, pages_list)):
                page_numbers = page_sequence(start_page, args.page_count)
                url_prior_summaries: Dict[str, str] = dict(prior_summaries)
                url_prior_label_meta: Dict[str, Dict] = dict(prior_label_meta)

                for page_idx, page_number in enumerate(page_numbers):
                    page_url = f"{base_url}&page={page_number}"
                    html = _http_get(page_url)
                    if not html:
                        print(f"[crawl] list fetch failed: {page_url}")
                        continue
                    print(f"[crawl] list page: {page_url}")
                    links = _parse_list_page(html, base_url)
                    posts: List[Dict] = []
                    for link in links:
                        if len(posts) >= args.max_posts:
                            print(f"[crawl] reached max_posts={args.max_posts}, stop crawling")
                            break
                        detail = _http_get(link)
                        if not detail:
                            print(f"[crawl] post fetch failed: {link}")
                            continue
                        parsed = _parse_post(detail)
                        if parsed and parsed.get("text"):
                            print(f"[crawl] fetched post: {link}")
                            posts.append(parsed)
                        else:
                            print(f"[crawl] post parse failed: {link}")
                        time.sleep(2.0)

                    print(f"[run] posts collected: {len(posts)} (base={base_url})")
                    target_texts: Dict[str, List[str]] = defaultdict(list)
                    label_meta: Dict[str, Dict] = {}

                    for post in posts:
                        text_content = post["text"]
                        females, males = detect_mentions(text_content, participants)
                        if females and males:
                            for f in females:
                                for m in males:
                                    label = f"{f['name']}♥{m['name']}"
                                    target_texts[label].append(text_content)
                                    label_meta[label] = {
                                        "type": "pair",
                                        "female_id": f["id"],
                                        "male_id": m["id"],
                                    }
                        else:
                            for t in (females or males):
                                label = t["name"]
                                target_texts[label].append(text_content)
                                label_meta[label] = {
                                    "type": "single",
                                    "target_id": t["id"],
                                }

                    if pending_future is not None:
                        analysis = pending_future.result()
                        url_prior_summaries, url_prior_label_meta = process_analysis(
                            db,
                            analysis,
                            pending_context["combined_label_meta"],
                            episode_id,
                            capture_time,
                            args.event_threshold,
                            bool(pending_context["save_summary"]),
                            str(pending_context["base_url"]),
                        )

                    if not target_texts and not url_prior_summaries:
                        print(f"[run] no matched targets for base={base_url}")
                        pending_future = None
                        pending_context = {}
                        continue

                    combined_texts: Dict[str, List[str]] = defaultdict(list)
                    combined_label_meta: Dict[str, Dict] = {}
                    combined_label_meta.update(url_prior_label_meta)
                    combined_label_meta.update(label_meta)
                    for label, texts in target_texts.items():
                        combined_texts[label].extend(texts)
                    for label in url_prior_summaries.keys():
                        combined_texts.setdefault(label, [])

                    print(f"[run] targets grouped: {len(combined_texts)} (base={base_url})")
                    pending_future = executor.submit(
                        gemini_analyze_all_targets_hourly,
                        api_key,
                        {label: {"texts": texts} for label, texts in combined_texts.items()},
                        prior_summaries=url_prior_summaries,
                    )
                    pending_context = {
                        "combined_label_meta": combined_label_meta,
                        "save_summary": False,
                        "base_url": base_url,
                    }

                if pending_future is not None:
                    analysis = pending_future.result()
                    url_prior_summaries, url_prior_label_meta = process_analysis(
                        db,
                        analysis,
                        pending_context["combined_label_meta"],
                        episode_id,
                        capture_time,
                        args.event_threshold,
                        bool(pending_context["save_summary"]),
                        str(pending_context["base_url"]),
                    )

                prior_summaries = dict(url_prior_summaries)
                prior_label_meta = dict(url_prior_label_meta)

            if prior_summaries:
                summary_inserts = insert_summaries_only(
                    db,
                    episode_id,
                    prior_label_meta,
                    prior_summaries,
                )
                print(f"[db] commit ok: summaries={summary_inserts} (base=final)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
